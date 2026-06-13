import os
import json
import hashlib
import datetime as dt
import base64
from functools import wraps
from urllib.parse import urlencode

import pandas as pd
import requests
import jwt
from flask import Flask, request, jsonify, render_template, redirect
from dotenv import load_dotenv

load_dotenv()

# =========================
# Config
# =========================
APP_DIR = os.path.dirname(__file__)
TOKENS_FILE = os.path.join(APP_DIR, "tokens.json")
LICENSE_FILE = os.path.join(APP_DIR, "licenses.json")

JWT_SECRET = os.getenv("JWT_SECRET", "dev_jwt_change_me")
SECRET_KEY = os.getenv("SECRET_KEY", "dev_change_me")

AO_OP_SAVE_PATH = os.getenv("AO_OP_SAVE_PATH", "/api/other-payment/bulk-save.do")

OAUTH_AUTHORIZE_URL = "https://account.accurate.id/oauth/authorize"
OAUTH_TOKEN_URL = "https://account.accurate.id/oauth/token"
ACCOUNT_DB_LIST_URL = "https://account.accurate.id/api/db-list.do"
ACCOUNT_OPEN_DB_URL = "https://account.accurate.id/api/open-db.do"

LAST_DEBUG = {
    "time": None,
    "form_sample": None,
    "url": None,
    "headers": None,
    "response_status": None,
    "response": None,
    "summary": None,
}

OP_TEMPLATE_COLUMNS = [
    "SEQ", "NUMBER", "TRANSDATE", "BANKNO", "PAYEE", "DESCRIPTION",
    "BRANCHID", "BRANCHNAME", "CHEQUEDATE", "CHEQUENO", "RATE", "TYPEAUTONUMBER", "ID",
    "ACCOUNTNO", "AMOUNT", "EXPENSENAME", "MEMO", "DEPARTMENT", "DETAILID", "DETAILSTATUS",
    "DATACLASSIFICATION1NAME", "DATACLASSIFICATION2NAME", "DATACLASSIFICATION3NAME",
    "DATACLASSIFICATION4NAME", "DATACLASSIFICATION5NAME", "DATACLASSIFICATION6NAME",
    "DATACLASSIFICATION7NAME", "DATACLASSIFICATION8NAME", "DATACLASSIFICATION9NAME",
    "DATACLASSIFICATION10NAME"
]

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY


# =========================
# Utils: token file
# =========================
def save_tokens(data: dict):
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_tokens():
    if not os.path.exists(TOKENS_FILE):
        return {}
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            txt = f.read().strip()
            if not txt:
                return {}
            return json.loads(txt)
    except Exception:
        return {}


# =========================
# Utils: license & auth
# =========================
def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_licenses():
    if not os.path.exists(LICENSE_FILE):
        return [
            {
                "email": "demo@aca-aol.id",
                "password_sha256": sha256("1234"),
                "active": True,
                "expires": None,
                "customer_name": "Demo User",
            }
        ]
    with open(LICENSE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def license_valid(email: str, password: str):
    licenses = load_licenses()
    email = (email or "").strip().lower()

    lic = next(
        (x for x in licenses if str(x.get("email", "")).strip().lower() == email),
        None
    )

    if not lic:
        return False, "Email tidak terdaftar", None

    if not lic.get("active"):
        return False, "Akun tidak aktif", None

    expires = lic.get("expires")
    if expires:
        try:
            exp_dt = dt.datetime.fromisoformat(expires + "T23:59:59")
            if dt.datetime.now() > exp_dt:
                return False, "Akun expired", None
        except Exception:
            return False, "Format expires di licenses.json salah", None

    if sha256(password) != lic.get("password_sha256"):
        return False, "Password salah", None

    return True, "OK", lic


def make_token(email: str) -> str:
    payload = {
        "email": email,
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=12),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"ok": False, "message": "Unauthorized"}), 401
        token = auth[7:]
        try:
            jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        except Exception:
            return jsonify({"ok": False, "message": "Invalid session"}), 401
        return fn(*args, **kwargs)

    return wrapper


# =========================
# OAuth helpers
# =========================
def refresh_access_token_if_needed():
    tokens = load_tokens()
    access_token = (tokens.get("access_token") or "").strip()
    refresh_token = (tokens.get("refresh_token") or "").strip()
    expires_at = (tokens.get("expires_at") or "").strip()

    if not access_token:
        return tokens

    if not expires_at:
        return tokens

    try:
        exp = dt.datetime.fromisoformat(expires_at)
        if dt.datetime.now() < exp - dt.timedelta(minutes=2):
            return tokens
    except Exception:
        return tokens

    if not refresh_token:
        return tokens

    client_id = (os.getenv("AO_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("AO_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        return tokens

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    headers = {"Authorization": f"Basic {basic}"}
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}

    r = requests.post(OAUTH_TOKEN_URL, headers=headers, data=data, timeout=60)
    if not r.ok:
        return tokens

    j = r.json()
    expires_in = int(j.get("expires_in") or 3600)
    new_exp = dt.datetime.now() + dt.timedelta(seconds=expires_in)

    tokens.update(
        {
            "access_token": j.get("access_token"),
            "refresh_token": j.get("refresh_token") or refresh_token,
            "expires_at": new_exp.isoformat(),
            "updated_at": dt.datetime.now().isoformat(),
        }
    )
    save_tokens(tokens)
    return tokens


def accurate_post(path: str, data: dict):
    tokens = refresh_access_token_if_needed()
    access_token = (tokens.get("access_token") or "").strip()
    host = (tokens.get("host") or "").strip()
    x_session_id = (tokens.get("x_session_id") or "").strip()

    if not access_token or not host or not x_session_id:
        raise ValueError("OAuth belum lengkap. Connect + pilih DB dulu.")

    url = f"{host}/accurate{path}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Session-ID": x_session_id,
        "Accept": "application/json",
    }

    return requests.post(url, headers=headers, data=data, timeout=120)


# =========================
# Excel helpers
# =========================
def normalize_column_name(col):
    return str(col).strip().upper()


def parse_date_ddmmyyyy(val):
    if val is None:
        return None

    if isinstance(val, (dt.datetime, dt.date)):
        d = val.date() if isinstance(val, dt.datetime) else val
        return d.strftime("%d/%m/%Y")

    if isinstance(val, (int, float)) and str(val).strip() != "":
        try:
            base = dt.datetime(1899, 12, 30)
            d = base + dt.timedelta(days=float(val))
            return d.strftime("%d/%m/%Y")
        except Exception:
            pass

    s = str(val).strip()
    if not s:
        return None

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            d = dt.datetime.strptime(s, fmt)
            return d.strftime("%d/%m/%Y")
        except Exception:
            continue

    try:
        d = pd.to_datetime(s, dayfirst=True, errors="raise")
        return d.strftime("%d/%m/%Y")
    except Exception:
        return None


def parse_bool(val):
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("true", "1", "yes", "y", "ya"):
        return True
    if s in ("false", "0", "no", "n", "tidak", ""):
        return False
    return None


def parse_money(val, default=None):
    if val is None:
        return default

    if isinstance(val, (int, float)) and not pd.isna(val):
        return float(val)

    s = str(val).strip()
    if s == "":
        return default

    try:
        return float(s.replace(",", ""))
    except Exception:
        return default


def parse_int(val, default=None):
    if val is None or str(val).strip() == "":
        return default
    try:
        return int(float(str(val).replace(",", "").strip()))
    except Exception:
        return default


# =========================
# Other Payment Builder
# =========================
def build_other_payment_payload_from_df(df: pd.DataFrame):
    df = df.rename(columns=lambda c: normalize_column_name(c))
    df = df.fillna("")

    required_cols = ["TRANSDATE", "BANKNO", "PAYEE", "ACCOUNTNO", "AMOUNT", "EXPENSENAME"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Kolom wajib tidak ada: {col}")

    normalized_rows = []
    for idx, row in df.iterrows():
        line_no = idx + 2

        trans_date = parse_date_ddmmyyyy(row.get("TRANSDATE"))
        if not trans_date:
            raise ValueError(f"Row {line_no}: TRANSDATE tidak valid")

        bank_no = str(row.get("BANKNO", "")).strip()
        if not bank_no:
            raise ValueError(f"Row {line_no}: BANKNO kosong")

        payee = str(row.get("PAYEE", "")).strip()
        if not payee:
            raise ValueError(f"Row {line_no}: PAYEE kosong")

        account_no = str(row.get("ACCOUNTNO", "")).strip()
        if not account_no:
            raise ValueError(f"Row {line_no}: ACCOUNTNO kosong")

        amount = parse_money(row.get("AMOUNT"))
        if amount is None:
            raise ValueError(f"Row {line_no}: AMOUNT kosong / tidak valid")

        expense_name = str(row.get("EXPENSENAME", "")).strip()
        if not expense_name:
            raise ValueError(f"Row {line_no}: EXPENSENAME kosong")

        number = str(row.get("NUMBER", "")).strip()

        normalized_rows.append({
            **row.to_dict(),
            "TRANSDATE": trans_date,
            "BANKNO": bank_no,
            "PAYEE": payee,
            "ACCOUNTNO": account_no,
            "AMOUNT": amount,
            "EXPENSENAME": expense_name,
            "NUMBER": number,
        })

    auto_i = 1

    def auto_op_no(date_str, i):
        d = date_str.replace("/", "")
        return f"OP-{d}-{i:03d}"

    grouped = {}
    for r in normalized_rows:
        if not r["NUMBER"]:
            r["NUMBER"] = auto_op_no(r["TRANSDATE"], auto_i)
            auto_i += 1
        grouped.setdefault(r["NUMBER"], []).append(r)

    data = []

    for number, rows in grouped.items():
        def seq_key(x):
            s = str(x.get("SEQ", "")).strip()
            try:
                return int(float(s))
            except Exception:
                return 999999

        rows = sorted(rows, key=seq_key)
        head = rows[0]

        tx = {
            "bankNo": head["BANKNO"],
            "payee": head["PAYEE"],
            "transDate": head["TRANSDATE"],
            "number": number,
            "detailAccount": []
        }

        header_map = {
            "BRANCHID": "branchId",
            "BRANCHNAME": "branchName",
            "CHEQUEDATE": "chequeDate",
            "CHEQUENO": "chequeNo",
            "DESCRIPTION": "description",
            "ID": "id",
            "RATE": "rate",
            "TYPEAUTONUMBER": "typeAutoNumber",
        }

        for src, dst in header_map.items():
            val = head.get(src, "")
            if str(val).strip() == "":
                continue

            if src in ("BRANCHID", "ID", "TYPEAUTONUMBER"):
                val = parse_int(val)
            elif src == "CHEQUEDATE":
                val = parse_date_ddmmyyyy(val)
            elif src == "RATE":
                val = parse_money(val)
            else:
                val = str(val).strip()

            if val not in (None, ""):
                tx[dst] = val

        for r in rows:
            det = {
                "accountNo": str(r.get("ACCOUNTNO", "")).strip(),
                "amount": parse_money(r.get("AMOUNT"), 0),
                "expenseName": str(r.get("EXPENSENAME", "")).strip(),
            }

            optional_detail_map = {
                "DETAILSTATUS": "_status",
                "DEPARTMENT": "departmentName",
                "DETAILID": "id",
                "MEMO": "memo",
                "DATACLASSIFICATION1NAME": "dataClassification1Name",
                "DATACLASSIFICATION2NAME": "dataClassification2Name",
                "DATACLASSIFICATION3NAME": "dataClassification3Name",
                "DATACLASSIFICATION4NAME": "dataClassification4Name",
                "DATACLASSIFICATION5NAME": "dataClassification5Name",
                "DATACLASSIFICATION6NAME": "dataClassification6Name",
                "DATACLASSIFICATION7NAME": "dataClassification7Name",
                "DATACLASSIFICATION8NAME": "dataClassification8Name",
                "DATACLASSIFICATION9NAME": "dataClassification9Name",
                "DATACLASSIFICATION10NAME": "dataClassification10Name",
            }

            for src, dst in optional_detail_map.items():
                val = r.get(src, "")
                if str(val).strip() == "":
                    continue
                if src == "DETAILID":
                    val = parse_int(val)
                else:
                    val = str(val).strip()
                if val not in (None, ""):
                    det[dst] = val

            tx["detailAccount"].append(det)

        data.append(tx)

    return {"data": data}


def other_payment_payload_to_form_params(payload: dict) -> dict:
    out = {}

    for i, tx in enumerate(payload.get("data", [])):
        for k, v in tx.items():
            if k == "detailAccount":
                continue
            if v in (None, ""):
                continue
            out[f"data[{i}].{k}"] = v

        for j, det in enumerate(tx.get("detailAccount", [])):
            for k, v in det.items():
                if v in (None, ""):
                    continue
                out[f"data[{i}].detailAccount[{j}].{k}"] = v

    return {k: str(v) for k, v in out.items()}


# =========================
# Routes: UI
# =========================
@app.get("/")
def home():
    return render_template("index.html")


# =========================
# Routes: login/license
# =========================
@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"ok": False, "message": "Email & password wajib"}), 400

    ok, msg, lic = license_valid(email, password)
    if not ok:
        return jsonify({"ok": False, "message": msg}), 401

    token = make_token(email)

    return jsonify({
        "ok": True,
        "token": token,
        "customer_name": lic.get("customer_name"),
        "email": email
    })


# =========================
# Routes: status
# =========================
@app.get("/api/ao-status")
def api_ao_status():
    tokens = load_tokens()
    return jsonify(
        {
            "ok": True,
            "has_token": bool((tokens.get("access_token") or "").strip()),
            "has_session": bool((tokens.get("host") or "").strip()) and bool((tokens.get("x_session_id") or "").strip()),
            "db_id": tokens.get("db_id"),
            "db_alias": tokens.get("db_alias"),
        }
    )


@app.get("/api/debug-last")
def api_debug_last():
    return jsonify({"ok": True, **LAST_DEBUG})


@app.post("/api/ao-logout")
def api_ao_logout():
    if os.path.exists(TOKENS_FILE):
        os.remove(TOKENS_FILE)
    return jsonify({"ok": True})


# =========================
# Routes: build payload OP
# =========================
@app.post("/api/build-other-payment")
@require_auth
def api_build_other_payment():
    if "file" not in request.files:
        return jsonify({"ok": False, "message": "File tidak ditemukan"}), 400

    f = request.files["file"]
    if not f.filename.lower().endswith((".xlsx", ".xls")):
        return jsonify({"ok": False, "message": "File harus Excel (.xlsx/.xls)"}), 400

    try:
        df = pd.read_excel(f)
        built = build_other_payment_payload_from_df(df)

        tx_count = len(built.get("data", []))
        account_count = sum(len(x.get("detailAccount", [])) for x in built.get("data", []))

        return jsonify({
            "ok": True,
            "payload": built,
            "summary": {
                "transactions": tx_count,
                "lines": account_count,
                "accounts": account_count,
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


# =========================
# Routes: import Other Payment
# =========================
@app.post("/api/import-other-payment")
@require_auth
def api_import_other_payment():
    body = request.get_json(silent=True) or {}
    payload = body.get("payload")

    if not payload or "data" not in payload:
        return jsonify({"ok": False, "message": "payload kosong"}), 400

    tokens = refresh_access_token_if_needed()
    access_token = (tokens.get("access_token") or "").strip()
    host = (tokens.get("host") or "").strip()
    x_session = (tokens.get("x_session_id") or "").strip()

    if not access_token or not host or not x_session:
        return jsonify({
            "ok": False,
            "message": "OAuth belum lengkap. Connect + pilih DB dulu."
        }), 400

    tx_list = payload.get("data", [])
    results = []
    success_count = 0
    failed_count = 0
    raw_responses = []
    url = f"{host}/accurate{AO_OP_SAVE_PATH}"

    try:
        # Accurate bulk-save max 100 data per request
        for start in range(0, len(tx_list), 100):
            chunk = tx_list[start:start + 100]
            chunk_payload = {"data": chunk}
            form_params = other_payment_payload_to_form_params(chunk_payload)

            if start == 0:
                LAST_DEBUG["form_sample"] = dict(list(form_params.items())[:120])

            r = accurate_post(AO_OP_SAVE_PATH, data=form_params)
            try:
                resp_json = r.json()
            except Exception:
                resp_json = {"raw": r.text}

            raw_responses.append(resp_json)

            chunk_ok = r.ok and isinstance(resp_json, dict) and resp_json.get("s") is True

            if not chunk_ok:
                if isinstance(resp_json, dict):
                    if isinstance(resp_json.get("d"), list):
                        chunk_errors = [str(x) for x in resp_json.get("d", [])]
                    elif resp_json.get("d"):
                        chunk_errors = [str(resp_json.get("d"))]
                    elif resp_json.get("message"):
                        chunk_errors = [str(resp_json.get("message"))]
                    elif resp_json.get("error"):
                        chunk_errors = [str(resp_json.get("error"))]
                    else:
                        chunk_errors = ["Transaksi ditolak Accurate."]
                else:
                    chunk_errors = ["Response Accurate tidak dikenali."]

            for offset, tx in enumerate(chunk, start=1):
                idx = start + offset
                payment_no = str(tx.get("number") or f"TX-{idx}").strip()
                trans_date = str(tx.get("transDate") or "-").strip()
                payee = str(tx.get("payee") or "-").strip()

                if chunk_ok:
                    success_count += 1
                    results.append({
                        "index": idx,
                        "number": payment_no,
                        "transDate": trans_date,
                        "payee": payee,
                        "ok": True,
                        "errors": [],
                        "raw_response": resp_json,
                    })
                else:
                    failed_count += 1
                    results.append({
                        "index": idx,
                        "number": payment_no,
                        "transDate": trans_date,
                        "payee": payee,
                        "ok": False,
                        "errors": chunk_errors,
                        "raw_response": resp_json,
                    })

        summary = {
            "total": len(results),
            "success": success_count,
            "failed": failed_count
        }

        LAST_DEBUG["time"] = dt.datetime.now().isoformat()
        LAST_DEBUG["url"] = url
        LAST_DEBUG["headers"] = {
            "Authorization": "Bearer ***",
            "X-Session-ID": x_session
        }
        LAST_DEBUG["response_status"] = 200 if failed_count == 0 else 400
        LAST_DEBUG["response"] = raw_responses
        LAST_DEBUG["summary"] = summary

        if failed_count == 0:
            return jsonify({
                "ok": True,
                "message": "Import berhasil",
                "summary": summary,
                "results": results
            }), 200

        return jsonify({
            "ok": False,
            "message": "Import selesai",
            "summary": summary,
            "results": results
        }), 400

    except Exception as e:
        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500


# =========================
# Routes: OAuth
# =========================
@app.get("/oauth/start")
def oauth_start():
    client_id = (os.getenv("AO_CLIENT_ID") or "").strip()
    redirect_uri = (os.getenv("AO_REDIRECT_URI") or "").strip()
    scope = (os.getenv("AO_SCOPE") or "").strip()

    if not client_id or not redirect_uri or not scope:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "OAuth env belum lengkap. Isi AO_CLIENT_ID, AO_REDIRECT_URI, AO_SCOPE di .env",
                }
            ),
            500,
        )

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scope,
    }

    url = OAUTH_AUTHORIZE_URL + "?" + urlencode(params)
    return redirect(url, code=302)


@app.get("/oauth/callback")
def oauth_callback():
    code = (request.args.get("code") or "").strip()
    if not code:
        return "Tidak ada parameter code. OAuth ditolak / gagal.", 400

    client_id = (os.getenv("AO_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("AO_CLIENT_SECRET") or "").strip()
    redirect_uri = (os.getenv("AO_REDIRECT_URI") or "").strip()
    if not client_id or not client_secret or not redirect_uri:
        return "OAuth env belum lengkap. Isi AO_CLIENT_ID/AO_CLIENT_SECRET/AO_REDIRECT_URI di .env", 500

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    headers = {"Authorization": f"Basic {basic}"}
    data = {"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri}

    r = requests.post(OAUTH_TOKEN_URL, headers=headers, data=data, timeout=60)
    try:
        j = r.json()
    except Exception:
        j = {"raw": r.text}

    if not r.ok:
        return jsonify({"ok": False, "message": "Gagal tukar code ke token", "response": j}), r.status_code

    expires_in = int(j.get("expires_in") or 3600)
    exp = dt.datetime.now() + dt.timedelta(seconds=expires_in)

    tokens = load_tokens()
    tokens.update(
        {
            "access_token": j.get("access_token"),
            "refresh_token": j.get("refresh_token"),
            "scope": j.get("scope"),
            "token_type": j.get("token_type"),
            "expires_at": exp.isoformat(),
            "updated_at": dt.datetime.now().isoformat(),
        }
    )
    save_tokens(tokens)

    return """
    <script>
      window.location.href = "/";
    </script>
    """


# =========================
# Routes: db list & open db
# =========================
@app.get("/api/db-list")
def api_db_list():
    tokens = refresh_access_token_if_needed()
    access_token = (tokens.get("access_token") or "").strip()
    if not access_token:
        return jsonify({"ok": False, "message": "Belum connect OAuth. Klik Connect Accurate dulu."}), 401

    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(ACCOUNT_DB_LIST_URL, headers=headers, timeout=60)

    try:
        j = r.json()
    except Exception:
        j = {"raw": r.text}

    if not r.ok:
        return jsonify({"ok": False, "message": "db-list gagal", "status": r.status_code, "response": j}), r.status_code

    return jsonify({"ok": True, "response": j})


@app.post("/api/open-db")
def api_open_db():
    body = request.get_json(silent=True) or {}
    db_id = str(body.get("id") or "").strip()
    db_alias = str(body.get("alias") or "").strip()

    tokens = refresh_access_token_if_needed()
    access_token = (tokens.get("access_token") or "").strip()
    if not access_token:
        return jsonify({"ok": False, "message": "Belum connect OAuth."}), 401
    if not db_id:
        return jsonify({"ok": False, "message": "db id kosong."}), 400

    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(ACCOUNT_OPEN_DB_URL, headers=headers, params={"id": db_id}, timeout=60)

    try:
        j = r.json()
    except Exception:
        j = {"raw": r.text}

    if not r.ok:
        return jsonify({"ok": False, "message": "open-db gagal", "status": r.status_code, "response": j}), r.status_code

    tokens.update(
        {
            "db_id": db_id,
            "db_alias": db_alias or tokens.get("db_alias"),
            "host": j.get("host"),
            "x_session_id": j.get("session"),
            "updated_at": dt.datetime.now().isoformat(),
        }
    )
    save_tokens(tokens)

    return jsonify({"ok": True, "response": j})


# =========================
# Template download
# =========================
@app.get("/api/template")
def api_template():
    sample_row_1 = {
        "SEQ": "1",
        "NUMBER": "OP-13062026-001",
        "TRANSDATE": "13/06/2026",
        "BANKNO": "1-1101",
        "PAYEE": "PT Contoh Vendor",
        "DESCRIPTION": "Pembayaran operasional sample",
        "BRANCHID": "",
        "BRANCHNAME": "",
        "CHEQUEDATE": "13/06/2026",
        "CHEQUENO": "",
        "RATE": "1",
        "TYPEAUTONUMBER": "",
        "ID": "",
        "ACCOUNTNO": "6-1100",
        "AMOUNT": "1000000",
        "EXPENSENAME": "Biaya listrik",
        "MEMO": "Pembayaran listrik bulan Juni",
        "DEPARTMENT": "",
        "DETAILID": "",
        "DETAILSTATUS": "",
        "DATACLASSIFICATION1NAME": "",
        "DATACLASSIFICATION2NAME": "",
        "DATACLASSIFICATION3NAME": "",
        "DATACLASSIFICATION4NAME": "",
        "DATACLASSIFICATION5NAME": "",
        "DATACLASSIFICATION6NAME": "",
        "DATACLASSIFICATION7NAME": "",
        "DATACLASSIFICATION8NAME": "",
        "DATACLASSIFICATION9NAME": "",
        "DATACLASSIFICATION10NAME": "",
    }
    sample_row_2 = sample_row_1.copy()
    sample_row_2["SEQ"] = "2"
    sample_row_2["ACCOUNTNO"] = "6-1200"
    sample_row_2["AMOUNT"] = "500000"
    sample_row_2["EXPENSENAME"] = "Biaya internet"
    sample_row_2["MEMO"] = "Pembayaran internet bulan Juni"

    csv_lines = []
    csv_lines.append(",".join(OP_TEMPLATE_COLUMNS))

    for row in [sample_row_1, sample_row_2]:
        vals = []
        for col in OP_TEMPLATE_COLUMNS:
            val = str(row.get(col, ""))
            if "," in val or '"' in val or "\n" in val:
                val = '"' + val.replace('"', '""') + '"'
            vals.append(val)
        csv_lines.append(",".join(vals))

    csv = "\n".join(csv_lines)

    return app.response_class(
        csv,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=template-other-payment.csv"},
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    app.run(host="0.0.0.0", port=port, debug=False)
