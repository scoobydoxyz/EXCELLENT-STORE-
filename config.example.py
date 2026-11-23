# ---- Database ----
# Kosongkan untuk mode demo (buat database sendiri + seed produk dummy).
# Isi path file SQLite bot untuk mode produksi, contoh:
# DB_PATH = "/storage/emulated/0/ExcellentStoreBot/data/bot.db"
DB_PATH = ""

# ---- Keamanan ----
SECRET_KEY = "ganti-dengan-string-acak-panjang"
ADMIN_PASSWORD = "ganti-password-admin"

# ---- Notifikasi pembayaran (/notify) ----
# Rahasia yang harus dikirim notifier di header X-Secret
NOTIFY_SECRET = "ganti-rahasia-notify"

# ---- QRIS ----
# String QRIS statis dari DANA Bisnis (tempel di sini atau via panel admin nanti).
# Biarkan kosong bila belum ada — metode QRIS otomatis nonaktif.
STATIC_QRIS = ""

# ---- Rekening / E-Wallet (tampil di checkout) ----
# Format: {"nama": "...", "nomor": "...", "pemilik": "...", "jenis": "bank|ewallet"}
ACCOUNTS = [
    # {"nama": "DANA / ShopeePay / GoPay", "nomor": "0851xxxx", "pemilik": "Nama Kamu", "jenis": "ewallet"},
    # {"nama": "SeaBank", "nomor": "901xxx", "pemilik": "Nama Kamu", "jenis": "bank"},
]

# ---- Binance ----
BINANCE_ENABLED = False
BINANCE_WALLET = ""
BINANCE_NETWORK = "TRC20"
BINANCE_FEE_PCT = 2.0
# "api" = ambil kurs otomatis dari CoinGecko tiap request (cache 15 menit),
# atau isi angka manual mis. 17900
BINANCE_RATE_SOURCE = "api"

# ---- Umum ----
ORDER_EXPIRY_MINUTES = 30
TOLERANCE_RUPIAH = 100  # toleransi pencocokan nominal
