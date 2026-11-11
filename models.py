from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


ROLE_EDITOR = 0
ROLE_VIEWER = 1
ROLE_MANAGER = 2
ROLE_ADMIN = 3

ROLES = {
    ROLE_ADMIN: ("admin", "Administrator"),
    ROLE_EDITOR: ("editor", "Editor"),
    ROLE_MANAGER: ("manager", "Manager"),
    ROLE_VIEWER: ("viewer", "Viewer"),
}
NAME_PARTICLES_SHORT = {"de", "da", "do", "das", "dos", "e", "di", "du"}


class User(db.Model, UserMixin):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    privilege = db.Column(db.Integer, nullable=False, default=1)
    first_name = db.Column(db.String(60), nullable=True)
    last_name = db.Column(db.String(60), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    photo = db.deferred(db.Column(db.LargeBinary, nullable=True))
    photo_version = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_active(self):
        return bool(self.active)

    @property
    def role_key(self):
        return ROLES.get(self.privilege, ROLES[ROLE_VIEWER])[0]

    @property
    def role_label(self):
        return ROLES.get(self.privilege, ROLES[ROLE_VIEWER])[1]

    @property
    def is_admin(self):
        return self.privilege == ROLE_ADMIN

    @property
    def can_edit(self):
        return self.privilege in (ROLE_EDITOR, ROLE_ADMIN)

    @property
    def can_use_modules(self):
        return self.privilege in (ROLE_EDITOR, ROLE_MANAGER, ROLE_ADMIN)

    @property
    def short_name(self):
        words = self.full_name.split()
        if not words:
            return self.username.split("@")[0]
        picked = [words[0]]
        for w in words[1:]:
            if w.lower() not in NAME_PARTICLES_SHORT:
                picked.append(w)
                break
        return " ".join(picked)

    @property
    def has_photo(self):
        return self.photo_version > 0

    def to_public(self):
        return {
            "id": self.id,
            "username": self.username,
            "firstName": self.first_name or "",
            "lastName": self.last_name or "",
            "fullName": self.full_name,
            "shortName": self.short_name,
            "role": self.role_key,
            "roleLabel": self.role_label,
            "privilege": self.privilege,
            "active": bool(self.active),
            "photoVersion": self.photo_version if self.has_photo else 0,
        }

    @property
    def full_name(self):
        return " ".join(p for p in (self.first_name, self.last_name) if p).strip()

    def __repr__(self):
        return f"<User {self.username} (privilege={self.privilege})>"


class Category(db.Model):
    __tablename__ = "category"

    name = db.Column(db.String(120), primary_key=True)
    price = db.Column(db.Float, nullable=True)
    bulk_qty = db.Column(db.Float, nullable=True)
    bulk_price = db.Column(db.Float, nullable=True)
    cleaning_price = db.Column(db.Float, nullable=True)

    items = db.relationship("Item", backref="category", lazy=True)

    def to_dict(self):
        return {
            "name": self.name,
            "price": self.price,
            "bulkQty": self.bulk_qty,
            "bulkPrice": self.bulk_price,
            "cleaningPrice": self.cleaning_price,
        }


class Item(db.Model):
    __tablename__ = "item"

    id = db.Column(db.String(80), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    cat_name = db.Column(db.String(120), db.ForeignKey("category.name"), nullable=False)
    unit = db.Column(db.String(40), nullable=False, default="pcs")
    base_stock = db.Column(db.Float, nullable=False, default=0)
    order_index = db.Column(db.Integer, nullable=False, default=0)
    removed = db.Column(db.Boolean, nullable=False, default=False)
    renamed_name = db.Column(db.String(200), nullable=True)
    is_custom = db.Column(db.Boolean, nullable=False, default=False)
    target_value = db.Column(db.Float, nullable=True)

    monthly_records = db.relationship(
        "MonthlyRecord", backref="item", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def display_name(self):
        return self.renamed_name or self.name

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.display_name,
            "cat": self.cat_name,
            "unit": self.unit,
            "stock": self.base_stock,
            "orderIndex": self.order_index,
            "target": self.target_value,
        }


class MonthlyRecord(db.Model):
    __tablename__ = "monthly_record"
    __table_args__ = (db.UniqueConstraint("month", "item_id", name="uix_month_item"),)

    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(7), nullable=False)
    item_id = db.Column(db.String(80), db.ForeignKey("item.id"), nullable=False)
    stock = db.Column(db.Float, nullable=False, default=0)
    outflow = db.Column(db.Float, nullable=False, default=0)
    cleaning = db.Column(db.Float, nullable=False, default=0)
    month_purchase = db.Column(db.Float, nullable=False, default=0)

    def to_dict(self):
        return {
            "stock": self.stock,
            "outflow": self.outflow,
            "cleaning": self.cleaning,
            "monthPurchase": self.month_purchase,
        }


class Budget(db.Model):
    __tablename__ = "budget"

    month = db.Column(db.String(7), primary_key=True)
    value = db.Column(db.Float, nullable=True)


class SyncState(db.Model):

    __tablename__ = "sync_state"

    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.Integer, nullable=False, default=0)


class SiteSetting(db.Model):

    __tablename__ = "site_setting"

    key = db.Column(db.String(40), primary_key=True)
    value = db.Column(db.String(120), nullable=False, default="")
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class Schedule(db.Model):

    __tablename__ = "schedule"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    requester_name = db.Column(db.String(130), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    routine = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    done = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    done_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "userId": self.user_id,
            "name": self.requester_name,
            "date": self.date.isoformat(),
            "routine": self.routine,
            "quantity": self.quantity,
            "done": self.done,
            "createdAt": self.created_at.strftime("%Y-%m-%d %H:%M"),
        }


class UniformRequest(db.Model):

    __tablename__ = "uniform_request"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    manager_name = db.Column(db.String(130), nullable=False)
    employee_name = db.Column(db.String(130), nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    shift = db.Column(db.String(5), nullable=False)
    items = db.Column(db.String(300), nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    done = db.Column(db.Boolean, nullable=False, default=False)
    refused = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    refusal_reason = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
    done_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "userId": self.user_id,
            "manager": self.manager_name,
            "employee": self.employee_name,
            "kind": self.kind,
            "shift": self.shift,
            "items": [i for i in self.items.split(";") if i],
            "reason": self.reason,
            "done": self.done,
            "refused": self.refused,
            "refusalReason": self.refusal_reason or "",
            "createdAt": self.created_at.strftime("%Y-%m-%d %H:%M"),
        }
