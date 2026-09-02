# Agent Harness Blueprint

Last Updated: 2026-07-26 · Applies to: every repo, every machine, every model tier
Concrete schemas, skeletons, and literal file drafts live in [SPECS.md](./SPECS.md).

**Thesis.** A repo's harness is defined by its **blast radius** — what can irreversibly break
there. Everything else follows: how much standing context it may cost, which gates exist, what
authority agents hold, and what the repo is allowed to grow for itself. The harness assumes the
model may be weak, wrong, or cheaper next year: judgment gets encoded into *structure* (hooks,
budgets, region maps, restricted toolsets) that a weaker model inherits for free.

**The harness guards catastrophe, not capability.** Hard walls exist only for the irreversible —
secret exposure, destroyed or unowned work, rewritten shared history, public leaks, production
data. Everything reversible stays within agent autonomy at every tier: tiers scale
*verification* with blast radius, and they never subtract autonomy (ratified in issue #92).

Every mechanism here was either proven in the estate or is the missing half of something that
half-worked. Nothing is speculative.

---

## 0. The Twelve Laws (cross-cutting, all tiers)

1. **Enforcement ladder.** memory → CLAUDE.md → skill → hook → CI → structure (restricted
   toolset, branch protection, sandbox). Every rule lives at exactly ONE layer — the cheapest
   that actually enforces it. Prose is promoted to a hook only when violation is objectively
   machine-detectable AND has recurred. (Formalizes Options `workflow_enforcement.md`.)
2. **One home per policy.** Every policy has exactly one file; everything else links, never
   restates. (Taskdeck's review policy lived in 7 files; #1220 took 14 review rounds partly
   reconciling copies.)
3. **Second-occurrence rule + pruning symmetry.** Nothing is built speculatively — structure
   arrives with the second item (second correction → rule; third bulk-read → region map; second
   repo needing a skill → hoist it global). Every growth trigger has a decay twin: session logs
   expire in 14 days, memories uncited 90 days fold to one line, skills uninvoked a quarter get
   archived, superseded strategies collapse to one SUPERSEDED line. Growth without decay
   produced olb's 1,251-file memory swamp.
4. **Budgets with rotation.** Every standing artifact has a hard line cap (table in SPECS §3).
   Overflow ROTATES to `archive/` — never deleted, never accumulates in the routed path.
   A mandate that cannot be literally obeyed (Taskdeck's ~80k-token required-reading chain)
   teaches agents to ignore mandates — the most corrosive failure mode found in the estate.
5. **Tripwires are not walls.** Regex deny hooks, stamp checks, and token-presence checks are
   tripwires: cheap, worth keeping, never counted as safety. Walls are branch protection that
   *requires named checks*, toolset-restricted subagents, and hermetic runtimes. (The old
   prefix deny list missed `git push -f`; Taskdeck's branch protection "required nothing.")
6. **The weaker the model, the harder the harness.** Spend the top model writing structure and
   reviewing; run cheap models only inside mapped regions with skills, stop conditions, and
   PR-only output. A weak model + tight region + stop-hook verification beats a strong model +
   an 80k-token read mandate.
7. **Capture is automatic; promotion must be scheduled.** Any ledger/memory/inbox without a
   scheduled consumer degrades into noise (314/314 failure-ledger entries unclassified after
   8 weeks; nightly lane red 5/5 days unnoticed). The Gardener (§4) is that consumer.
8. **Authority is declared, not negotiated.** Push/merge autonomy is a written per-repo setting
   in `.agent-harness/tier.json` — the same developer currently runs opposite git postures in different repos,
   discoverable only by tripping hooks.
9. **Tracked-issue-or-it-doesn't-exist.** Plans living only in prose lose to tracked issues
   every time (Taskdeck's only archive plan sat in a gitignored file while agents worked the
   tracker). Any doc-resident plan gets mirrored into the tracker or it will not happen.
10. **Misleading authority is worse than nothing.** Dead repos get 3-line tombstones; stale
    authoritative docs (metricalgo's 245-line AGENTS.md for a path that no longer exists) get
    deleted, not maintained; superseded docs leave the routed path.
11. **Every loop terminates.** Review is one review round plus one fix round, then ship or park.
    Fix commits are earned only by confirmed CRITICAL/HIGH defects; every other finding becomes
    a tracked issue or a one-line decline on the thread — never a silent drop, never a
    fix-commit cascade. A red gate gets three genuinely different attempts, a disputed fact one
    re-measure; then ship what is sound and park the rest. Evidence invalidation is scoped: a
    head change re-proves what changed, never everything. (Issue #92 measured the unbounded
    form: 90% of this repo's PR commits were post-review fixes, and fix rounds introduced
    defects of their own.)
12. **Mission first.** Harness, floor, gate, and doc work happens only when it IS the mission;
    friction found mid-task becomes a one-line tracked issue, never a detour. No new gates whose
    subject is other gates or doc consistency — grandfathered: the ones already built AND the
    ones this blueprint itself prescribes (§3 stale-map stamps, the T3 docs-stamp/budget lane,
    §7's vendor parity-diffs, SPECS §7's stop-hook states); the Gardener may propose retiring
    any whose upkeep exceeds what it catches. Sessions are judged
    by finished tasks: budget each task, park at ~2× budget, and close with a scoreboard
    (finished / parked / rounds used) ahead of the evidence sections. (Issue #92 measured the
    inverse: 9:1 ceremony-to-execution and zero product-capability PRs.)

---

## 1. The Tier Ladder

**Tiers add verification, never permission.** Every tier ships autonomously on its own
authority; what rises with blast radius is how much independent verification a merge must carry
— none at T1/T2 beyond green proving checks, ONE bounded independent review round at T3, the
full declared two-review gate at T4. A tier is never a reason to wait, ask, or leave finished
work unmerged — within the repo's declared authority: `.agent-harness/tier.json` binds over
these defaults, and `merge: gated`/`human-only` means exactly that at any tier.

| Tier | Name | Defined by (blast radius) | Standing context | CI | Authority (default) | Estate examples |
|---|---|---|---|---|---|---|
| T0 | **Tombstone** | Nothing runs here | ≤200 tokens | none | none | jekyt, repos, Taskdeck-gemini, pr812-fixes, junk wrappers |
| T1 | **Sandbox** | Only irreversible loss matters (secrets, privacy, money) | ≤1k | none | full, incl. main; no review owed | hq-private (+`sensitive_data`), LeetCode, CV-builder, new prototypes |
| T2 | **Daily driver** | Lost work / lost context costs real hours | ≤3k | none (optional fast pre-commit) | push+merge free; self-review on green checks | extract-api (reference implementation), NavSentinel |
| T3 | **Workshop** | Regressions are expensive; sole stakeholder | ≤6k | required lane, single-OS, <10 min | push free; merge on green + one bounded independent review round | Taskdeck (after diet), wealthlens-hq |
| T4 | **Live wire** | Other people, money, or production data | ≤8k | full gate + branch protection | push/merge behind the full declared gate (two independent reviews + green CI) | olb/series_tools_python, staticprofit (if revived) |

**Overlay flags** (orthogonal to tier, set in `tier.json`):
- `sensitive_data` — adds privacy denies (block pushes to public remotes, `gh repo create --public`)
  at ANY tier. hq-private is low code-trust but radioactive-data; tier ≠ sensitivity. One ratified
  exemption (issue #48): a push ATTRIBUTABLE to a non-sensitive repository is exempt from the
  *contextual* overlay a sensitive session root spreads over cross-repo work. Attributable means
  ALL of: the command's git globals cannot redirect which repository git operates on (only
  `-C <path>` is tolerated — `--work-tree`/`--git-dir`/`-c core.worktree` make the toplevel name a
  different repository from the one whose objects are uploaded); the repo's own tier declaration
  sets `sensitive_data` EXPLICITLY false (an omitted key is silence, not consent); neither that
  checkout nor the primary checkout behind it — a linked worktree can sit outside — is inside a
  directory declaring `sensitive_data`; and it ships its own named local branches (or HEAD, or
  refspec-less with no configured `remote.*.push`) to a destination that RESOLVES to one of its own
  configured remotes, with no multi-ref, tag-publishing or deletion selector in any spelling git
  accepts. Each condition is enforced, not asserted: the PR #132 review found four of them
  bypassable and one of those was an exfiltration path the pre-#48 floor had closed.
  A second, separately ratified exception (owner decision 2026-08-03) covers a public-source
  repository whose ignored local runtime data remains sensitive. It is declared outside `flags`
  as `public_synthetic_publication: {remote, repository}` because it is a relaxation: every
  co-located tier declaration must grant the identical literal remote name and GitHub
  `OWNER/REPOSITORY`, silence or disagreement denies, and the command must explicitly push one
  named local branch or `HEAD` to that remote's single matching push URL. Configured
  `core.gitProxy`/`core.sshCommand` or declared-remote `receivepack`/`vcs`, command-line
  `--receive-pack`/`--exec`, refspec-less pushes, force-with-lease,
  force/tag/delete/multi-ref selectors, URL destinations, remote or slug mismatches, linked
  worktrees with a sensitive primary, and unresolved probes retain the deny.
  This declaration does not inspect Git objects or prove a diff synthetic; the repository's
  exact-diff and synthetic-artifact gates remain required before publication. All other
  `sensitive_data` denies, including public repo/gist creation, visibility changes, and arbitrary
  `gh api` mutation, remain active.
- `wave_mode` — multi-agent batch work in progress: worktree protocol mandatory, work-loss
  guards escalate to deny (another agent's work is in the blast radius), coordinator verifies
  clean main after every wave.
- `dormant_production` — frozen but revivable live system: strip to a ≤20-line REVIVAL.md
  (how to run, hazards, re-seed tier) + the floor. (identity/platform-identity, staticprofit.)

### T0 — Tombstone
3-line CLAUDE.md: `FROZEN <date>. Do not develop here. Live repo: <path>.` Delete any other
scaffold — stale config actively misleads. Tombstone junk 1-commit wrappers at the wrapper
level so `git -C` at the wrong depth self-identifies. One row in `~/.claude/ESTATE.md`.
Gardener skips these dirs entirely. **Exit:** human revives → `harness seed --tier N` removes
the tombstone in the same commit that installs the floor.

### T1 — Sandbox
The current *global* posture, demoted to an explicit per-repo choice. `bypassPermissions` in
uncommitted `settings.local.json`. Global deny floor (§2) rides along free. CLAUDE.md ≤40
lines: what this is, how to run it, any hard data rule. No CI, no STATUS, no skills beyond the
global process three, no review policy, no read-first list. Fan-out banned — inline is always
cheaper here. **Promote to T2** on evidence of durable use: 3rd+ return session, something
consuming its output, or the first "wish I had a test" moment.

### T2 — Daily driver (template: extract-api, the estate's cleanest instance)
- SessionStart hook prints a 4-line orientation (rules digest + next BACKLOG item + open
  HUMAN_TODO items) — replaces doc re-reading at ~0 tokens. When open HUMAN_TODO items + open
  PRs exceed a threshold it appends a one-line nudge to run the `guided-walkthrough` skill (§6);
  the skill is the home, the hook only points at it.
- `HUMAN_TODO.md` (standard name; existing wired names like Taskdeck's OUTSTANDING_TASKS.md
  are grandfathered — note the alias in ESTATE.md): human-only items with IDs, surfaced in
  every summary, cleared only by the human.
- `tasks/BACKLOG.md` session protocol (law 9 starts here).
- PostToolUseFailure → sanitized JSONL ledger, with a triage cadence (Gardener, §4).
- 3–5 process skills ≤60 lines (onramp, safe-slice, verification-closeout, failure-capture).
  HARD RULE: no read-first ladders; never re-mandate auto-injected files.
- Stack allowlist lives HERE in repo `settings.json` — not in the user-level file.
- Hooks `$CLAUDE_PROJECT_DIR`-relative and self-tested (`make test-hooks`). Absolute paths
  silently break worktree agents (olb's do today).
- Optional diff-scoped pre-commit: fast lint/typecheck only; every local gate ≤60s or it
  breeds `--no-verify` culture.
**Promote to T3** when: another repo/person/automation consumes output; a regression costs
>1 hour; the same failure class recurs twice; or the repo exceeds one context window (→ the
first region map IS the promotion act). **Demote to T1** after 60 days dormant.

### T3 — Workshop
Everything in T2, plus:
- **Required CI lane**, single OS, <10 min: lint + typecheck + unit + docs-stamp/budget script.
  No OS matrices, no container builds on docs-only changes, no scheduled lanes without the
  red-lane law (below).
- **Branch protection requiring the lane by name** (verify via `gh api`, don't assume).
- **Region system ON** (§3) — the promotion trigger and the cure are the same thing.
- **Bounded review pipeline** (the `review-and-ship` skill is the concrete home): ONE review
  round — publish ready-for-review, request the bot review, post findings on the PR. The round
  counts only once an independent review has actually arrived: the requested bot review, or an
  independent agent review when no bot lands within a bounded wait — never merge at T3+
  without an arrived independent review, and a clean review (zero findings) satisfies the
  round: the PR ships on it. Then one severity-bar triage: only confirmed CRITICAL/HIGH
  defects earn fix commits, and everything else becomes a tracked issue or a one-line decline
  on the thread. Severity is judged by the finding's content, never the reviewer's label — a
  bot's P0/P1 meets the bar exactly when it names a confirmed correctness, security, or
  data-loss defect. One fix round, verified against the fix diff — the re-requested bot review
  at T3+ IS that verification pass, not a second round — then ship or park (law 11); never
  pause mid-pipeline to ask whether to continue. PostToolUse nudge after `gh pr create` points
  at the skill (~20 tokens, exactly when relevant).
- **Stop-hook verification** (first tier for it): narrowly detectable states only — PR opened
  this session must have a findings comment; src edits must have a test run (warn at T3, block
  at T4). Stated-override path required, or it trains hook-disabling. Spec in SPECS §7.
- Two-file truth split with hard caps: "now" doc ≤150 lines, history rotates to archive.
- Diff-scoped pre-commit (staged .cs → build, .ts/.vue → typecheck) IF measured ≤60s, else the
  check stays in CI. The latency budget is the law; content adapts.
**Promote to T4** when deployed anywhere, when consumption is automated (failures propagate
with no human buffer), or when a failure would HARM other people, money, or production data —
a person merely consuming the output promotes T2→T3; T4 begins where failure hurts a third
party rather than inconveniencing a consumer. Autonomy stays constant; the verification a
merge must carry is what rises. **Demotion
trigger:** a required lane red >7 days while work continues means the gate is dead — fix it or
formally demote; permanently red gates teach gate-ignoring.

### T4 — Live wire
Everything in T3, plus:
- **Canonical merge gate**: 2 independent adversarial reviews — at least one from the
  toolset-restricted no-Bash/no-Write reviewer agent — + green CI + the requested bot review
  triaged once by the severity bar (bots caught real bugs self-review missed 3+ recorded
  times) + never `--delete-branch` a stacked base. T4 raises how many independent eyes the
  single review round gets, never how many rounds run — law 11's ceiling binds here too.
  Sweep-then-push for large PRs: one multi-agent sweep, one push — never round-per-push cycles.
- **Blocking diff-scoped gitleaks** in the required lane (pr-mode never reds on legacy).
- **Advisory-first gate flips** (ADR-0035 pattern): every new gate lands `enforce:false` with an
  inline comment naming the flip condition, tracking issue, and break-glass path.
- **Red-lane law enforced by cron**: any scheduled lane red 2 consecutive runs → fix-or-delete
  issue auto-filed. Perf gates on shared runners are trend artifacts, never pass/fail.
- Release discipline: consumers pull tagged releases; forward-only migrations validated in CI;
  rollback exercised at least once, on a schedule; deploys are human-confirmed HUMAN_TODO items.
- Coverage/typecheck ratchets (quality only moves up). Hermetic per-vendor runtimes and
  per-tool MCP write gates. Harness version pinning + verify-by-artifact during money-path
  waves (the CC 2.1.15x tool-channel corruption cost a 55-PR audit — at T4 the harness itself
  is in the threat model).
- Human-commit bypass: below T4, human direct commits are exempt by design (the Claude hook
  only sees agent commits). At T4 the wall is branch protection + PR-only merges, which binds
  humans too; optional `core.hooksPath` git-native fast checks if wanted.
**No tier above.** T4's standing review is for DEMOTION, quarterly: when users/money stop
depending on it, tear down deliberately within a month — strip release lanes and dual-review
ceremony, keep the floor, leave a tombstone or REVIVAL.md. (Taskdeck's ~1,000 lines of dead
release YAML and 6 weeks of red lanes post-pivot are the cautionary exhibit.)

---

## 2. The Floor (the only thing that never varies)

One logical, argv-aware PreToolUse deny floor (dispatcher spec in SPECS §5), with identical policy
at every tier and explicit runtime adapters, protecting only the IRREVERSIBLE. Claude wires the
shared dispatcher globally; each active Codex repo owns one project adapter carrying an
**audit-only** normalized dispatcher marker — a declaration the runtime never verifies, so a
dispatcher change obliges refreshing every consumer marker and re-trusting each adapter in a
fresh `/hooks` session (SPECS §5). Never stack a global and project Codex floor:

- force-push in all spellings (`--force`, `-f`, `+refspec`) to shared branches
- `rm -rf` outside repo/scratch paths; `| Remove-Item` PowerShell forms; `sudo`; `curl|sh`
- secret-file mutation; with `sensitive_data`: pushes to public remotes, `gh repo create --public`
  (public pushes carry the issue-#48 attribution exemption — §1 overlay flags — when the pushed repo
  explicitly declares non-sensitive, is not contained in a sensitive root by either its checkout or
  its primary one, is not reached through a repository-redirecting git global, and ships its own
  named branches to a destination resolving to its own configured remote)

**Work-loss guards are tier-dependent, not floor**: `reset --hard`, `clean -fd`,
`checkout -- .`, `worktree remove --force` are *allowed* at T1–T2 (solo relaxed-git posture —
wealthlens proved blocking
them causes merge-gymnastics workarounds), warn at T3, deny at T4 and under `wave_mode`
(another agent's work is then in the blast radius). A T3 repo whose relaxed posture is
*declared* (`tier.json` flag `relaxed_work_loss_guards`, per SPECS §2) keeps them allow below
T4/wave_mode — the flag is ignored where guards are walls.

Plain `worktree remove` allows at EVERY tier, `wave_mode` included (owner ruling 2026-07-27;
issues #41/#117/#123). Git refuses it on a tree with tracked modifications or untracked
files and a checked-out branch survives it — but its clean check ignores gitignored content,
which removal then deletes, so **a `.env` living only in that worktree is gone**; and a
**detached** worktree's commits are held only by its own HEAD and die with the removal (law
7's `git switch -c` mandate exists for exactly this). Allowed because git checks the part
that matters, never because the plain form is harmless. What DOES stay on the work-loss
ladder is every spelling that can carry `--force` or disable git's check without showing it
in argv: a runtime-computed action word, a dynamic option/separator-free operand token, and
`-c status.showUntrackedFiles=no`-class config — an opaque spelling never scores better
than the literal form it might be.

**Never scan commit-message or PR-body text at any tier.** Proven repeatedly to block the
agent's own descriptions and train `--body-file` workarounds. Secrets-in-content is CI
gitleaks' job (diff-scoped); command safety is the argv parser's job.

The floor is a defense-in-depth tripwire by law 5, not an exhaustive shell sandbox. Its bounded
parser and bypass matrix cover the explicitly tested command forms; the walls at T3+ remain
branch protection and restricted toolsets. A change to the floor is T4-class work (top model +
review) no matter which repo it runs in.

**FEATURE-FROZEN (2026-07-26 — ratified in issue #92; decision record #96).** The floor is a
tripwire at its useful maximum: 272 → ~9.5k lines as measured in issue #92 (11.3k by 1.6.12)
bought a 12–14% false-positive rate on real agent commands with no recorded save of a real
irreversible action, and seven versions of hardening shipped without ever executing anywhere.
Only three classes of change may touch `dispatch.py`: **(a)** false-positive fixes that
blocked real work, **(b)** the ratified #21 slice sequence, and **(c)** repairs to a SPECS §6
charter regression as literally written (a listed must-block form newly allowed, or a listed
must-allow form newly blocked) — the catastrophe matrix is always repaired. A newly
discovered bypass FAMILY — a wrapper, interpreter, encoding, or shell shape the parser does
not model — is recorded as one line in [FLOOR_LIMITATIONS.md](./FLOOR_LIMITATIONS.md) and its
issue closed, never fixed. No new floor version is DEPLOYED until the currently deployed one
is re-trusted and canaried (HUMAN_TODO H-2) — a permitted fix still merges to `main` and
bumps `FLOOR_VERSION`; what waits on H-2 is `sync-global --apply` and the consumer marker
refresh. Shrinking the FP rate toward the ~0.1% it once measured is the only hardening
direction left open.

The owner-authorized 2026-08-03 Developer Lens exact-route publication exception is one explicit,
bounded exception to that freeze; it does not reopen general parser or bypass-family work. The
feature freeze resumes immediately after that contract lands.

**Posture (owner decision 2026-09-02).** Re-measured on the owner's box before the change, the
deployed floor's real blocks were still the #21 profile: the opacity class and force-push
spellings, two months on. The owner ruled that below T4/`wave_mode` the floor is a guide, not a
wall: pure opacity proceeds, and every other deny or ask becomes one deliberate double-check
(`FLOOR_ACK`, SPECS §5.4). This lands the ratified #26/#62 slices in one seam and, by the owner's
explicit direction, goes one step past #26's "never a charter deny" invariant: the irreversible
core below T4 is protected by a forced re-read of the exact command, not by refusal. T4,
`wave_mode` and (by default) `sensitive_data` keep the walls; any repo can declare
`floor_posture: wall`. The freeze is otherwise unchanged.

---

## 3. Regions — the context-economy primitive (T3+; embryo at T2)

The mechanism that makes "work in a self-contained region without digging into others" real:

1. **`AGENT_MAP.md`** at repo root, ≤100 lines: seam table (domain → entry points → invariants
   → verification command) + an explicit **Do-Not-Read-By-Default** negative index (archives,
   generated artifacts, node_modules, dead dirs) + the 6-line Minimum Handoff Shape.
2. **Directory-scoped `CLAUDE.md`** (≤30 lines) in each region root — harness-native: it
   auto-loads only when files there are touched. Region-local rules live here, nowhere else.
3. **Optional detail maps** `docs/regions/<domain>.md` (≤100 lines), loaded on demand.
4. **The write path**: updating the map is part of Definition of Done when a seam moves —
   enforced by the DoD checklist, not memory. This is what makes the repo SELF-EXPANDING
   without a crawler or scheduled re-scan burning credits.
5. **Task prompts name a region.** Worker agents log a one-line reason before reading outside
   it. Subagents receive a region map, never "the repo".

**Fan-out economics**: stay INLINE when a task touches ≤2 files in one mapped region. Fan out
when regions are disjoint, required context exceeds ~20k tokens, or an independent lens is
structurally required (review). T0/T1 never fan out. Heuristics, not laws — deep coupling makes
"disjoint" illusory (worktree waves leaked 5/6 despite protocols); when a fan-out produces
merge conflicts, that's evidence the regions aren't real yet. **Right-size the fleet**: default
≤3–5 subagents, a broad sweep/audit ≤8–12, never a reflexive fleet; put wide mechanical fan-out
on the cheap tier at medium/high effort (never low — a cheap model at low effort compounds two
handicaps) and reserve the top tier at high/xhigh for the narrow judgment core. Subagents that
still need judgment go on the default tier at low effort, not the cheap one. This is what stops
a top-model session from spawning a subagent fleet that drains the
budget before finishing — the `model-effort-routing` skill (§6) is the home for the sizing rules.

**Stale-map risk**: a wrong map misroutes — worse than no map. Maps carry `Last-Verified:`
stamps; the budget script flags >90 days; human edits outside the harness are the known hole
(the weekly sitting is the backstop).

---

## 4. Self-expansion — the Gardener loop (T2+)

`capture (hooks, zero inline tokens) → triage (scheduled agent) → promote/prune
(ONE ≤100-line PR) → ratify (human merges)`.

- **Cadence**: weekly per active repo, default-tier model at effort low (§5 — its triage and
  promotion calls are judgment; low effort is what keeps it cheap enough to schedule), runs
  against its own worktree
  (never the live checkout — one-writer rule per checkout). SessionStart nudges if the ledger
  exceeds 25 entries or 14 days untriaged.
- **What it does**: classify ledger entries (4-way: blocker / non-blocking-risk / pre-existing
  noise / invalid signal); route recurring lessons via the destination table (rule → CLAUDE.md,
  workflow → skill, domain → region map, decision → ADR — Taskdeck's GUIDE_UPDATE_PROTOCOL,
  extracted nearly verbatim); run the budget script; flag stale stamps; fold expired memories;
  flag tier/reality mismatches (deploy scripts present but tier < T4).
- **Skill-forge** (the "automate skill creation" requirement): clustered ledger entries or a
  second-occurrence memory line → draft SKILL.md from the anatomy template (frontmatter
  trigger, "Do not use when" anti-trigger, ≤60 lines, verbatim guard phrases) → validation
  script → branch + PR. The human ratifies by merging; agents never self-install skills.
- **Self-limiting (load-bearing)**: two consecutive unmerged Gardener PRs auto-pause the
  Gardener for that repo and flag tier mismatch. The pipeline must not become ceremony that
  runs unread — that is the 314/314 failure recurring one level up.
- **Human rhythm**: ONE weekly ~15-minute estate sitting — merge/reject Gardener PRs, glance
  at red lanes, clear HUMAN_TODO items. A scheduled agent aggregates every repo's HUMAN_TODO
  into hq-private (the existing command centre). Bounded weekly attention is the actual fix
  for every noise-decay failure observed.

---

## 5. Model & effort routing

Route by JUDGMENT vs MECHANICAL, never by size. Effort level is the cheaper dial — use it
before switching models. Full table in SPECS §8; the shape:

Model tiers below (`top` / `default` / `cheap`) are ROUTING tiers — unrelated to the T0–T4
blast-radius ladder in §1.

| Work | Model tier | Effort |
|---|---|---|
| Harness growth: deny floor/dispatcher, region maps, skills, hooks, ADRs, global laws; promotion/demotion audits; anything irreversible | top | xhigh |
| Adversarial review, merge decisions | top | high (xhigh when irreversible or wide blast radius) |
| Code implementation, debugging, feature slices inside mapped regions, routine PRs | default | high |
| Gardener triage, tombstone classification, routing/promotion calls, judgment-bearing subagent work, lookups | default | low |
| Doc rotation, formatting sweeps, mechanical transforms that are hard to get wrong — including wide mechanical fan-out (§3) | cheap | medium–high, never low |

**Delegation is not a task class.** Route a subagent by what it is DOING, never by the fact that
it is a subagent: a mechanical sweep handed to eight workers is still mechanical (cheap tier,
medium/high effort, §3), and a single worker asked for an independent judgment is still judgment.

Triage and classification sit on the **default** tier, not the cheap one: deciding what matters
is judgment wearing mechanical clothes. That misclassification is what kept the Gardener
definition (`~/.claude/agents/gardener.md` — the one canonical path this doc set uses for it)
pinned to a cheap model through three separate prose bans.

- **Default-up rule**: when unsure whether a task needs judgment, use the stronger model.
- **Hard rails**: a weak model never merges, never edits canonical docs or the deny floor,
  never approves its own tier's gates. Pinned via `model:` in an agent definition —
  `~/.claude/agents/*.md` globally, `.claude/agents/*.md` per repo (walls, with
  `tests/check-agent-models.ps1` in the config repo asserting no definition pins a banned model;
  that script is the authority on the banned set) + the routing table in global CLAUDE.md
  (convention — hooks cannot reliably see the running model, so this part is honestly a
  tripwire). A `model:` pin binds the SUBAGENT it defines, never the session that delegates to
  it: a top-level or headless run must bind its own model (see SPECS §10 for the scheduled case).
  An agent `model:` pin is the ONE permitted derived copy of a model name — a machine-read field
  cannot hold an indirection — and it is governed, not trusted: SPECS §10 carries the derivation
  contract (re-pin every affected definition in the same commit that changes the skill; declare
  the tier beside the pin; issue #76 tracks making the check enforce agreement).
- **Acceptance test for the whole blueprint**: a weaker model completes one mapped-region task
  per active repo without reading outside the region. That passing is the success criterion.
- **Do NOT restate the ladder here.** Which named model fills `top` / `default` / `cheap`, at
  which effort, plus the fan-out fleet caps (§3), live in the `model-effort-routing` global skill
  (§6) and nowhere else. This blueprint owns only the DURABLE part — the task-class→tier mapping
  above, effort-first, judgment-vs-mechanical, default-up — so the calibration can change without
  a blueprint edit. A model name written in two places is how a stale routing row outlives three
  separate prose bans; when in doubt, delete the local copy and point at the skill.
  The one model-level statement that is law rather than calibration, and therefore does belong
  here: **never Haiku, any version** (standing owner directive — quality too low). Family-wide
  on purpose: a ban pinned to one version number reads as permission for the next one. This
  prose is where the ban is DECLARED; the enforced banned set lives in the config repo's
  `tests/check-agent-models.ps1`, which is what actually rejects a definition. If the two ever
  disagree, the script is the one that binds and the mismatch is the bug — so widening the ban
  means editing both in the same change.
- **Spend the top tier on STRUCTURE, not chores** — global CLAUDE.md, deny floor + dispatcher,
  region maps for Taskdeck/olb, agent definitions, this repo — then adversarially review them
  with it. Judgment encoded in structure is judgment a cheaper model inherits for free. Mechanical
  migration (rotation, compaction, applying tombstones) goes to cheaper tiers inside that
  structure. This is a standing rule about where top-tier attention pays off, not a race against
  an access window: the top tier is reserved by value, not rationed by availability.

---

## 6. Global & machine layers

**`~/.claude/` becomes a versioned repo** (config, CLAUDE.md, hooks/, agents/, skills/,
selected scripts — NOT caches/history) with a private remote, plus scheduled backup of
`projects/*/memory/`. Today the entire meta-system and 139 memory files are one disk failure
from gone.

- **Global CLAUDE.md** (ratified 2026-07-26, issue #92; the claude-config repo is the
  canonical home and SPECS §1 the in-repo reference mirror): the universal laws once re-earned
  per repo as duplicate memory files — never merge red CI, bounded reviews (one round + one
  fix round, CRITICAL/HIGH-confirmed bar), verify-before-done, close-keyword hygiene, no
  `--delete-branch` on stacked bases, HUMAN_TODO surfacing, question protocol, worktree guard,
  tier check, loop convergence, mission-first. The per-repo memory duplicates were deleted as
  the law set shipped (the last two folded 2026-07-26). `doctor --config-root <claude-config>`
  separately exact-byte checks the supplied source `CLAUDE.md` and `codex/AGENTS.md` against
  their deployed Claude and Codex runtime files, but only after proving the supplied checkout is
  the clean, published `main` of the harness origin's `claude-config` sibling. A missing,
  unreadable, or noncanonical source is `UNPROVEN`; a readable mismatch fails. This document
  itself asserts nothing about deployment.
- **Global settings diet**: strip the 23 dotnet/npm stack entries into repo-tier settings;
  global `defaultMode` returns to prompt/acceptEdits; remove global
  `skipDangerousModePermissionPrompt` — max trust becomes a per-repo T1 declaration.
- **`~/.claude/ESTATE.md`** registry: repo → root (source/, Desktop/, …) → tier → status →
  live path → wrapper warnings → HUMAN_TODO alias. Covers ALL roots; doubles as the
  promotion-audit worksheet. New-repo intake: `harness seed --tier 1` at creation; human
  assigns tier.
- **Codex mirror and floor topology**: global Codex guidance mirrors the universal laws, but the
  Codex floor hook is project-local. Each active repo pins the shared `~/.claude/hooks/dispatch.py`
  from one `.codex/hooks.json`; global Codex floor wiring is removed to prevent double dispatch.
- **Machine layer, `MACHINE.md` + bootstrap** (distinct from repo tiers and global laws):
  front-load `C:\Program Files\Git\cmd` in PATH permanently (Cygwin git), commit vitest
  `maxWorkers` config where it OOMs, scheduled `gh auth` refresh, `DISABLE_AUTOUPDATER`
  rationale + harness version pinning policy. Each of these already cost multiple failed
  sessions and lives only in memory files today.
- **Global agents** (`~/.claude/agents/`): `reviewer.md` (NO Bash/Write — structural; a
  "read-only" instruction to a Bash-capable agent demonstrably does not hold),
  `gardener.md` — the canonical path for every reference to it is `~/.claude/agents/gardener.md`
  (default-tier model at low effort — cheap enough to run on a schedule, but its
  triage and promotion calls are judgment, not mechanics; write-scoped to docs/ + .claude/),
  `worktree-worker.md`.
- **Global process skills** stay ≤40 lines, stack-agnostic (safe-shell, small-safe-slice,
  verification-closeout — already good); plus three ≤80-line workflow-mode skills: `guided-walkthrough`
  (turns a cumulative backlog — HUMAN_TODO + open PRs + ledger blockers — into a numbered q-N
  walkthrough with per-item context, suggested action, owner tag, and a step-by-step for human-only
  items; the explicitly-requested exception to the global CLAUDE.md question-batching law),
  `model-effort-routing` (the
  effort→model→agent-count ladder plus the §3 fan-out caps that stop a reflexive subagent fleet),
  and `review-and-ship` (the bounded review pipeline — law 11 in executable form; ships from
  claude-config for both runtimes).
  That skill is the SINGLE home for named models and their effort bindings — §5 and SPECS §8 carry
  only the task-class→tier shape and point here; neither may restate the ladder. Global
  CLAUDE.md (law 5 + the Working-style section) and the T2 SessionStart nudge only point at these.
  Repo-tier skills come from the template layer here; domain skills grow per-repo by the
  second-occurrence rule.
- **Plugins**: enable only what maps to a workflow verb actually used; where a plugin overlaps
  a local skill (pr-review-toolkit vs adversarial-review), pick ONE per verb and record the
  choice in ESTATE.md. Delete disabled marketplace clones (~40MB of Glob noise).
- **MCP policy**: tier-neutral default = single gateway (MCP_DOCKER) + deferred ToolSearch. A
  repo earns a dedicated MCP server by the second-occurrence rule (a workflow needed it 3+
  times). Per-tool write gates (approve only mutating tools) from T3. One config format per
  vendor, dead entries removed at migration.
- **Token instrumentation**: record a per-repo baseline (typical session cost) in tier.json at
  migration; the Gardener PR reports its own token spend; scheduled agents carry a hard spend
  cap (default-tier model at effort low + one ≤100-line PR) and the auto-pause rule is the kill
  switch.
  The blueprint's promise is token economy — measure it or it's a vibe.

---

## 7. Multi-vendor policy

**Single-runtime by default.** No `.codex/` mirror unless a second vendor genuinely runs
sessions in that repo (decision recorded in ESTATE.md per repo).

- **Keep external bot reviewers everywhere at T3+** (Codex on PRs — Codex only, never Copilot):
  a free independent review tier that caught real bugs self-review missed. Publish
  ready-for-review (a draft invites no bots), request the review, and triage what arrives once
  by the severity bar — the bots supply T3's independent round; they never license an unbounded
  comment loop (law 11).
- **If a second runtime is real** (olb today): thin vendor shim only — routing README +
  runtime config + one dated `00_ACTIVE.md` pointer (edited on pivots; it propagated the
  archive pivot in one 54-line edit). Shared skill BODIES with 4-line vendor adapters, plus a
  CI parity-diff that fails on drift. Never forked SKILL.md mirrors — 10 of 13 drifted at
  Taskdeck; "keep mirrors aligned" as a doc instruction never works.
- **Resolve policy conflicts at the canon level**: one delegation policy stated once (in
  AGENTS.md), vendor files link to it. (Today Codex says "spawn subagents without asking"
  while CLAUDE.md says "only when asked" — same repo.)
- **Global vendor mirror**: the universal laws Claude gets from `~/.claude/CLAUDE.md` reach Codex
  through `~/.codex/AGENTS.md` (Codex's global personal-instructions file) — a faithful mirror of
  the twelve laws, tier ladder, working style (incremental commits, no-coauthor, right-sized fan-out)
  and the floor note. It declares `~/.claude/CLAUDE.md` canonical and must be kept in sync (a
  parity-diff belongs on the roadmap). This is WHY per-repo dual-runtime AGENTS.md files stay thin:
  the universal rules arrive globally for Codex exactly as they do for Claude, so nothing is
  restated per repo — only the vendor-runtime delta and repo-specific rules live in the repo file.

---

## 8. Estate migration map

Order chosen by risk × leverage. The top tier does steps marked ★ (judgment); cheaper tiers
execute the rest inside that structure. Taskdeck steps map onto EXISTING tracked issues — do not
create a parallel plan (law 9).

1. ★ **Global layer** (one evening, highest leverage): write `~/.claude/CLAUDE.md` +
   ESTATE.md + MACHINE.md; settings diet; argv-aware deny floor + dispatcher + test matrix;
   global agents; `git init` ~/.claude config; delete global detritus (pr600-review/,
   teams/session-*, blocklist test entries, daemon.lock, disabled marketplaces, the four
   stale Apr-9 bootstrap-*.ps1 after salvaging as template source).
2. **olb hotfixes FIRST despite the blueprint order** — highest-stakes / lowest-hygiene combo
   (production money, deployed daily): convert absolute-path hooks to `$CLAUDE_PROJECT_DIR`
   (they silently break worktree agents today); verify branch protection actually requires
   named checks via `gh api`. Two hours, real risk retired.
3. **Tombstones + REVIVAL.md files** (30 min): jekyt, repos, Taskdeck-gemini,
   TaskdeckDemoExpansion, pr812-fixes, AgentForge(+Archive), all junk wrappers;
   REVIVAL.md for platform-identity and metricalgo/staticprofit (replacing the stale-path
   245-line AGENTS.md). Then cold-archive or delete the dead duplicates (several GB of
   search noise).
4. ★ **Certify extract-api as the T2 reference**: extract its scaffold (CLAUDE.md split,
   4 skills, self-tested hooks, BACKLOG protocol) into `templates/tier2/` here; write its
   tier.json. First Gardener cycle on its 2,324-line ledger.
5. **hq-private → T1 + `sensitive_data`**: add tier line + privacy denies; rename to
   HUMAN_TODO.md convention or record alias. Verify it has a private remote (irreplaceable
   content). Nothing else — it already conforms.
6. **Seed/bootstrapper CLI shipped (2026-07-13)** (SPECS §9): `harness.py seed`, `audit`,
   `sync-global`, and `doctor`; the germ refuses overwrite. `tier-up` and estate-wide mutation
   remain deferred until repeated use earns them.
7. **Taskdeck → T3 diet, via its own tracked issues**: #1138 (STATUS → ≤150-line head +
   rotation), #1275/ARCHIVE-07 (CI right-sizing: drop dual-OS matrix, path-filter, DELETE the
   5/5-red nightly perf + 4/4-red mutation lanes under the red-lane law), #1276/ARCHIVE-08
   (dead surface: ~1,000 lines of release/staging/SBOM YAML, ORCHESTRATION_STATE.md out of the
   routed path, stale worktree dirs), #1269/ARCHIVE-01 (two-tier review gate = this
   blueprint's T3 review pipeline). New small issues to seed: one-home policy collapse
   (7 copies → 1), retire the .codex skill mirror (keep 00_ACTIVE.md + bot reviewers), strip
   skill read-first ladders to region-map references, move bypassPermissions to
   settings.local.json, remove/fence scripts/git/redistribute-commit-dates.ps1.
   ★ Region maps: backend (Domain/Application/Infrastructure/Api), frontend
   (views/stores/composables), automation/capture-review, CI+docs.
8. **wealthlens-hq → T3**: tier.json codifying its relaxed-git authority (it is the written
   spec for sub-T4 git freedom); Gardener on the 1,602-line ledger; red-lane law over its 11
   workflows; ★ region maps for the 33.9k-file tree.
9. ★ **olb → T4 formalization**: memory compaction (1,251-file .codex/memories + 111-file
   memories/ + 12.6KB index → extract-api's 4-file endpoint is the target); encode its earned
   rules (tagged-release pulls, forward-only migrations, UAI deploy sequencing, 2-review gate,
   ratchets) into tier.json + CLAUDE.md; skill suite 21 → ~8; single-runtime decision for
   Codex there (runtime with thin shim + parity CI, or bot-reviewer-only).
10. **Memory graduation pass** across all 7 memory dirs: universal laws → global CLAUDE.md
    (delete the duplicates same-commit), contradictions resolved (worktrees-broken vs -fixed),
    session logs pruned, Options' 12.6KB index → one-liners.
11. **Turn on the rhythm**: weekly Gardener on the 4 active repos only; weekly 15-minute
    estate sitting; HUMAN_TODO aggregation into hq-private.
12. ★ **Acceptance test for the migration**: hand a cheaper-tier model one mapped-region task
    per active repo; fix whatever it stumbles on. Passing means the judgment soaked into the
    structure — that is the whole point of §5's routing. There is no deadline to beat here: the
    top tier is reserved by value, not rationed by availability, so re-run this whenever the
    structure changes materially rather than once against a closing window.

---

## 9. How this blueprint fails (watch for these)

- **It becomes the next sprawl.** The harness obeys its own budgets: total standing harness
  ≤500 lines at T3; the blueprint is subject to the one-home rule and Gardener pruning like
  everything else. If the quarterly demotion review gets skipped, ceremony calcifies — same
  disease, better names.
- **The harness generates its own workload.** An unbounded frontier — shell-bypass families,
  gates that check gates — consumes sessions without finishing any mission: measured
  2026-07-26, zero of this repo's 24 PRs added product capability and 81% of its open issues
  were floor bypasses or floor false positives (issue #92). Law 12 quarantines meta-work, and
  the Gardener may propose retiring any gate whose upkeep exceeds what it catches.
- **Evidence becomes the product.** Closeouts that demand evidence categories but no task count
  teach agents to optimize evidence instead of outcomes (the overnight doctrine measured 9:1
  ceremony-to-execution by word count — issue #92). The law-12 scoreboard — finished / parked /
  rounds used, ahead of the evidence sections — is the countermeasure; when rigor rises while
  throughput falls, the harness itself is the defect.
- **The dispatcher is a single point of failure.** One parser bug—or a runtime's fail-open hook
  launch/output behavior—can drop the floor. Rule-evaluation exceptions fail closed after a Bash
  command is identified, but wiring still requires audit, smoke tests, and live canaries; changes
  are always T4-class work.
- **Caps degrade content instead of curating it.** The budget checker must emit ROTATE
  instructions, never "trim to pass"; rotation is the Gardener's job, not inline deletion
  under CI pressure.
- **Cheap maintenance agents confidently corrupt canon.** They only ever open PRs; the human
  merges. If merges become rubber stamps, the rail has already failed — auto-pause exists for
  exactly this.
- **Stale region maps misroute** — worse than no map. Stamps + max-age tripwires + the weekly
  sitting; human edits outside the harness remain the known hole.
- **Model routing misclassifies judgment as mechanical.** Default-up when unsure, and accept
  the eroded savings.
- **Gate fatigue at T3+.** Every local gate ≤60s; demotion must feel like honest right-sizing,
  not failure — otherwise the ladder gets climbed once and then ignored.
- **Promotion-by-incident** means most tier boundaries are paid for with one real failure.
  Acceptable for a solo dev ONLY because irreversible-loss classes are floor-level from day 0
  and never promotion-gated.
