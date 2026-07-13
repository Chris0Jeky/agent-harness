# Migration Prompt — re-work a repo's harness to the blueprint

Last Updated: 2026-07-06 · Paste the block below into a Fable/top-model session opened in the
target repo. Then paste the matching per-repo appendix from the bottom of this file.

---

## The prompt (paste verbatim, appendix after it)

```
Re-work this repo's agent harness to conform to the estate-wide tiered blueprint. You are the
top routed model: do the judgment work yourself (tier reasoning, region maps, law collapses,
anything irreversible); delegate only mechanical sweeps.

RESOURCES (read in this order, nothing else up front; discover paths, do not assume a user profile):
1. <agent-harness-root>/BLUEPRINT.md   — the tier ladder and ten laws
2. <agent-harness-root>/SPECS.md       — schemas, budgets, hook wiring, skeletons
3. <config-root>/ESTATE.md             — this repo's assigned tier + flags, when current for this machine
4. The per-repo appendix pasted below this prompt     — priorities and cautions for THIS repo
(<agent-harness-root>/BOOK.md holds the reasoning behind the laws — consult it
when a law seems wrong for this repo, before overriding it.)

GROUND RULES:
- This repo's own contributor protocol (CLAUDE.md/AGENTS.md, PR/review/merge rules) governs HOW
  you land changes. The blueprint governs WHAT the harness should become. Conflict → follow the
  repo's process, flag the conflict in your report.
- Small reviewable slices. Config/docs changes in one PR per concern; never mix with code fixes.
- Production repos (T4 targets): propose-first — post the plan as an issue/PR description and
  get sign-off before touching hooks or CI. Never run destructive git ops while migrating.
- Second-occurrence law: do NOT build speculative scaffolding (no empty region dirs, no skills
  for workflows that haven't recurred, no memory hierarchies for future growth).
- Out-of-scope findings become tracked issues, never silent drops. Tracked-issue-or-it-doesn't-exist.

DO, IN ORDER:
1. SURVEY (read-only): current .claude/settings(.local).json, hooks, skills (count + line
   counts + read-first ladders), CLAUDE.md/AGENTS.md sizes, canonical docs sizes, CI lanes +
   their last 5 conclusions (gh run list), failure-ledger size, memory dir size, .codex/ plane
   if any. Produce a one-screen gap table: current vs the tier profile in BLUEPRINT §1.
2. FLOOR: copy agent-harness/templates/hooks/{dispatch.py,smoke_test.py} into .claude/hooks/,
   wire per SPECS §5 ($CLAUDE_PROJECT_DIR-relative, one dispatcher per event), write
   `.agent-harness/tier.json` (tier/flags/authority from the appendix; note any intentional
   stricter-local-floor layering in a "notes" field). Run smoke_test.py — must be green.
   Retire superseded old hooks in the same PR (don't double-spawn processes per Bash call).
3. SETTINGS HYGIENE: committed settings.json gets defaultMode acceptEdits + the repo's stack
   allowlist; bypassPermissions (if wanted) moves to gitignored settings.local.json. Verify
   worktree/clone behavior: every protocol-mandated first command must be allowlisted.
4. DIET (apply BLUEPRINT laws 2/3/4): one home per policy (collapse restatements to links);
   strip skill read-first ladders (skills may point only at the seam map + the "now"-doc head,
   never at >200-line docs, never at auto-injected files); budgets pass per SPECS §3 with
   ROTATE-to-archive, never trim-to-pass; superseded docs leave the routed path; delete or
   CI-diff any hand-mirrored vendor artifact.
5. MEMORY GRADUATION: in ~/.claude/projects/<this-repo>/memory/, delete feedback files now
   covered by the global laws (~/.claude/CLAUDE.md) — list each deletion in your report;
   resolve contradictory memories; prune session logs >14 days; superseded strategies collapse
   to one SUPERSEDED line; index entries become one-liners.
6. CI RIGHT-SIZING (per tier profile): single-OS required lane for T3; red-lane law — any
   scheduled lane red 2+ consecutive runs gets a fix-or-delete issue filed NOW; delete lanes
   serving cancelled ambitions (per appendix). Land CI changes as their own PR.
7. REGIONS (T3+ only, and only if the repo exceeds one context window): AGENT_MAP.md seam map
   (≤100 lines) + Do-Not-Read negative index + directory-scoped CLAUDE.md per major region
   (SPECS §4 skeletons). Write the maps yourself — this is judgment work.
8. VERIFY + REPORT: smoke tests green; repo test suite if anything it covers changed; update
   the repo's row in ~/.claude/ESTATE.md (tier confirmed, aliases, decisions taken); close
   with the handoff shape: Changed / Verified / NOT verified / Failures+workarounds / Docs
   sync / Next safe slice — plus the gap table now marked done/deferred/issue-N.

The acceptance test for your work: after this migration, a WEAKER model given one
mapped-region task in this repo should complete it without reading outside the region and
without tripping a single false-positive gate.
```

---

## Per-repo appendices

### olb — Options/series_tools_python/options_limits_backtest (target: T4 live wire) — DO FIRST
PRODUCTION. Real money. Deployed daily. Propose-first for everything beyond step A.
- A. HOTFIX BEFORE ALL ELSE (was flagged 2026-07-06, may already be done — verify): hooks in
  .claude/settings.json use ABSOLUTE paths → convert to $CLAUDE_PROJECT_DIR (absolute paths
  silently no-op in worktree agents); then verify branch protection actually REQUIRES named
  checks: `gh api repos/{owner}/{repo}/branches/main/protection` — the estate has had
  configured-but-empty protection before.
- tier.json: tier 4, authority push=gated merge=gated. Keep its earned rules and write them in:
  2-review merge gate, PR aging, tagged-release pulls, forward-only migrations, UAI deploy
  sequencing, coverage/tsc ratchets.
- Memory compaction is the big win: .codex/memories ≈ 1,251 files + memories/ ≈ 111 files +
  12.6KB MEMORY index. Target shape: extract-api's 4-file consolidated endpoint. Session logs
  and point-in-time SHAs go first. Do this as its own reviewed PR-equivalent.
- Skills 21 → ~8 by merging overlaps. Codex runtime decision: if Codex still runs sessions
  here, thin shim + CI parity-diff per BLUEPRINT §7; if not, retire to bot-reviewer-only.
- Pin harness version during money-path waves (MACHINE.md rationale: the 2.1.15x incident).

### wealthlens-hq (target: T3 workshop)
- tier.json codifying its ALREADY-WRITTEN relaxed-git posture (feedback_relaxed_git memory) —
  authority push=free merge=gated; work-loss guards stay relaxed below wave_mode.
- Gardener-style triage of the 1,602-line failure ledger (one PR, ≤100 lines).
- Red-lane law over its 11 workflows: `gh run list` each scheduled lane; red 2+ → fix-or-delete
  issue filed immediately.
- Keep: worktree.symlinkDirectories (it's the estate's reference for that), wl-* skill naming.
- Region maps: the tree is 33.9k files — write the seam map for the 3-4 domains you actually
  observe in git activity; do not map speculative regions.

### extract-api (target: T2 daily driver — the REFERENCE implementation)
- This repo is being CERTIFIED, not overhauled. Its 102-line CLAUDE.md, orientation/rulebook
  split, 4 small skills, self-tested $CLAUDE_PROJECT_DIR hooks, and BACKLOG protocol are the
  canon. Where the new template (agent-harness/templates/hooks/) and its hooks differ, prefer
  the template's argv-aware floor but PRESERVE its session_start.py orientation ping — then
  push improvements you find here back into agent-harness/templates/tier2/ so the template
  stays truthful.
- tier.json: tier 2, authority per its written working-style (push gated like merge).
- First gardener cycle on the 2,324-line ledger.
- Its consolidated working-style-eng-practices.md is cross-repo canon — check nothing in it
  contradicts ~/.claude/CLAUDE.md; reconcile in favor of the global file and slim the local copy.

### hq-private (target: T1 sandbox + sensitive_data)
- MINIMAL touch. Keep the 34-line privacy-contract CLAUDE.md as-is (it is the T1 template).
- tier.json: tier 1, flags.sensitive_data=true (the floor then blocks public repo/gist
  creation). Verify the repo has a PRIVATE remote and recent pushes — its content is
  irreplaceable; if no remote, that's HUMAN_TODO item #1.
- Adopt/confirm the HUMAN_TODO aggregation role (other repos' action items flow here).
- Do NOT add: CI, review pipeline, skills beyond the existing two, failure ledger.

### NavSentinel (target: T2 daily driver)
- Standard T2 kit per BLUEPRINT §1: floor + tier.json, SessionStart ping, HUMAN_TODO
  (ACTION_ITEMS.md is the grandfathered alias — record it in ESTATE.md).
- Memory graduation with care: KEEP the harness-fabrication incident memories (they justify
  verify-by-artifact) — they are reference canon, not duplicates.
- Prune the 9 autonomous_loop_* session logs into one summary memory.

### Any NEW repo
- `harness seed --tier 1` equivalent until the CLI exists: copy templates/hooks/, write a
  ≤40-line CLAUDE.md and tier.json (tier 1), add the ESTATE.md row. Nothing else until the
  second-occurrence law demands it.
