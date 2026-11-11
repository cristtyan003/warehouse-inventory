import common as t

app = t.load_app("safe_days")
check = t.Checker()
editor, viewer, anon = t.login(app, t.EDITOR), t.login(app, t.VIEWER), app.app.test_client()

check("starts at 0", viewer.get("/api/bootstrap").get_json()["safeDays"] == 0)
before = editor.get("/api/version").get_json()["version"]
r = editor.post("/api/safe-days", json={"days": "123"})
check("editor saves 123", r.status_code == 200 and r.get_json()["safeDays"] == 123)
check("viewer sees 123", viewer.get("/api/bootstrap").get_json()["safeDays"] == 123)
check("sync version increases", editor.get("/api/version").get_json()["version"] > before)
check("viewer cannot edit (403)", viewer.post("/api/safe-days", json={"days": 5}).status_code == 403)
check("anonymous cannot edit", anon.post("/api/safe-days", json={"days": 5}).status_code in (302, 401))
for bad in ("abc", "-5", "1.5", "", None, "100000", "10000000000000000000000"):
    r = editor.post("/api/safe-days", json={"days": bad})
    check(f"rejects {bad!r}", r.status_code == 400 and "error" in r.get_json())
check("value is unchanged after rejections", viewer.get("/api/bootstrap").get_json()["safeDays"] == 123)
check("accepts 0 and 99999", editor.post("/api/safe-days", json={"days": 0}).status_code == 200 and editor.post("/api/safe-days", json={"days": 99999}).get_json()["safeDays"] == 99999)
check("accepts a JSON number", editor.post("/api/safe-days", json={"days": 42}).get_json()["safeDays"] == 42)
check.finish()
