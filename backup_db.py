import os
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "warehouse.db"))
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
KEEP = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 30

if not os.path.exists(SOURCE):
    sys.exit(f"Database not found: {SOURCE}")

os.makedirs(BACKUP_DIR, exist_ok=True)
target = os.path.join(BACKUP_DIR, datetime.now().strftime("warehouse_%Y-%m-%d_%H%M.db"))

source = sqlite3.connect(SOURCE)
destination = sqlite3.connect(target)
with destination:
    source.backup(destination)
destination.close()
source.close()
print("Backup created:", target)

existing = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("warehouse_") and f.endswith(".db"))
for name in existing[:-KEEP]:
    os.remove(os.path.join(BACKUP_DIR, name))
    print("Removed old backup:", name)
