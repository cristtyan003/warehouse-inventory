import os

from app import app
from models import ROLE_ADMIN, ROLE_EDITOR, ROLE_MANAGER, ROLE_VIEWER, Category, Item, User, db
from seed_data import CLEANING_DEFAULT, ITEMS, PRICE_DEFAULT, TARGET_DEFAULT

DEMO_USERS = (
    ("admin@example.com", ROLE_ADMIN, "Alex", "Admin"),
    ("editor@example.com", ROLE_EDITOR, "Erin", "Editor"),
    ("manager@example.com", ROLE_MANAGER, "Morgan", "Manager"),
    ("viewer@example.com", ROLE_VIEWER, "Val", "Viewer"),
)


def seed_catalog():
    if Category.query.first() is None:
        categories = {item["cat"] for item in ITEMS}
        for name in sorted(categories):
            db.session.add(
                Category(name=name, price=PRICE_DEFAULT.get(name), cleaning_price=CLEANING_DEFAULT.get(name))
            )
        db.session.commit()
        print(f"Created {len(categories)} categories.")

    if Item.query.first() is None:
        per_category = {}
        for item in ITEMS:
            per_category[item["cat"]] = per_category.get(item["cat"], 0) + 1
        for index, item in enumerate(ITEMS):
            total_target = TARGET_DEFAULT.get(item["cat"])
            target = round(total_target / per_category[item["cat"]]) if total_target is not None else None
            db.session.add(
                Item(
                    id=item["id"],
                    name=item["name"],
                    cat_name=item["cat"],
                    unit=item["unit"],
                    base_stock=item["stock"],
                    order_index=index,
                    target_value=target,
                )
            )
        db.session.commit()
        print(f"Created {len(ITEMS)} items.")


def seed_users():
    password = os.environ.get("DEMO_PASSWORD")
    if not password:
        print("Set DEMO_PASSWORD to create the demo accounts.")
        return
    created = 0
    for email, privilege, first, last in DEMO_USERS:
        if User.query.filter_by(username=email).first():
            continue
        user = User(username=email, privilege=privilege, first_name=first, last_name=last)
        user.set_password(password)
        db.session.add(user)
        created += 1
    db.session.commit()
    print(f"Created {created} demo account(s).")


def seed():
    db.create_all()
    seed_catalog()
    seed_users()


if __name__ == "__main__":
    with app.app_context():
        seed()
