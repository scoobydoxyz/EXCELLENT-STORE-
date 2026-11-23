"""Excellent Store — web full-stack (Flask + SQLite).

Mode demo    : DB_PATH kosong -> pakai demo.db (seed via seed_demo.py)
Mode produksi: DB_PATH menunjuk file SQLite milik ExcellentStoreBot
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from functools import wraps

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   session, url_for)
from sqlalchemy import create_engine, func, or_, select
from sqlalchemy.orm import sessionmaker

import models
from models import (Base, Category, Invoice, Order, OrderItem, Payment, Product,
                    StockItem, User)

try:
    import config as C
except ImportError:
    C = None  # semua akses via getattr(..., default)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.secret_key = getattr(C, "SECRET_KEY", "dev-secret-ganti-di-config")
app.config["JSON_AS_ASCII"] = False

DB_PATH = getattr(C, "DB_PATH", "") or ""
DEMO_DB = os.path.join(BASE_DIR, "demo.db")
ACTIVE_DB = DB_PATH if (DB_PATH and os.path.exists(DB_PATH)) else DEMO_DB
DEMO_MODE = ACTIVE_DB == DEMO_DB

engine = create_engine(f"sqlite:///{ACTIVE_DB}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)

CFG = {
    "static_qris": getattr(C, "STATIC_QRIS", "") or "",
    "accounts": getattr(C, "ACCOUNTS", []) or [],
    "binance_enabled": bool(getattr(C, "BINANCE_ENABLED", False)),
    "binance_wallet": getattr(C, "BINANCE_WALLET", "") or "",
    "binance_network": getattr(C, "BINANCE_NETWORK", "TRC20") or "TRC20",
    "binance_fee": float(getattr(C, "BINANCE_FEE_PCT", 2.0) or 0),
    "binance_rate_source": getattr(C, "BINANCE_RATE_SOURCE", "api") or "api",
    "notify_secret": getattr(C, "NOTIFY_SECRET", "") or "",
    "expiry_min": int(getattr(C, "ORDER_EXPIRY_MINUTES", 30) or 30),
    "tolerance": int(getattr(C, "TOLERANCE_RUPIAH", 100) or 100),
    "admin_password": getattr(C, "ADMIN_PASSWORD", "") or "",
}

_rate_cache = {"value": 0, "ts": 0}


# ============ helper ============

def db():
    s = Session()
    return s


@app.teardown_appcontext
def _close(exc):
    pass


def rupiah(v) -> str:
    try:
        return "Rp " + f"{int(Decimal(str(v))):,}".replace(",", ".")
    except Exception:
        return f"Rp {v}"


app.jinja_env.filters["rupiah"] = rupiah


def get_web_user(s) -> User:
    u = s.execute(select(User).where(User.tg_id == -1)).scalar_one_or_none()
    if not u:
        u = User(tg_id=-1, username="web_guest", full_name="Web Guest", lang="id")
        s.add(u)
        s.flush()
    return u


def stock_count(s, product_id: int) -> int:
    return s.execute(
        select(func.count()).select_from(StockItem).where(
            StockItem.product_id == product_id,
            StockItem.status == "AVAILABLE")).scalar() or 0


def used_unique_codes(s) -> set:
    rows = s.execute(
        select(Invoice.unique_amount).where(Invoice.status == "OPEN")).scalars().all()
    out = set()
    for ua in rows:
        try:
            out.add(int(Decimal(str(ua)) % 100))
        except Exception:
            pass
    return out


def next_unique_code(s) -> int:
    used = used_unique_codes(s)
    for i in range(100):
        if i not in used:
            return i
    return 0


def make_invoice_no(s, product: Product) -> str:
    product.sold_seq = int(product.sold_seq or 0) + 1
    s.flush()
    pcode = (getattr(product, "code", "") or "PRD").upper()
    return f"INV-EXC-{datetime.now().strftime('%Y%m%d')}-{pcode}{product.sold_seq:04d}"


def get_rate() -> float:
    """Kurs USDT/IDR: manual dari config atau CoinGecko (cache 15 mnt)."""
    src = CFG["binance_rate_source"]
    try:
        if float(src) > 0:
            return float(src)
    except (TypeError, ValueError):
        pass
    now = time.time()
    if _rate_cache["value"] and now - _rate_cache["ts"] < 900:
        return _rate_cache["value"]
    try:
        req = urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=idr",
            headers={"User-Agent": "ExcellentStoreWeb/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
            val = float(data["tether"]["idr"])
            _rate_cache.update(value=val, ts=now)
            return val
    except Exception:
        return _rate_cache["value"] or 0


def cart_items(s):
    cart = session.get("cart", {})
    items, total = [], Decimal(0)
    for pid_s, qty in cart.items():
        try:
            pid, qty = int(pid_s), int(qty)
        except (TypeError, ValueError):
            continue
        p = s.get(Product, pid)
        if not p or not p.active or p.archived:
            continue
        sub = p.price * qty
        total += sub
        items.append({"product": p, "qty": qty, "subtotal": sub,
                      "stok": stock_count(s, pid)})
    return items, total


def pay_methods():
    m = []
    if CFG["static_qris"]:
        m.append({"code": "qris", "nama": "QRIS", "icon": "🔍",
                  "desc": "Scan QR — semua e-wallet & m-banking"})
    if CFG["accounts"]:
        m.append({"code": "transfer", "nama": "Transfer Bank / E-Wallet", "icon": "💳",
                  "desc": "DANA, GoPay, ShopeePay, bank lokal"})
    if CFG["binance_enabled"] and CFG["binance_wallet"]:
        m.append({"code": "binance", "nama": "Binance Pay (USDT)", "icon": "🟡",
                  "desc": f"Crypto via {CFG['binance_network']}"})
    return m


def settle_order(s, order: Order, adapter: str, amount, ref: str, note: str = ""):
    """Tandai lunas + alokasikan stok. Idempotent via provider_ref."""
    dup = s.execute(select(Payment).where(
        Payment.order_id == order.id, Payment.provider_ref == ref)
    ).scalar_one_or_none()
    if dup:
        return {"ok": True, "duplicate": True}
    inv = order.invoice
    if inv:
        inv.status = "PAID"
    s.add(Payment(order_id=order.id, adapter=adapter, state="PAID",
                  amount=Decimal(str(amount)), provider_ref=ref, note=note))
    delivered = []
    for item in order.items:
        for _ in range(item.qty):
            st = s.execute(select(StockItem).where(
                StockItem.product_id == item.product_id,
                StockItem.status == "AVAILABLE")
                .order_by(StockItem.id).limit(1)).scalar_one_or_none()
            if not st:
                break
            st.status = "SOLD"
            st.locked_order_id = order.id
            delivered.append({"nama": item.product.name, "payload": st.payload})
    order.state = "COMPLETED" if delivered else "PAID"
    s.commit()
    return {"ok": True, "delivered": delivered}


def try_expire(s, order: Order):
    if order.state == "WAITING_PAYMENT" and order.expires_at:
        exp = order.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            order.state = "EXPIRED"
            if order.invoice:
                order.invoice.status = "EXPIRED"
            s.commit()
            return True
    return False


# ============ katalog ============

@app.route("/")
def index():
    s = db()
    try:
        q = request.args.get("q", "").strip()
        cat = request.args.get("cat", "").strip()
        cats = s.execute(select(Category).where(Category.active == True)  # noqa: E712
                         .order_by(Category.name)).scalars().all()
        stmt = select(Product).where(Product.active == True,  # noqa: E712
                                     Product.archived == False)  # noqa: E712
        if cat:
            stmt = stmt.where(Product.category_id == int(cat)) if cat.isdigit() \
                else stmt.where(Product.category.has(slug=cat))
        if q:
            stmt = stmt.where(or_(Product.name.ilike(f"%{q}%"),
                                  Product.description.ilike(f"%{q}%")))
        products = s.execute(stmt.order_by(Product.name)).scalars().all()
        stok = {p.id: stock_count(s, p.id) for p in products}
        return render_template("index.html", products=products, cats=cats,
                               stok=stok, q=q, cat=cat,
                               cart_n=sum(session.get("cart", {}).values()))
    finally:
        s.close()


@app.route("/produk/<int:pid>")
def produk(pid):
    s = db()
    try:
        p = s.get(Product, pid)
        if not p or not p.active or p.archived:
            abort(404)
        return render_template("produk.html", p=p, stok=stock_count(s, pid),
                               cart_n=sum(session.get("cart", {}).values()))
    finally:
        s.close()


# ============ keranjang (session) ============

@app.route("/api/keranjang/tambah", methods=["POST"])
def k_tambah():
    s = db()
    try:
        pid = int(request.form.get("pid", 0))
        qty = max(1, min(99, int(request.form.get("qty", 1))))
        p = s.get(Product, pid)
        if not p or not p.active or p.archived:
            return jsonify({"ok": False, "error": "Produk tidak tersedia"}), 400
        if stock_count(s, pid) < qty:
            return jsonify({"ok": False, "error": "Stok tidak cukup"}), 400
        cart = session.get("cart", {})
        cart[str(pid)] = min(99, cart.get(str(pid), 0) + qty)
        session["cart"] = cart
        return jsonify({"ok": True, "n": sum(cart.values())})
    finally:
        s.close()


@app.route("/api/keranjang/hapus", methods=["POST"])
def k_hapus():
    cart = session.get("cart", {})
    cart.pop(str(request.form.get("pid", "")), None)
    session["cart"] = cart
    return jsonify({"ok": True, "n": sum(cart.values())})


@app.route("/keranjang")
def keranjang():
    s = db()
    try:
        items, total = cart_items(s)
        return render_template("keranjang.html", items=items, total=total)
    finally:
        s.close()


# ============ checkout ============

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    s = db()
    try:
        items, total = cart_items(s)
        if not items:
            return redirect(url_for("index"))
        methods = pay_methods()
        if request.method == "POST":
            method = request.form.get("method", "")
            if method not in [m["code"] for m in methods]:
                return render_template("checkout.html", items=items, total=total,
                                       methods=methods, error="Pilih metode pembayaran.")
            for it in items:
                if it["stok"] < it["qty"]:
                    return render_template(
                        "checkout.html", items=items, total=total, methods=methods,
                        error=f"Stok {it['product'].name} tidak cukup.")
            user = get_web_user(s)
            first = items[0]["product"]
            inv_no = make_invoice_no(s, first)
            code = next_unique_code(s)
            unique_amount = int(total) + code
            exp = datetime.now(timezone.utc) + timedelta(minutes=CFG["expiry_min"])
            order = Order(invoice_no=inv_no, user_id=user.id, state="WAITING_PAYMENT",
                          subtotal=total, total=total, expires_at=exp, pay_method=method)
            s.add(order)
            s.flush()
            for it in items:
                s.add(OrderItem(order_id=order.id, product_id=it["product"].id,
                                qty=it["qty"], unit_price=it["product"].price))
            s.add(Invoice(order_id=order.id, total=total,
                          unique_amount=Decimal(unique_amount), status="OPEN"))
            s.commit()
            session.pop("cart", None)
            return redirect(url_for("bayar", invoice=inv_no))
        return render_template("checkout.html", items=items, total=total,
                               methods=methods)
    finally:
        s.close()


# ============ pembayaran ============

def _pay_context(s, order: Order):
    inv = order.invoice
    ctx = {"order": order, "inv": inv, "method": order.pay_method,
           "exp_min": CFG["expiry_min"]}
    if order.pay_method == "qris":
        from qris import make_dynamic
        ctx["qris_str"] = make_dynamic(CFG["static_qris"], int(inv.unique_amount))
        ctx["amount"] = int(inv.unique_amount)
    elif order.pay_method == "transfer":
        ctx["accounts"] = CFG["accounts"]
        ctx["amount"] = int(inv.unique_amount)
    elif order.pay_method == "binance":
        rate = order.rate_locked and float(order.rate_locked) or get_rate()
        if not order.rate_locked and rate:
            order.rate_locked = Decimal(str(rate))
            s.commit()
        fee = CFG["binance_fee"]
        usdt = (float(order.total) / rate * (1 + fee / 100)) if rate else 0
        ctx.update(rate=rate, fee=fee, usdt=f"{usdt:.4f}",
                   wallet=CFG["binance_wallet"], network=CFG["binance_network"],
                   amount=float(order.total))
    return ctx


@app.route("/bayar/<invoice>")
def bayar(invoice):
    s = db()
    try:
        order = s.execute(select(Order).where(
            Order.invoice_no == invoice)).scalar_one_or_none()
        if not order:
            abort(404)
        try_expire(s, order)
        if order.state in ("COMPLETED", "PAID"):
            return redirect(url_for("sukses", invoice=invoice))
        if order.state != "WAITING_PAYMENT":
            return render_template("status.html", order=order)
        ctx = _pay_context(s, order)
        return render_template("bayar.html", **ctx, demo=DEMO_MODE)
    finally:
        s.close()


@app.route("/api/order/<invoice>/status")
def api_status(invoice):
    s = db()
    try:
        order = s.execute(select(Order).where(
            Order.invoice_no == invoice)).scalar_one_or_none()
        if not order:
            return jsonify({"ok": False}), 404
        try_expire(s, order)
        return jsonify({"ok": True, "state": order.state,
                        "invoice": order.invoice_no})
    finally:
        s.close()


@app.route("/sukses/<invoice>")
def sukses(invoice):
    s = db()
    try:
        order = s.execute(select(Order).where(
            Order.invoice_no == invoice)).scalar_one_or_none()
        if not order or order.state not in ("PAID", "COMPLETED"):
            abort(404)
        delivered = []
        for item in order.items:
            rows = s.execute(select(StockItem).where(
                StockItem.locked_order_id == order.id,
                StockItem.product_id == item.product_id)).scalars().all()
            for st in rows:
                delivered.append({"nama": item.product.name, "payload": st.payload})
        return render_template("sukses.html", order=order, delivered=delivered)
    finally:
        s.close()


@app.route("/lacak", methods=["GET", "POST"])
def lacak():
    order, error = None, ""
    if request.method == "POST":
        inv = (request.form.get("invoice") or "").strip().upper()
        s = db()
        try:
            order = s.execute(select(Order).where(
                Order.invoice_no == inv)).scalar_one_or_none()
            if not order:
                error = "Invoice tidak ditemukan."
            else:
                try_expire(s, order)
        finally:
            s.close()
    return render_template("lacak.html", order=order, error=error)


# ============ /notify (format sama seperti bot) ============

@app.route("/notify", methods=["POST"])
def notify():
    if CFG["notify_secret"]:
        if request.headers.get("X-Secret", "") != CFG["notify_secret"]:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    amount = data.get("amount")
    source = (data.get("source") or "").lower()
    usdt = str(data.get("usdt") or "")
    ref = str(data.get("ref") or data.get("event_id")
              or f"{source}-{amount}-{int(time.time())}")
    s = db()
    try:
        now = datetime.now(timezone.utc)
        open_orders = s.execute(
            select(Order).where(Order.state == "WAITING_PAYMENT")).scalars().all()
        matched = None
        for o in open_orders:
            try_expire(s, o)
            if o.state != "WAITING_PAYMENT" or not o.invoice:
                continue
            if source == "binance" and o.pay_method == "binance" and usdt:
                rate = float(o.rate_locked or get_rate() or 0)
                if not rate:
                    continue
                exp_usdt = float(o.total) / rate * (1 + CFG["binance_fee"] / 100)
                if abs(float(usdt) - exp_usdt) <= 0.01:
                    matched = o
                    break
            elif amount is not None and o.pay_method in ("qris", "transfer"):
                try:
                    if abs(float(amount) - float(o.invoice.unique_amount)) \
                            <= CFG["tolerance"]:
                        matched = o
                        break
                except (TypeError, ValueError):
                    pass
        if not matched:
            return jsonify({"ok": True, "matched": False})
        adapter = {"qris": "qris", "transfer": "bank"}.get(
            matched.pay_method, matched.pay_method)
        r = settle_order(s, matched, adapter, amount or 0, f"web-{ref}",
                         note=f"notify source={source}")
        return jsonify({"ok": True, "matched": True,
                        "invoice": matched.invoice_no,
                        "state": matched.state, **r})
    finally:
        s.close()


@app.route("/notify/ping", methods=["POST"])
def notify_ping():
    return jsonify({"ok": True})


@app.route("/health")
def health():
    return jsonify({"ok": True, "demo": DEMO_MODE, "db": ACTIVE_DB})


# ============ admin ============

def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get("admin_ok"):
            return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return w


@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    err = ""
    if request.method == "POST":
        if request.form.get("password") == CFG["admin_password"] and CFG["admin_password"]:
            session["admin_ok"] = True
            return redirect(url_for("admin_dash"))
        err = "Password salah."
    return render_template("admin/login.html", error=err)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_ok", None)
    return redirect(url_for("index"))


@app.route("/admin/dashboard")
@admin_required
def admin_dash():
    s = db()
    try:
        stats = {
            "produk": s.execute(select(func.count()).select_from(Product)).scalar(),
            "stok": s.execute(select(func.count()).select_from(StockItem)
                              .where(StockItem.status == "AVAILABLE")).scalar(),
            "order_open": s.execute(select(func.count()).select_from(Order)
                                    .where(Order.state == "WAITING_PAYMENT")).scalar(),
            "order_done": s.execute(select(func.count()).select_from(Order)
                                    .where(Order.state.in_(["PAID", "COMPLETED"]))).scalar(),
        }
        recent = s.execute(select(Order).order_by(Order.id.desc()).limit(10)
                           ).scalars().all()
        return render_template("admin/dashboard.html", stats=stats, recent=recent)
    finally:
        s.close()


@app.route("/admin/produk")
@admin_required
def admin_produk():
    s = db()
    try:
        products = s.execute(select(Product).order_by(Product.name)).scalars().all()
        stok = {p.id: stock_count(s, p.id) for p in products}
        return render_template("admin/produk.html", products=products, stok=stok)
    finally:
        s.close()


@app.route("/admin/produk/<int:pid>/toggle", methods=["POST"])
@admin_required
def admin_toggle(pid):
    s = db()
    try:
        p = s.get(Product, pid)
        if p:
            p.active = not p.active
            s.commit()
    finally:
        s.close()
    return redirect(url_for("admin_produk"))


@app.route("/admin/produk/<int:pid>/stok", methods=["POST"])
@admin_required
def admin_stok(pid):
    s = db()
    try:
        payload = (request.form.get("payload") or "").strip()
        if payload and s.get(Product, pid):
            s.add(StockItem(product_id=pid, payload=payload,
                            checksum=hashlib.sha256(payload.encode()).hexdigest(),
                            status="AVAILABLE"))
            s.commit()
    finally:
        s.close()
    return redirect(url_for("admin_produk"))


@app.route("/admin/order")
@admin_required
def admin_order():
    s = db()
    try:
        orders = s.execute(select(Order).order_by(Order.id.desc()).limit(50)
                           ).scalars().all()
        return render_template("admin/order.html", orders=orders)
    finally:
        s.close()


# ============ demo helper ============

@app.route("/api/demo/bayar/<invoice>", methods=["POST"])
def demo_bayar(invoice):
    """Tombol simulasi pembayaran — HANYA mode demo."""
    if not DEMO_MODE:
        abort(403)
    s = db()
    try:
        order = s.execute(select(Order).where(
            Order.invoice_no == invoice)).scalar_one_or_none()
        if not order or order.state != "WAITING_PAYMENT":
            return jsonify({"ok": False}), 400
        amt = float(order.invoice.unique_amount) if order.invoice else float(order.total)
        r = settle_order(s, order, order.pay_method or "demo", amt,
                         f"demo-{invoice}", note="simulasi demo")
        return jsonify({"ok": True, **r})
    finally:
        s.close()


if __name__ == "__main__":
    if DEMO_MODE and not os.path.exists(DEMO_DB):
        print("demo.db belum ada — jalankan: python3 seed_demo.py")
    print(f"DB aktif : {ACTIVE_DB}  (demo={DEMO_MODE})")
    print(f"Metode   : {[m['code'] for m in pay_methods()] or ['-belum ada-']}")
    app.run(host="0.0.0.0", port=5000, debug=False)
