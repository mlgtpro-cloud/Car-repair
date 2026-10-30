import sqlite3
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
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, part_id INTEGER, qty INTEGER, supplier TEXT, status TEXT DEFAULT 'Ordered', ordered_on TEXT DEFAULT CURRENT_TIMESTAMP);
"""
SERVICES = ["Oil Change", "Brake Service", "Tyre Replacement", "Battery Replacement", "Aircond Service", "General Inspection"]

def init_db():
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    if not c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        c.execute("INSERT INTO users(name,username,password,role) VALUES('Admin','admin',?,'admin')",
                  (generate_password_hash("admin123"),))
        c.executemany("INSERT INTO parts(name,stock,reorder_level,price) VALUES(?,?,?,?)",
                      [("Engine Oil 4L", 20, 5, 85), ("Brake Pad Set", 8, 4, 120), ("Oil Filter", 3, 5, 25), ("Car Battery", 6, 3, 280)])
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

@app.post("/admin/booking/<int:i>/complete")
@login_required("admin")
def complete(i):
    f = request.form
    pid = f.get("part_id") or None
    qty = int(f.get("qty") or 0)
    part_cost = 0
    if pid and qty:
        p = db().execute("SELECT * FROM parts WHERE id=?", (pid,)).fetchone()
        if p["stock"] < qty:
            flash(f"Not enough stock for {p['name']} (only {p['stock']} left)."); return redirect(url_for("admin"))
        db().execute("UPDATE parts SET stock=stock-? WHERE id=?", (qty, pid))
        part_cost = p["price"] * qty
    db().execute("INSERT INTO records(booking_id,work_done,part_id,qty,cost) VALUES(?,?,?,?,?)",
                 (i, f["work_done"], pid, qty, part_cost + float(f.get("labour") or 0)))
    db().execute("UPDATE bookings SET status='Completed' WHERE id=?", (i,))
    db().commit(); flash("Service record saved.")
    return redirect(url_for("admin"))

@app.route("/admin/records")
@login_required("admin")
def records():
    rows = db().execute("""SELECT r.*, b.plate, b.model, b.service, u.name AS customer, p.name AS part
        FROM records r JOIN bookings b ON b.id=r.booking_id JOIN users u ON u.id=b.user_id
        LEFT JOIN parts p ON p.id=r.part_id ORDER BY r.id DESC""").fetchall()
    return render_template("records.html", records=rows)

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
    db().execute("INSERT INTO orders(part_id,qty,supplier) VALUES(?,?,?)", (f["part_id"], int(f["qty"]), f["supplier"]))
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
