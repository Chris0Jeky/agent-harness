"""Oracle tests - each test maps to one planted bug id.

While bugs are present, these fail. After fixes/golden.patch, all pass.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import app  # noqa: E402


def test_BUG01_off_by_one_window_sum():
    values = [1, 2, 3, 4, 5]
    # sum of indices 1..3 exclusive end=4 -> 2+3+4=9
    assert app.window_sum(values, 1, 4) == 9


def test_BUG02_wrong_comparison_eligible_at_threshold():
    assert app.is_eligible(0.0, threshold=0.0) is True
    assert app.is_eligible(-0.1, threshold=0.0) is False


def test_BUG03_swapped_args_scale_offset():
    # 10 * 2 + 3 = 23
    assert app.scale_offset(10, 2, 3) == 23


def test_BUG04_missing_return_none():
    assert app.first_nonempty(["", "  ", ""]) is None
    assert app.first_nonempty(["", "hi"]) == "hi"


def test_BUG05_case_insensitive_config(tmp_path: Path):
    (tmp_path / "App.Config").write_text("x=1\n", encoding="utf-8")
    # Force the listing fallback even on a case-insensitive filesystem.
    # The exact-match fast path otherwise conceals BUG-05 on Windows/macOS.
    with mock.patch.object(Path, "exists", return_value=False):
        found = app.resolve_config(tmp_path, "app.config")
    assert found == tmp_path / "App.Config"


def test_BUG06_timezone_aware_deadline():
    deadline = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
    now = dt.datetime(2029, 12, 31, 12, 0, tzinfo=dt.timezone.utc)
    hours = app.hours_until(deadline, now=now)
    assert hours == pytest.approx(12.0)


def test_BUG07_query_uses_placeholder():
    q = app.build_user_query("ada")
    assert "'ada'" not in q
    assert "?" in q or "%s" in q or ":name" in q
    # fingerprint: must not embed raw user string via quotes
    assert "ada" not in q or ":name" in q


def test_BUG08_default_limit_ten():
    items = list(range(25))
    page = app.paginate(items)  # default page=1, limit=10
    assert page == list(range(10))


def test_BUG09_empty_list_mean():
    assert app.safe_mean([]) == 0.0
    assert app.safe_mean([2.0, 4.0]) == 3.0


def test_BUG10_created_status_201():
    resp = app.create_response(True, created=True)
    assert resp["status"] == 201
