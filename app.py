import sqlite3, random, calendar
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "change-this-secret"
DB = "garage.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, username TEXT UNIQUE, password TEXT, role TEXT DEFAULT 'customer');
CREATE TABLE IF NOT EXISTS bookings(id INTEGER PRIMARY KEY, user_id INTEGER, plate TEXT, model TEXT, service TEXT, date TEXT, notes TEXT, status TEXT DEFAULT 'Pending');
CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, booking_id INTEGER, work_done TEXT, part_id INTEGER, qty INTEGER, cost REAL, done_on TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS parts(id INTEGER PRIMARY KEY, name TEXT UNIQUE, stock INTEGER, reorder_level INTEGER, price REAL);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, part_id INTEGER, qty INTEGER, supplier TEXT, unit_cost REAL DEFAULT 0, status TEXT DEFAULT 'Ordered', ordered_on TEXT DEFAULT CURRENT_TIMESTAMP);
"""
SERVICES = ["Oil Change", "Brake Service", "Tyre Replacement", "Battery Replacement", "Aircond Service", "General Inspection"]

def month_back(now, k):
    y, m = now.year, now.month - k
    while m <= 0:
        m += 12; y -= 1
    return y, m

def seed_demo(c):
    """Demo customers, bookings, repair records and part orders spread over ~13 months so reports look real."""
    if c.execute("SELECT 1 FROM users WHERE username='user123'").fetchone():
        return
    pw = generate_password_hash("password123")
    uid = {}
    for name, uname in [("Demo User", "user123"), ("Ahmad Faiz", "faiz"), ("Siti Aminah", "siti"), ("Tan Wei Ming", "weiming")]:
        uid[uname] = c.execute("INSERT INTO users(name,username,password) VALUES(?,?,?)", (name, uname, pw)).lastrowid
    parts = {r[1]: (r[0], r[2]) for r in c.execute("SELECT id,name,price FROM parts")}
    now = datetime.utcnow() + timedelta(hours=8)
    day = lambda n: (now - timedelta(days=n)).strftime("%Y-%m-%d")

    def add(owner, plate, car, svc, date, status, work=None, part=None, qty=0, labour=0):
        bid = c.execute("INSERT INTO bookings(user_id,plate,model,service,date,notes,status) VALUES(?,?,?,?,?,?,?)",
                        (uid[owner], plate, car, svc, date, "", status)).lastrowid
        if status == "Completed":
            pid, price = parts[part] if part else (None, 0)
            c.execute("INSERT INTO records(booking_id,work_done,part_id,qty,cost,done_on) VALUES(?,?,?,?,?,?)",
                      (bid, work, pid, qty, price * qty + labour, date + " 04:00:00"))

    def order(part, qty, sup, cost, date):
        c.execute("INSERT INTO orders(part_id,qty,supplier,unit_cost,status,ordered_on) VALUES(?,?,?,?,'Received',?)",
                  (parts[part][0], qty, sup, cost, date + " 04:00:00"))

    # ---- history: previous 13 months, business slowly growing ----
    cars = [("user123", "WXY 1234", "Perodua Myvi"), ("faiz", "VDE 5521", "Proton Saga"), ("siti", "PQR 8890", "Honda City"),
            ("weiming", "JKL 3302", "Toyota Vios"), ("faiz", "BMA 7712", "Mazda CX-5"), ("weiming", "KLM 4410", "Toyota Corolla Cross"),
            ("siti", "RTY 2288", "Perodua Axia"), ("user123", "PBH 6677", "Honda Civic"), ("faiz", "WQA 1190", "Proton X50"),
            ("siti", "VCC 3045", "Toyota Hilux")]
    pool = ["Oil Change"] * 5 + ["Brake Service"] * 3 + ["Battery Replacement"] * 2 + ["Aircond Service"] * 2 + ["Tyre Replacement"] + ["General Inspection"] * 2
    work = {"Oil Change": "Changed engine oil and filter", "Brake Service": "Replaced brake pads", "Battery Replacement": "Replaced car battery",
            "Aircond Service": "Aircond cleaning and gas top-up", "Tyre Replacement": "Replaced tyres and alignment", "General Inspection": "Full inspection, no major issues"}
    part_for = {"Oil Change": "Engine Oil 4L", "Brake Service": "Brake Pad Set", "Battery Replacement": "Car Battery"}
    labour = {"Oil Change": (40, 60), "Brake Service": (80, 100), "Battery Replacement": (30, 40),
              "Aircond Service": (150, 200), "Tyre Replacement": (300, 450), "General Inspection": (60, 80)}
    stock_orders = [("Engine Oil 4L", 6, "Hoklol Auto", 70), ("Brake Pad Set", 4, "AutoParts KL", 95),
                    ("Oil Filter", 10, "Hoklol Auto", 18), ("Car Battery", 2, "Amaron Supplier", 220)]
    rng = random.Random(7)
    for k in range(13, 0, -1):
        y, m = month_back(now, k)
        last = calendar.monthrange(y, m)[1]
        for _ in range(6 + (13 - k) // 2 + rng.randint(0, 3)):
            owner, plate, car = rng.choice(cars)
            svc = rng.choice(pool)
            date = "%04d-%02d-%02d" % (y, m, rng.randint(1, last))
            if rng.random() < 0.07:
                add(owner, plate, car, svc, date, "Rejected")
            else:
                part = part_for.get(svc)
                qty = (2 if svc == "Oil Change" and rng.random() < 0.3 else 1) if part else 0
                add(owner, plate, car, svc, date, "Completed", work[svc], part, qty, rng.randint(*labour[svc]))
        for part, qty, sup, cost in rng.sample(stock_orders, 2):
            order(part, qty, sup, cost, "%04d-%02d-%02d" % (y, m, rng.randint(1, last)))

    # ---- recent weeks (shows in the daily view) ----
    recent = [
        ("user123", "WXY 1234", "Perodua Myvi", "Oil Change", 13, "Completed", "Changed engine oil and oil filter", "Engine Oil 4L", 1, 40),
        ("faiz", "VDE 5521", "Proton Saga", "Brake Service", 12, "Completed", "Replaced front brake pads", "Brake Pad Set", 1, 80),
        ("siti", "PQR 8890", "Honda City", "Oil Change", 11, "Completed", "Changed engine oil", "Engine Oil 4L", 1, 40),
        ("weiming", "JKL 3302", "Toyota Vios", "Battery Replacement", 10, "Completed", "Replaced car battery", "Car Battery", 1, 30),
        ("user123", "WXY 1234", "Perodua Myvi", "General Inspection", 9, "Completed", "Full inspection, no major issues", None, 0, 60),
        ("faiz", "VDE 5521", "Proton Saga", "Oil Change", 8, "Completed", "Changed oil filter and topped up oil", "Oil Filter", 1, 40),
        ("user123", "WXY 1234", "Perodua Myvi", "Oil Change", 7, "Completed", "Changed engine oil", "Engine Oil 4L", 1, 40),
        ("siti", "PQR 8890", "Honda City", "Brake Service", 6, "Completed", "Replaced rear brake pads", "Brake Pad Set", 1, 80),
        ("weiming", "JKL 3302", "Toyota Vios", "Aircond Service", 5, "Completed", "Aircond cleaning and gas top-up", None, 0, 180),
        ("faiz", "BMA 7712", "Mazda CX-5", "Oil Change", 4, "Completed", "Changed engine oil (2 units)", "Engine Oil 4L", 2, 50),
        ("faiz", "VDE 5521", "Proton Saga", "Tyre Replacement", 4, "Completed", "Replaced 2 tyres and alignment", None, 0, 380),
        ("weiming", "JKL 3302", "Toyota Corolla Cross", "Brake Service", 3, "Completed", "Replaced front brake pads", "Brake Pad Set", 1, 90),
        ("siti", "PQR 8890", "Honda City", "Battery Replacement", 2, "Completed", "Replaced car battery", "Car Battery", 1, 30),
        ("siti", "PQR 8890", "Honda City", "Oil Change", 1, "Completed", "Changed oil filter", "Oil Filter", 1, 40),
        ("user123", "WXY 1234", "Perodua Myvi", "Aircond Service", 0, "Approved"),
        ("faiz", "BMA 7712", "Mazda CX-5", "Brake Service", -1, "Pending"),
        ("weiming", "JKL 3302", "Toyota Vios", "Oil Change", -2, "Pending"),
        ("siti", "ABC 9001", "Proton X50", "General Inspection", -3, "Rejected"),
    ]
    for u, plate, car, svc, ago, status, *rest in recent:
        add(u, plate, car, svc, day(ago), status, *rest)
    for part, qty, sup, cost, ago in [("Engine Oil 4L", 10, "Hoklol Auto", 70, 12), ("Brake Pad Set", 5, "AutoParts KL", 95, 9),
                                      ("Oil Filter", 10, "Hoklol Auto", 18, 6), ("Car Battery", 2, "Amaron Supplier", 220, 3)]:
        order(part, qty, sup, cost, day(ago))
    for name, stock in [("Engine Oil 4L", 18), ("Brake Pad Set", 6), ("Oil Filter", 4), ("Car Battery", 4)]:
        c.execute("UPDATE parts SET stock=? WHERE name=?", (stock, name))

def init_db():
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    try:
        c.execute("ALTER TABLE orders ADD COLUMN unit_cost REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    if not c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        c.execute("INSERT INTO users(name,username,password,role) VALUES('Admin','admin',?,'admin')",
                  (generate_password_hash("admin123"),))
        c.executemany("INSERT INTO parts(name,stock,reorder_level,price) VALUES(?,?,?,?)",
                      [("Engine Oil 4L", 20, 5, 85), ("Brake Pad Set", 8, 4, 120), ("Oil Filter", 3, 5, 25), ("Car Battery", 6, 3, 280)])
    seed_demo(c)
    c.commit(); c.close()

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d: d.close()

def login_required(role):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if session.get("role") != role:
                flash("Please log in with the correct account."); return redirect(url_for("login"))
            return f(*a, **k)
        return w
    return deco

@app.route("/")
def index():
    if session.get("role") == "admin": return redirect(url_for("admin"))
    if session.get("role") == "customer": return redirect(url_for("my_bookings"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        try:
            db().execute("INSERT INTO users(name,username,password) VALUES(?,?,?)",
                         (f["name"], f["username"], generate_password_hash(f["password"])))
            db().commit(); flash("Registered. Please log in."); return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already taken.")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db().execute("SELECT * FROM users WHERE username=?", (request.form["username"],)).fetchone()
        if u and check_password_hash(u["password"], request.form["password"]):
            session.update(uid=u["id"], name=u["name"], role=u["role"]); return redirect(url_for("index"))
        flash("Invalid username or password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

# ---------- Customer ----------
@app.route("/my", methods=["GET", "POST"])
@login_required("customer")
def my_bookings():
    if request.method == "POST":
        f = request.form
        db().execute("INSERT INTO bookings(user_id,plate,model,service,date,notes) VALUES(?,?,?,?,?,?)",
                     (session["uid"], f["plate"].upper(), f["model"], f["service"], f["date"], f["notes"]))
        db().commit(); flash("Reservation submitted. Waiting for admin approval.")
        return redirect(url_for("my_bookings"))
    rows = db().execute("SELECT * FROM bookings WHERE user_id=? ORDER BY id DESC", (session["uid"],)).fetchall()
    return render_template("customer.html", bookings=rows, services=SERVICES)

# ---------- Admin: bookings & service records ----------
@app.route("/admin")
@login_required("admin")
def admin():
    rows = db().execute("SELECT b.*, u.name AS customer FROM bookings b JOIN users u ON u.id=b.user_id ORDER BY b.id DESC").fetchall()
    parts = db().execute("SELECT * FROM parts ORDER BY name").fetchall()
    return render_template("admin.html", bookings=rows, parts=parts)

@app.post("/admin/booking/<int:i>/<action>")
@login_required("admin")
def booking_action(i, action):
    status = {"approve": "Approved", "reject": "Rejected"}.get(action)
    if status:
        db().execute("UPDATE bookings SET status=? WHERE id=?", (status, i)); db().commit()
    return redirect(url_for("admin"))

@app.route("/admin/booking/<int:i>")
@login_required("admin")
def booking_detail(i):
    b = db().execute("SELECT b.*, u.name AS customer FROM bookings b JOIN users u ON u.id=b.user_id WHERE b.id=?", (i,)).fetchone()
    if not b:
        return redirect(url_for("admin"))
    parts = db().execute("SELECT * FROM parts ORDER BY name").fetchall()
    rec = db().execute("SELECT r.*, p.name AS part FROM records r LEFT JOIN parts p ON p.id=r.part_id WHERE r.booking_id=?", (i,)).fetchone()
    return render_template("booking.html", b=b, parts=parts, rec=rec)

@app.post("/admin/booking/<int:i>/complete")
@login_required("admin")
def complete(i):
    b = db().execute("SELECT status FROM bookings WHERE id=?", (i,)).fetchone()
    if not b or b["status"] != "Approved":
        return redirect(url_for("admin"))
    f = request.form
    pid = f.get("part_id") or None
    qty = int(f.get("qty") or 0)
    part_cost = 0
    if pid and qty:
        p = db().execute("SELECT * FROM parts WHERE id=?", (pid,)).fetchone()
        if p["stock"] < qty:
            flash(f"Not enough stock for {p['name']} (only {p['stock']} left).")
            return redirect(url_for("booking_detail", i=i))
        db().execute("UPDATE parts SET stock=stock-? WHERE id=?", (qty, pid))
        part_cost = p["price"] * qty
    db().execute("INSERT INTO records(booking_id,work_done,part_id,qty,cost) VALUES(?,?,?,?,?)",
                 (i, f["work_done"], pid, qty, part_cost + float(f.get("labour") or 0)))
    db().execute("UPDATE bookings SET status='Completed' WHERE id=?", (i,))
    db().commit(); flash("Repair record saved. Booking completed.")
    return redirect(url_for("booking_detail", i=i))

@app.route("/admin/records")
@login_required("admin")
def records():
    rows = db().execute("""SELECT r.*, b.plate, b.model, b.service, u.name AS customer, p.name AS part
        FROM records r JOIN bookings b ON b.id=r.booking_id JOIN users u ON u.id=b.user_id
        LEFT JOIN parts p ON p.id=r.part_id ORDER BY r.id DESC""").fetchall()
    return render_template("records.html", records=rows)

@app.route("/admin/reports")
@login_required("admin")
def reports():
    def rows(sql):
        return db().execute(sql).fetchall()
    one = lambda sql: db().execute(sql).fetchone()[0]
    TZ = "'+8 hours'"  # Malaysia time
    BRAND = "substr(b.model,1,instr(b.model||' ',' ')-1)"
    now = datetime.utcnow() + timedelta(hours=8)
    zero = {"services": 0, "revenue": 0.0, "spend": 0.0}

    # per-day figures: cars serviced + revenue (completed repairs), money spent (part orders)
    daily = {}
    for r in rows(f"SELECT substr(datetime(done_on,{TZ}),1,10), COUNT(*), SUM(cost) FROM records GROUP BY 1"):
        x = daily.setdefault(r[0], dict(zero)); x["services"] = r[1]; x["revenue"] = r[2] or 0
    for r in rows(f"SELECT substr(datetime(ordered_on,{TZ}),1,10), SUM(qty*COALESCE(unit_cost,0)) FROM orders GROUP BY 1"):
        daily.setdefault(r[0], dict(zero))["spend"] = r[1] or 0

    def roll(n):  # group days into months (n=7) or years (n=4)
        out = {}
        for k, v in daily.items():
            o = out.setdefault(k[:n], dict(zero))
            for f in zero:
                o[f] += v[f]
        return out
    def pack(keys, src):
        g = lambda f: [round(src.get(k, zero)[f], 2) for k in keys]
        return {"labels": keys, "services": g("services"), "revenue": g("revenue"), "spend": g("spend")}
    monthly, yearly = roll(7), roll(4)
    dkeys = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    mkeys = ["%04d-%02d" % month_back(now, k) for k in range(11, -1, -1)]
    first_year = min([int(k) for k in yearly] or [now.year])
    ykeys = [str(y) for y in range(first_year, now.year + 1)]
    periods = {"daily": pack(dkeys, daily), "monthly": pack(mkeys, monthly), "yearly": pack(ykeys, yearly)}
    today = daily.get(now.strftime("%Y-%m-%d"), zero)

    st = rows("SELECT status, COUNT(*) FROM bookings GROUP BY status")
    mo = rows("SELECT substr(date,1,7) m, COUNT(*) FROM bookings GROUP BY m ORDER BY m")
    sv = rows("SELECT service, COUNT(*) n FROM bookings GROUP BY service ORDER BY n DESC")
    us = rows("SELECT p.name, SUM(r.qty) n FROM records r JOIN parts p ON p.id=r.part_id GROUP BY p.name ORDER BY n DESC LIMIT 5")
    sk = rows("SELECT name, stock, reorder_level FROM parts ORDER BY name")
    bb = rows(f"SELECT {BRAND} br, COUNT(*) n FROM bookings b GROUP BY br ORDER BY n DESC")
    rb = rows(f"SELECT {BRAND} br, ROUND(SUM(r.cost),2) t FROM records r JOIN bookings b ON b.id=r.booking_id GROUP BY br ORDER BY t DESC")
    tm = rows("SELECT model, COUNT(*) n FROM bookings GROUP BY model ORDER BY n DESC LIMIT 10")
    L = lambda rs, i: [r[i] for r in rs]
    d = {
        "periods": periods,
        "status": {"labels": L(st, 0), "values": L(st, 1)},
        "month": {"labels": L(mo, 0), "values": L(mo, 1)},
        "services": {"labels": L(sv, 0), "values": L(sv, 1)},
        "parts": {"labels": L(us, 0), "values": L(us, 1)},
        "stock": {"labels": L(sk, 0), "stock": L(sk, 1), "reorder": L(sk, 2)},
        "brand": {"labels": L(bb, 0), "values": L(bb, 1)},
        "brandrev": {"labels": L(rb, 0), "values": L(rb, 1)},
        "model": {"labels": L(tm, 0), "values": L(tm, 1)},
    }
    completed = one("SELECT COUNT(*) FROM bookings WHERE status='Completed'")
    revenue = one("SELECT COALESCE(SUM(cost),0) FROM records")
    spend = one("SELECT COALESCE(SUM(qty*COALESCE(unit_cost,0)),0) FROM orders")
    kpi = {
        "total": one("SELECT COUNT(*) FROM bookings"),
        "pending": one("SELECT COUNT(*) FROM bookings WHERE status='Pending'"),
        "completed": completed, "revenue": revenue, "spend": spend, "net": revenue - spend,
        "avg": revenue / completed if completed else 0,
        "low": one("SELECT COUNT(*) FROM parts WHERE stock<=reorder_level"),
        "today": today,
    }
    return render_template("reports.html", d=d, kpi=kpi)

# ---------- Admin: inventory & part orders ----------
@app.route("/admin/inventory")
@login_required("admin")
def inventory():
    parts = db().execute("SELECT * FROM parts ORDER BY name").fetchall()
    orders = db().execute("SELECT o.*, p.name FROM orders o JOIN parts p ON p.id=o.part_id ORDER BY o.id DESC").fetchall()
    return render_template("inventory.html", parts=parts, orders=orders)

@app.post("/admin/inventory/add")
@login_required("admin")
def add_part():
    f = request.form
    try:
        db().execute("INSERT INTO parts(name,stock,reorder_level,price) VALUES(?,?,?,?)",
                     (f["name"], int(f["stock"]), int(f["reorder_level"]), float(f["price"])))
        db().commit()
    except sqlite3.IntegrityError:
        flash("Part already exists.")
    return redirect(url_for("inventory"))

@app.post("/admin/order")
@login_required("admin")
def submit_order():
    f = request.form
    db().execute("INSERT INTO orders(part_id,qty,supplier,unit_cost) VALUES(?,?,?,?)", (f["part_id"], int(f["qty"]), f["supplier"], float(f.get("unit_cost") or 0)))
    db().commit(); flash("Part order submitted.")
    return redirect(url_for("inventory"))

@app.post("/admin/order/<int:i>/receive")
@login_required("admin")
def receive_order(i):
    o = db().execute("SELECT * FROM orders WHERE id=? AND status='Ordered'", (i,)).fetchone()
    if o:
        db().execute("UPDATE parts SET stock=stock+? WHERE id=?", (o["qty"], o["part_id"]))
        db().execute("UPDATE orders SET status='Received' WHERE id=?", (i,)); db().commit()
    return redirect(url_for("inventory"))

init_db()

if __name__ == "__main__":
    app.run(debug=True)
