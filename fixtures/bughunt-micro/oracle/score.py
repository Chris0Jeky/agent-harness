"""Score the curated BH3 fixture from complete JUnit evidence, never console text.

This is an offline test runner, not a sandbox for hostile candidate programs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ("bugs/MANIFEST.json", "tests/test_oracle.py", "src/app.py", "oracle/score.py")


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def load_bugs(data: bytes) -> list[dict]:
    manifest = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)
    if not isinstance(manifest, dict) or manifest.get("fixture") != "bughunt-micro":
        raise ValueError("expected the bughunt-micro manifest")
    total = manifest.get("planted_total")
    bugs = manifest.get("bugs")
    if (
        type(total) is not int
        or not 1 <= total <= 10
        or not isinstance(bugs, list)
        or len(bugs) != total
    ):
        raise ValueError("expected 1..10 bugs matching planted_total")
    ids, tests = set(), set()
    for bug in bugs:
        if not isinstance(bug, dict):
            raise ValueError("expected a bug object")
        identity, test = bug.get("id"), bug.get("test")
        if (
            not isinstance(identity, str)
            or not re.fullmatch(r"BUG-[0-9]{2}", identity)
            or not isinstance(test, str)
            or not re.fullmatch(r"test_[A-Za-z0-9_]+", test)
            or identity in ids
            or test in tests
        ):
            raise ValueError("bug IDs and test names must be valid and unique")
        fingerprint = bug.get("fingerprint_rg")
        if fingerprint is not None:
            if not isinstance(fingerprint, str):
                raise ValueError("fingerprint must be a regex string")
            re.compile(fingerprint)
        ids.add(identity)
        tests.add(test)
    return bugs


def read_results(report: Path, bugs: list[dict], exit_code: int) -> dict[str, bool]:
    if exit_code not in (0, 1):
        raise ValueError("pytest did not complete an ordinary test run")
    tree = ET.parse(report)
    if tree.getroot().tag != "testsuites":
        raise ValueError("unexpected JUnit root")
    cases = list(tree.iter("testcase"))
    expected = {bug["test"] for bug in bugs}
    names = [case.get("name") for case in cases]
    if len(names) != len(expected) or set(names) != expected:
        raise ValueError("JUnit must contain exactly one result per planted bug")
    outcomes = {}
    for case in cases:
        if case.find("error") is not None or case.find("skipped") is not None:
            raise ValueError("setup, teardown or skipped cases are not score evidence")
        outcomes[case.get("name")] = case.find("failure") is None
    expected_exit = 0 if all(outcomes.values()) else 1
    if exit_code != expected_exit:
        raise ValueError("pytest exit status disagrees with the complete case results")
    return outcomes


def score(root: Path = ROOT) -> dict:
    result = {
        "valid": False,
        "passed": 0,
        "total": 0,
        "per_bug": [],
        "pytest_exit": None,
        "mode": "invalid",
    }
    try:
        inputs = {name: (root / name).read_bytes() for name in INPUTS}
        bugs = load_bugs(inputs["bugs/MANIFEST.json"])
        result["total"] = len(bugs)
        source = inputs["src/app.py"].decode("utf-8")
        result["inputs_sha256"] = {
            name: hashlib.sha256(data).hexdigest() for name, data in inputs.items()
        }
        environment = dict(os.environ)
        for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
            environment.pop(key, None)
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        with tempfile.TemporaryDirectory(prefix="bh3-score-") as directory:
            temporary = Path(directory)
            report = temporary / "results.xml"
            config = temporary / "pytest.ini"
            config.write_text("[pytest]\n", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-m",
                    "pytest",
                    "-c",
                    str(config),
                    "--noconftest",
                    "-p",
                    "no:cacheprovider",
                    "--junitxml",
                    str(report),
                    "--basetemp",
                    str(temporary / "work"),
                    str(root / "tests/test_oracle.py"),
                ],
                cwd=root,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
            result["pytest_exit"] = completed.returncode
            outcomes = read_results(report, bugs, completed.returncode)
        if any((root / name).read_bytes() != data for name, data in inputs.items()):
            raise ValueError("fixture inputs changed during scoring")
        per_bug = []
        for bug in bugs:
            fingerprint = bug.get("fingerprint_rg")
            per_bug.append(
                {
                    "id": bug["id"],
                    "test": bug["test"],
                    "passed": outcomes[bug["test"]],
                    # Fingerprints describe source text; they never award points.
                    "fingerprint_present": (
                        re.search(fingerprint, source) is not None
                        if fingerprint is not None
                        else None
                    ),
                }
            )
        passed = sum(row["passed"] for row in per_bug)
        result.update(
            valid=True,
            passed=passed,
            per_bug=per_bug,
            mode="all_fixed" if passed == len(bugs) else "bugs_present",
        )
    except (
        OSError,
        ValueError,
        re.error,
        ET.ParseError,
        subprocess.TimeoutExpired,
    ) as exc:
        result["error"] = str(exc)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="require every bug fixed")
    args = parser.parse_args(argv)
    result = score()
    print(json.dumps(result, indent=2))
    if not result["valid"]:
        return 2
    return int(args.check and result["mode"] != "all_fixed")


if __name__ == "__main__":
    raise SystemExit(main())
