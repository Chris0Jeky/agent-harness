"""Temporary branch-only byte construction. Never writes a Git ref or PR."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import urllib.request

FILES = ["harness.py", "tests/test_sync_input_roots.py", "tests/test_doctor_downward_cwd.py", "tests/test_skill_preflight_unavailable_root.py"]
INPUTS = {"tests/test_harness.py": "12cac087584266d71b7c1abb0ac815cd5231225b", "tests/test_sync_input_roots.py": "809301b140d2e6a6a15453ffc6538c26653f6558", "tests/test_doctor_downward_cwd.py": "8298a018ea10d2510536550ae2ff5a4f78b3d776", "tests/test_skill_preflight_unavailable_root.py": "08215e0be5e56091453e29aa167c221a9dbb69ca"}

def blob(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()

def build():
    for path, expected in INPUTS.items():
        assert blob(Path(path).read_bytes()) == expected, path
    recipe = json.loads(Path(".maintenance/roots-recipe.json").read_text())
    path = Path("harness.py")
    assert blob(path.read_bytes()) == recipe["source"]
    text = path.read_bytes().decode("utf-8")
    for item in recipe["replacements"]:
        assert text.count(item["old"]) == item["count"], item["old"]
        text = text.replace(item["old"], item["new"])
    data = text.encode("utf-8")
    assert blob(data) == recipe["expected"]
    path.write_bytes(data)
    subprocess.run([sys.executable, "-m", "black", *FILES], check=True)
    subprocess.run([sys.executable, "-m", "ruff", "check", *FILES], check=True)
    subprocess.run([sys.executable, "-m", "py_compile", *FILES], check=True)
    sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / "tests")]
    suite = unittest.TestSuite()
    for name in ("test_sync_input_roots", "test_doctor_downward_cwd", "test_skill_preflight_unavailable_root"):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
    import test_harness
    for name in unittest.defaultTestLoader.getTestCaseNames(test_harness.HarnessTests):
        if name.startswith(("test_sync_global", "test_doctor", "test_logical_root")):
            suite.addTest(test_harness.HarnessTests(name))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    assert result.wasSuccessful()
    subprocess.run(["git", "diff", "--check"], check=True)
    changed = subprocess.check_output(["git", "diff", "--name-only"], text=True).splitlines()
    assert set(changed) <= set(FILES), changed
    subprocess.run(["git", "diff", "--", "harness.py"], check=True)
    receipt = {path: blob(Path(path).read_bytes()) for path in FILES}
    Path(".maintenance/prepared.json").write_text(json.dumps(receipt, indent=2))
    print("PREPARED", json.dumps(receipt, sort_keys=True))

def publish():
    assert os.environ["GITHUB_REPOSITORY"] == "Chris0Jeky/agent-harness"
    receipt = json.loads(Path(".maintenance/prepared.json").read_text())
    assert set(receipt) == set(FILES)
    for path, expected in receipt.items():
        data = Path(path).read_bytes()
        assert blob(data) == expected, path
        payload = json.dumps({"encoding": "base64", "content": base64.b64encode(data).decode()}).encode()
        request = urllib.request.Request("https://api.github.com/repos/Chris0Jeky/agent-harness/git/blobs", data=payload, method="POST", headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Accept": "application/vnd.github+json", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        assert result["sha"] == expected, path
        print("BLOB", path, expected, flush=True)

if __name__ == "__main__":
    {"build": build, "publish": publish}[sys.argv[1]]()
