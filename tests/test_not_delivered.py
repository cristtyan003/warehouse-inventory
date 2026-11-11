import common as t

app = t.load_app("not_delivered")
check = t.Checker()
admin, manager = t.login(app, t.ADMIN), t.login(app, t.MANAGER)

BODY = {"employee": "john doe", "kind": "Replacement", "shift": "T2", "items": ["Pants"],
        "reason": "Pants torn at the knee, need a replacement"}
rid = manager.post("/api/uniform-requests", json=BODY).get_json()["id"]

check("a manager cannot refuse a request (403)", manager.post("/api/uniform-requests/refuse", json={"id": rid, "reason": "x" * 20}).status_code == 403)
r = admin.post("/api/uniform-requests/refuse", json={"id": rid, "reason": "short"})
check("a short justification gives 400 with a message", r.status_code == 400 and "error" in r.get_json())
check("an oversized justification gives 400", admin.post("/api/uniform-requests/refuse", json={"id": rid, "reason": "a" * 501}).status_code == 400)
r = admin.post("/api/uniform-requests/refuse", json={"id": rid, "reason": "Requested size 44 is out of stock"})
d = r.get_json()
check("editor refuses with a justification", r.status_code == 200 and d["refused"] and not d["done"] and "stock" in d["refusalReason"])
check("the manager sees the justification", manager.get("/api/uniform-requests").get_json()[0]["refusalReason"].startswith("Requested size"))
d = admin.post("/api/uniform-requests/status", json={"id": rid, "done": True}).get_json()
check("marking delivered clears the refusal", d["done"] and not d["refused"] and d["refusalReason"] == "")
admin.post("/api/uniform-requests/refuse", json={"id": rid, "reason": "Employee has left the company"})
d = admin.post("/api/uniform-requests/refuse", json={"id": rid, "refused": False}).get_json()
check("reopening clears everything", not d["refused"] and not d["done"] and d["refusalReason"] == "")

check.finish()
