# agent-harness

The reusable, tiered blueprint for how AI agents (Claude Code first, any vendor second) are
configured across every repo and machine Chris works on.

| File | What it is |
|---|---|
| `BLUEPRINT.md` | The law: tier ladder (T0 tombstone → T4 live wire), the ten laws, regions, the Gardener loop, model/effort routing, estate migration map |
| `SPECS.md` | The details: tier.json schema, budget table, hook wiring, deny-floor test matrix, skeletons, Gardener/skill-forge specs |
| `BOOK.md` | The why: field notes and the origin stories behind every law — read on a couch, not in a context window |
| `MIGRATION_PROMPT.md` | Paste-ready prompt (+ per-repo appendices) to re-work any repo's harness with a top-model session |
| `templates/hooks/` | Canonical `dispatch.py` (argv-aware deny floor) + `smoke_test.py` (169-case matrix). Deployed copies live in `~/.claude/hooks/` and per-repo `.claude/hooks/`; `harness audit` diffs them against these |
| `legacy/` | The four salvaged Apr-2026 `bootstrap-*.ps1` scripts — template source material only; superseded, never run |

Status (2026-07-13): global layer SHIPPED (`~/.claude/CLAUDE.md` laws, deny floor live and
smoke-tested, ESTATE.md, MACHINE.md, agents/, settings diet; `~/.claude` versioned as private
repo `claude-config`). Canonical floor v1.3.2 adds ancestor-aware tier resolution, strict
authority validation, canonical deletion containment, hostile temp-root rejection, and precise
`rm` flag parsing. Dead estate tombstoned. Taskdeck
declared T3 (PR #1292 + issue #1291).
Next: run MIGRATION_PROMPT.md sessions in olb (FIRST — production hotfix), wealthlens-hq,
extract-api, hq-private, NavSentinel; then the bootstrapper CLI (SPECS §9) and the weekly
Gardener rhythm.

Provenance: synthesized by Fable 5 from a 12-agent estate survey, three independent
architecture proposals, and an adversarial completeness critique. This repo obeys its own
laws: one home per policy, budgets with rotation, no speculative scaffolding.
