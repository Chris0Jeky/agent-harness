#!/usr/bin/env python3
"""Harness dispatcher — the deny floor (PreToolUse) for all tiers.

Canonical copy: agent-harness/templates/hooks/dispatch.py
Deployed copies: ~/.claude/hooks/dispatch.py (global) and per-repo .claude/hooks/.
`harness audit` diffs deployed copies against the canonical one.

Contract (BLUEPRINT §2, SPECS §5-6):
- Blocks only the IRREVERSIBLE at every tier: force-push in all spellings, rm -rf outside
  the project, pipe-to-shell installs, sudo, secret-file mutation, PowerShell pipe-deletes.
- Work-loss guards (reset --hard, clean -f, checkout -- ., restore .) are tier-dependent:
  allow at T1-T2, ask at T3, deny at T4 or wave_mode. A repo whose declared posture is
  relaxed-git (tier.json flag `relaxed_work_loss_guards`) keeps them allow below T4/wave_mode;
  the flag is IGNORED at T4 and under wave_mode (other agents' work is in the blast radius).
- NEVER inspects commit-message / PR-body text: quoted strings are stripped before matching.
- Failure behavior: stdin that cannot be parsed -> allow (we cannot even identify the
  command; denying would brick every session). Exceptions during RULE EVALUATION -> deny
  (fail closed). Changes to this file are T4-class work: top model + review + smoke tests.

A change here must keep `smoke_test.py` green: python smoke_test.py
"""
import json
import os
import re
import sys

FLOOR_VERSION = "1.2.0 (2026-07-06)"

# --- helpers ---------------------------------------------------------------

_SINGLE_Q = re.compile(r"'[^']*'")
_DOUBLE_Q = re.compile(r'"(?:\\.|[^"\\])*"')


def strip_quotes(text: str) -> str:
    """Remove INERT quoted substrings so message/body text can never trip a rule.

    Single-quoted text never expands -> always stripped. Double-quoted text is
    stripped only when it contains no unescaped $ or backtick; if it does, the
    shell EXECUTES the substitution, so the text must stay visible for scanning.
    (Semantics ported from wealthlens-hq's earned pre_tool_use hardening: the
    naive strip-all-quotes let `git commit -m "wip $(rm -rf /)"` fail open.)
    """
    text = _SINGLE_Q.sub(" ", text)

    def _dq(m: "re.Match[str]") -> str:
        return m.group(0) if re.search(r"(?<!\\)[$`]", m.group(0)) else " "

    return _DOUBLE_Q.sub(_dq, text)


def norm_path(p: str) -> str:
    return p.replace("\\", "/").rstrip("/").lower()


def is_absolute(p: str) -> bool:
    return bool(re.match(r"^([a-zA-Z]:[\\/]|[\\/]|~)", p))


DANGEROUS_ROOTS = re.compile(r"^(/|~|~/|[a-zA-Z]:/?|/c/users/[^/]+|c:/users/[^/]+)$")


def load_tier(project_dir: str) -> dict:
    """Read .claude/tier.json if present; absent -> sandbox-like defaults (floor only)."""
    cfg = {"tier": 1, "flags": {}}
    if not project_dir:
        return cfg
    path = os.path.join(project_dir, ".claude", "tier.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        cfg["tier"] = int(data.get("tier", 1))
        cfg["flags"] = data.get("flags", {}) or {}
    except (OSError, ValueError):
        pass
    return cfg


def segments(sanitized: str):
    """Split a sanitized command line into per-command segments.

    Splits on chains (; newline | || &&) AND on substitution/subshell delimiters
    ($( ), <( ), backticks, parens) so an inner command is checked exactly like a
    top-level one — `git commit $(git push --force ...)` must not fail open.
    """
    return [s.strip() for s in re.split(r"[;\n()`|]|&&", sanitized) if s.strip()]


def tokens(segment: str):
    return segment.split()


# --- rules ------------------------------------------------------------------


def check(command: str, tier_cfg: dict, project_dir: str):
    """Return (decision, reason). decision in {'allow', 'ask', 'deny'}."""
    tier = tier_cfg.get("tier", 1)
    flags = tier_cfg.get("flags", {})
    wave = bool(flags.get("wave_mode"))
    sensitive = bool(flags.get("sensitive_data"))
    strict = tier >= 4 or wave  # work-loss guards become walls
    # Declared relaxed-git posture (BLUEPRINT §2): work-loss guards stay allow below
    # T4/wave_mode. Never weakens `strict` — the flag is ignored where guards are walls.
    relaxed = bool(flags.get("relaxed_work_loss_guards")) and not strict

    sanitized = strip_quotes(command)

    # Pipe rules run on the full sanitized text (the pipe IS the signal).
    if re.search(r"\b(curl|wget|iwr|irm)\b[^|;&]*\|\s*(sh|bash|zsh|pwsh|powershell|iex)\b",
                 sanitized, re.IGNORECASE):
        return "deny", "Piping a download straight into a shell is irreversible-by-design. Download, inspect, then run."
    if re.search(r"\|\s*(Remove-Item|del|rd)\b", sanitized, re.IGNORECASE):
        return "deny", "Piping into Remove-Item/del deletes whatever upstream matched. Enumerate first, delete explicitly."

    for seg in segments(sanitized):
        toks = tokens(seg)
        if not toks:
            continue
        head = toks[0].lower()

        if head == "sudo":
            return "deny", "sudo is blocked at the floor. If elevation is truly needed, the human runs it."

        # ---- git rules ----
        if head == "git":
            sub = ""
            for t in toks[1:]:
                if not t.startswith("-"):
                    sub = t.lower()
                    break

            if sub == "push":
                for t in toks[2:]:
                    if t == "--force" or (t.startswith("--force=")):
                        return "deny", "Force-push rewrites shared history. Use --force-with-lease on your own branch, or merge instead."
                    if t == "--force-with-lease" or t.startswith("--force-with-lease="):
                        if strict:
                            return "deny", "T4/wave: no force variants at all — other work rides on these refs."
                        continue
                    if re.match(r"^-[a-zA-Z]*f[a-zA-Z]*$", t):
                        return "deny", "git push -f is a force-push. Use --force-with-lease on your own branch, or merge instead."
                    if t.startswith("+") and len(t) > 1:
                        return "deny", "A +refspec is a forced update in disguise."

            if sub == "reset" and "--hard" in toks:
                if strict:
                    return "deny", "T4/wave: hard reset discards work that may not be yours. Inspect state; ask."
                if tier >= 3 and not relaxed:
                    return "ask", "T3: git reset --hard discards uncommitted work. Confirm you want this."

            if sub == "clean" and any(re.match(r"^-[a-zA-Z]*f", t) for t in toks[2:]):
                if strict:
                    return "deny", "T4/wave: git clean -f deletes untracked files that may belong to another agent."
                if tier >= 3 and not relaxed:
                    return "ask", "T3: git clean -f deletes untracked files. Confirm."

            if sub == "checkout" and "--" in toks:
                after = toks[toks.index("--") + 1:]
                if "." in after:
                    if strict:
                        return "deny", "T4/wave: checkout -- . wipes all local modifications."
                    if tier >= 3 and not relaxed:
                        return "ask", "T3: checkout -- . wipes local modifications. Confirm."

            if sub == "restore" and "." in toks[2:] and "--staged" not in toks:
                if strict:
                    return "deny", "T4/wave: git restore . wipes all local modifications."
                if tier >= 3 and not relaxed:
                    return "ask", "T3: git restore . wipes local modifications. Confirm."

        # ---- rm rules ----
        if head == "rm":
            flags_str = "".join(t.lstrip("-") for t in toks[1:] if t.startswith("-"))
            targets = [t for t in toks[1:] if not t.startswith("-")]
            if "r" in flags_str and "f" in flags_str:
                if not targets:
                    return "deny", "rm -rf with no clear target."
                for target in targets:
                    nt = norm_path(target)
                    if target == "*":
                        return "deny", "rm -rf * is a floor rule: enumerate and delete explicitly."
                    if DANGEROUS_ROOTS.match(nt):
                        return "deny", f"rm -rf {target}: refusing a filesystem/home root."
                    if is_absolute(target):
                        proj = norm_path(project_dir) if project_dir else ""
                        tmp_ok = "/temp/" in nt or "/tmp/" in nt or nt.startswith("/tmp")
                        if not ((proj and nt.startswith(proj)) or tmp_ok):
                            return "deny", f"rm -rf on an absolute path outside the project: {target}"

        # ---- PowerShell explicit recursive delete on outside-project absolute path ----
        if head in ("remove-item", "ri"):
            if any(re.match(r"^-recurse", t, re.IGNORECASE) for t in toks[1:]):
                for target in (t for t in toks[1:] if not t.startswith("-")):
                    nt = norm_path(target)
                    proj = norm_path(project_dir) if project_dir else ""
                    if is_absolute(target) and not (proj and nt.startswith(proj)) \
                            and "/temp/" not in nt and DANGEROUS_ROOTS.match(nt):
                        return "deny", f"Recursive Remove-Item on {target}: refusing a root."
                    if is_absolute(target) and proj and not nt.startswith(proj) and "/temp/" not in nt:
                        return "deny", f"Recursive Remove-Item outside the project: {target}"

        # ---- secret-file mutation ----
        secret_rx = re.compile(r"(^|[\\/])\.env(\.[\w.]+)?$|credential|secrets?\.|id_rsa|\.pem$",
                               re.IGNORECASE)
        if head in ("rm", "del", "mv", "set-content", "sc"):
            for target in (t for t in toks[1:] if not t.startswith("-")):
                if secret_rx.search(target):
                    return "deny", f"Mutating a secret-looking file ({target}) is floor-blocked. The human manages secrets."
        redir = re.search(r">{1,2}\s*(\S+)", seg)
        if redir and secret_rx.search(redir.group(1)):
            return "deny", f"Redirecting output into a secret-looking file ({redir.group(1)}) is floor-blocked."

        # ---- sensitive_data overlay ----
        if sensitive and head == "gh":
            if len(toks) >= 3 and toks[1] in ("repo", "gist") and toks[2] == "create":
                if any(t in ("--public", "-p") for t in toks):
                    return "deny", "sensitive_data repo: creating PUBLIC repos/gists is blocked."

    return "allow", ""


# --- entry ------------------------------------------------------------------


def respond(decision: str, reason: str):
    if decision == "allow":
        sys.exit(0)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": f"[floor {FLOOR_VERSION}] {reason}",
        }
    }))
    sys.exit(0)


def main():
    event = "pre"
    if "--event" in sys.argv:
        try:
            event = sys.argv[sys.argv.index("--event") + 1]
        except IndexError:
            pass
    if event != "pre":
        sys.exit(0)  # global layer wires only the floor; other events are repo-tier

    try:
        payload = json.load(sys.stdin)
    except Exception:
        # Cannot even identify the command — denying here would brick every session.
        sys.exit(0)

    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command.strip():
        sys.exit(0)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ""

    try:
        decision, reason = check(command, load_tier(project_dir), project_dir)
    except Exception as exc:  # fail CLOSED during rule evaluation
        respond("deny", f"dispatcher error ({exc.__class__.__name__}) — floor unavailable; fix ~/.claude/hooks before proceeding.")
        return
    respond(decision, reason)


if __name__ == "__main__":
    main()
