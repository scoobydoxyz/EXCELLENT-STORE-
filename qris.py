"""QRIS dinamis — diadaptasi dari logika ExcellentStoreBot (app/dana/qris.py).

Standar EMVCo/QRIS:
  1. Ambil string QRIS STATIS milik toko.
  2. Ubah tag 01 dari "11" (statis) menjadi "12" (dinamis).
  3. Sisipkan tag 54 = nominal rupiah tepat (tanpa desimal).
  4. Hitung ulang CRC16-CCITT (tag 63).

Fungsi di sini murni (tanpa DB/jaringan) agar mudah dites.
"""
from __future__ import annotations


def parse_tlv(s: str) -> dict:
    out, i = {}, 0
    s = (s or "").strip()
    while i + 4 <= len(s):
        tag, ln_s = s[i:i + 2], s[i + 2:i + 4]
        if not tag.isdigit() or not ln_s.isdigit():
            raise ValueError(f"TLV rusak di posisi {i}")
        ln = int(ln_s)
        val = s[i + 4:i + 4 + ln]
        if len(val) != ln:
            raise ValueError(f"TLV terpotong di tag {tag}")
        out[tag] = val
        i += 4 + ln
    if i != len(s):
        raise ValueError("TLV ada sisa karakter")
    return out


def build_tlv(fields: dict) -> str:
    parts = []
    for tag in sorted(fields, key=int):
        v = fields[tag]
        if len(v) > 99:
            raise ValueError(f"nilai tag {tag} terlalu panjang")
        parts.append(f"{tag}{len(v):02d}{v}")
    return "".join(parts)


def crc16_ccitt(data: str) -> str:
    crc = 0xFFFF
    for ch in data.encode("utf-8"):
        crc ^= ch << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def verify_crc(qr: str) -> bool:
    try:
        parse_tlv(qr)
    except ValueError:
        return False
    body, crc = qr[:-8], qr[-4:]
    return qr[-8:-4] == "6304" and crc16_ccitt(body + "6304") == crc.upper()


def make_dynamic(static_qr: str, amount: int) -> str:
    """Buat QRIS dinamis dari QRIS statis + nominal rupiah (tanpa desimal)."""
    amount = int(amount)
    if amount <= 0:
        raise ValueError("nominal harus > 0")
    if amount >= 10 ** 12:
        raise ValueError("nominal terlalu besar")
    fields = parse_tlv(static_qr)
    if fields.get("00") != "01":
        raise ValueError("bukan payload QRIS (tag 00)")
    if not verify_crc(static_qr):
        raise ValueError("CRC QRIS statis tidak valid")
    fields["01"] = "12"          # dinamis
    fields["54"] = str(amount)   # nominal tepat
    fields.pop("63", None)
    body = build_tlv(fields) + "6304"
    return body + crc16_ccitt(body)
