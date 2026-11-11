import os

import common as t
from models import Category, Item, User, db

app = t.load_app("backend")
check = t.Checker()
admin, editor, manager, viewer = (t.login(app, u) for u in (t.ADMIN, t.EDITOR, t.MANAGER, t.VIEWER))
anon = app.app.test_client()

check.section("seed")
with app.app.app_context():
    check("57 items seeded", Item.query.count() == 57)
    check("25 categories seeded", Category.query.count() == 25)
    check("4 demo accounts", User.query.count() == 4)
data = admin.get("/api/bootstrap").get_json()
check("bootstrap exposes permissions", data["canEdit"] and data["isAdmin"] and data["me"]["role"] == "admin")
check("viewer cannot edit", viewer.get("/api/bootstrap").get_json()["canEdit"] is False)
check("anonymous users are redirected", anon.get("/api/bootstrap").status_code == 302)

check.section("login")
bad = anon.post("/login", data={"username": t.ADMIN, "password": "wrong"})
check("wrong password shows an error", b"Invalid username/email or password." in bad.data)
check("unknown user shows the same error", b"Invalid username/email or password." in anon.post("/login", data={"username": "ghost@example.com", "password": "x"}).data)
check("email lookup is case-insensitive", anon.post("/login", data={"username": t.ADMIN.upper(), "password": t.DEMO_PASSWORD}).status_code == 302)
for target, expected in (("/", "/"), ("/api/version", "/api/version"), ("//evil.com", "/"), ("https://evil.com", "/"), ("/\\evil.com", "/")):
    r = app.app.test_client().post(f"/login?next={target}", data={"username": t.ADMIN, "password": t.DEMO_PASSWORD})
    check(f"next={target} redirects to {expected}", r.headers["Location"].endswith(expected) and "evil" not in r.headers["Location"])

check.section("registration")
REG = {"first_name": "Ana", "last_name": "Costa", "email": "ana@example.com", "password": "long-enough-1", "confirm": "long-enough-1"}


def register(**changes):
    return app.app.test_client().post("/register", data=dict(REG, **changes))


cases = [
    ({"first_name": ""}, b"first name"),
    ({"last_name": ""}, b"last name"),
    ({"first_name": "A1"}, b"letters"),
    ({"email": "nope"}, b"valid email"),
    ({"password": "short", "confirm": "short"}, b"at least 8"),
    ({"confirm": "different-pass-1"}, b"do not match"),
    ({"email": t.ADMIN}, b"already exists"),
]
for changes, fragment in cases:
    check(f"rejects: {fragment.decode()}", fragment in register(**changes).data)
r = register()
check("valid registration redirects to login", r.status_code == 302 and "/login" in r.headers["Location"])
with app.app.app_context():
    created = User.query.filter_by(username="ana@example.com").first()
    check("new accounts are viewers with a clean name", created.privilege == 1 and created.full_name == "Ana Costa")
check("the new account can sign in", t.login(app, "ana@example.com", "long-enough-1").get("/api/bootstrap").status_code == 200)

os.environ["ALLOWED_EMAIL_DOMAINS"] = "corp.test, partner.test"
check("domain list blocks others", b"allowed domain" in register(email="x@example.com").data)
check("first domain is accepted", register(email="a@corp.test").status_code == 302)
check("second domain is accepted", register(email="b@partner.test").status_code == 302)
os.environ["ALLOWED_EMAIL_DOMAINS"] = "*"
check("wildcard accepts any domain", register(email="c@anything.org").status_code == 302)
os.environ["REGISTRATION_CODE"] = "letmein"
check("missing code is rejected", b"Invalid access code" in register(email="d@example.com").data)
check("wrong code is rejected", b"Invalid access code" in register(email="d@example.com", code="nope").data)
check("correct code is accepted", register(email="d@example.com", code="letmein").status_code == 302)
del os.environ["REGISTRATION_CODE"]
os.environ["ALLOW_REGISTRATION"] = "0"
check("registration can be disabled", register(email="e@example.com").status_code == 404)
del os.environ["ALLOW_REGISTRATION"]

check.section("catalog")
r = editor.post("/api/catalog/add-item", json={"name": "Test Item", "cat": "Gloves"})
new = r.get_json()
check("editor adds an item", r.status_code == 200 and new["id"].startswith("custom-") and new["name"] == "Test Item")
check("add requires a name", editor.post("/api/catalog/add-item", json={"cat": "Gloves"}).status_code == 400)
check("rename works", editor.post("/api/catalog/rename-item", json={"itemId": new["id"], "name": "Renamed"}).get_json()["name"] == "Renamed")
check("blank rename is refused", editor.post("/api/catalog/rename-item", json={"itemId": new["id"], "name": " "}).status_code == 400)
ids = [i["id"] for i in admin.get("/api/bootstrap").get_json()["items"]]
editor.post("/api/catalog/reorder", json={"order": list(reversed(ids))})
check("reorder is persisted", [i["id"] for i in admin.get("/api/bootstrap").get_json()["items"]] == list(reversed(ids)))
check("remove works", editor.post("/api/catalog/remove-item", json={"itemId": new["id"]}).status_code == 200)
check("removed items leave the catalog", new["id"] not in [i["id"] for i in admin.get("/api/bootstrap").get_json()["items"]])
check("unknown item gives 404", editor.post("/api/catalog/remove-item", json={"itemId": "nope"}).status_code == 404)

check.section("records and prices")
item = ids[0]
r = editor.post("/api/monthly", json={"month": "2026-01", "itemId": item, "stock": 12, "outflow": 3})
check("editor saves a monthly record", r.status_code == 200 and r.get_json()["stock"] == 12)
check("record can be read back", editor.get("/api/month/2026-01").status_code == 200)
check("monthly requires month and item", editor.post("/api/monthly", json={"itemId": item}).status_code == 400)
check("budget is saved", editor.post("/api/budget", json={"month": "2026-01", "value": 900}).get_json()["value"] == 900)
check("item target is saved", editor.post("/api/item-target", json={"itemId": item, "value": 40}).get_json()["value"] == 40)
check("category price is saved", editor.post("/api/category", json={"name": "Gloves", "price": 7.5}).get_json()["price"] == 7.5)

check.section("read-only roles")
writes = [
    ("/api/monthly", {"month": "2026-01", "itemId": item, "stock": 1}),
    ("/api/budget", {"month": "2026-01", "value": 1}),
    ("/api/category", {"name": "Gloves", "price": 1}),
    ("/api/item-target", {"itemId": item, "value": 1}),
    ("/api/catalog/add-item", {"name": "x", "cat": "Gloves"}),
    ("/api/catalog/remove-item", {"itemId": item}),
    ("/api/catalog/rename-item", {"itemId": item, "name": "x"}),
    ("/api/catalog/reorder", {"order": ids}),
    ("/api/support-email", {"email": "a@b.co"}),
    ("/api/safe-days", {"days": 5}),
]
for path, body in writes:
    check(f"viewer 403 on {path}", viewer.post(path, json=body).status_code == 403)
    check(f"manager 403 on {path}", manager.post(path, json=body).status_code == 403)

check.section("password change")
who = t.login(app, "ana@example.com", "long-enough-1")
check("wrong current password", who.post("/api/me/password", json={"current": "x", "new": "another-pass-1", "confirm": "another-pass-1"}).status_code == 400)
check("mismatched confirmation", who.post("/api/me/password", json={"current": "long-enough-1", "new": "another-pass-1", "confirm": "nope-nope-1"}).status_code == 400)
check("too short", who.post("/api/me/password", json={"current": "long-enough-1", "new": "abc", "confirm": "abc"}).status_code == 400)
check("valid change", who.post("/api/me/password", json={"current": "long-enough-1", "new": "another-pass-1", "confirm": "another-pass-1"}).status_code == 200)
check("old password stops working", b"Invalid" in app.app.test_client().post("/login", data={"username": "ana@example.com", "password": "long-enough-1"}).data)
check("new password works", t.login(app, "ana@example.com", "another-pass-1").get("/api/bootstrap").status_code == 200)

check.section("bootstrap admin")
os.environ.update(ADMIN_EMAIL="root@example.com", ADMIN_PASSWORD="root-pass-123")
with app.app.app_context():
    app.ensure_first_admin()
    check("existing installs are left untouched", User.query.filter_by(username="root@example.com").first() is None)
    User.query.delete()
    db.session.commit()
    app.ensure_first_admin()
    root = User.query.filter_by(username="root@example.com").first()
    check("an empty database gets the configured admin", root is not None and root.privilege == 3 and root.check_password("root-pass-123"))
    app.ensure_first_admin()
    check("running it again does not duplicate", User.query.count() == 1)
check.finish()
