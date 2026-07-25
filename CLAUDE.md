# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The runtime-neutral source for the tier model, shared deny floor, and portable bootstrap/audit
tooling used across all of Chris's Codex and Claude repositories. Codex and Claude share policy
and parsing; runtime-specific hook output stays explicit.

Doc hierarchy — read in this order, only as deep as needed:
- `README.md` — executable commands and current shipped state
- `BLUEPRINT.md` — durable policy (tier ladder, the ten laws, regions, model routing)
- `SPECS.md` — schemas, budgets, hook wiring, deny-floor test matrix
- `BOOK.md` — rationale only; never needed for routine work
- `legacy/` — historical source material; never run anything in it

This repo is tier 3 (workshop) per `.agent-harness/tier.json`: push free, merge gated.

## Commands

```powershell
py -3 -m pip install -r requirements-dev.txt   # ruff + black, pinned

# Full verification (same gates as CI, which runs on Windows/macOS/Linux, Python 3.11)
py -3 -m unittest discover -s tests -p "test_*.py" -v
py -3 templates\hooks\smoke_test.py            # deny-floor bypass matrix
py -3 -m ruff check harness.py tests\test_harness.py tests\test_curl_option_arity.py tests\test_git_editor_terminal_flows.py scripts\generate_curl_option_arity_fixture.py templates\hooks\dispatch.py templates\hooks\smoke_test.py
py -3 -m black --check <same file list as ruff>

# Single test
py -3 -m unittest tests.test_harness.<TestClass>.<test_method> -v

# Harness CLI (inspect first; installation is never implicit)
py -3 harness.py doctor [--repo <path>]
py -3 harness.py audit <repo> [--json]
py -3 harness.py seed <repo> --tier N [--sensitive-data]
py -3 harness.py sync-global --config-root <claude-config checkout> [--apply]
```

Ruff and Black run only on the explicit file list above (see `.github/workflows/ci.yml`);
new Python files must be added to all three CI steps (ruff, black, py_compile).

## Architecture

Two Python artifacts, both deliberately dependency-free (stdlib only):

**`harness.py`** — single-file CLI with four subcommands:
- `audit` — validates a repo's tier declaration, doc line budgets (CLAUDE.md is capped per
  tier: T3 = 150 lines), and scans `SCAN_PATHS` files for stale hard-coded user-profile paths.
  It also runs the **reality checks** (`reality_findings`): declared `sensitive_data` vs each
  remote's real host visibility, vendored floor bytes vs template vs deployed global, and
  declared `human_todo` vs a file that exists. `MISMATCH` fails; `UNPROVEN` is printed loudly
  and never renders as a pass; probes are read-only, deadline-bounded, and injectable
  (`command_runner`) so tests never spawn a process or hit the network
- `seed` — writes a write-once `.agent-harness/tier.json`; refuses to overwrite
- `sync-global` — diffs (default) or installs (`--apply`) shared global guidance, managed
  skills, and the dispatcher bytes into `~/.claude/hooks`, backing up anything it replaces
- `doctor` — checks inspectable global hook sources; `--repo` conditionally walks every active
  project `.codex` layer, including JSON and inline TOML hooks and linked-worktree root mappings.
  It validates each complete hook subtree and the hook-specific metadata it interprets before
  requiring the canonical root adapter's POSIX and Windows commands to match a conservative
  direct/wrapper execution shape and declare the current dispatcher marker. A repo-relative
  wrapper path is rejected when the session cwd is not the hook source root. Non-default persisted
  project-root markers, unsupported stored legacy profile selectors, and inspectable activation
  blockers fail closed. It does not fully validate unrelated config fields, prove runtime/cloud
  overrides, or execute the hook — a CWD-specific new-session `/hooks` review and live safe/deny
  canary remain mandatory.

Roughly half of `harness.py` is the static analyzer for Codex hook commands
(`shell_command_segments`, `segment_invokes_direct_floor`, `command_binds_pin`, …). It is
intentionally conservative: reject anything it cannot prove safe.

**`templates/hooks/dispatch.py`** — the canonical shared Claude/Codex deny floor (~8.5k lines).
Invoked as a PreToolUse hook with `--event pre --runtime claude|codex`; reads the repo's tier
from `.agent-harness/tier.json` (falling back to `.claude/`) and emits the runtime-appropriate
allow/ask/deny JSON. Contract (docstring + BLUEPRINT §2, SPECS §5-6):
- Blocks only the irreversible at every tier (force-push, rm -rf outside project, pipe-to-shell
  installs, sudo, secret-file mutation); work-loss guards are tier-dependent
- Strips quoted strings before matching — never inspects commit-message/PR-body text
- Unparseable stdin → allow (can't identify the command); exception during rule evaluation →
  deny (fail closed)
- It is a tripwire, not a sandbox: it only parses command-line argv. It does not cover
  apply_patch/Edit/Write/MCP surfaces, stdin-fed interpreters, or a runtime that fails open

`templates/hooks/smoke_test.py` holds the `CASES` bypass matrix (~3k lines of cases) exercising
Bash/PowerShell/cmd forms: quoting, wrappers, nested interpreters, encoded PowerShell, pipelines,
curl/wget output binding, git push safety, secret-file mutation.

`.codex/hooks.json` is this repo's own project-local Codex adapter. Its `commandWindows`/POSIX
commands declare the normalized SHA-256 of `dispatch.py` as an **audit-only** marker — the runtime
never verifies it (SPECS §5), so any dispatch.py change requires bumping `FLOOR_VERSION` in that
file AND refreshing the marker here and in every consumer repo (see `normalized_text_sha256` in
harness.py), then a new-session `/hooks` re-trust per repo. Never call it runtime enforcement.

`tests/fixtures/` includes a curl option-arity fixture generated by
`scripts/generate_curl_option_arity_fixture.py` — regenerate rather than hand-edit it.

## Change rules

- `templates/hooks/dispatch.py` is T4-class shared infrastructure regardless of this repo's
  tier: any change requires the smoke suite, the harness unit tests, and an independent
  read-only review before merge.
- Keep `harness.py` and `dispatch.py` stdlib-only and portable across Windows/macOS/Linux.
- Never hard-code a user profile path (audit flags it); discover `$HOME`, `$CODEX_HOME`, and
  Git roots at runtime.
- `seed` must stay write-once; `sync-global` must keep dry-run default and backups on apply.
- Add a test with every new enforcement or migration behavior.
- Small, present-tense commits; never squash-merge.
- This file is budget-capped at 150 lines by `harness.py audit` — rotate detail into the
  linked docs instead of growing it.
