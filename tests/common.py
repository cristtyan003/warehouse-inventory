import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DEMO_PASSWORD = "demo-pass-123"
ADMIN = "admin@example.com"
EDITOR = "editor@example.com"
MANAGER = "manager@example.com"
VIEWER = "viewer@example.com"


def load_app(name, prepare=None, seed_data=True):
    path = os.path.join(tempfile.mkdtemp(), f"{name}.db")
    os.environ["DATABASE_URL"] = "sqlite:///" + path
    os.environ["DEMO_PASSWORD"] = DEMO_PASSWORD
    if prepare:
        prepare(path)
    import app as flask_app
    from seed import seed

    flask_app.app.config["TESTING"] = True
    if seed_data:
        with flask_app.app.app_context():
            seed()
    return flask_app


def login(flask_app, username, password=DEMO_PASSWORD):
    client = flask_app.app.test_client()
    client.post("/login", data={"username": username, "password": password})
    return client


class Checker:
    def __init__(self):
        self.failures = []

    def __call__(self, label, condition):
        print(f"[{'OK ' if condition else 'FAIL'}] {label}")
        if not condition:
            self.failures.append(label)

    def section(self, title):
        print(f"\n=== {title} ===")

    def finish(self):
        print("\n" + "=" * 60)
        if self.failures:
            print(f"{len(self.failures)} check(s) failed:")
            for label in self.failures:
                print("  -", label)
            raise SystemExit(1)
        print("All checks passed")
