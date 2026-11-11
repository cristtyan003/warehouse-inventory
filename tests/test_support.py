import common as t

app = t.load_app("support")
check = t.Checker()
editor, viewer = t.login(app, t.EDITOR), t.login(app, t.VIEWER)

check("bootstrap exposes the default support email", editor.get("/api/bootstrap").get_json()["supportEmail"] == app.DEFAULT_SUPPORT_EMAIL)
check("viewer cannot change it", viewer.post("/api/support-email", json={"email": "a@b.com"}).status_code == 403)
for bad in ["", "abc", "a@b", "a b@c.com", "a@b.com,c@d.com", "<x>@b.com", "a" * 120 + "@b.com"]:
    check(f"rejects {bad[:20]!r}", editor.post("/api/support-email", json={"email": bad}).status_code == 400)
r = editor.post("/api/support-email", json={"email": "  help.desk@example.com "})
check("editor saves a trimmed address", r.status_code == 200 and r.get_json()["supportEmail"] == "help.desk@example.com")
check("viewer sees the new address", viewer.get("/api/bootstrap").get_json()["supportEmail"] == "help.desk@example.com")
check("page renders the new address", "help.desk@example.com" in viewer.get("/").get_data(as_text=True))
check.finish()
