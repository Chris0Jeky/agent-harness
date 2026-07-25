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

`audit` also measures declarations against reality instead of against other documents:
a declared `sensitive_data` overlay against each remote's actual host visibility, vendored
`dispatch.py` and `smoke_test.py` bytes under `hooks/` or `.claude/hooks/` against the canonical
template (reporting `FLOOR_VERSION` alongside the hashes), and a declared
`human_todo` against a file that exists. A repo that vendors nothing says so rather than
emitting nothing. The deployed `~/.claude/hooks` copy is reported as an `advisory`, never a
failure: it is the auditing machine's state, so making it a repo verdict would let the same
repo pass in CI and fail on a developer box; `doctor` owns that axis. Each reports `MISMATCH` (a hard failure, exit 1),
`UNPROVEN` (the check could not run — never rendered as a pass, never a failure), or `ok`.
Every probe is read-only, bounded by a per-command timeout and an aggregate deadline, and
skipped entirely when the repo declares nothing to check, so an offline or `gh`-less run
degrades to `UNPROVEN` and exits 0. Because the byte comparison reads the harness working
tree, a non-`main` or dirty harness checkout is refused as the canonical reference and said
so. The audit summary line and `--json` both carry the count of `UNPROVEN` checks, so a run
that measured nothing cannot read as a clean one. `doctor` surfaces the same findings for
`--repo`, plus a global `floor version` check; when the reference is refused that check prints
`[UNPROVEN]`, never `[ok]`, and — like every unproven check — leaves the exit code alone.

`seed` refuses to overwrite an existing runtime-neutral tier declaration. `sync-global` backs
up changed global guidance, shared Claude-home hook bytes, and managed skill folders before
replacing them. It also prunes the obsolete managed global Codex floor while preserving unrelated
Codex hooks. Each active repo must update its project `.codex/hooks.json` pin and be reviewed and
trusted with `/hooks` in a new Codex session; never stack a global and project Codex floor.
`doctor` rejects deny-floor copies in every statically inspectable global hook source: user and
system `hooks.json`, system `requirements.toml`, inline system/base and selectable profile-v2
hooks, and the legacy managed config file. On Windows it resolves the system layer through the
ProgramData known folder, as Codex does. Before counting a floor, it validates the complete hook
subtree and the hook-specific metadata it statically interprets: every supported event, the JSON
object wrapper and parser constraints, config hook state, and managed requirements hook paths — a
managed hook directory must be absolute and, unless it is a UNC path no audit should block on,
must exist on the platform that resolves it. It
scans every selectable profile-v2 file conservatively; unreadable or malformed hook sources and
profile enumeration fail closed. Other ConfigToml and requirements fields are not fully
schema-validated. Ignored JSON values are traversed iteratively, but the stdlib JSON decoder still
imposes an explicit fail-closed bound at pathological nesting depths before schema inspection.
Managed-cloud, MDM, per-invocation, and plugin hooks remain runtime-only evidence and must be
reconciled in `/hooks`.

`doctor --repo` accepts the Git-root layer walk only when every inspectable top-level
`project_root_markers` declaration in the system, base-user, and stored profile-v2 configs is
absent or exactly `[".git"]`; any other, conflicting, malformed, or unreadable declaration fails
closed. CLI and managed-cloud overrides are not statically inspectable. Under
that qualified default topology, it walks every active `.codex` layer from the checkout root
through the requested directory and audits both `hooks.json` and inline `[hooks]` in `config.toml`,
because Codex loads both forms. Across those sources it
requires exactly one project-floor candidate, one conservatively recognized POSIX/Windows
execution shape, and one current normalized dispatcher marker. That marker is **audit-only**: it
is never passed to or verified by `dispatch.py` at runtime, so it proves the trusted hook
definition was written against those bytes and nothing more (see SPECS §5 for the mandatory
refresh/re-trust sequencing after a dispatcher change). A separate `Codex adapter contract` check
names every candidate handler and platform command that declares no marker, declares a stale one,
or never passes `--event pre --runtime codex`; a vendored dispatcher or wrapper flag delegation is
reported as inventory rather than a failure. Because Codex runs hook commands from the session
cwd, a repo-relative wrapper path is rejected when the session cwd is not the hook source root,
and recorded as a cwd-dependency note in the audits where it does resolve.
That floor must be the canonical root
`.codex/hooks.json` adapter; nested config-only layers are allowed. Static validation does not
execute the hook or grant trust. It also rejects inspectable activation blockers: managed-only
requirements, managed hook-feature requirements, persisted canonical/legacy hook feature
disables, and a disabled canonical handler state, plus the unsupported stored legacy `profile`
selector. A managed requirements pin of the hook feature *on* does not clear a persisted disable:
Codex's merge order for that contest is not statically provable, so `doctor` names both
declarations, calls the outcome UNPROVEN, and fails closed. Valid feature values inside the
inactive legacy profile map do not affect activation; malformed hook feature values still fail the
typed-load boundary. A CLI-selected profile-v2 name colliding with that legacy map remains a
runtime-only boundary. CLI, session, and managed-cloud activation can override the static result,
so a CWD-specific new-session `/hooks` review and live safe/deny canary remain mandatory.

For a linked Git worktree, Codex maps each active hook layer to the same relative `.codex` directory
in the root checkout that owns the Git common directory. `doctor --repo` reports those mapped
sources and rejects worktree-only or different local `hooks.json` and inline-hook declarations. An
identical tracked worktree copy is allowed but remains inactive. Static root discovery currently
fails closed for linked worktrees whose primary checkout uses `--separate-git-dir`, and when the
common Git directory has no checkout (for example, a bare repository). Configure, review, and trust
the root-checkout adapter through `/hooks`; do not edit trust hashes manually or use a bypass flag.

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

Release provenance (v1.5.4, 2026-07-24): combines PR #15's Windows recursive-delete
fallback and protected Git-config mutation hardening with PR #16's value-aware sequencer
terminal-flow parsing and self-cleaning neutral smoke fixtures. Both surfaces retain their
focused regressions in the self-counting matrix and harness unit suite.

Provenance: synthesized by Fable 5 from a 12-agent estate survey, three independent
architecture proposals, and an adversarial completeness critique. This repo obeys its own
laws: one home per policy, budgets with rotation, no speculative scaffolding.
