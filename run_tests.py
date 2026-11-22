
"""Test runner: prints Expected vs Actual for each test case and writes TEST_REPORT.md.
Run:  python run_tests.py
Each test uses a fresh temporary database, so tests do not affect each other."""

import os, re, sqlite3, tempfile
from app import create_app, price_summary


def fresh():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    app = create_app(path)
    app.config["TESTING"] = True
    return app, app.test_client(), path


def pid(path, name):
    return sqlite3.connect(path).execute(
        "SELECT id FROM products WHERE name=?", (name,)
    ).fetchone()[0]


def stock(path, name):
    return sqlite3.connect(path).execute(
        "SELECT stock FROM products WHERE name=?", (name,)
    ).fetchone()[0]


def one(path, sql, *a):
    return sqlite3.connect(path).execute(sql, a).fetchone()


def add(c, path, name, qty):
    return c.post(
        "/cart/add",
        data={"product_id": pid(path, name), "qty": qty},
        follow_redirects=True
    )


GOOD = {
    "name": "Asha Patil",
    "phone": "9876543210",
    "address": "Flat 4, Baner Road, Pune"
}

CARD_OK = {
    "method": "card",
    "card_number": "4111 1111 1111 1111",
    "expiry": "12/30",
    "cvv": "123"
}


def checkout(c):
    r = c.post("/checkout", data=GOOD)
    return int(re.search(r"/pay/(\d+)", r.headers["Location"]).group(1))


# ---- each test returns (expected, actual, passed) ----

def tc01():  # positive
    app, c, p = fresh()
    r = c.get("/?q=milk").get_data(as_text=True)
    ok = "Milk" in r and "Apple" not in r
    return "Only milk products listed", "Milk listed, Apple not listed" if ok else "wrong results", ok


def tc02():  # negative
    app, c, p = fresh()
    r = c.get("/?q=zzzz").get_data(as_text=True)
    ok = "No products found" in r
    return "'No products found' message", "message shown" if ok else "no message", ok


def tc03():  # positive: cart + price calc
    app, c, p = fresh()
    add(c, p, "Milk", 2)
    add(c, p, "Bread", 1)
    r = c.get("/cart").get_data(as_text=True)
    ok = "169" in r and "₹30" in r and "199" in r
    return "Subtotal 169, delivery 30, total 199", "values found in cart page" if ok else "wrong totals", ok


def tc04():  # negative: stock shortage / excess quantity
    app, c, p = fresh()
    r = add(c, p, "Strawberry", 5).get_data(as_text=True)
    ok = "Only 3 of Strawberry in stock" in r and not c.get("/cart").get_data(as_text=True).count("Strawberry") > 1
    return "Rejected: 'Only 3 of Strawberry in stock'", "rejected with stock message" if ok else "not rejected", ok


def tc05():  # negative: out of stock item
    app, c, p = fresh()
    r = add(c, p, "Almond Milk", 1).get_data(as_text=True)
    ok = "out of stock" in r
    return "Rejected: out of stock", "rejected" if ok else "added", ok


def tc06():  # boundary: invalid quantities 0, -1, abc
    app, c, p = fresh()
    msgs = [add(c, p, "Milk", q).get_data(as_text=True) for q in ("0", "-1", "abc")]
    ok = all(("at least 1" in m or "whole number" in m) for m in msgs)
    return "0, -1 and 'abc' all rejected", "all rejected" if ok else "some accepted", ok


def tc07():  # boundary: max quantity 10 allowed, 11 rejected
    app, c, p = fresh()
    a = add(c, p, "Drinking Water", 10).get_data(as_text=True)
    b = add(c, p, "Drinking Water", 1).get_data(as_text=True)
    ok = "Added 10" in a and "Maximum 10" in b
    return "10 accepted, 11th unit rejected", "10 accepted, 11 rejected" if ok else "limit not enforced", ok


def tc08():  # boundary: delivery fee threshold
    a, b, d = price_summary(299), price_summary(300), price_summary(0)
    ok = a["delivery_fee"] == 30 and b["delivery_fee"] == 0 and d["delivery_fee"] == 0
    return "299 -> fee 30; 300 -> fee 0; empty -> 0", f"299 -> {a['delivery_fee']}; 300 -> {b['delivery_fee']}", ok


def tc09():  # negative: checkout validation
    app, c, p = fresh()
    add(c, p, "Milk", 1)
    r = c.post("/checkout", data={
        "name": "A", "phone": "12345", "address": "short"
    }).get_data(as_text=True)
    ok = "valid 10-digit" in r and "at least 10 characters" in r and "at least 2 characters" in r
    return "Name, phone and address errors shown; no order created", "3 errors shown" if ok else "missing errors", ok and one(p, "SELECT COUNT(*) FROM orders")[0] == 0


def tc10():  # positive: successful payment
    app, c, p = fresh()
    add(c, p, "Milk", 2)
    oid = checkout(c)
    c.post(f"/pay/{oid}", data=CARD_OK)
    st = one(p, "SELECT status, payment_status FROM orders WHERE id=?", oid)
    ok = st == ("Placed", "Paid") and stock(p, "Milk") == 58
    return "Order Placed/Paid, Milk stock 60 -> 58", f"{st[0]}/{st[1]}, Milk stock {stock(p,'Milk')}", ok


def tc11():  # negative: payment failure
    app, c, p = fresh()
    add(c, p, "Milk", 2)
    oid = checkout(c)
    c.post(f"/pay/{oid}", data={**CARD_OK, "card_number": "4000 0000 0000 0002"})
    st = one(p, "SELECT status, payment_status FROM orders WHERE id=?", oid)
    cart_kept = bool(c.get("/cart").get_data(as_text=True).count("Milk"))
    ok = st == ("Payment Failed", "Failed") and stock(p, "Milk") == 60 and cart_kept
    return "Payment Failed, stock unchanged (60), cart kept", f"{st[0]}, stock {stock(p,'Milk')}, cart kept={cart_kept}", ok


def tc12():  # negative: retry after failure then succeed
    app, c, p = fresh()
    add(c, p, "Milk", 1)
    oid = checkout(c)
    c.post(f"/pay/{oid}", data={"method": "upi", "upi_id": "failtest@upi"})
    c.post(f"/pay/{oid}", data={"method": "upi", "upi_id": "asha@okbank"})
    st = one(p, "SELECT status FROM orders WHERE id=?", oid)[0]
    n = one(p, "SELECT COUNT(*) FROM payment_attempts WHERE order_id=?", oid)[0]
    return "Declined then approved; 2 attempts logged; Placed", f"{st}, {n} attempts", st == "Placed" and n == 2


def tc13():  # negative: stock shortage at payment time
    app, c, p = fresh()
    add(c, p, "Strawberry", 3)
    oid = checkout(c)
    sqlite3.connect(p).execute(
        "UPDATE products SET stock=1 WHERE name='Strawberry'"
    ).connection.commit()
    c.post(f"/pay/{oid}", data=CARD_OK)
    st = one(p, "SELECT status, payment_status FROM orders WHERE id=?", oid)
    ok = st == ("Cancelled", "Not charged") and stock(p, "Strawberry") == 1
    return "Order Cancelled, not charged, stock stays 1 (no negative stock)", f"{st[0]}/{st[1]}, stock {stock(p,'Strawberry')}", ok


def tc14():  # negative: invalid card details
    app, c, p = fresh()
    add(c, p, "Milk", 1)
    oid = checkout(c)
    r = c.post(
        f"/pay/{oid}",
        data={**CARD_OK, "card_number": "1234"},
        follow_redirects=True
    ).get_data(as_text=True)
    ok = "16 digits" in r and one(p, "SELECT status FROM orders WHERE id=?", oid)[0] == "Pending Payment"
    return "'Card number must be 16 digits'; order still pending", "error shown" if ok else "accepted", ok


def tc15():  # workflow: delivery status flow
    app, c, p = fresh()
    add(c, p, "Milk", 1)
    oid = checkout(c)
    c.post(f"/pay/{oid}", data=CARD_OK)
    seen = [one(p, "SELECT status FROM orders WHERE id=?", oid)[0]]
    for _ in range(4):
        c.post(f"/admin/orders/{oid}/advance")
        seen.append(one(p, "SELECT status FROM orders WHERE id=?", oid)[0])
    ok = seen == ["Placed", "Packed", "Out for Delivery", "Delivered", "Delivered"]
    return "Placed > Packed > Out for Delivery > Delivered, stops there", " > ".join(seen), ok


def tc16():  # negative: cannot advance an unpaid order
    app, c, p = fresh()
    add(c, p, "Milk", 1)
    oid = checkout(c)
    c.post(f"/admin/orders/{oid}/advance")
    st = one(p, "SELECT status FROM orders WHERE id=?", oid)[0]
    return "Unpaid order stays 'Pending Payment'", st, st == "Pending Payment"


# ---- TC-17: blocked card test ----
def tc17():  # negative: blocked card (simulated)
    app, c, p = fresh()
    add(c, p, "Milk", 1)
    oid = checkout(c)

    c.post(
        f"/pay/{oid}",
        data={**CARD_OK, "card_number": "4000 0000 0000 0069"}
    )

    st = one(p, "SELECT status FROM orders WHERE id=?", oid)[0]

    return "Payment Failed for blocked card", st, st == "Payment Failed"


TESTS = [
    ("TC-01", "Search by name", "Positive", tc01),
    ("TC-02", "Search with no match", "Negative", tc02),
    ("TC-03", "Cart totals and delivery fee", "Positive", tc03),
    ("TC-04", "Quantity above stock", "Negative", tc04),
    ("TC-05", "Out-of-stock item", "Negative", tc05),
    ("TC-06", "Invalid quantity (0, -1, text)", "Boundary", tc06),
    ("TC-07", "Max 10 per item", "Boundary", tc07),
    ("TC-08", "Free-delivery threshold 299/300", "Boundary", tc08),
    ("TC-09", "Checkout form validation", "Negative", tc09),
    ("TC-10", "Successful payment reduces stock", "Positive", tc10),
    ("TC-11", "Payment declined keeps cart, no stock change", "Negative", tc11),
    ("TC-12", "Retry payment after failure", "Negative", tc12),
    ("TC-13", "Stock runs out before payment completes", "Negative", tc13),
    ("TC-14", "Invalid card details", "Negative", tc14),
    ("TC-15", "Delivery status workflow (simulated)", "Positive", tc15),
    ("TC-16", "Unpaid order cannot ship", "Negative", tc16),
    ("TC-17", "Blocked card is declined", "Negative", tc17),
]


if __name__ == "__main__":
    rows, passed = [], 0

    for tid, name, kind, fn in TESTS:
        try:
            exp, act, ok = fn()
        except Exception as e:
            exp, act, ok = "no error", f"ERROR: {e}", False

        passed += ok
        rows.append((tid, name, kind, exp, act, "PASS" if ok else "FAIL"))

        print(f"{tid} [{kind:8}] {name:48} {'PASS' if ok else 'FAIL'}")

    print(f"\n{passed}/{len(TESTS)} passed")

    with open("TEST_REPORT.md", "w", encoding="utf-8") as f:
        f.write("# Test Report - Online Grocery Application\n\n")
        f.write("Payment and delivery tracking are SIMULATED.\n\n")
        f.write("| ID | Test | Type | Expected | Actual | Result |\n")
        f.write("|---|---|---|---|---|---|\n")

        for r in rows:
            f.write("| " + " | ".join(r) + " |\n")

        f.write(f"\n**{passed}/{len(TESTS)} passed.**\n")
