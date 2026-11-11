import glob
import os
import subprocess
import sys

root = os.path.dirname(os.path.abspath(__file__))
failed = []
for path in sorted(glob.glob(os.path.join(root, "tests", "test_*.py"))):
    name = os.path.basename(path)
    result = subprocess.run([sys.executable, path], capture_output=True, text=True)
    status = "passed" if result.returncode == 0 else "FAILED"
    print(f"{name}: {status}")
    if result.returncode != 0:
        failed.append(name)
        print(result.stdout[-2000:], result.stderr[-2000:])
sys.exit(1 if failed else 0)
