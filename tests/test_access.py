import common as t
from models import User, db

app = t.load_app("access")
check = t.Checker()
admin, editor, manager, viewer = (t.login(app, u) for u in (t.ADMIN, t.EDITOR, t.MANAGER, t.VIEWER))

NEW = {"firstName": "Lia", "lastName": "Souza", "username": "lia@example.com", "role": "manager", "password": "temp-pass-123"}

check.section("who can manage accounts")
for who, client in (("editor", editor), ("manager", manager), ("viewer", viewer)):
    check(f"{who} cannot list users", client.get("/api/users").status_code == 403)
    check(f"{who} cannot create users", client.post("/api/users/create", json=NEW).status_code == 403)
check("admin lists users", len(admin.get("/api/users").get_json()) == 4)
check("editor lists managers", editor.get("/api/managers").status_code == 200)
check("manager cannot list managers", manager.get("/api/managers").status_code == 403)

check.section("creating accounts")
r = admin.post("/api/users/create", json=NEW)
check("admin creates a manager", r.status_code == 200 and r.get_json()["role"] == "manager")
check("duplicate email is refused", admin.post("/api/users/create", json=NEW).status_code == 400)
for label, changes in (("bad email", {"username": "nope"}), ("bad role", {"role": "root"}), ("short password", {"password": "abc"}),
                       ("missing name", {"firstName": ""}), ("name with digits", {"lastName": "S0uza"})):
    check(f"{label} is refused", admin.post("/api/users/create", json={**NEW, "username": "z@example.com", **changes}).status_code == 400)
check("new account can sign in", t.login(app, "lia@example.com", "temp-pass-123").get("/api/bootstrap").status_code == 200)
check("managers list includes it", any(m["username"] == "lia@example.com" for m in editor.get("/api/managers").get_json()))

with app.app.app_context():
    lia = User.query.filter_by(username="lia@example.com").first().id
    me = User.query.filter_by(username=t.ADMIN).first().id

check.section("updating accounts")
r = admin.post("/api/users/update", json={"id": lia, "role": "editor", "firstName": "Lia", "lastName": "Souza-Lima"})
check("role and name are updated", r.get_json()["role"] == "editor" and r.get_json()["fullName"] == "Lia Souza-Lima")
check("blocking an account works", admin.post("/api/users/update", json={"id": lia, "active": False}).get_json()["active"] is False)
check("a blocked account cannot sign in", b"blocked" in app.app.test_client().post("/login", data={"username": "lia@example.com", "password": "temp-pass-123"}).data)
admin.post("/api/users/update", json={"id": lia, "active": True, "newPassword": "other-pass-456"})
check("an admin can reset a password", t.login(app, "lia@example.com", "other-pass-456").get("/api/bootstrap").status_code == 200)
check("email clash is refused", admin.post("/api/users/update", json={"id": lia, "username": t.VIEWER}).status_code == 400)
check("unknown account gives 404", admin.post("/api/users/update", json={"id": 9999}).status_code == 404)
check("admins cannot demote themselves", admin.post("/api/users/update", json={"id": me, "role": "viewer"}).status_code == 400)
check("admins cannot block themselves", admin.post("/api/users/update", json={"id": me, "active": False}).status_code == 400)

check.section("last administrator")
admin.post("/api/users/update", json={"id": lia, "role": "admin"})
lia_client = t.login(app, "lia@example.com", "other-pass-456")
check("a second admin can demote the first", lia_client.post("/api/users/update", json={"id": me, "role": "viewer"}).status_code == 200)
check("the last admin cannot be deleted", lia_client.post("/api/users/delete", json={"id": lia}).status_code == 400)
check("the last admin cannot be demoted", lia_client.post("/api/users/update", json={"id": lia, "role": "viewer"}).status_code == 400)

check.section("deleting accounts")
with app.app.app_context():
    spare = User(username="spare@example.com", privilege=1)
    spare.set_password(t.DEMO_PASSWORD)
    db.session.add(spare)
    db.session.commit()
    spare_id = spare.id
check("an account without records can be deleted", lia_client.post("/api/users/delete", json={"id": spare_id}).status_code == 200)
mgr = t.login(app, t.MANAGER)
mgr.post("/api/uniform-requests", json={"employee": "Joao Silva", "kind": "Replacement", "shift": "T1", "items": ["Pants"], "reason": "Torn at the knee badly"})
with app.app.app_context():
    mgr_id = User.query.filter_by(username=t.MANAGER).first().id
r = lia_client.post("/api/users/delete", json={"id": mgr_id})
check("an account with records must be blocked instead", r.status_code == 400 and "Block" in r.get_json()["error"])
check("admins cannot delete themselves", lia_client.post("/api/users/delete", json={"id": lia}).status_code == 400)

check.section("profile")
check("profile saves a clean name", viewer.post("/api/profile", json={"firstName": "VERA", "lastName": "santos"}).get_json()["fullName"] == "Vera Santos")
check("profile rejects digits", viewer.post("/api/profile", json={"firstName": "V3ra", "lastName": "Santos"}).status_code == 400)
check("bootstrap reflects the profile", viewer.get("/api/bootstrap").get_json()["me"]["shortName"] == "Vera Santos")
check.finish()
