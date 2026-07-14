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
| `harness.py` | Dependency-free CLI: repo `seed`/`audit`, live `doctor`, and backed-up Codex global sync |
| `templates/hooks/` | Canonical cross-runtime `dispatch.py` + self-counting v1.4.4 bypass matrix. Codex global drift/install is explicit through `harness.py sync-global`; project adapter wiring remains repo-owned |
| `templates/codex/` | Codex lifecycle-hook wiring; install paths are rendered at sync time |
| `legacy/` | The four salvaged Apr-2026 `bootstrap-*.ps1` scripts — template source material only; superseded, never run |

## Use

```powershell
# Inspect first; installation is never implicit.
py -3 .\harness.py doctor
py -3 .\harness.py audit C:\path\to\repo
py -3 .\harness.py seed C:\path\to\repo --tier 2 --sensitive-data

# Diff, then install the versioned Codex global layer with backups.
py -3 .\harness.py sync-global --config-root C:\path\to\claude-config
py -3 .\harness.py sync-global --config-root C:\path\to\claude-config --apply
```

`seed` refuses to overwrite an existing runtime-neutral tier declaration. `sync-global` backs
up changed global guidance/hooks and managed skill folders before replacing them. After a hook
change, review and trust its hash with `/hooks` in a new Codex session.

Status (2026-07-14): the blueprint, shared v1.4.4 deny floor, Codex adapter, portable CLI, and
versioned global Codex layer are implemented. The bounded matrix hardens supported Bash,
PowerShell, and cmd forms across authority resolution, quoting, wrappers, nested interpreters,
pipelines, git push safety, and secret-file mutations. It remains a defense-in-depth tripwire,
not an exhaustive shell sandbox. Gardener scheduling remains intentionally deferred until the
bootstrap/audit loop has earned trust through real use.

Provenance: synthesized by Fable 5 from a 12-agent estate survey, three independent
architecture proposals, and an adversarial completeness critique. This repo obeys its own
laws: one home per policy, budgets with rotation, no speculative scaffolding.
