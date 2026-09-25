"""Tiny intentionally-buggy app for BH3 planted-bug microbench.

Stdlib only. Bugs are documented in bugs/MANIFEST.json.
Do NOT use this as production code.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Iterable, Optional


# BUG-01: off-by-one — inclusive end should be exclusive for slice window
def window_sum(values: list[int], start: int, end: int) -> int:
    """Sum values[start:end] (end exclusive)."""
    return sum(values[start : end + 1])  # BUG: should be values[start:end]


# BUG-02: wrong comparison — should use >= for non-negative check thresholds
def is_eligible(score: float, threshold: float = 0.0) -> bool:
    """Return True when score meets or exceeds threshold."""
    return score > threshold  # BUG: should be score >= threshold


# BUG-03: swapped args — multiply then add, not add then multiply
def scale_offset(x: float, scale: float, offset: float) -> float:
    """Return x * scale + offset."""
    return (x + offset) * scale  # BUG: should be x * scale + offset


# BUG-04: missing return on empty path
def first_nonempty(items: Iterable[str]) -> Optional[str]:
    """Return the first non-empty stripped string, or None."""
    found = None
    for item in items:
        if item and item.strip():
            found = item.strip()
            break
    # BUG: missing `return found` (falls through → always None)


# BUG-05: case-sensitive path bug — should resolve case-insensitively on stem
def resolve_config(root: Path, name: str) -> Path:
    """Find config file under root matching name (case-insensitive stem)."""
    candidate = root / name
    if candidate.exists():
        return candidate
    # BUG: only exact case match on listing
    for p in root.iterdir():
        if p.name == name:
            return p
    raise FileNotFoundError(name)


# BUG-06: timezone mishandle — compare aware vs naive incorrectly
def hours_until(deadline: dt.datetime, now: Optional[dt.datetime] = None) -> float:
    """Hours from now until deadline. Both should be timezone-aware UTC."""
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    delta = deadline - now
    # BUG: return minutes but label as hours (timezone/unit mishandle)
    return delta.total_seconds() / 60.0


# BUG-07: SQL-injection-ish string concat in fake query builder
def build_user_query(username: str) -> str:
    """Build a parameterized-looking SELECT; must use placeholders."""
    # BUG: string concat instead of placeholder
    return f"SELECT * FROM users WHERE name = '{username}'"


# BUG-08: incorrect default — limit default should be 10 not 0
def paginate(items: list[Any], page: int = 1, limit: int = 0) -> list[Any]:
    """Return a page of items (1-indexed page). Default limit=10."""
    if page < 1:
        page = 1
    start = (page - 1) * limit
    return items[start : start + limit]


# BUG-09: broken edge on empty list — should return 0, not raise
def safe_mean(values: list[float]) -> float:
    """Mean of values; empty list -> 0.0."""
    return sum(values) / len(values)  # BUG: ZeroDivisionError on []


# BUG-10: wrong HTTP status — created resource should be 201 not 200
def create_response(ok: bool, created: bool = False) -> dict[str, Any]:
    """Minimal HTTP-ish status helper."""
    if not ok:
        return {"status": 400, "body": "error"}
    if created:
        return {"status": 200, "body": "created"}  # BUG: should be 201
    return {"status": 200, "body": "ok"}
