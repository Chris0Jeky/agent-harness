"""Reconstruct one reviewed, hash-bound patch; publish blobs only, never refs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zlib

BASE = "eb881070808eabd7122baed9238999de67c05719"
PATCH_SHA = "e4d6d920b6ee4a222fadcee512452d194c1bba87ebbe09df97928aa7cd840366"
EXPECTED = {
    "harness.py": "2d524b482d4d5510265f98e9928f64ea48c11207",
    "tests/test_harness.py": "89319228121e7ef4597357ae7e36bc1d3dd02e9f",
    "tests/test_managed_agent_atomic.py": "8590004be2b218f0b07b237a87d428fccb6b3841",
    "docs/maintenance/MANAGED_AGENTS.md": "66416aed4e7cc31d58ba87197f8a880af9be1110",
}
OUTPUT = Path(".maintenance-output")


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def run(name, command, expected=0):
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    text = result.stdout + result.stderr
    (OUTPUT / (name + ".log")).write_text(text, encoding="utf-8")
    print(text)
    if result.returncode != expected:
        raise SystemExit(f"{name}: exit {result.returncode}, expected {expected}")


def build():
    OUTPUT.mkdir(exist_ok=True)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD^"], text=True).strip()
    if actual != BASE:
        raise SystemExit("unexpected preparation base")
    encoded = Path(".maintenance/agents-253.patch.zlib.b64").read_text().strip()
    # Repair two identified transport transcription errors before the whole-patch hash gate.
    encoded = encoded.replace("NbsUUKl8", "NbsUKl8").replace("y7R3V3oXbAIC", "y7R3V68bAIC")
    patch = zlib.decompress(base64.b64decode(encoded, validate=True))
    if hashlib.sha256(patch).hexdigest() != PATCH_SHA:
        raise SystemExit("reviewed patch hash mismatch; no source changed")
    patch_path = OUTPUT / "reviewed.patch"
    patch_path.write_bytes(patch)
    run("patch-check", ["git", "apply", "--check", str(patch_path)])
    subprocess.run(["git", "apply", "--index", str(patch_path)], check=True)
    changed = subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).splitlines()
    if set(changed) != set(EXPECTED):
        raise SystemExit("unexpected candidate paths")
    for path, expected in EXPECTED.items():
        if git_blob(Path(path).read_bytes()) != expected:
            raise SystemExit("unformatted candidate differs from reviewed local bytes: " + path)
    python_files = [path for path in EXPECTED if path.endswith(".py")]
    run("black", [sys.executable, "-m", "black", *python_files])
    run("ruff", [sys.executable, "-m", "ruff", "check", *python_files])
    run("compile", [sys.executable, "-m", "py_compile", *python_files])
    run("atomic-tests", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_managed_agent_atomic.py", "-v"])
    run("harness-tests", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_harness.py", "-v"])
    subprocess.run(["git", "add", "--", *EXPECTED], check=True)
    run("whitespace", ["git", "diff", "--cached", "--check"])
    candidate = subprocess.check_output(["git", "diff", "--cached", "--binary"])
    (OUTPUT / "candidate.patch").write_bytes(candidate)
    manifest = {"base": BASE, "reviewed_patch_sha256": PATCH_SHA, "files": {}}
    for path in EXPECTED:
        data = Path(path).read_bytes()
        destination = OUTPUT / "files" / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        manifest["files"][path] = {"git_blob": git_blob(data), "sha256": hashlib.sha256(data).hexdigest()}
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


def publish():
    manifest = json.loads((OUTPUT / "manifest.json").read_text())
    if manifest["base"] != BASE or set(manifest["files"]) != set(EXPECTED):
        raise SystemExit("invalid publish manifest")
    for path, record in manifest["files"].items():
        data = (OUTPUT / "files" / path).read_bytes()
        if git_blob(data) != record["git_blob"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise SystemExit("artifact changed before blob publication")
        request = urllib.request.Request(
            "https://api.github.com/repos/Chris0Jeky/agent-harness/git/blobs",
            data=json.dumps({"content": base64.b64encode(data).decode(), "encoding": "base64"}).encode(),
            headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Accept": "application/vnd.github+json", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            actual = json.load(response)["sha"]
        if actual != record["git_blob"]:
            raise SystemExit("published blob identity mismatch")
        print(path, actual)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    {"build": build, "publish": publish}[sys.argv[1]]()
