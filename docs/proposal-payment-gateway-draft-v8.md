# Proposal Payment Gateway & Penarikan Dana — Draft v8

Status: Draft v8 · 19 Nov 2026
Dasar kode: `dev` (`e570704`, PR #34) + `feature/subscription-plan` (`9c1d7f5`).
Dokumen lengkap, menggantikan Draft v7 (yang berupa revisi per bagian atas PDF Draft v6 Rintisan).

---

## Perubahan dari Draft v7

| # | Topik | Draft v8 |
|---|---|---|
| 1 | Provider | **DANA** adalah provider aktif (`PAYMENT_PROVIDER=dana`, default). Provider **Rintisan dihapus** (`7ae07c0`). **DOKU** tersedia sebagai alternatif yang bisa dipilih lewat env. |
| 2 | Channel | DANA Gapura Custom Checkout: VA (BCA, BNI, BRI, Mandiri, Permata, CIMB), kartu kredit/debit, e-wallet (OVO, GoPay, ShopeePay, LinkAja). **QRIS tidak ditawarkan.** |
| 3 | Tarif | Tarif DANA **sudah termasuk PPN 11%**: VA Rp2.775, kartu 3,219%, e-wallet 2,22%. Orang tua menanggung biaya (gross-up). |
| 4 | Penarikan | Lewat **DANA Transfer to Bank**. Biaya penarikan **Rp2.500** untuk semua provider (biaya BI-FAST), ditanggung sekolah. |
| 5 | Cancel & refund | Checkout pending bisa dibatalkan. Checkout yang sudah dibayar bisa **di-refund penuh secara online** lewat DANA, oleh admin Classping atau staf keuangan cabang. |
| 6 | Aktivasi gateway | **Bukan lagi checkbox di admin web.** Pembayaran online orang tua adalah fitur paket langganan cabang (`payment_gateway`). Paket kedaluwarsa → orang tua melihat peringatan `GATEWAY_DISABLED`. |
| 7 | Pembayaran langganan | Tagihan langganan cabang dibayar lewat aggregator yang sama (referensi `SUB-…`, webhook yang sama). Uangnya masuk ke Classping dan **tidak pernah** masuk dompet cabang. |
| 8 | API orang tua | Tidak berubah: URL, request/response, kode error, dan status sama. Kode channel mengikuti DANA (mis. `VIRTUAL_ACCOUNT_BCA`), bukan kode Rintisan (`VABCA`). |

---

## 1. Ringkasan

| # | Topik | Isi |
|---|---|---|
| 1 | Arsitektur | Library reusable `libs/payment_aggregator` (tanpa Django) berisi facade `PaymentAggregator`, interface provider, rumus fee, serta provider DANA dan DOKU. Wiring Classping ada di `apps/payment_aggregator/` (tarif kontrak, env, pemilihan provider). |
| 2 | Pembayar | Orang tua membayar tagihan siswa secara online. Biaya channel ditambahkan di atas tagihan; cabang menerima **total tagihan penuh**. Classping tidak mengambil fee sendiri. |
| 3 | Dana masuk | Saat dibayar, total tagihan masuk ke dompet cabang sebagai **pending**. Setelah DANA settle, saldo berpindah ke **available** (dicek per jam). |
| 4 | Penarikan | Staf keuangan cabang (principal / officer) menarik saldo available ke rekening bank sekolah, dengan OTP email dan biaya Rp2.500. |
| 5 | Langganan | Gateway hanya aktif selama langganan cabang aktif (trial, aktif, atau masa tenggang 7 hari). |
| 6 | Perhitungan | Tidak ada rumus di view atau serializer. Semua rumus fee ada di `payment_aggregator/fees.py`; tarif ada di `apps/payment_aggregator/providers/<provider>.py`. |

---

## 2. Alur pembayaran orang tua

### 2.1 Endpoint

| Kode | Method & path | Siapa | Isi |
|---|---|---|---|
| B0 | `GET /api/gateway/invoices/?student_id=` | Orang tua | Semua tagihan siswa beserta status bisa-dibayar-online (`is_payment_gateway_enabled`, alasan per tagihan). |
| B1 | `GET /api/gateway/channels/?invoice_ids=1,2` | Orang tua | Channel yang tersedia untuk total tagihan, dengan `transaction_fee` dan `amount` per channel, serta batas waktu. |
| B2 | `POST /api/gateway/checkout/` + header `Idempotency-Key` | Orang tua (wali siswa) | Membuat checkout dan billing DANA. Mengembalikan nomor VA / link pembayaran. Request ulang dengan key yang sama mengembalikan checkout yang sama. |
| B3 / B4 | `GET /api/gateway/payments[/{id}]/` | Orang tua (siswanya), staf (cabangnya) | Daftar dan detail checkout. |
| B5 | `POST /api/gateway/payments/{id}/cancel/` `{"reason"}` | Orang tua pembuat, staf keuangan, admin | Membatalkan checkout pending; tagihan bisa dibayar lagi. |
| — | `POST /api/gateway/payments/{id}/refund/` `{"reason"}` | Admin Classping, staf keuangan cabang | Refund penuh online untuk checkout yang ditandai `needs_refund`. |

### 2.2 Aturan checkout (`apps/payment_gateway/constants.py`)

| Aturan | Nilai |
|---|---|
| Satu checkout | 1–5 tagihan (`MAX_INVOICES_PER_CHECKOUT = 5`) dari **satu siswa** dan **satu cabang** |
| Batas waktu bayar | 60 menit (`PAYMENT_DEADLINE_MINUTES`). Classping sendiri yang meng-expire checkout; DANA tidak mengirim callback expiry. |
| Cek expiry | 2 menit setelah `expires_at` (`PAYMENT_EXPIRY_CHECK_DELAY_MINUTES`), lewat job Celery dan sebagai cadangan sinkronisasi status |
| Tagihan terkunci | Selama checkout pending, tagihan tidak bisa dibayar manual atau dimasukkan ke checkout lain (`INVOICE_LOCKED`) |
| Bayar terlambat | Pembayaran yang dikonfirmasi setelah checkout expired / dibatalkan tetap menjadi **PAID**; uang tidak pernah hilang. Bila tagihan sudah lunas dengan cara lain, checkout ditandai `needs_refund`. |

### 2.3 Status checkout

| Dari | Ke | Kapan |
|---|---|---|
| — | `pending` | Checkout dibuat dan billing DANA berhasil |
| — | `failed` | DANA menolak atau tidak bisa dihubungi saat membuat billing (orang tua tidak pernah menerima instruksi bayar) |
| `pending` | `paid` | Webhook atau sinkronisasi status: DANA melaporkan PAID dengan nominal yang sama |
| `pending` | `expired` | Lewat 60 menit tanpa pembayaran |
| `pending` | `cancelled` | Dibatalkan (B5) |
| `expired` / `cancelled` / `failed` | `paid` | Pembayaran terlambat tetap diterima |

Nominal dari DANA yang berbeda dengan nominal checkout **tidak** diproses: checkout ditandai untuk review (`needs_review`).

---

## 3. Channel & biaya

### 3.1 Tarif DANA (`apps/payment_aggregator/providers/dana.py`)

DANA menambahkan PPN 11% di atas fee-nya, jadi setiap tarif = tarif DANA + PPN (`with_vat`).

| Channel (kode DANA) | Metode | Tarif | Jenis |
|---|---|---|---|
| `VIRTUAL_ACCOUNT_BCA`, `_BNI`, `_BRI`, `_MANDIRI`, `_PERMATA`, `_CIMB` | Virtual account | Rp2.500 + PPN = **Rp2.775** | flat |
| `NETWORK_PAY_PG_CARD` | Kartu (Visa, Mastercard, AMEX, JCB) | 2,9% + PPN = **3,219%** | persen |
| `NETWORK_PAY_PG_OVO`, `_GOPAY`, `_SPAY`, `_LINKAJA` | E-wallet | 2% + PPN = **2,22%** (tier tertinggi; DANA menyebut 1,5% atau 2%) | persen |
| QRIS | — | **Tidak ditawarkan** (aturan BI: MDR QRIS tidak boleh dibebankan ke pembayar) | — |

Channel tanpa tarif di `CHANNEL_FEES` tidak ditawarkan.

### 3.2 Rumus (gross-up, `payment_aggregator/fees.py`)

- **Flat**: `amount = tagihan + fee`.
- **Persen**: DANA memotong MDR dari nominal yang dibayar, jadi `amount = ceil(tagihan × 100 / (100 − tarif))`, dibulatkan ke atas ke rupiah penuh. Setelah dipotong, cabang tetap menerima minimal total tagihan.

| Tagihan Rp500.000 | Biaya | Dibayar orang tua |
|---|---|---|
| VA BCA | Rp2.775 | Rp502.775 |
| Kartu (3,219%) | Rp16.631 | Rp516.631 |
| E-wallet (2,22%) | Rp11.353 | Rp511.353 |

### 3.3 DOKU (alternatif, `PAYMENT_PROVIDER=doku`)

| Channel | Tarif (+ PPN) |
|---|---|
| VA BCA | Rp4.500 → Rp4.995 |
| VA lain (BNI, BRI, Mandiri, Permata, CIMB, Danamon, BSI) | Rp4.000 → Rp4.440 |
| Kartu | 2,8% + Rp2.000 → 3,108% + Rp2.220 |
| E-wallet DANA, DOKU Wallet | 1,5% → 1,665% |
| OVO / ShopeePay / LinkAja | batas atas kisaran: 3,18% / 4% / 3,5% (+ PPN) |

Checkout yang sudah ada tetap berbicara dengan provider pembuatnya walaupun `PAYMENT_PROVIDER` diganti (`PaymentAggregator.using(record.provider)`).

---

## 4. Webhook & settlement

### 4.1 Webhook (`apps/core/webhooks.py`)

| Path | Isi |
|---|---|
| `POST /api/webhooks/payment/` | Callback pembayaran dari provider mana pun (dikenali dari signature) |
| `POST /api/webhooks/disbursement/` | Callback penarikan |
| `POST /api/webhooks/<provider>/<event>/` | Mis. `/api/webhooks/dana/payment/` |
| `POST /api/webhooks/v1.0/debit/notify` | Path standar SNAP DANA (= payment) |
| `POST /api/webhooks/v1.0/debit/emoney/transfer-bank/notify.htm` | Path standar SNAP DANA (= disbursement) |

- **Tanpa JWT dan CSRF.** Setiap handler memverifikasi signature dari raw body; signature salah dijawab 401 `INVALID_WEBHOOK`.
- **Balasan sesuai format provider** (DANA: `responseCode`).
- **Routing di webhook pembayaran:**
  - referensi `PAY-…` → checkout orang tua (`GatewayPayment`);
  - referensi `SUB-…` → pembayaran langganan cabang (`SubscriptionPayment`, lihat §6).

### 4.2 Settlement dan dompet cabang

| Saat | Dompet cabang |
|---|---|
| Checkout `paid` | `post_payment_credit`: total tagihan penuh masuk ke **pending_balance** (ledger + saldo dalam satu transaksi) |
| DANA settle | `mark_payment_settled`: pending → **available_balance**. Dicek oleh `reconcile_settlements` setiap jam (menit ke-15). |
| Malam hari (23:00) | `check_branch_balances`: saldo dompet harus sama dengan ledger. Selisih dicatat di log dan diemail ke ops (`OPS_ALERT_EMAIL`). |

Ledger adalah sumber kebenaran; saldo dompet hanyalah cache. Biaya channel tidak pernah masuk ke dompet cabang.

---

## 5. Penarikan dana cabang

### 5.1 Endpoint (staf keuangan: principal / officer)

| Kode | Method & path | Isi |
|---|---|---|
| C2 | `GET /api/wallet/` | Saldo available dan pending, `withdrawal_enabled`, `withdrawal_fee` |
| C3 / C3b | `GET /api/wallet/ledger/[{id}/]` | Mutasi ledger; detail menyertakan checkout atau penarikan terkait |
| C4 | `GET /api/payout-accounts/` | Rekening tujuan yang tersimpan |
| C7 | `POST /api/withdrawals/preview/` | Validasi, rincian (nominal, biaya, yang diterima rekening), dan kirim OTP ke email cabang |
| C8 | `POST /api/withdrawals/otp/resend/` | Kirim ulang OTP |
| C9 | `POST /api/withdrawals/` `{reference, code, fee_acknowledged: true}` | Verifikasi OTP, debit saldo, kirim disbursement |
| C10 | `GET /api/withdrawals[/{id}]/` | Status penarikan |

### 5.2 Aturan

| Aturan | Nilai |
|---|---|
| Biaya | **Rp2.500 per penarikan** (`DISBURSEMENT_FEE`, sama untuk semua provider), ditanggung sekolah: rekening menerima nominal − Rp2.500 |
| OTP | 6 digit, berlaku 3 menit, maksimal 3 kali salah (`apps/wallets/constants.py`), dikirim ke email cabang |
| Urutan aman | Debit di-commit **sebelum** provider dipanggil. Penolakan pasti → debit dibalik. Hasil tidak pasti (timeout) → tetap `processing` sampai callback atau polling (setiap 5 menit) memberi kepastian. |
| DANA | Transfer to Bank dari **Merchant Disbursement Account (MDA)**. Butuh env `DANA_PAYOUT_PHONE` dan MDA yang terisi. MDA diisi ops lewat VA di DANA Merchant Portal; settlement Gapura tidak mengisi MDA. |
| Fitur belum siap | Bila provider belum dikonfigurasi untuk penarikan, `GET /api/wallet/` menampilkan `withdrawal_enabled: false` dan aksi penarikan mengembalikan 503 `WITHDRAWAL_UNAVAILABLE`, bukan 500. |

### 5.3 Refund online

Refund berlaku untuk checkout `paid` yang ditandai `needs_refund` (mis. tagihan sudah lunas lebih dulu dengan cara lain).

- **Nominal:** seluruh nominal yang dibayar (tagihan + biaya channel) dikembalikan ke pembayar lewat DANA, dan didebit dari saldo available cabang. Ditolak bila saldo tidak cukup.
- **Urutan aman:** sama seperti penarikan, debit di-commit dulu baru DANA dipanggil.
  - Berhasil → `REFUNDED`.
  - Ditolak → `FAILED`, debit dibalik.
  - Hasil tidak pasti → `PROCESSING`. Mengulang mengirim `refund_no` yang sama, sehingga DANA tidak pernah me-refund dua kali.

---

## 6. Kaitan dengan langganan cabang (`feature/subscription-plan`)

### 6.1 Pembayaran online orang tua adalah fitur paket

| Sebelum | Sesudah |
|---|---|
| Checkbox "Enable payment gateway" di form cabang admin web (`Branch.is_payment_gateway_enabled`) | Fitur `payment_gateway` di paket langganan. Semua tier (Starter, Growth, Pro) memilikinya. |
| `branch.is_payment_gateway_enabled` dicek di `get_invoice_payability` | `entitlements.has(branch, "payment_gateway")` |

| Status langganan cabang | Orang tua |
|---|---|
| Trial (6 bulan, limit Starter), aktif, atau masa tenggang 7 hari | Bisa bayar online |
| Kedaluwarsa (setelah masa tenggang), atau dibatalkan | `GATEWAY_DISABLED`: peringatan yang sudah ada di aplikasi, tidak bisa membuat checkout baru |

Yang tidak berubah:
- **Checkout yang sudah dimulai** sebelum kedaluwarsa tetap bisa dibayar, dan pembayaran terlambat tetap diterima.
- **Dompet, settlement, penarikan, dan refund** tetap berjalan: itu uang sekolah.
- **Response API tidak berubah**: `is_payment_gateway_enabled` di B0 sekarang dihitung dari paket.
- **Cabang yang gateway-nya mati sebelum fitur langganan** tetap mati lewat override per cabang (`payment_gateway = false`, migrasi `branch_subscriptions.0002`), sampai diputuskan lain di admin web → Subscriptions.

Read-only dimulai **tepat** saat masa tenggang habis, karena setiap pengecekan menghitung status dari waktu sekarang. Tidak menunggu job per jam.

### 6.2 Tagihan langganan dibayar lewat aggregator yang sama

| | Pembayaran orang tua | Pembayaran langganan cabang |
|---|---|---|
| Tabel | `gateway_payments` | `subscription_payments` |
| Referensi | `PAY-YYYYMMDD-000123` | `SUB-YYYYMMDD-000045` |
| Pembayar | Wali siswa | Staf cabang mana pun (principal, guru, officer) |
| Biaya channel | Ditanggung pembayar (gross-up) | Ditanggung pembayar (gross-up), rumus yang sama |
| Tagihan | Tagihan siswa | Tagihan langganan (harga tier / add-on + PPN 11%) |
| Uang masuk ke | Dompet cabang (pending → available) | **Classping**. Tidak pernah menyentuh dompet cabang. |
| Webhook | `/api/webhooks/payment/` | Sama; dibedakan dari prefix `SUB-` |
| Setelah dibayar | Tagihan siswa lunas | Paket / add-on aktif, limit langsung naik |
| API | `/api/gateway/…` | `/api/subscription/invoices/{id}/channels/`, `…/checkout/`, `/api/subscription/addons/` (beli add-on langsung ke pembayaran) |

Contoh tagihan langganan dengan kartu: Starter Rp199.000 + Storage +10 GB Rp50.000 + PPN Rp27.390 = Rp276.390. Dengan biaya kartu 3,219% (Rp9.193), staf membayar **Rp285.583**.

Detail langganan: `docs/proposal-subscription-plan-draft-v3.md`.

---

## 7. Arsitektur & struktur kode

```
libs/
  payment_aggregator/                  # library reusable (pip: payment-aggregator), tanpa Django
    src/payment_aggregator/
      aggregator.py                    # PaymentAggregator(provider): facade, tanpa state global
      fees.py                          # SEMUA rumus: flat, gross-up, batas channel, biaya tarik
      base.py                          # interface provider + dataclass & status netral
      banks.py                         # kode bank tujuan penarikan
      exceptions.py                    # error dengan code stabil
      testing.py                       # FakeSession, FakeResponse, key_pair, make_provider
      providers/dana/                  # Gapura Custom Checkout, cancel, refund, Transfer to Bank
      providers/doku/                  # Checkout, Kirim DOKU
    tests/                             # unittest murni (tanpa Django)
  plan_subscriptions/                  # library langganan (lihat proposal langganan)

apps/
  payment_aggregator/                  # wiring Classping (tanpa model)
    constants.py                       # VAT_RATE 11%, DISBURSEMENT_FEE Rp2.500, with_vat()
    providers/dana.py, doku.py         # tarif kontrak, env private key, MCC 8211, build()
    aggregator.py                      # provider aktif (PAYMENT_PROVIDER) + using(name)
  payment_gateway/                     # checkout orang tua: models, services, views, tasks
  wallets/                             # dompet, ledger, rekening, OTP, penarikan
  branch_subscriptions/                # langganan cabang: SubscriptionPayment, routing SUB-
  core/webhooks.py                     # webhook generik per provider + path SNAP DANA
```

Aturan implementasi:
1. **Hanya lewat facade:** kode bisnis hanya memanggil `PaymentAggregator` (`create_billing`, `get_billing_status`, `parse_billing_callback`, `cancel_billing`, `refund_billing`, `transfer_balance`, `get_transfer_status`, `get_channels`, `calculate_transaction_fee`, `calculate_withdrawal`, …).
2. **Library tanpa aturan Classping:** library tidak berisi aturan Classping, import Django, atau tarif kontrak.
3. **Menambah provider:**
   - implementasi di `libs/payment_aggregator/.../providers/<nama>/`;
   - modul tarif di `apps/payment_aggregator/providers/<nama>.py`;
   - satu baris di `PROVIDER_MODULES`.

   Setelah itu provider bisa dipilih dengan `PAYMENT_PROVIDER=<nama>` dan otomatis mendapat URL webhook-nya.
4. **Pemanggilan HTTP:** tidak pernah dilakukan di bawah lock database. Status selalu diubah dengan row lock dan cek transisi (`can_transition_to`).

---

## 8. Env & konfigurasi

| Env | Isi |
|---|---|
| `PAYMENT_PROVIDER` | `dana` (default) atau `doku` |
| `SITE_URL` | Untuk URL notify default (`SITE_URL` + `/api/webhooks/payment/`) |
| `DANA_ENV` | `sandbox` / `production` |
| `DANA_MERCHANT_ID`, `DANA_CLIENT_ID`, `DANA_CLIENT_SECRET`, `DANA_CHANNEL_ID` | Kredensial DANA |
| `CLASSPING_DANA_PRIVATE_KEY` | Teks PEM private key **Classping** (penanda tangan request) |
| `DANA_PUBLIC_KEY` | Teks PEM public key **DANA** (bukan pasangan kunci dari dashboard kita) |
| `DANA_RETURN_URL` | Wajib; halaman kembali setelah bayar |
| `DANA_PAYOUT_PHONE` | Wajib untuk penarikan |
| `DANA_NOTIFY_URL`, `DANA_MCC` (default 8211), `DANA_BASE_URL` | Opsional |
| `DOKU_*`, `CLASSPING_DOKU_PRIVATE_KEY` | Hanya bila `PAYMENT_PROVIDER=doku` |
| `SUBSCRIPTION_TAX_RATE` (default `0.11`), `SUBSCRIPTION_TRIAL_DAYS` (default `180`) | Langganan cabang |

Kunci PEM boleh berisi baris baru asli atau `\n` literal, dan tidak pernah di-commit.

---

## 9. Admin web (superadmin)

| Menu | Isi |
|---|---|
| Online Payments | Daftar checkout orang tua (filter status / cabang / flag), detail, Sync status, Cancel, Refund |
| Wallets | Saldo per cabang, ledger |
| Withdrawals | Daftar penarikan, resend, sync, resolve |
| **Subscriptions** (baru) | Langganan per cabang: status, limit, tagihan, pembayaran `SUB-…`, aksi admin (perpanjang trial, ganti tier, override, tandai lunas via transfer bank) |
| **Plans** (baru) | Tier, harga, fitur (termasuk `payment_gateway`), add-on |
| Cabang → form | Checkbox payment gateway **dihapus**; diganti catatan bahwa gateway dan storage mengikuti paket. Detail cabang menautkan ke langganannya. |

---

## 10. Testing

- **Library `payment_aggregator`** diuji tanpa Django: `python -m unittest discover -s libs/payment_aggregator/tests -t libs/payment_aggregator`.
- **Tes wiring** (`apps/payment_aggregator/tests.py`) mengunci:
  - DANA sebagai default;
  - tarif DANA per channel dan QRIS yang tidak ditawarkan;
  - biaya tarik Rp2.500;
  - env `CLASSPING_DANA_PRIVATE_KEY`;
  - `DANA_PAYOUT_PHONE` yang wajib untuk penarikan.
- **Checkout, expiry, race condition** (pembayaran bersamaan dengan expiry / cancel, callback ganda), **settlement, penarikan, dan refund** diuji di `apps/payment_gateway` dan `apps/wallets`.
- **Langganan** (`apps/branch_subscriptions/tests.py`) menguji:
  - gateway mati setelah kedaluwarsa, tepat di akhir masa tenggang;
  - checkout `SUB-` lewat webhook yang sama menaikkan limit tanpa menyentuh dompet;
  - idempotency pembelian add-on.
- **Hasil di `feature/subscription-plan`:** 551 tes. Semua lulus, kecuali 4 error dari dua file tes yang belum di-track (`apps/core/test_provider_down.py`, `apps/wallets/test_unavailable.py`). Keduanya meng-import `api_exception_handler`, yang belum ada di branch ini.

---

## 11. Checklist go-live

| # | Item |
|---|---|
| 1 | `PAYMENT_PROVIDER=dana`, semua env DANA terisi di `.env.production` (§8) |
| 2 | Public key Classping terdaftar di DANA; `DANA_PUBLIC_KEY` berisi key **milik DANA** |
| 3 | URL notify terdaftar di DANA: `/api/webhooks/payment/` (atau path SNAP); callback sandbox lolos verifikasi signature |
| 4 | MDA DANA terisi dan `DANA_PAYOUT_PHONE` diset sebelum penarikan diaktifkan |
| 5 | Image dibangun ulang (`docker compose build`) agar `libs/payment_aggregator` dan `libs/plan_subscriptions` terpasang |
| 6 | Migrasi dijalankan: `plan_subscriptions.0001`, `branch_subscriptions.0001–0002`. Setiap cabang mendapat langganan (trial Starter). |
| 7 | Worker + beat Celery berjalan: settlement (per jam), polling penarikan (5 menit), cek saldo (23:00), job langganan |
| 8 | Template Mailjet terpasang: OTP penarikan, status penarikan, alert saldo, 7 email langganan |
| 9 | `feature/subscription-plan` di-rebase ke `dev` (14 commit tertinggal) sebelum PR |

---

## 12. Pertanyaan terbuka

1. **Biaya bank VA.** Tarif VA Rp2.775 belum termasuk biaya bank masing-masing (disepakati Classping dengan tiap bank). Berapa per bank, dan apakah ikut dibebankan ke orang tua?
2. **Tier e-wallet DANA.** Saat ini dipakai 2% + PPN (tier tertinggi) supaya cabang tidak pernah kurang. Bila kontrak 1,5%, turunkan `MDR_EWALLET`.
3. **Gateway untuk cabang lama.** Cabang yang dulu mematikan gateway tetap mati lewat override. Apakah semua cabang langsung mendapat gateway sesuai paket saat launch?
4. **Cabang lama saat launch.** Trial 6 bulan dengan limit Starter (usulan saat ini), atau langsung bayar sesuai tier?
5. **Pengisian MDA.** Siapa yang mengisi MDA DANA, seberapa sering, dan berapa saldo minimum sebelum penarikan diblok?
