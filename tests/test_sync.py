import common as t

app = t.load_app("sync")
check = t.Checker()
editor, viewer, anon = t.login(app, t.EDITOR), t.login(app, t.VIEWER), app.app.test_client()


def version(client=viewer):
    return client.get("/api/version").get_json()["version"]


t0 = version()
check.section("version endpoint")
check("anonymous is redirected", anon.get("/api/version").status_code == 302)
check("initial version is 0", t0 == 0)
check("response is not cached", viewer.get("/api/version").headers.get("Cache-Control") == "no-store")

check.section("editor writes, viewer reads")
r = editor.post("/api/monthly", json={"month": "2026-09", "itemId": "t-shirt-s", "stock": 74, "outflow": 30})
check("write accepted", r.status_code == 200)
check("version increased by exactly 1", version() == t0 + 1)
check("viewer sees the new value", viewer.get("/api/month/2026-09").get_json()["t-shirt-s"]["outflow"] == 30)

check.section("every write type bumps the version")
ids = [it["id"] for it in editor.get("/api/bootstrap").get_json()["items"]]
writes = [
    ("category", "/api/category", {"name": "T-Shirt", "price": 35.0}),
    ("item target", "/api/item-target", {"itemId": "t-shirt-s", "value": 40}),
    ("budget", "/api/budget", {"month": "2026-09", "value": 5000}),
    ("add item", "/api/catalog/add-item", {"name": "T-Shirt XXXL", "cat": "T-Shirt"}),
    ("rename item", "/api/catalog/rename-item", {"itemId": "t-shirt-s", "name": "T-Shirt XS"}),
    ("reorder", "/api/catalog/reorder", {"order": list(reversed(ids))}),
    ("remove item", "/api/catalog/remove-item", {"itemId": "chemical-gloves"}),
]
for label, url, body in writes:
    before = version()
    r = editor.post(url, json=body)
    check(f"{label}: accepted and version +1", r.status_code == 200 and version() == before + 1)

boot = viewer.get("/api/bootstrap").get_json()
check("viewer sees the renamed item", "T-Shirt XS" in [i["name"] for i in boot["items"]])
check("viewer sees the new category price", boot["categories"]["T-Shirt"]["price"] == 35.0)
check("viewer sees the budget", viewer.get("/api/budget").get_json()["2026-09"] == 5000)
check("viewer no longer sees the removed item", "chemical-gloves" not in [i["id"] for i in boot["items"]])

check.section("what must not bump the version")
before = version()
check("viewer write is forbidden", viewer.post("/api/monthly", json={"month": "2026-09", "itemId": "t-shirt-m", "stock": 9}).status_code == 403)
check("invalid write (400) does not count", editor.post("/api/monthly", json={}).status_code == 400)
check("unknown item (404) does not count", editor.post("/api/catalog/remove-item", json={"itemId": "missing"}).status_code == 404)
check("anonymous POST does not count", anon.post("/api/monthly", json={"month": "2026-09", "itemId": "t-shirt-m"}).status_code == 302)
for route in ("/api/bootstrap", "/api/budget", "/api/months", "/api/month/2026-09", "/api/version"):
    viewer.get(route)
anon.post("/login", data={"username": t.ADMIN, "password": "wrong"})
check("none of those changed the version", version() == before)

check.section("consecutive writes")
before = version()
for n in range(5):
    editor.post("/api/monthly", json={"month": "2026-09", "itemId": "t-shirt-m", "outflow": n})
check("5 writes raise the version by 5", version() == before + 5)
check.finish()
