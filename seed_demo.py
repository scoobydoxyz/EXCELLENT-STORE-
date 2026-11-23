"""Seed database demo: 12 produk digital dummy + stok contoh.

Jalankan:  python3 seed_demo.py
"""
import hashlib
import sys
from decimal import Decimal

sys.path.insert(0, ".")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from models import Base, Category, Product, StockItem, User

DB = "demo.db"

PRODUCTS = [
    # (code, nama, kategori, harga, deskripsi)
    ("NF", "Netflix Premium 1 Bulan", "streaming", 65000,
     "Akun Netflix Premium 4K UHD, 1 bulan penuh. Private profile, garansi."),
    ("SP", "Spotify Premium 1 Bulan", "musik", 55000,
     "Akun Spotify Premium individual 1 bulan. Bebas iklan, download offline."),
    ("CV", "Canva Pro 1 Bulan", "desain", 35000,
     "Canva Pro via invite tim 1 bulan. Semua fitur premium terbuka."),
    ("CC", "CapCut Pro 1 Bulan", "desain", 25000,
     "CapCut Pro 1 bulan via login. Efek & template premium terbuka."),
    ("YP", "YouTube Premium 1 Bulan", "streaming", 45000,
     "YouTube Premium 1 bulan. Tanpa iklan + YouTube Music."),
    ("M365", "Microsoft 365 1 Tahun", "produktivitas", 150000,
     "Microsoft 365 Personal 1 tahun. Word, Excel, PowerPoint + 1TB OneDrive."),
    ("AD", "Adobe Creative Cloud 1 Bulan", "desain", 120000,
     "Adobe CC All Apps 1 bulan. Photoshop, Premiere, Illustrator, dll."),
    ("DS", "Disney+ Hotstar 1 Bulan", "streaming", 40000,
     "Disney+ Hotstar 1 bulan. Film Disney, Marvel, Star Wars."),
    ("GPT", "ChatGPT Plus 1 Bulan", "ai", 300000,
     "ChatGPT Plus 1 bulan. Akses GPT terbaru, prioritas saat ramai."),
    ("VIU", "Viu Premium 1 Bulan", "streaming", 30000,
     "Viu Premium 1 bulan. Drakor & variety show tanpa iklan."),
    ("VD", "Vidio Platinum 1 Bulan", "streaming", 35000,
     "Vidio Platinum 1 bulan. Liga Inggris & konten premium."),
    ("G1", "Google One 100GB 1 Bulan", "produktivitas", 27000,
     "Google One 100GB 1 bulan via invite keluarga."),
]

CATS = [
    ("streaming", "Streaming"),
    ("musik", "Musik"),
    ("desain", "Desain"),
    ("produktivitas", "Produktivitas"),
    ("ai", "AI Tools"),
]

STOK_PER_PRODUK = 5


def main():
    import os
    if os.path.exists(DB):
        print(f"{DB} sudah ada — hapus dulu bila ingin seed ulang.")
        return
    engine = create_engine(f"sqlite:///{DB}")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()

    cat_map = {}
    for slug, name in CATS:
        c = Category(name=name, slug=slug, active=True)
        s.add(c)
        s.flush()
        cat_map[slug] = c.id

    for code, nama, cat, harga, desc in PRODUCTS:
        p = Product(
            sku=f"DEMO-{code}", code=code, name=nama, description=desc,
            category_id=cat_map[cat], price=Decimal(harga),
            type="digital", active=True, archived=False,
        )
        s.add(p)
        s.flush()
        for i in range(1, STOK_PER_PRODUK + 1):
            payload = f"[DEMO] {nama} — kode: DEMO-{code}-{i:03d} (ganti dengan data asli)"
            s.add(StockItem(
                product_id=p.id, payload=payload,
                checksum=hashlib.sha256(payload.encode()).hexdigest(),
                status="AVAILABLE",
            ))

    # user khusus order web
    s.add(User(tg_id=-1, username="web_guest", full_name="Web Guest", lang="id"))
    s.commit()
    n_prod = s.query(Product).count()
    n_stok = s.query(StockItem).count()
    print(f"OK: {n_prod} produk, {n_stok} stok di {DB}")
    s.close()


if __name__ == "__main__":
    main()
