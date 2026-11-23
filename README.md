# Excellent Store — Web Full-Stack

Toko produk digital versi web (Flask + SQLite). Pembayaran langsung di web:
QRIS dinamis, transfer bank/e-wallet, Binance Pay (USDT). Terintegrasi dengan
database ExcellentStoreBot bila tersedia, atau jalan mode demo mandiri.

## Struktur

```
excellent-web-full/
├── app.py              # aplikasi Flask (katalog, keranjang, checkout, /notify, admin)
├── models.py           # model SQLAlchemy (kompatibel tabel bot)
├── qris.py             # QRIS dinamis (diadaptasi dari bot)
├── seed_demo.py        # seed 12 produk dummy -> demo.db
├── config.py           # KONFIGURASI (jangan commit; lihat config.example.py)
├── config.example.py   # contoh konfigurasi
├── requirements.txt
├── templates/          # HTML (base, index, produk, keranjang, checkout, bayar, ...)
│   └── admin/          # login, dashboard, produk, order
├── static/             # style.css, logo.jpg
└── README.md
```

## Instalasi (STB Armbian / Linux)

```bash
# 1. Masuk folder & install dependensi
cd ~/excellent-web-full
pip install -r requirements.txt   # butuh: flask, sqlalchemy

# 2. Buat config dari contoh, lalu isi
cp config.example.py config.py
nano config.py
#   - SECRET_KEY      : string acak panjang
#   - ADMIN_PASSWORD  : password panel admin
#   - NOTIFY_SECRET   : rahasia header X-Secret untuk /notify
#   - STATIC_QRIS     : string QRIS statis dari DANA Bisnis (opsional)
#   - ACCOUNTS        : daftar rekening/e-wallet (opsional)
#   - BINANCE_*       : konfigurasi Binance Pay (opsional)

# 3a. MODE DEMO (tanpa bot): seed database contoh
python3 seed_demo.py        # -> demo.db (12 produk + 60 stok)

# 3b. MODE PRODUKSI (sharing DB bot): isi di config.py
#   DB_PATH = "/opt/ExcellentStoreBot/data/bot.db"   # sesuaikan path
#   Pastikan user web_guest ada (dibuat otomatis saat checkout pertama).

# 4. Jalankan
python3 app.py              # -> http://0.0.0.0:5000

# 5. (opsional) systemd agar jalan otomatis saat boot
```

### Systemd (opsional)

```ini
# /etc/systemd/system/excellent-web.service
[Unit]
Description=Excellent Store Web
After=network.target

[Service]
WorkingDirectory=/home/USER/excellent-web-full
ExecStart=/usr/bin/python3 app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now excellent-web
```

## Menghubungkan ke Database Bot

1. Cari file SQLite bot (biasanya `data/bot.db` di folder bot).
2. Isi `DB_PATH` di `config.py` dengan path absolutnya.
3. Web membaca tabel `products`, `stock_items`, `categories` langsung —
   produk & stok yang diatur via bot otomatis tampil di web.
4. Order web memakai user khusus `web_guest` (tg_id=-1, dibuat otomatis).
5. Format invoice sama dengan bot: `INV-EXC-YYYYMMDD-KODE0001`.
6. **Jangan** jalankan web dan bot dengan transaksi bersamaan pada file DB
   yang sama bila memakai SQLite via jaringan — di satu mesin (STB) aman.

## Notifikasi Pembayaran (/notify)

Format sama seperti bot. Notifier HP / script POST ke:

```
POST /notify
Header: X-Secret: <NOTIFY_SECRET>
Body (JSON): {"amount": 25000, "source": "dana", "ref": "unik-123"}
             {"source": "binance", "usdt": "1.3097", "ref": "unik-456"}
```

- `source`: dana | seabank | jago | gopay | ovo | bsi | binance
- Rupiah: dicocokkan ke `unique_amount` invoice OPEN (toleransi ±Rp100).
- Binance: dicocokkan ke USDT = total × (1+fee) / rate_terkunci (±0.01).
- Idempotent via `ref` (duplikat tidak dobel-settle).
- `POST /notify/ping` → `{"ok": true}` (health check notifier).

## Alur Checkout Web

1. Pilih produk → keranjang (session browser).
2. Checkout → pilih metode (QRIS / Transfer / Binance).
3. Halaman bayar: QR dinamis / nomor rekening / wallet USDT.
   Polling status tiap 5 detik.
4. Setelah bayar terdeteksi → halaman sukses menampilkan produk digital
   (payload dari `stock_items`).

## Panel Admin

- Buka `/admin`, login dengan `ADMIN_PASSWORD`.
- Dashboard: statistik produk/stok/order.
- Produk: aktif/nonaktif, tambah stok (payload teks).
- Order: daftar 50 order terakhir + status.

## Catatan

- QRIS dinamis dibuat lokal dari QRIS statis (tanpa gateway, tanpa biaya).
- Rate USDT/IDR otomatis dari CoinGecko (cache 15 menit) bila
  `BINANCE_RATE_SOURCE = "api"`, atau isi manual.
- Mode demo: tombol "Simulasikan Pembayaran" tampil di halaman bayar.
