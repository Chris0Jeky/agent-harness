# agent-harness

The reusable, tiered blueprint and portable tooling for how AI agents are configured across
every repo and machine Chris works on. Codex and Claude share policy; runtime adapters remain
explicit where their hook/config contracts differ.

| File | What it is |
|---|---|
| `BLUEPRINT.md` | The law: tier ladder (T0 tombstone → T4 live wire), the ten laws, regions, the Gardener loop, model/effort routing, estate migration map |
| `SPECS.md` | The details: tier.json schema, budget table, hook wiring, deny-floor test matrix, skeletons, Gardener/skill-forge specs |
| `BOOK.md` | The why: field notes and the origin stories behind every law — read on a couch, not in a context window |
| `MIGRATION_PROMPT.md` | Paste-ready prompt (+ per-repo appendices) to re-work any repo's harness with a top-model session |
| `harness.py` | Dependency-free CLI: repo `seed`/`audit`, live `doctor`, and backed-up shared global sync |
| `templates/hooks/` | Canonical cross-runtime `dispatch.py` + self-counting bypass matrix (version = `FLOOR_VERSION` in `dispatch.py`). `sync-global` installs these shared bytes in `~/.claude/hooks`; each active Codex repo owns one pinned `.codex/hooks.json` adapter |
| `legacy/` | The four salvaged Apr-2026 `bootstrap-*.ps1` scripts — template source material only; superseded, never run |

## Use

```powershell
# Inspect first; installation is never implicit.
py -3 .\harness.py doctor
py -3 .\harness.py doctor --repo C:\path\to\repo
py -3 .\harness.py audit C:\path\to\repo
py -3 .\harness.py seed C:\path\to\repo --tier 2 --sensitive-data

# Diff, then install global guidance, skills, and the shared dispatcher with backups.
py -3 .\harness.py sync-global --config-root C:\path\to\claude-config
py -3 .\harness.py sync-global --config-root C:\path\to\claude-config --apply
```

Install the pinned development tools with `py -3 -m pip install -r requirements-dev.txt`.
The same unit, smoke, Ruff, Black, and compile gates run on Windows, macOS, and Linux for every
pull request and push to `main`; workflow actions are pinned to immutable commit SHAs.

`seed` refuses to overwrite an existing runtime-neutral tier declaration. `sync-global` backs
up changed global guidance, shared Claude-home hook bytes, and managed skill folders before
replacing them. It also prunes the obsolete managed global Codex floor while preserving unrelated
Codex hooks. Each active repo must update its project `.codex/hooks.json` pin and be reviewed and
trusted with `/hooks` in a new Codex session; never stack a global and project Codex floor.
`doctor --repo` statically requires one project-floor candidate whose POSIX and Windows commands
match a conservative direct/wrapper execution shape and bind the current normalized dispatcher
hash to a named variable. It does not execute the hook or grant trust, so a new-session `/hooks`
review and live safe/deny canary remain mandatory.

For a linked Git worktree, Codex reads the project adapter from the root checkout that owns the
Git common directory, not the linked worktree's `.codex/hooks.json`. `doctor --repo` resolves that
active source even when given a subdirectory, reports it explicitly, and rejects a worktree-only or
different local copy. An identical tracked worktree copy is allowed but remains inactive. Configure,
review, and trust the root-checkout adapter through `/hooks`; do not edit trust hashes manually or
use a bypass flag.

Status (2026-07-24): the blueprint, shared deny floor (`FLOOR_VERSION` in `templates/hooks/dispatch.py`), project-local Codex adapter model,
portable CLI, and versioned global guidance layer are implemented. The bounded matrix hardens supported Bash,
PowerShell, and cmd forms across authority resolution, quoting, wrappers, nested interpreters,
pipelines, git push safety, and secret-file mutations. It remains a defense-in-depth tripwire,
not an exhaustive shell sandbox. Its guarantee is scoped to command-line argv it can parse: it
does NOT intercept `apply_patch`, Edit/Write, or MCP tool surfaces (those are separate matchers the
runtime must expose), it cannot recover program text passed through arbitrary interpreters or
stdin, and it cannot repair a runtime that fails open on hook spawn/timeout/crash. Those remain
Codex-engine limitations, not floor guarantees. Gardener scheduling remains intentionally deferred
until the bootstrap/audit loop has earned trust through real use.

Provenance: synthesized by Fable 5 from a 12-agent estate survey, three independent
architecture proposals, and an adversarial completeness critique. This repo obeys its own
laws: one home per policy, budgets with rotation, no speculative scaffolding.
