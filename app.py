import base64
import binascii
import hmac
import os
import re
import secrets
from datetime import date, datetime

from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from sqlalchemy import inspect, text
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from models import (
    ROLE_ADMIN,
    ROLE_EDITOR,
    ROLE_MANAGER,
    ROLE_VIEWER,
    Budget,
    Category,
    Item,
    MonthlyRecord,
    Schedule,
    SiteSetting,
    SyncState,
    UniformRequest,
    User,
    db,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REFERENCE_MONTH = os.environ.get("REFERENCE_MONTH", "2026-09")

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
NAME_PATTERN = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$", re.UNICODE)
MAX_NAME_LENGTH = 60
ROUTINES = ("BBS", "DSW", "Both")
MAX_SCHEDULE_QTY = 99
UNIFORM_KINDS = ("First issue", "Replacement")
UNIFORM_SHIFTS = ("T1", "T2", "T3", "ADM")
UNIFORM_ITEMS = ("T-Shirt", "Pants", "Shorts", "Fleece Jacket", "Safety Boots", "Beanie")
MIN_REASON_LENGTH = 10
MAX_REASON_LENGTH = 500
MAX_SAFE_DAYS = 99999
MAX_PHOTO_BYTES = 250000
ROLE_BY_KEY = {
    "viewer": ROLE_VIEWER,
    "manager": ROLE_MANAGER,
    "editor": ROLE_EDITOR,
    "admin": ROLE_ADMIN,
}
DEFAULT_SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@example.com")
EMAIL_RE = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]+$")


def get_safe_days():
    row = db.session.get(SiteSetting, "safe_days")
    try:
        return max(0, min(MAX_SAFE_DAYS, int(row.value))) if row else 0
    except (TypeError, ValueError):
        return 0

def get_support_email():
    row = db.session.get(SiteSetting, "support_email")
    return row.value if row and row.value else DEFAULT_SUPPORT_EMAIL


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "warehouse.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


with app.app_context():
    if db.engine.url.get_backend_name() == "sqlite":
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=10000")
            cur.close()


def ensure_schema():
    db.create_all()
    cols = {c["name"] for c in inspect(db.engine).get_columns("user")}
    with db.engine.begin() as conn:
        for col in ("first_name", "last_name"):
            if col not in cols:
                conn.execute(text(f'ALTER TABLE "user" ADD COLUMN {col} VARCHAR(60)'))
        ucols = {c["name"] for c in inspect(db.engine).get_columns("uniform_request")}
        if "refused" not in ucols:
            conn.execute(text("ALTER TABLE uniform_request ADD COLUMN refused BOOLEAN NOT NULL DEFAULT 0"))
        if "refusal_reason" not in ucols:
            conn.execute(text("ALTER TABLE uniform_request ADD COLUMN refusal_reason VARCHAR(500)"))
        if "active" not in cols:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN active BOOLEAN NOT NULL DEFAULT 1'))
        if "photo" not in cols:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN photo BLOB'))
        if "photo_version" not in cols:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN photo_version INTEGER NOT NULL DEFAULT 0'))
    ensure_first_admin()


def ensure_first_admin():
    email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    if not email or not password or User.query.first() is not None:
        return
    admin = User(username=email, privilege=ROLE_ADMIN, first_name="Admin", last_name="User")
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()


with app.app_context():
    ensure_schema()

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to access the warehouse inventory."


@app.errorhandler(HTTPException)
def api_errors_as_json(err):
    if request.path.startswith("/api/"):
        return jsonify({"error": err.description}), err.code
    return err


@login_manager.user_loader
def load_user(user_id):
    user = db.session.get(User, int(user_id))
    return user if user and user.active else None


def registration_enabled():
    return os.environ.get("ALLOW_REGISTRATION", "1") != "0"


def allowed_email_domains():
    raw = os.environ.get("ALLOWED_EMAIL_DOMAINS", "*")
    return [d.strip().lower().lstrip("@") for d in raw.split(",") if d.strip()]


def registration_code():
    return os.environ.get("REGISTRATION_CODE", "")


NAME_PARTICLES = {"de", "da", "do", "das", "dos", "e", "di", "du"}


def clean_name(raw):
    words = []
    for i, word in enumerate((raw or "").split()):
        if word.isupper() or word.islower():
            low = word.lower()
            word = (
                low
                if (i > 0 and low in NAME_PARTICLES)
                else "-".join(part.capitalize() for part in word.split("-"))
            )
        words.append(word)
    return " ".join(words)


def validate_name(label, name):
    if not name:
        return f"Enter your {label}."
    if len(name) > MAX_NAME_LENGTH:
        return f"The {label} can have at most {MAX_NAME_LENGTH} characters."
    if not NAME_PATTERN.match(name):
        return f"The {label} may only contain letters."
    return None


def validate_registration(email, password, confirm, code, first_name="", last_name=""):
    error = validate_name("first name", first_name) or validate_name("last name", last_name)
    if error:
        return error
    if not EMAIL_PATTERN.match(email):
        return "Enter a valid email address."
    domains = allowed_email_domains()
    if "*" not in domains and email.rsplit("@", 1)[1] not in domains:
        return "Use an email from an allowed domain (" + ", ".join("@" + d for d in domains) + ")."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"The password must have at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"The password can have at most {MAX_PASSWORD_LENGTH} characters."
    if password != confirm:
        return "The passwords do not match."
    needed_code = registration_code()
    if needed_code and not hmac.compare_digest(code.encode("utf-8"), needed_code.encode("utf-8")):
        return "Invalid access code."
    if User.query.filter(db.func.lower(User.username) == email).first():
        return "An account with this email already exists. Try signing in."
    return None


def safe_next_url(target):
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return url_for("dashboard")
    return target


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        identifier = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        user = None
        if identifier:
            user = User.query.filter(db.func.lower(User.username) == identifier).first()
        if user and user.check_password(password):
            if not user.active:
                error = "This account is blocked. Please contact an administrator."
            else:
                login_user(user)
                return redirect(safe_next_url(request.args.get("next")))
        else:
            error = "Invalid username/email or password."
    return render_template("login.html", error=error, registration_open=registration_enabled())


@app.route("/register", methods=["GET", "POST"])
def register():
    if not registration_enabled():
        abort(404)
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    error = None
    email = ""
    first_name = last_name = ""
    if request.method == "POST":
        first_name = clean_name(request.form.get("first_name"))
        last_name = clean_name(request.form.get("last_name"))
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        code = request.form.get("code") or ""
        error = validate_registration(email, password, confirm, code, first_name, last_name)
        if not error:
            user = User(username=email, privilege=1, first_name=first_name, last_name=last_name)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                error = "An account with this email already exists. Try signing in."
            else:
                flash("Account created! Sign in with your email and the password you chose.", "success")
                return redirect(url_for("login"))
    domains = [d for d in allowed_email_domains() if d != "*"]
    return render_template(
        "register.html",
        error=error,
        email=email,
        first_name=first_name,
        last_name=last_name,
        domains=domains,
        code_required=bool(registration_code()),
        min_password=MIN_PASSWORD_LENGTH,
    )


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        can_edit=current_user.can_edit,
        can_modules=current_user.can_use_modules,
        is_admin=current_user.is_admin,
        role_key=current_user.role_key,
        role_label=current_user.role_label,
        short_name=current_user.short_name,
        photo_version=current_user.photo_version if current_user.has_photo else 0,
        user_id=current_user.id,
        username=current_user.username,
        reference_month=REFERENCE_MONTH,
        full_name=current_user.full_name,
        first_name=current_user.first_name or "",
        last_name=current_user.last_name or "",
        support_email=get_support_email(),
    )


def require_editor():
    if not current_user.can_edit:
        abort(403, description="Your account has view-only access.")


def require_modules():
    if not current_user.can_use_modules:
        abort(
            403,
            description="Your access level does not allow using this module. Ask an administrator to grant access.",
        )


def require_admin():
    if not current_user.is_admin:
        abort(403, description="Only administrators can do this.")



def category_or_404(name):
    cat = db.session.get(Category, name)
    if not cat:
        abort(404, description=f"Category '{name}' not found.")
    return cat


def item_or_404(item_id):
    item = db.session.get(Item, item_id)
    if not item:
        abort(404, description=f"Item '{item_id}' not found.")
    return item


@app.route("/api/bootstrap")
@login_required
def api_bootstrap():
    categories = {c.name: c.to_dict() for c in Category.query.all()}
    items = Item.query.filter_by(removed=False).order_by(Item.order_index.asc()).all()
    return jsonify(
        {
            "categories": categories,
            "items": [it.to_dict() for it in items],
            "canEdit": current_user.can_edit,
            "referenceMonth": REFERENCE_MONTH,
            "canModules": current_user.can_use_modules,
            "isAdmin": current_user.is_admin,
            "me": {
                "id": current_user.id,
                "fullName": current_user.full_name,
                "firstName": current_user.first_name or "",
                "lastName": current_user.last_name or "",
                "shortName": current_user.short_name,
                "username": current_user.username,
                "role": current_user.role_key,
                "roleLabel": current_user.role_label,
                "photoVersion": current_user.photo_version if current_user.has_photo else 0,
            },
            "safeDays": get_safe_days(),
            "supportEmail": get_support_email(),
        }
    )


@app.route("/api/support-email", methods=["POST"])
@login_required
def api_set_support_email():
    require_editor()
    data = request.get_json(force=True, silent=True) or {}
    email = str(data.get("email", "")).strip()
    if not email or len(email) > 120 or not EMAIL_RE.match(email):
        abort(400, description="Enter a valid email address, for example name@company.com.")
    row = db.session.get(SiteSetting, "support_email")
    if row:
        row.value = email
    else:
        db.session.add(SiteSetting(key="support_email", value=email))
    db.session.commit()
    return jsonify({"supportEmail": email})


@app.route("/api/safe-days", methods=["POST"])
@login_required
def api_set_safe_days():
    require_editor()
    data = request.get_json(force=True, silent=True) or {}
    raw = str(data.get("days", "")).strip()
    if not raw.isdigit():
        abort(400, description="Enter whole numbers only (0 or more).")
    days = int(raw)
    if days > MAX_SAFE_DAYS:
        abort(400, description=f"The maximum is {MAX_SAFE_DAYS} days.")
    row = db.session.get(SiteSetting, "safe_days")
    if row:
        row.value = str(days)
    else:
        db.session.add(SiteSetting(key="safe_days", value=str(days)))
    db.session.commit()
    return jsonify({"safeDays": days})


@app.route("/api/month/<month>")
@login_required
def api_get_month(month):
    records = MonthlyRecord.query.filter_by(month=month).all()
    return jsonify({r.item_id: r.to_dict() for r in records})


@app.route("/api/months")
@login_required
def api_all_months():
    records = MonthlyRecord.query.all()
    by_month = {}
    for r in records:
        by_month.setdefault(r.month, {})[r.item_id] = r.to_dict()
    return jsonify(by_month)


@app.route("/api/budget")
@login_required
def api_budget():
    rows = Budget.query.all()
    return jsonify({b.month: b.value for b in rows})


@app.route("/api/monthly", methods=["POST"])
@login_required
def api_set_monthly():
    require_editor()
    data = request.get_json(force=True) or {}
    month, item_id = data.get("month"), data.get("itemId")
    if not month or not item_id:
        abort(400, description="month and itemId are required.")
    item_or_404(item_id)
    rec = MonthlyRecord.query.filter_by(month=month, item_id=item_id).first()
    if not rec:
        rec = MonthlyRecord(month=month, item_id=item_id)
        db.session.add(rec)
    for field in ("stock", "outflow", "cleaning", "monthPurchase"):
        if field in data:
            setattr(rec, "month_purchase" if field == "monthPurchase" else field, data[field] or 0)
    db.session.commit()
    return jsonify(rec.to_dict())


@app.route("/api/category", methods=["POST"])
@login_required
def api_set_category():
    require_editor()
    data = request.get_json(force=True) or {}
    name = data.get("name")
    if not name:
        abort(400, description="name is required.")
    cat = db.session.get(Category, name)
    if not cat:
        cat = Category(name=name)
        db.session.add(cat)
    field_map = {
        "price": "price",
        "bulkQty": "bulk_qty",
        "bulkPrice": "bulk_price",
        "cleaningPrice": "cleaning_price",
    }
    for js_field, col in field_map.items():
        if js_field in data:
            setattr(cat, col, data[js_field])
    db.session.commit()
    return jsonify(cat.to_dict())


@app.route("/api/item-target", methods=["POST"])
@login_required
def api_set_item_target():
    require_editor()
    data = request.get_json(force=True) or {}
    item = item_or_404(data.get("itemId"))
    item.target_value = data.get("value")
    db.session.commit()
    return jsonify({"itemId": item.id, "value": item.target_value})


@app.route("/api/budget", methods=["POST"])
@login_required
def api_set_budget():
    require_editor()
    data = request.get_json(force=True) or {}
    month = data.get("month")
    if not month:
        abort(400, description="month is required.")
    row = db.session.get(Budget, month)
    if not row:
        row = Budget(month=month)
        db.session.add(row)
    row.value = data.get("value")
    db.session.commit()
    return jsonify({"month": row.month, "value": row.value})


@app.route("/api/catalog/add-item", methods=["POST"])
@login_required
def api_catalog_add_item():
    require_editor()
    data = request.get_json(force=True) or {}
    name, cat_name = (data.get("name") or "").strip(), (data.get("cat") or "").strip()
    unit = (data.get("unit") or "pcs").strip()
    if not name or not cat_name:
        abort(400, description="name and cat are required.")
    if not db.session.get(Category, cat_name):
        db.session.add(Category(name=cat_name))
    max_order = db.session.query(db.func.max(Item.order_index)).scalar() or 0
    same_cat_last = (
        Item.query.filter_by(cat_name=cat_name, removed=False)
        .order_by(Item.order_index.desc())
        .first()
    )
    insert_at = (same_cat_last.order_index + 1) if same_cat_last else (max_order + 1)
    Item.query.filter(Item.order_index >= insert_at).update({Item.order_index: Item.order_index + 1})
    new_id = "custom-" + os.urandom(4).hex()
    item = Item(
        id=new_id,
        name=name,
        cat_name=cat_name,
        unit=unit,
        base_stock=0,
        order_index=insert_at,
        is_custom=True,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict())


@app.route("/api/catalog/remove-item", methods=["POST"])
@login_required
def api_catalog_remove_item():
    require_editor()
    data = request.get_json(force=True) or {}
    item = item_or_404(data.get("itemId"))
    item.removed = True
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/catalog/rename-item", methods=["POST"])
@login_required
def api_catalog_rename_item():
    require_editor()
    data = request.get_json(force=True) or {}
    item = item_or_404(data.get("itemId"))
    new_name = (data.get("name") or "").strip()
    if not new_name:
        abort(400, description="name is required.")
    item.renamed_name = new_name
    db.session.commit()
    return jsonify(item.to_dict())


@app.route("/api/catalog/reorder", methods=["POST"])
@login_required
def api_catalog_reorder():
    require_editor()
    data = request.get_json(force=True) or {}
    order = data.get("order") or []
    for idx, item_id in enumerate(order):
        Item.query.filter_by(id=item_id).update({Item.order_index: idx})
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/schedules")
@login_required
def api_schedules():
    if not current_user.can_use_modules:
        return jsonify([])
    query = Schedule.query
    if not current_user.can_edit:
        query = query.filter_by(user_id=current_user.id)
    rows = query.order_by(Schedule.date.asc(), Schedule.created_at.asc()).all()
    return jsonify([r.to_dict() for r in rows])


@app.route("/api/profile", methods=["POST"])
@login_required
def api_set_profile():
    data = request.get_json(force=True, silent=True) or {}
    first, last = clean_name(data.get("firstName")), clean_name(data.get("lastName"))
    error = validate_name("first name", first) or validate_name("last name", last)
    if error:
        abort(400, description=error)
    current_user.first_name, current_user.last_name = first, last
    db.session.commit()
    return jsonify(
        {
            "firstName": current_user.first_name,
            "lastName": current_user.last_name,
            "fullName": current_user.full_name,
            "shortName": current_user.short_name,
        }
    )


@app.route("/api/schedules", methods=["POST"])
@login_required
def api_create_schedule():
    require_modules()
    data = request.get_json(force=True, silent=True) or {}
    if not current_user.full_name:
        abort(400, description="Complete your first and last name before scheduling.")
    try:
        day = date.fromisoformat(str(data.get("date") or ""))
    except ValueError:
        abort(400, description="Invalid date.")
    if day < date.today():
        abort(400, description="The scheduled date cannot be in the past.")
    routine = data.get("routine")
    if routine not in ROUTINES:
        abort(400, description="Choose a routine: BBS, DSW or Both.")
    try:
        quantity = int(data.get("quantity"))
    except (TypeError, ValueError):
        abort(400, description="Enter a valid quantity.")
    if quantity < 1 or quantity > MAX_SCHEDULE_QTY:
        abort(400, description=f"The quantity must be between 1 and {MAX_SCHEDULE_QTY}.")
    row = Schedule(
        user_id=current_user.id,
        requester_name=current_user.full_name,
        date=day,
        routine=routine,
        quantity=quantity,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(row.to_dict())


def schedule_or_404(schedule_id):
    row = db.session.get(Schedule, schedule_id) if isinstance(schedule_id, int) else None
    if not row:
        abort(404, description="Routine not found.")
    return row


@app.route("/api/schedules/status", methods=["POST"])
@login_required
def api_schedule_status():
    require_modules()
    require_editor()
    data = request.get_json(force=True, silent=True) or {}
    row = schedule_or_404(data.get("id"))
    row.done = bool(data.get("done"))
    row.done_at = datetime.now() if row.done else None
    db.session.commit()
    return jsonify(row.to_dict())


@app.route("/api/schedules/delete", methods=["POST"])
@login_required
def api_schedule_delete():
    require_modules()
    require_editor()
    data = request.get_json(force=True, silent=True) or {}
    row = schedule_or_404(data.get("id"))
    db.session.delete(row)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/uniform-requests")
@login_required
def api_uniform_requests():
    if not current_user.can_use_modules:
        return jsonify([])
    query = UniformRequest.query
    if not current_user.can_edit:
        query = query.filter_by(user_id=current_user.id)
    rows = query.order_by(UniformRequest.created_at.desc(), UniformRequest.id.desc()).all()
    return jsonify([r.to_dict() for r in rows])


@app.route("/api/uniform-requests", methods=["POST"])
@login_required
def api_create_uniform_request():
    require_modules()
    data = request.get_json(force=True, silent=True) or {}
    if not current_user.full_name:
        abort(400, description="Complete your first and last name before submitting a request.")
    employee = clean_name(data.get("employee"))
    if len(employee.split()) < 2:
        abort(400, description="Enter the employee's full name (first and last name).")
    if len(employee) > 120 or not NAME_PATTERN.match(employee):
        abort(400, description="The employee name may only contain letters (120 characters max).")
    kind = data.get("kind")
    if kind not in UNIFORM_KINDS:
        abort(400, description="Choose the type: first issue or replacement.")
    shift = data.get("shift")
    if shift not in UNIFORM_SHIFTS:
        abort(400, description="Choose the employee's shift.")
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raw_items = []
    items = [i for i in UNIFORM_ITEMS if i in raw_items]
    if not items:
        abort(400, description="Select at least one item.")
    reason = " ".join(str(data.get("reason") or "").split())
    if len(reason) < MIN_REASON_LENGTH:
        abort(400, description=f"Describe the reason (at least {MIN_REASON_LENGTH} characters); requests without detail are not fulfilled.")
    if len(reason) > MAX_REASON_LENGTH:
        abort(400, description=f"The reason can have at most {MAX_REASON_LENGTH} characters.")
    row = UniformRequest(
        user_id=current_user.id,
        manager_name=current_user.full_name,
        employee_name=employee,
        kind=kind,
        shift=shift,
        items=";".join(items),
        reason=reason,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(row.to_dict())


def uniform_request_or_404(request_id):
    row = db.session.get(UniformRequest, request_id) if isinstance(request_id, int) else None
    if not row:
        abort(404, description="Request not found.")
    return row


@app.route("/api/uniform-requests/status", methods=["POST"])
@login_required
def api_uniform_request_status():
    require_modules()
    require_editor()
    data = request.get_json(force=True, silent=True) or {}
    row = uniform_request_or_404(data.get("id"))
    row.done = bool(data.get("done"))
    row.done_at = datetime.now() if row.done else None
    if row.done:
        row.refused = False
        row.refusal_reason = None
    db.session.commit()
    return jsonify(row.to_dict())


@app.route("/api/uniform-requests/refuse", methods=["POST"])
@login_required
def api_uniform_request_refuse():
    require_modules()
    require_editor()
    data = request.get_json(force=True, silent=True) or {}
    row = uniform_request_or_404(data.get("id"))
    if data.get("refused") is False:
        row.refused = False
        row.refusal_reason = None
        row.done_at = None
    else:
        reason = " ".join(str(data.get("reason") or "").split())
        if len(reason) < MIN_REASON_LENGTH:
            abort(400, description=f"Explain the reason with at least {MIN_REASON_LENGTH} characters.")
        if len(reason) > MAX_REASON_LENGTH:
            abort(400, description=f"The justification can have at most {MAX_REASON_LENGTH} characters.")
        row.refused = True
        row.refusal_reason = reason
        row.done = False
        row.done_at = datetime.now()
    db.session.commit()
    return jsonify(row.to_dict())


@app.route("/api/uniform-requests/delete", methods=["POST"])
@login_required
def api_uniform_request_delete():
    require_modules()
    require_editor()
    data = request.get_json(force=True, silent=True) or {}
    row = uniform_request_or_404(data.get("id"))
    db.session.delete(row)
    db.session.commit()
    return jsonify({"ok": True})


def bump_version():
    updated = SyncState.query.filter_by(id=1).update({SyncState.version: SyncState.version + 1})
    if not updated:
        db.session.add(SyncState(id=1, version=1))


@app.after_request
def bump_version_after_write(response):
    if request.method == "POST" and request.path.startswith("/api/") and response.status_code < 300:
        try:
            bump_version()
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.warning("Could not bump the sync version after a write.")
    return response


def read_photo(raw):
    if not isinstance(raw, str) or not raw.startswith("data:image/jpeg;base64,"):
        abort(400, description="Upload a JPG, PNG or WebP image.")
    try:
        blob = base64.b64decode(raw.split(",", 1)[1], validate=True)
    except (binascii.Error, ValueError):
        abort(400, description="Could not read the image. Try another one.")
    if len(blob) > MAX_PHOTO_BYTES:
        abort(400, description="The image is too large. Try a smaller photo.")
    if blob[:3] != b"\xff\xd8\xff":
        abort(400, description="Upload a JPG, PNG or WebP image.")
    return blob


def set_photo(user, blob):
    user.photo = blob
    user.photo_version = (user.photo_version or 0) + 1 if blob else 0


@app.route("/avatar/<int:user_id>")
@login_required
def avatar(user_id):
    user = db.session.get(User, user_id)
    if not user or not user.has_photo:
        abort(404)
    etag = f'"{user.id}-{user.photo_version}"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304, headers={"ETag": etag})
    response = Response(user.photo, mimetype="image/jpeg")
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=86400"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.route("/api/me/photo", methods=["POST"])
@login_required
def api_me_photo():
    data = request.get_json(force=True, silent=True) or {}
    if data.get("remove"):
        set_photo(current_user, None)
    else:
        set_photo(current_user, read_photo(data.get("image")))
    db.session.commit()
    return jsonify(current_user.to_public())


@app.route("/api/me/password", methods=["POST"])
@login_required
def api_me_password():
    data = request.get_json(force=True, silent=True) or {}
    current, new, confirm = (str(data.get(k) or "") for k in ("current", "new", "confirm"))
    if not current_user.check_password(current):
        abort(400, description="The current password is incorrect.")
    if len(new) < MIN_PASSWORD_LENGTH:
        abort(400, description=f"The new password must have at least {MIN_PASSWORD_LENGTH} characters.")
    if len(new) > MAX_PASSWORD_LENGTH:
        abort(400, description=f"The new password can have at most {MAX_PASSWORD_LENGTH} characters.")
    if new != confirm:
        abort(400, description="The new password confirmation does not match.")
    current_user.set_password(new)
    db.session.commit()
    return jsonify({"ok": True})


def record_counts():
    counts = {}
    for model in (Schedule, UniformRequest):
        for uid, n in db.session.query(model.user_id, db.func.count(model.id)).group_by(model.user_id):
            counts[uid] = counts.get(uid, 0) + n
    return counts


def user_row(user, counts):
    row = user.to_public()
    row["records"] = counts.get(user.id, 0)
    row["isMe"] = user.id == current_user.id
    return row


def other_active_admins(exclude_id):
    return User.query.filter(User.privilege == ROLE_ADMIN, User.active.is_(True), User.id != exclude_id).count()


def parse_role(raw):
    key = str(raw or "").strip().lower()
    if key not in ROLE_BY_KEY:
        abort(400, description="Choose a valid access level.")
    return ROLE_BY_KEY[key]


def parse_username(raw):
    username = str(raw or "").strip().lower()
    if not EMAIL_PATTERN.match(username) or len(username) > 80:
        abort(400, description="Enter a valid email address.")
    return username


def parse_password(raw):
    password = str(raw or "")
    if len(password) < MIN_PASSWORD_LENGTH:
        abort(400, description=f"The password must have at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        abort(400, description=f"The password can have at most {MAX_PASSWORD_LENGTH} characters.")
    return password


@app.route("/api/users")
@login_required
def api_users():
    require_admin()
    counts = record_counts()
    users = User.query.order_by(db.func.lower(User.first_name), db.func.lower(User.username)).all()
    return jsonify([user_row(u, counts) for u in users])


@app.route("/api/managers")
@login_required
def api_managers():
    require_editor()
    managers = (
        User.query.filter(User.privilege == ROLE_MANAGER, User.active.is_(True))
        .order_by(db.func.lower(User.first_name), db.func.lower(User.username))
        .all()
    )
    return jsonify([m.to_public() for m in managers])


@app.route("/api/users/create", methods=["POST"])
@login_required
def api_users_create():
    require_admin()
    data = request.get_json(force=True, silent=True) or {}
    first, last = clean_name(data.get("firstName")), clean_name(data.get("lastName"))
    error = validate_name("first name", first) or validate_name("last name", last)
    if error:
        abort(400, description=error)
    username = parse_username(data.get("username"))
    role = parse_role(data.get("role"))
    password = parse_password(data.get("password"))
    if User.query.filter(db.func.lower(User.username) == username).first():
        abort(400, description="An account with this email already exists.")
    user = User(username=username, privilege=role, first_name=first, last_name=last)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify(user_row(user, {}))


@app.route("/api/users/update", methods=["POST"])
@login_required
def api_users_update():
    require_admin()
    data = request.get_json(force=True, silent=True) or {}
    user = db.session.get(User, int(data.get("id") or 0))
    if not user:
        abort(404, description="Account not found.")
    is_me = user.id == current_user.id
    first = clean_name(data.get("firstName", user.first_name))
    last = clean_name(data.get("lastName", user.last_name))
    if first or last:
        error = validate_name("first name", first) or validate_name("last name", last)
        if error:
            abort(400, description=error)
    username = parse_username(data.get("username", user.username))
    role = parse_role(data.get("role", user.role_key))
    active = bool(data.get("active", user.active))
    if is_me and (role != user.privilege or not active):
        abort(400, description="You cannot change your own role or block your own account.")
    if user.privilege == ROLE_ADMIN and user.active and (role != ROLE_ADMIN or not active):
        if other_active_admins(user.id) < 1:
            abort(400, description="At least one active administrator must remain.")
    clash = User.query.filter(db.func.lower(User.username) == username, User.id != user.id).first()
    if clash:
        abort(400, description="Another account with this email already exists.")
    new_password = str(data.get("newPassword") or "")
    if new_password:
        user.set_password(parse_password(new_password))
    user.first_name, user.last_name = first or None, last or None
    user.username, user.privilege, user.active = username, role, active
    if data.get("removePhoto"):
        set_photo(user, None)
    db.session.commit()
    return jsonify(user_row(user, record_counts()))


@app.route("/api/users/delete", methods=["POST"])
@login_required
def api_users_delete():
    require_admin()
    data = request.get_json(force=True, silent=True) or {}
    user = db.session.get(User, int(data.get("id") or 0))
    if not user:
        abort(404, description="Account not found.")
    if user.id == current_user.id:
        abort(400, description="You cannot delete your own account.")
    if user.privilege == ROLE_ADMIN and user.active and other_active_admins(user.id) < 1:
        abort(400, description="At least one active administrator must remain.")
    n = record_counts().get(user.id, 0)
    if n:
        abort(
            400,
            description=f"This account has {n} routine or request record(s). "
            "Block the account instead of deleting it so the history is preserved.",
        )
    db.session.delete(user)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/version")
@login_required
def api_version():
    state = db.session.get(SyncState, 1)
    response = jsonify({"version": state.version if state else 0})
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")))
