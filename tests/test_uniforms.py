import common as t
from models import User, db

app = t.load_app("uniforms")
check = t.Checker()

admin, manager, anon = t.login(app, t.ADMIN), t.login(app, t.MANAGER), app.app.test_client()
second = app.app.test_client()
second.post("/register", data={"first_name": "Bia", "last_name": "Lima", "email": "bia@example.com",
                               "password": "strong-pass-123", "confirm": "strong-pass-123"})
with app.app.app_context():
    User.query.filter_by(username="bia@example.com").update({"privilege": 2})
    nameless = User(username="nameless@example.com", privilege=2)
    nameless.set_password(t.DEMO_PASSWORD)
    db.session.add(nameless)
    db.session.commit()
second.post("/login", data={"username": "bia@example.com", "password": "strong-pass-123"})
nameless_client = t.login(app, "nameless@example.com")

BASE = {"employee": "john doe", "kind": "Replacement", "shift": "T2",
        "items": ["Pants", "T-Shirt"], "reason": "Pants torn at the knee, need to swap size 42 for 44"}

check.section("access and nameless accounts")
check("anonymous list is redirected", anon.get("/api/uniform-requests").status_code == 302)
r = nameless_client.post("/api/uniform-requests", json=BASE)
check("a manager without a name cannot request (400)", r.status_code == 400 and "name" in r.get_json()["error"].lower())
admin.post("/api/profile", json={"firstName": "Chief", "lastName": "Editor"})

check.section("creating a request (manager filled in automatically)")
r = manager.post("/api/uniform-requests", json=BASE)
d = r.get_json()
check("manager creates the request", r.status_code == 200)
check("manager name comes from the signed-in user", d["manager"] == "Morgan Manager")
check("employee name is normalised", d["employee"] == "John Doe")
check("items follow the fixed form order", d["items"] == ["T-Shirt", "Pants"])
check("starts as not delivered", d["done"] is False)
r = manager.post("/api/uniform-requests", json=dict(BASE, manager="Someone Else", userId=999))
check("a spoofed manager is ignored", r.get_json()["manager"] == "Morgan Manager")
r = second.post("/api/uniform-requests", json=dict(BASE, kind="First issue", shift="ADM", items=["Beanie"]))
check("another manager can create too", r.status_code == 200 and r.get_json()["manager"] == "Bia Lima")
check("editor can request as well", admin.post("/api/uniform-requests", json=dict(BASE, shift="T1")).status_code == 200)

check.section("validation")
invalid = [
    (dict(BASE, employee=""), "empty employee"),
    (dict(BASE, employee="Maria"), "employee without last name"),
    (dict(BASE, employee="J0ao Silva"), "employee with a digit"),
    (dict(BASE, employee="<b>x</b> y"), "employee with HTML"),
    (dict(BASE, kind="Return"), "unknown type"),
    (dict(BASE, kind=None), "missing type"),
    (dict(BASE, shift="T9"), "unknown shift"),
    (dict(BASE, shift=None), "missing shift"),
    (dict(BASE, items=[]), "no items"),
    (dict(BASE, items=["Helmet"]), "unknown item"),
    (dict(BASE, items="T-Shirt"), "items not a list"),
    (dict(BASE, reason="torn"), "reason too short"),
    (dict(BASE, reason="   " * 10), "reason only spaces"),
    (dict(BASE, reason="x" * 501), "reason too long"),
]
for body, label in invalid:
    r = manager.post("/api/uniform-requests", json=body)
    check(f"{label} -> 400 JSON", r.status_code == 400 and "error" in r.get_json())
r = manager.post("/api/uniform-requests", json=dict(BASE, items=["Beanie", "Beanie", "Helmet", "Shorts"]))
check("duplicate and unknown items are filtered", r.get_json()["items"] == ["Shorts", "Beanie"])
check("non-JSON body gives 400", manager.post("/api/uniform-requests", data="not json", content_type="text/plain").status_code == 400)
r = manager.post("/api/uniform-requests", json=dict(BASE, reason="<script>alert(1)</script> replace it"))
check("HTML in text is stored as text", r.status_code == 200 and "<script>" in r.get_json()["reason"])

check.section("visibility")
mine = manager.get("/api/uniform-requests").get_json()
check("a manager sees only their own", all(m["manager"] == "Morgan Manager" for m in mine) and len(mine) == 4)
check("another manager sees only theirs", len(second.get("/api/uniform-requests").get_json()) == 1)
everything = admin.get("/api/uniform-requests").get_json()
check("the editor sees all 6", len(everything) == 6)
check("newest first", [x["id"] for x in everything] == sorted([x["id"] for x in everything], reverse=True))

check.section("delivering and deleting (editor only)")
rid = mine[0]["id"]
for client, who in ((manager, "owner"), (second, "other manager")):
    check(f"{who} cannot mark delivered (403)", client.post("/api/uniform-requests/status", json={"id": rid, "done": True}).status_code == 403)
    check(f"{who} cannot delete (403)", client.post("/api/uniform-requests/delete", json={"id": rid}).status_code == 403)
r = admin.post("/api/uniform-requests/status", json={"id": rid, "done": True})
check("editor marks delivered", r.status_code == 200 and r.get_json()["done"] is True)
check("owner sees it delivered", any(m["id"] == rid and m["done"] for m in manager.get("/api/uniform-requests").get_json()))
check("editor reopens", admin.post("/api/uniform-requests/status", json={"id": rid, "done": False}).get_json()["done"] is False)
check("unknown id gives 404", admin.post("/api/uniform-requests/status", json={"id": 9999, "done": True}).status_code == 404)
check("invalid id gives 404", admin.post("/api/uniform-requests/delete", json={"id": "x"}).status_code == 404)
check("editor deletes", admin.post("/api/uniform-requests/delete", json={"id": rid}).status_code == 200)
check("deleted request is gone", all(x["id"] != rid for x in admin.get("/api/uniform-requests").get_json()))

check.section("sync version")
v0 = admin.get("/api/version").get_json()["version"]
second.post("/api/uniform-requests", json=BASE)
check("a new request bumps the version", admin.get("/api/version").get_json()["version"] == v0 + 1)
second.post("/api/uniform-requests", json=dict(BASE, reason="short"))
check("a rejected request does not", admin.get("/api/version").get_json()["version"] == v0 + 1)

check.section("page")
html = admin.get("/").get_data(as_text=True)
check("sidebar entry", 'id="sideUniform"' in html and "Uniform / PPE Requests" in html)
check("login and register have the animated background", all('id="waves"' in anon.get(p).get_data(as_text=True) for p in ("/login", "/register")))
check.finish()
