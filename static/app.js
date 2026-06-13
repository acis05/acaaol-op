let token = sessionStorage.getItem("app_token") || null;
let selectedFile = null;
let builtPayload = null;
let ao = {
  has_token: false,
  has_session: false,
  db_id: null,
  db_alias: null
};

const $ = (id) => document.getElementById(id);

// ======================
// Basic helpers
// ======================
function log(msg) {
  const el = $("log");
  if (!el) return;
  el.textContent += msg + "\n";
  el.scrollTop = el.scrollHeight;
}

function clearLog() {
  const el = $("log");
  if (el) el.textContent = "";
}

function setText(id, value = "") {
  const el = $(id);
  if (el) el.textContent = value;
}

function setSummary(text) {
  setText("summary", text || "");
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setBadge(id, text, type = "neutral") {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.className = `badge ${type}`;
}

function showResultPanel(summary = {}, results = []) {
  const panel = $("resultPanel");
  if (panel) panel.classList.remove("hidden");

  const total = summary.total ?? summary.transactions ?? results.length ?? 0;
  const success = summary.success ?? 0;
  const failed = summary.failed ?? 0;

  setText("statTotal", total);
  setText("statSuccess", success);
  setText("statFailed", failed);

  const failedItems = results.filter(x => !x.ok);
  const note = $("failureNote");
  const text = $("failureText");

  if (failedItems.length > 0) {
    const lines = [];
    lines.push("CATATAN GAGAL IMPORT OTHER PAYMENT");
    lines.push("==================================");
    failedItems.forEach((x, idx) => {
      lines.push("");
      lines.push(`${idx + 1}. Payment: ${x.number || "-"} | Tanggal: ${x.transDate || "-"} | Penerima: ${x.payee || "-"}`);
      const errors = Array.isArray(x.errors) && x.errors.length ? x.errors : ["Tidak ada detail error dari Accurate."];
      errors.forEach(err => lines.push(`   - ${err}`));
    });

    if (note) note.classList.remove("hidden");
    if (text) text.value = lines.join("\n");
  } else {
    if (note) note.classList.add("hidden");
    if (text) text.value = "";
  }
}

function clearResultPanel() {
  const panel = $("resultPanel");
  if (panel) panel.classList.add("hidden");
  setText("statTotal", "0");
  setText("statSuccess", "0");
  setText("statFailed", "0");
  const note = $("failureNote");
  const text = $("failureText");
  if (note) note.classList.add("hidden");
  if (text) text.value = "";
}

// ======================
// Notify helpers
// ======================
function clearNotify() {
  const box = $("notifyBox");
  const titleEl = $("notifyTitle");
  const bodyEl = $("notifyBody");
  if (!box || !titleEl || !bodyEl) return;

  box.classList.add("hidden");
  box.classList.remove("success", "error", "info");
  titleEl.textContent = "";
  bodyEl.innerHTML = "";
}

function showNotify(type, title, html = "") {
  const box = $("notifyBox");
  const titleEl = $("notifyTitle");
  const bodyEl = $("notifyBody");
  if (!box || !titleEl || !bodyEl) return;

  box.classList.remove("hidden", "success", "error", "info");
  box.classList.add(type || "info");

  titleEl.textContent = title || "";
  bodyEl.innerHTML = html || "";
}

function renderSimpleMessage(lines = []) {
  const arr = Array.isArray(lines) ? lines : [lines];
  return `
    <ul class="notify-list">
      ${arr.filter(Boolean).map(x => `<li>${escapeHtml(x)}</li>`).join("")}
    </ul>
  `;
}

const notifyClose = $("notifyClose");
if (notifyClose) {
  notifyClose.onclick = () => clearNotify();
}

const btnCopyFailures = $("btnCopyFailures");
if (btnCopyFailures) {
  btnCopyFailures.onclick = async () => {
    const text = $("failureText")?.value || "";
    if (!text) return;

    try {
      await navigator.clipboard.writeText(text);
      btnCopyFailures.textContent = "Tersalin";
      setTimeout(() => btnCopyFailures.textContent = "Copy Catatan", 1200);
    } catch {
      $("failureText")?.select();
      document.execCommand("copy");
      btnCopyFailures.textContent = "Tersalin";
      setTimeout(() => btnCopyFailures.textContent = "Copy Catatan", 1200);
    }
  };
}

// ======================
// State helpers
// ======================
function isLoggedIn() {
  return !!token;
}

function isFileReady() {
  return !!selectedFile;
}

function isPayloadReady() {
  return !!builtPayload;
}

function isDbReady() {
  return !!ao.has_session;
}

function updateViewByLogin() {
  const loggedIn = isLoggedIn();

  if ($("loginView")) {
    $("loginView").classList.toggle("hidden", loggedIn);
  }

  if ($("appView")) {
    $("appView").classList.toggle("hidden", !loggedIn);
  }
}

function updateUI() {
  updateViewByLogin();

  const loggedIn = isLoggedIn();
  const fileReady = isFileReady();
  const payloadReady = isPayloadReady();
  const dbReady = isDbReady();
  const oauthReady = !!ao.has_token;

  if ($("btnBuild")) $("btnBuild").disabled = !(loggedIn && fileReady);
  if ($("btnImport")) $("btnImport").disabled = !(loggedIn && dbReady && payloadReady);
  if ($("btnLoadDb")) $("btnLoadDb").disabled = !oauthReady;

  if ($("btnUseDb")) {
    const sel = $("dbSelect");
    const hasSelectedDb = !!(sel && sel.value && String(sel.value).trim() !== "");
    $("btnUseDb").disabled = !(oauthReady && hasSelectedDb);
  }

  if (oauthReady && dbReady) {
    setBadge("connectionBadge", "Database aktif", "ok");
  } else if (oauthReady) {
    setBadge("connectionBadge", "OAuth siap", "info");
  } else {
    setBadge("connectionBadge", "Belum connect", "neutral");
  }

  setBadge("fileBadge", fileReady ? "File dipilih" : "Belum ada file", fileReady ? "ok" : "neutral");

  if (payloadReady) {
    setBadge("processBadge", "Siap import", "ok");
  } else if (fileReady) {
    setBadge("processBadge", "Perlu cek file", "info");
  } else {
    setBadge("processBadge", "Menunggu file", "neutral");
  }

  const status = [];
  status.push(loggedIn ? "Login OK" : "Belum login");
  status.push(oauthReady ? "OAuth OK" : "Belum Connect");
  status.push(dbReady ? `DB Aktif${ao.db_alias ? ": " + ao.db_alias : ""}` : "DB belum dipilih");
  setText("aoStatus", status.join(" · "));
}

function resetExcelState() {
  selectedFile = null;
  builtPayload = null;
  if ($("file")) $("file").value = "";
  setText("fileName", "Belum ada file dipilih");
  setSummary("");
  clearNotify();
  clearResultPanel();
  updateUI();
}

// ======================
// HTTP helpers
// ======================
async function getJson(url) {
  const r = await fetch(url);
  const t = await r.text();

  let j;
  try {
    j = JSON.parse(t);
  } catch {
    j = { raw: t };
  }

  if (!r.ok) {
    const err = new Error(j?.message || `HTTP ${r.status}`);
    err.data = j;
    err.status = r.status;
    throw err;
  }

  return j;
}

async function postJson(url, body, auth = true) {
  const headers = { "Content-Type": "application/json" };
  if (auth && token) headers["Authorization"] = `Bearer ${token}`;

  const r = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body || {})
  });

  const t = await r.text();

  let j;
  try {
    j = JSON.parse(t);
  } catch {
    j = { raw: t };
  }

  if (!r.ok) {
    const err = new Error(j?.message || `HTTP ${r.status}`);
    err.data = j;
    err.status = r.status;
    throw err;
  }

  return j;
}

async function postForm(url, formData) {
  const headers = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const r = await fetch(url, {
    method: "POST",
    headers,
    body: formData
  });

  const t = await r.text();

  let j;
  try {
    j = JSON.parse(t);
  } catch {
    j = { raw: t };
  }

  if (!r.ok) {
    const err = new Error(j?.message || `HTTP ${r.status}`);
    err.data = j;
    err.status = r.status;
    throw err;
  }

  return j;
}

async function fetchAoStatus() {
  try {
    const st = await getJson("/api/ao-status");
    ao = {
      has_token: !!st.has_token,
      has_session: !!st.has_session,
      db_id: st.db_id || null,
      db_alias: st.db_alias || null
    };
  } catch {
    ao = {
      has_token: false,
      has_session: false,
      db_id: null,
      db_alias: null
    };
  }
  updateUI();
}

// ======================
// Theme
// ======================
function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme");
  document.documentElement.setAttribute("data-theme", cur === "clear" ? "" : "clear");
}

if ($("themeToggle")) {
  $("themeToggle").onclick = toggleTheme;
}

if ($("themeToggleApp")) {
  $("themeToggleApp").onclick = toggleTheme;
}

// ======================
// Login
// ======================
if ($("btnLogin")) {
  $("btnLogin").onclick = async () => {
    setText("loginStatus", "");
    clearLog();
    clearNotify();

    try {
      const email = $("email")?.value?.trim() || "";
      const password = $("password")?.value?.trim() || "";

      const res = await postJson("/api/login", { email, password }, false);
      token = res.token;
      sessionStorage.setItem("app_token", token);

      if ($("customerInfo")) {
        $("customerInfo").textContent = "Customer: " + (res.customer_name || "-") + (res.email ? " · " + res.email : "");
      }

      setText("loginStatus", "Login berhasil");
      updateUI();

      await fetchAoStatus();
    } catch (e) {
      token = null;
      sessionStorage.removeItem("app_token");
      setText("loginStatus", "Login gagal: " + e.message);

      if ($("customerInfo")) {
        $("customerInfo").textContent = "";
      }

      updateUI();
    }
  };
}

["email", "password"].forEach((id) => {
  const el = $(id);
  if (el) {
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && $("btnLogin")) {
        $("btnLogin").click();
      }
    });
  }
});

if ($("btnAppLogout")) {
  $("btnAppLogout").onclick = () => {
    token = null;
    sessionStorage.removeItem("app_token");
    resetExcelState();
    clearNotify();
    clearLog();
    setText("loginStatus", "");
    setText("customerInfo", "");
    updateUI();
  };
}

// ======================
// File picker
// ======================
if ($("file")) {
  $("file").addEventListener("change", (e) => {
    clearNotify();
    clearResultPanel();

    selectedFile = e.target.files?.[0] || null;
    builtPayload = null;
    setSummary("");

    if (selectedFile) {
      setText("fileName", selectedFile.name);
    } else {
      setText("fileName", "Belum ada file dipilih");
    }

    updateUI();
  });
}

// ======================
// Reset file
// ======================
if ($("btnResetFile")) {
  $("btnResetFile").onclick = () => {
    resetExcelState();
  };
}

// ======================
// Load DB
// ======================
if ($("btnLoadDb")) {
  $("btnLoadDb").onclick = async () => {
    try {
      clearNotify();

      const res = await getJson("/api/db-list");
      const arr = res?.response?.d || [];

      const sel = $("dbSelect");
      if (sel) {
        sel.innerHTML = "";

        const firstOpt = document.createElement("option");
        firstOpt.value = "";
        firstOpt.textContent = "-- pilih database --";
        sel.appendChild(firstOpt);

        arr.forEach((db) => {
          const opt = document.createElement("option");
          opt.value = db.id;
          opt.textContent = `${db.alias || "DB"} (ID: ${db.id})`;
          opt.dataset.alias = db.alias || "";
          sel.appendChild(opt);
        });
      }

      updateUI();

      if (arr.length === 0) {
        showNotify("info", "Database tidak ditemukan", renderSimpleMessage(["Tidak ada database yang muncul di akun ini."]));
      } else {
        showNotify("info", "Database berhasil dimuat", renderSimpleMessage([`Total database: ${arr.length}. Silakan pilih database tujuan.`]));
      }
    } catch (e) {
      showNotify("error", "Load database gagal", renderSimpleMessage([e.message]));
    }
  };
}

// ======================
// DB select change
// ======================
if ($("dbSelect")) {
  $("dbSelect").addEventListener("change", () => {
    updateUI();
  });
}

// ======================
// Use DB
// ======================
if ($("btnUseDb")) {
  $("btnUseDb").onclick = async () => {
    try {
      clearNotify();

      const sel = $("dbSelect");
      const id = sel?.value;
      const alias = sel?.selectedOptions?.[0]?.dataset?.alias || sel?.selectedOptions?.[0]?.textContent || "";

      if (!id) throw new Error("Pilih database dulu");

      const res = await postJson("/api/open-db", { id, alias }, false);

      await fetchAoStatus();
      showNotify("success", "Database aktif", renderSimpleMessage([`Database siap digunakan: ${alias || id}`]));
    } catch (e) {
      showNotify("error", "Database gagal digunakan", renderSimpleMessage([e.message]));
    }
  };
}

// ======================
// Logout Accurate
// ======================
if ($("btnLogoutAO")) {
  $("btnLogoutAO").onclick = async () => {
    try {
      clearNotify();
      await fetch("/api/ao-logout", { method: "POST" });

      ao = {
        has_token: false,
        has_session: false,
        db_id: null,
        db_alias: null
      };

      builtPayload = null;
      setSummary("");
      clearResultPanel();
      updateUI();

      showNotify("success", "Logout Accurate berhasil", renderSimpleMessage(["Silakan Connect lagi untuk akun Accurate lain."]));
    } catch (e) {
      showNotify("error", "Logout Accurate gagal", renderSimpleMessage([e.message]));
    }
  };
}

// ======================
// Build Other Payment
// ======================
if ($("btnBuild")) {
  $("btnBuild").onclick = async () => {
    try {
      clearNotify();
      clearResultPanel();

      if (!token) throw new Error("Login dulu");
      if (!selectedFile) throw new Error("Pilih file Excel dulu");

      const fd = new FormData();
      fd.append("file", selectedFile);

      setSummary("Sedang mengecek file...");
      const res = await postForm("/api/build-other-payment", fd);

      builtPayload = res.payload;

      setSummary(`File siap diimport: ${res.summary.transactions} payment, ${res.summary.lines} detail akun.`);
      showResultPanel({
        total: res.summary.transactions,
        success: 0,
        failed: 0
      }, []);

      showNotify(
        "success",
        "File siap diimport",
        renderSimpleMessage([
          `Jumlah payment: ${res.summary.transactions}`,
          `Jumlah detail akun: ${res.summary.lines}`,
          "Klik Import ke Accurate untuk melanjutkan."
        ])
      );

      updateUI();
    } catch (e) {
      builtPayload = null;
      setSummary("");
      clearResultPanel();
      showNotify("error", "File belum bisa diproses", renderSimpleMessage([e.message]));
      updateUI();
    }
  };
}

// ======================
// Import Other Payment
// ======================
if ($("btnImport")) {
  $("btnImport").onclick = async () => {
    try {
      clearNotify();

      if (!token) throw new Error("Login dulu");
      if (!ao.has_session) throw new Error("Pilih DB dulu");
      if (!builtPayload) throw new Error("Cek file dulu");

      setSummary("Sedang mengimport Other Payment ke Accurate...");
      const res = await postJson("/api/import-other-payment", { payload: builtPayload }, true);

      const summary = res.summary || {};
      const results = res.results || [];
      const hasFailed = (summary.failed || 0) > 0;

      showResultPanel(summary, results);
      setSummary(hasFailed ? "Import selesai, ada payment yang perlu diperbaiki." : "Import berhasil. Semua payment berhasil masuk ke Accurate.");

      showNotify(
        hasFailed ? "error" : "success",
        hasFailed ? "Import selesai dengan catatan" : "Import berhasil",
        renderSimpleMessage([
          `Total payment: ${summary.total || 0}`,
          `Sukses: ${summary.success || 0}`,
          `Gagal: ${summary.failed || 0}`
        ])
      );

      if (!hasFailed) {
        selectedFile = null;
        builtPayload = null;
        if ($("file")) $("file").value = "";
        setText("fileName", "Belum ada file dipilih");
      }
    } catch (e) {
      const data = e.data || {};
      const summary = data.summary || {};
      const results = data.results || [];

      if (results.length > 0) {
        showResultPanel(summary, results);
        setSummary("Import selesai, ada payment yang perlu diperbaiki.");
        showNotify(
          "error",
          "Import selesai dengan catatan",
          renderSimpleMessage([
            `Total payment: ${summary.total || 0}`,
            `Sukses: ${summary.success || 0}`,
            `Gagal: ${summary.failed || 0}`,
            "Lihat Catatan gagal di bawah."
          ])
        );
      } else if (data.response?.d) {
        setSummary("");
        showNotify("error", "Import gagal", renderSimpleMessage(data.response.d));
      } else {
        setSummary("");
        showNotify("error", "Import gagal", renderSimpleMessage([e.message]));
      }
    } finally {
      updateUI();
    }
  };
}

// ======================
// Init
// ======================
window.addEventListener("load", async () => {
  token = sessionStorage.getItem("app_token") || null;
  updateUI();
  if (token) {
    await fetchAoStatus();
  }
});
