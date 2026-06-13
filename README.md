# ACA-AOL Other Payment (Pembayaran Kas/Bank)

Modul import Excel ke Accurate Online untuk **Other Payment / Pembayaran Kas Bank**.

## Endpoint Accurate

```env
AO_OP_SAVE_PATH=/api/other-payment/bulk-save.do
AO_SCOPE=other_payment_save
AO_REDIRECT_URI=https://op.aca-aol.id/oauth/callback
```

## Kolom Excel

Template mencakup seluruh kolom utama dan optional yang tersedia pada API Other Payment:

- Header transaksi: NUMBER, TRANSDATE, BANKNO, PAYEE, DESCRIPTION, BRANCHID, BRANCHNAME, CHEQUEDATE, CHEQUENO, RATE, TYPEAUTONUMBER, ID
- Detail akun: ACCOUNTNO, AMOUNT, EXPENSENAME, MEMO, DEPARTMENT, DETAILID, DETAILSTATUS, DATACLASSIFICATION1NAME sampai DATACLASSIFICATION10NAME

1 baris Excel = 1 detail akun pembayaran. Baris dengan NUMBER yang sama akan digabung menjadi 1 transaksi Other Payment.

## Jalankan lokal

```bash
pip install -r requirements.txt
python app.py
```

Buka `http://localhost:3000`.
