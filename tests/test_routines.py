import sqlite3
from datetime import date, timedelta

import common as t


def legacy_schema(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE user (id INTEGER PRIMARY KEY, username VARCHAR(80) UNIQUE NOT NULL,
                           password_hash VARCHAR(255) NOT NULL, privilege INTEGER NOT NULL);
        """
    )
    con.commit()
    con.close()


app = t.load_app("routines", prepare=legacy_schema)
check = t.Checker()

check.section("migrating an older database")
db_path = app.app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
con = sqlite3.connect(db_path)
cols = [r[1] for r in con.execute('PRAGMA table_info("user")')]
tables = [r[0] for r in con.execute("select name from sqlite_master")]
con.close()
check("name columns were added", "first_name" in cols and "last_name" in cols)
check("schedule table was created", "schedule" in tables)

from models import User, db

with app.app.app_context():
    nameless = User(username="nameless@example.com", privilege=2)
    nameless.set_password(t.DEMO_PASSWORD)
    db.session.add(nameless)
    db.session.commit()
    check("an account without a name keeps working", nameless.full_name == "")

admin = t.login(app, t.ADMIN)
manager = t.login(app, t.MANAGER)
nameless_client = t.login(app, "nameless@example.com")
anon = app.app.test_client()

today = date.today()
tomorrow = (today + timedelta(days=1)).isoformat()
yesterday = (today - timedelta(days=1)).isoformat()

check.section("anonymous and nameless accounts")
check("anonymous list is redirected", anon.get("/api/schedules").status_code == 302)
r = nameless_client.post("/api/schedules", json={"date": tomorrow, "routine": "BBS", "quantity": 1})
check("nameless account cannot schedule (400 with message)", r.status_code == 400 and "name" in r.get_json()["error"].lower())
check("profile without last name is rejected", nameless_client.post("/api/profile", json={"firstName": "Ana", "lastName": ""}).status_code == 400)
r = nameless_client.post("/api/profile", json={"firstName": "ana", "lastName": "SOUZA lima"})
check("valid profile is saved and normalised", r.status_code == 200 and r.get_json()["fullName"] == "Ana Souza Lima")

check.section("creating routines")
r = nameless_client.post("/api/schedules", json={"date": tomorrow, "routine": "Both", "quantity": 2})
check("manager schedules for themselves", r.status_code == 200 and r.get_json()["name"] == "Ana Souza Lima")
mine_id = r.get_json()["id"]
check("new routines start pending", r.get_json()["done"] is False)
r = admin.post("/api/schedules", json={"date": tomorrow, "routine": "BBS", "quantity": 1})
check("editor can schedule too", r.status_code == 200)
other_id = r.get_json()["id"]
invalid = [
    ({"date": yesterday, "routine": "BBS", "quantity": 1}, "past date"),
    ({"date": "2026-02-31", "routine": "BBS", "quantity": 1}, "non-existent date"),
    ({"date": "", "routine": "BBS", "quantity": 1}, "empty date"),
    ({"date": tomorrow, "routine": "XYZ", "quantity": 1}, "unknown routine"),
    ({"date": tomorrow, "routine": "BBS", "quantity": 0}, "zero quantity"),
    ({"date": tomorrow, "routine": "BBS", "quantity": -3}, "negative quantity"),
    ({"date": tomorrow, "routine": "BBS", "quantity": "abc"}, "non-numeric quantity"),
    ({"date": tomorrow, "routine": "BBS", "quantity": 1000}, "huge quantity"),
    ({"date": tomorrow, "routine": "BBS"}, "missing quantity"),
]
for body, label in invalid:
    r = nameless_client.post("/api/schedules", json=body)
    check(f"{label} is rejected (400 JSON)", r.status_code == 400 and "error" in r.get_json())
check("scheduling for today is allowed", nameless_client.post("/api/schedules", json={"date": today.isoformat(), "routine": "DSW", "quantity": 1}).status_code == 200)

check.section("visibility")
mine = nameless_client.get("/api/schedules").get_json()
check("a manager sees only their own routines", len(mine) == 2 and all(m["name"] == "Ana Souza Lima" for m in mine))
everything = admin.get("/api/schedules").get_json()
check("the editor sees everyone's", len(everything) == 3)
check("list is ordered by date", [x["date"] for x in everything] == sorted(x["date"] for x in everything))

check.section("completing and deleting (editor only)")
check("manager cannot complete their own (403)", nameless_client.post("/api/schedules/status", json={"id": mine_id, "done": True}).status_code == 403)
check("manager cannot complete someone else's (403)", nameless_client.post("/api/schedules/status", json={"id": other_id, "done": True}).status_code == 403)
check("manager cannot delete (403)", nameless_client.post("/api/schedules/delete", json={"id": mine_id}).status_code == 403)
r = admin.post("/api/schedules/status", json={"id": mine_id, "done": True})
check("editor completes", r.status_code == 200 and r.get_json()["done"] is True)
check("owner sees it completed", any(m["id"] == mine_id and m["done"] for m in nameless_client.get("/api/schedules").get_json()))
check("editor reopens", admin.post("/api/schedules/status", json={"id": mine_id, "done": False}).get_json()["done"] is False)
r = admin.post("/api/schedules/status", json={"id": 99999, "done": True})
check("unknown id gives a 404 JSON", r.status_code == 404 and "error" in r.get_json())
check("invalid id gives a 404", admin.post("/api/schedules/status", json={"id": "abc", "done": True}).status_code == 404)
check("editor deletes", admin.post("/api/schedules/delete", json={"id": other_id}).status_code == 200)
check("deleted routine is gone", all(x["id"] != other_id for x in admin.get("/api/schedules").get_json()))

check.section("managers overview")
check("manager cannot list managers", manager.get("/api/managers").status_code == 403)
r = admin.get("/api/managers")
names = {m["username"] for m in r.get_json()}
check("editor lists active managers only", r.status_code == 200 and names == {"manager@example.com", "nameless@example.com"})
with app.app.app_context():
    User.query.filter_by(username="nameless@example.com").update({"active": False})
    db.session.commit()
check("blocked managers are left out", {m["username"] for m in admin.get("/api/managers").get_json()} == {"manager@example.com"})

check.section("sync version")
v0 = admin.get("/api/version").get_json()["version"]
manager.post("/api/profile", json={"firstName": "Morgan", "lastName": "Manager"})
manager.post("/api/schedules", json={"date": tomorrow, "routine": "DSW", "quantity": 1})
v1 = admin.get("/api/version").get_json()["version"]
check("scheduling bumps the version", v1 > v0)
manager.post("/api/schedules", json={"date": yesterday, "routine": "DSW", "quantity": 1})
check("a rejected request does not bump it", admin.get("/api/version").get_json()["version"] == v1)

check.section("page")
html = admin.get("/").get_data(as_text=True)
check("sidebar and menu button are present", 'id="menuBtn"' in html and 'id="sidebar"' in html)
check("routines entry is in the menu", "Safety Routines" in html)
check("editor gets CAN_EDIT = true", "const CAN_EDIT = true;" in html)
check("viewer gets CAN_EDIT = false", "const CAN_EDIT = false;" in t.login(app, t.VIEWER).get("/").get_data(as_text=True))
check("initial month comes from the calendar", "currentCalendarMonth()" in html)
check.finish()
