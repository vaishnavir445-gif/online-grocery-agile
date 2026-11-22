"""Online Grocery Application - Flask + SQLite prototype (Agile Final Jury).

SIMULATED (not live): the payment gateway and delivery tracking.
No real money, GPS or notification service is used anywhere.
"""
import os
import re
import sqlite3
from datetime import datetime

from flask import (Flask, abort, current_app, flash, g, redirect,
                   render_template, request, session, url_for)

MAX_QTY = 10                 # business rule: max units of one item per order
DELIVERY_FEE = 30            # rupees
FREE_DELIVERY_AT = 300       # subtotal at/above this gets free delivery
STATUS_FLOW = ["Placed", "Packed", "Out for Delivery", "Delivered"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
  unit TEXT NOT NULL, price INTEGER NOT NULL CHECK(price > 0),
  stock INTEGER NOT NULL CHECK(stock >= 0), emoji TEXT);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY, customer_name TEXT, phone TEXT, address TEXT,
  subtotal INTEGER, delivery_fee INTEGER, total INTEGER,
  status TEXT, payment_method TEXT, payment_status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS order_items(
  id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id),
  product_id INTEGER, name TEXT, price INTEGER, qty INTEGER);
CREATE TABLE IF NOT EXISTS payment_attempts(
  id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id),
  method TEXT, outcome TEXT, reason TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS order_events(
  id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id),
  status TEXT, created_at TEXT);
"""

# name, category, unit, price (Rs), stock, emoji
SEED = [
    ("Apple", "Fruits", "1 kg", 120, 40, "🍎"), ("Banana", "Fruits", "1 dozen", 50, 60, "🍌"),
    ("Mango", "Fruits", "1 kg", 150, 25, "🥭"), ("Strawberry", "Fruits", "1 box", 80, 3, "🍓"),
    ("Tomato", "Vegetables", "1 kg", 40, 50, "🍅"), ("Potato", "Vegetables", "1 kg", 30, 80, "🥔"),
    ("Onion", "Vegetables", "1 kg", 35, 70, "🧅"), ("Carrot", "Vegetables", "1 kg", 45, 45, "🥕"),
    ("Spinach", "Vegetables", "1 bunch", 25, 30, "🥬"),
    ("Milk", "Dairy", "1 L", 62, 60, "🥛"), ("Curd", "Dairy", "400 g", 45, 40, "🥣"),
    ("Paneer", "Dairy", "200 g", 90, 25, "🧀"), ("Butter", "Dairy", "100 g", 58, 30, "🧈"),
    ("Eggs", "Dairy", "1 dozen", 84, 40, "🥚"), ("Almond Milk", "Dairy", "1 L", 190, 0, "🥛"),
    ("Bread", "Bakery", "1 loaf", 45, 35, "🍞"), ("Croissant", "Bakery", "1 piece", 40, 20, "🥐"),
    ("Basmati Rice", "Staples", "5 kg", 380, 20, "🍚"), ("Wheat Flour", "Staples", "5 kg", 260, 25, "🌾"),
    ("Toor Dal", "Staples", "1 kg", 160, 30, "🫘"), ("Sugar", "Staples", "1 kg", 48, 50, "🍬"),
    ("Salt", "Staples", "1 kg", 22, 60, "🧂"), ("Cooking Oil", "Staples", "1 L", 155, 30, "🛢️"),
    ("Potato Chips", "Snacks", "1 pack", 20, 80, "🍟"), ("Biscuits", "Snacks", "1 pack", 30, 70, "🍪"),
    ("Namkeen", "Snacks", "200 g", 55, 40, "🥜"),
    ("Tea", "Beverages", "250 g", 125, 35, "🍵"), ("Coffee", "Beverages", "100 g", 180, 20, "☕"),
    ("Orange Juice", "Beverages", "1 L", 110, 25, "🧃"), ("Drinking Water", "Beverages", "1 L", 20, 100, "💧"),
]


# ---------- pure business-rule helpers (easy to unit test) ----------
def price_summary(subtotal):
    fee = 0 if (subtotal == 0 or subtotal >= FREE_DELIVERY_AT) else DELIVERY_FEE
    return {"subtotal": subtotal, "delivery_fee": fee, "total": subtotal + fee}


def parse_qty(raw):
    try:
        q = int(str(raw).strip())
    except (ValueError, TypeError):
        return None, "Quantity must be a whole number."
    if q < 1:
        return None, "Quantity must be at least 1."
    return q, None


def check_qty(product, wanted):
    """Stock and max-quantity rules. Returns an error message or None."""
    if product["stock"] <= 0:
        return f"{product['name']} is out of stock."
    if wanted > MAX_QTY:
        return f"Maximum {MAX_QTY} per item."
    if wanted > product["stock"]:
        return f"Only {product['stock']} of {product['name']} in stock."
    return None


def validate_checkout(form):
    errors = {}
    name = form.get("name", "").strip()
    phone = form.get("phone", "").strip()
    address = form.get("address", "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,59}", name):
        errors["name"] = "Enter your name (letters only, at least 2 characters)."
    if not re.fullmatch(r"[6-9]\d{9}", phone):
        errors["phone"] = "Enter a valid 10-digit mobile number."
    if len(address) < 10:
        errors["address"] = "Enter the full delivery address (at least 10 characters)."
    return {"name": name, "phone": phone, "address": address}, errors


def simulated_gateway(method, form):
    """SIMULATED payment gateway. Returns (outcome, message).
    outcome: 'invalid' (bad input), 'declined', or 'approved'."""
    if method == "upi":
        upi = form.get("upi_id", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{2,}@[A-Za-z]{2,}", upi):
            return "invalid", "Enter a valid UPI ID like name@bank."
        if upi.lower().startswith("fail"):
            return "declined", "UPI payment declined (simulated)."
        return "approved", ""
    if method == "card":
        number = re.sub(r"\s", "", form.get("card_number", ""))
        expiry = form.get("expiry", "").strip()
        cvv = form.get("cvv", "").strip()
        if not re.fullmatch(r"\d{16}", number):
            return "invalid", "Card number must be 16 digits."
        m = re.fullmatch(r"(0[1-9]|1[0-2])/(\d{2})", expiry)
        if not m:
            return "invalid", "Expiry must be in MM/YY format."
        now = datetime.now()
        if (2000 + int(m.group(2)), int(m.group(1))) < (now.year, now.month):
            return "invalid", "This card has expired."
        if not re.fullmatch(r"\d{3}", cvv):
            return "invalid", "CVV must be 3 digits."
        if number.endswith("0002"):
            return "declined", "Card declined by bank (simulated)."
        if number.endswith("9995"):
            return "declined", "Insufficient funds (simulated)."
        if number.endswith("0069"):
            return "declined", "Card blocked by bank (simulated)."
        return "approved", ""
    return "invalid", "Choose a payment method."


# ---------- app factory ----------
def create_app(db_path=None):
    app = Flask(__name__)
    app.secret_key = "demo-secret-key"        # demo only
    app.config["DATABASE"] = db_path or os.path.join(app.root_path, "grocery.db")

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(current_app.config["DATABASE"], isolation_level=None)
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_):
        db = g.pop("db", None)
        if db:
            db.close()

    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        if db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            db.executemany("INSERT INTO products(name,category,unit,price,stock,emoji) VALUES(?,?,?,?,?,?)", SEED)

    def now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def product_or_404(pid):
        p = get_db().execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if not p:
            abort(404)
        return p

    def cart_lines():
        lines = []
        for pid, qty in session.get("cart", {}).items():
            p = get_db().execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if p:
                lines.append({"p": p, "qty": qty, "line_total": p["price"] * qty})
        return lines

    @app.context_processor
    def inject():
        return {"cart_count": sum(session.get("cart", {}).values()), "MAX_QTY": MAX_QTY,
                "STATUS_FLOW": STATUS_FLOW}

    # ----- catalogue / search -----
    @app.get("/")
    def index():
        q = request.args.get("q", "").strip()
        cat = request.args.get("category", "").strip()
        sql, args = "SELECT * FROM products WHERE 1=1", []
        if q:
            sql += " AND (name LIKE ? OR category LIKE ?)"
            args.extend([f"%{q}%", f"%{q}%"])
        if cat:
            sql += " AND category = ?"
            args.append(cat)
        db = get_db()
        products = db.execute(sql + " ORDER BY category, name", args).fetchall()
        cats = [r[0] for r in db.execute("SELECT DISTINCT category FROM products ORDER BY 1")]
        return render_template("index.html", products=products, cats=cats, q=q, cat=cat)

    # ----- cart -----
    @app.post("/cart/add")
    def cart_add():
        p = product_or_404(request.form.get("product_id"))
        q, err = parse_qty(request.form.get("qty", "1"))
        cart = session.get("cart", {})
        wanted = cart.get(str(p["id"]), 0) + (q or 0)
        if not err:
            err = check_qty(p, wanted)
        if err:
            flash(err, "error")
        else:
            cart[str(p["id"])] = wanted
            session["cart"] = cart
            flash(f"Added {q} x {p['name']} to your cart. Cart has {sum(cart.values())} items.", "success")
        return redirect(request.referrer or url_for("index"))

    @app.post("/cart/update")
    def cart_update():
        p = product_or_404(request.form.get("product_id"))
        q, err = parse_qty(request.form.get("qty"))
        if not err:
            err = check_qty(p, q)
        if err:
            flash(err, "error")
        else:
            cart = session.get("cart", {})
            cart[str(p["id"])] = q
            session["cart"] = cart
            flash(f"Updated {p['name']} to {q}.", "success")
        return redirect(url_for("cart"))

    @app.post("/cart/remove")
    def cart_remove():
        cart = session.get("cart", {})
        cart.pop(str(request.form.get("product_id")), None)
        session["cart"] = cart
        return redirect(url_for("cart"))

    @app.get("/cart")
    def cart():
        lines = cart_lines()
        return render_template("cart.html", lines=lines,
                               s=price_summary(sum(l["line_total"] for l in lines)))

    # ----- checkout -> creates order awaiting payment -----
    @app.route("/checkout", methods=["GET", "POST"])
    def checkout():
        lines = cart_lines()
        if not lines:
            flash("Your cart is empty.", "error")
            return redirect(url_for("index"))
        for l in lines:                       # re-check stock before ordering
            err = check_qty(l["p"], l["qty"])
            if err:
                flash(err + " Please update your cart.", "error")
                return redirect(url_for("cart"))
        s = price_summary(sum(l["line_total"] for l in lines))
        if request.method == "POST":
            data, errors = validate_checkout(request.form)
            if errors:
                return render_template("checkout.html", lines=lines, s=s, data=data, errors=errors)
            db = get_db()
            cur = db.execute(
                "INSERT INTO orders(customer_name,phone,address,subtotal,delivery_fee,total,status,payment_status,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (data["name"], data["phone"], data["address"], s["subtotal"], s["delivery_fee"],
                 s["total"], "Pending Payment", "Pending", now()))
            oid = cur.lastrowid
            db.executemany("INSERT INTO order_items(order_id,product_id,name,price,qty) VALUES(?,?,?,?,?)",
                           [(oid, l["p"]["id"], l["p"]["name"], l["p"]["price"], l["qty"]) for l in lines])
            session["my_orders"] = session.get("my_orders", []) + [oid]
            return redirect(url_for("pay", order_id=oid))
        return render_template("checkout.html", lines=lines, s=s, data={}, errors={})

    # ----- SIMULATED payment -----
    @app.route("/pay/<int:order_id>", methods=["GET", "POST"])
    def pay(order_id):
        db = get_db()
        order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            abort(404)
        if order["status"] not in ("Pending Payment", "Payment Failed"):
            return redirect(url_for("order", order_id=order_id))
        if request.method == "POST":
            method = request.form.get("method", "")
            outcome, msg = simulated_gateway(method, request.form)
            if outcome == "invalid":
                flash(msg, "error")
                return redirect(url_for("pay", order_id=order_id))
            if outcome == "declined":
                db.execute("UPDATE orders SET status='Payment Failed', payment_status='Failed', payment_method=? WHERE id=?", (method, order_id))
                db.execute("INSERT INTO payment_attempts(order_id,method,outcome,reason,created_at) VALUES(?,?,?,?,?)",
                           (order_id, method, "declined", msg, now()))
                flash(msg + " Your cart is saved - try another method.", "error")
                return redirect(url_for("pay", order_id=order_id))
            # approved -> reduce stock atomically (fixes the "last unit sold twice" defect)
            items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
            db.execute("BEGIN IMMEDIATE")
            short = None
            for it in items:
                cur = db.execute("UPDATE products SET stock = stock - ? WHERE id=? AND stock >= ?",
                                 (it["qty"], it["product_id"], it["qty"]))
                if cur.rowcount == 0:
                    short = it["name"]
                    break
            if short:
                db.execute("ROLLBACK")
                db.execute("UPDATE orders SET status='Cancelled', payment_status='Not charged', payment_method=? WHERE id=?", (method, order_id))
                db.execute("INSERT INTO payment_attempts(order_id,method,outcome,reason,created_at) VALUES(?,?,?,?,?)",
                           (order_id, method, "stock_failed", f"{short} ran out of stock", now()))
                flash(f"Sorry, {short} just went out of stock. You were not charged. Please update your cart.", "error")
                return redirect(url_for("cart"))
            db.execute("UPDATE orders SET status='Placed', payment_status='Paid', payment_method=? WHERE id=?", (method, order_id))
            db.execute("INSERT INTO order_events(order_id,status,created_at) VALUES(?,?,?)", (order_id, "Placed", now()))
            db.execute("INSERT INTO payment_attempts(order_id,method,outcome,reason,created_at) VALUES(?,?,?,?,?)",
                       (order_id, method, "approved", "", now()))
            db.execute("COMMIT")
            session["cart"] = {}
            flash("Payment successful (simulated). Your order is placed!", "success")
            return redirect(url_for("order", order_id=order_id))
        return render_template("pay.html", order=order)

    # ----- order summary / tracking / history -----
    @app.get("/order/<int:order_id>")
    def order(order_id):
        db = get_db()
        o = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not o:
            abort(404)
        items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
        times = {e["status"]: e["created_at"] for e in db.execute(
            "SELECT status, created_at FROM order_events WHERE order_id=? ORDER BY id", (order_id,))}
        # SIMULATED rider position (% of the route): fixed per status, and while
        # "Out for Delivery" it moves from 55% to 95% over 60 seconds.
        rider = {"Placed": 5, "Packed": 25, "Out for Delivery": 55, "Delivered": 100}.get(o["status"], 0)
        if o["status"] == "Out for Delivery" and "Out for Delivery" in times:
            secs = (datetime.now() - datetime.strptime(times["Out for Delivery"], "%Y-%m-%d %H:%M:%S")).total_seconds()
            rider = round(55 + min(secs / 60, 1) * 40, 1)
        return render_template("order.html", o=o, items=items, times=times, rider=rider)

    @app.get("/orders")
    def orders():
        ids = session.get("my_orders", [])
        rows = []
        if ids:
            rows = get_db().execute(
                f"SELECT * FROM orders WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id DESC", ids).fetchall()
        return render_template("orders.html", orders=rows)

    # ----- store staff (demo): move SIMULATED delivery status forward -----
    @app.get("/admin/orders")
    def admin_orders():
        rows = get_db().execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
        low = get_db().execute("SELECT * FROM products WHERE stock <= 5 ORDER BY stock").fetchall()
        return render_template("admin.html", orders=rows, low=low)

    @app.post("/admin/orders/<int:order_id>/advance")
    def admin_advance(order_id):
        db = get_db()
        o = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not o:
            abort(404)
        if o["status"] not in STATUS_FLOW or o["status"] == STATUS_FLOW[-1]:
            flash(f"Order #{order_id} cannot move forward from '{o['status']}'.", "error")
        else:
            nxt = STATUS_FLOW[STATUS_FLOW.index(o["status"]) + 1]
            db.execute("UPDATE orders SET status=? WHERE id=?", (nxt, order_id))
                      db.execute("INSERT INTO order_events(order_id,status,created_at) VALUES(?,?,?)", (order_id, nxt, now()))
            flash(f"Order #{order_id} is now '{nxt}' (simulated tracking).", "success")
        return redirect(url_for("admin_orders"))

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
