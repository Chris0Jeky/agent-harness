# The Harness Book

*Field notes from the day a machine audited its own working conditions.*

Written 2026-07-06 by Fable 5, for Chris — so that what was learned in one long day does not
dissolve back into the entropy it was pulled from. The BLUEPRINT is the law; this book is the
*why*. Laws without their stories get cargo-culted, then resented, then ignored. Stories keep
laws honest.

(A note on budgets: the blueprint caps every *standing* artifact, and this book is long. That
is not hypocrisy — the book is a reading artifact, not standing context. No agent is ever
required to load it. It is for you, on a couch, with coffee.)

---

## Preface: Why now

You said it yourself: you have Fable for a window, and Opus after. The instinct was to spend
the strong model on *doing more things*. The audit said the opposite: spend it on **structure**.
A strong model's judgment, written into hooks, maps, budgets, and tests, is inherited for free
by every weaker model that follows. A strong model's judgment spent on chores evaporates the
moment the session ends.

That is the thesis of everything below: **judgment is a liquid; structure is the only
container that holds it.**

---

## Chapter 1 — The estate as a mirror

The survey read eight territories of your world: the global config, Taskdeck's workspace, its
protocol stack, its documentation system, its CI estate, the Codex plane, every sibling repo,
and seven repos' worth of accumulated memory. The single most striking finding was not any
failure. It was this:

**You had already invented almost everything, separately, at least once.**

- The enforcement ladder — memory is guidance, skills are procedures, hooks are stops — you
  wrote it yourself in Options' `workflow_enforcement.md` after memory alone failed.
- The human-action-items file was independently reinvented **four times** under four names
  (OUTSTANDING_TASKS, ACTION_ITEMS, ACTION-REQUIRED, USER_ACTION_ITEMS), with the same three
  rules each time: read first, surface always, only the human clears.
- The negative index ("Do Not Read By Default") existed in two repos. The seam map existed in
  two. The failure ledger in four. The relaxed-git posture was *written down as policy* in
  wealthlens while Taskdeck enforced its exact opposite.

Four active repos converged on the same architecture without a blueprint. That convergence is
the strongest evidence the blueprint is *right* — it codifies what survival already selected
for. But convergence-without-canon has a cost: every repo paid for each lesson separately,
usually with an incident. The point of the global layer is that **no lesson should ever be
paid for twice.**

The mirror also showed one inversion worth remembering forever:

> The most elaborate harness in the estate protected Taskdeck — archive-bound, one user —
> while olb, which handles real money in production and deployed *that same day*, had
> absolute-path hooks that silently break its parallel agents and a 1,251-file memory swamp.

Protection had followed **attention**, not **risk**. Harnesses grow where you happen to be
working, not where failure costs the most. Tiering by blast radius is the correction: it makes
protection follow consequences.

---

## Chapter 2 — The mandate that cannot be obeyed

Taskdeck's required-reading chain — STATUS, masterplan, AGENTS, CLAUDE, principles, indexes,
protocols — sums to roughly **eighty thousand tokens**. No agent can literally obey it and
still have room to work. So no agent obeys it. Every agent *ritually skims*, and the mandate
teaches a deeper lesson than any of its content: *mandates here are decorative.*

This is the most corrosive failure mode found anywhere in the estate, and it deserves its own
law because it is invisible while it happens. Nothing crashes. No test goes red. The docs look
magnificent. But the "source of truth" doc had become a 1,369-line delivery narrative wearing
a truth label, and the highest-trust document became the least-read one.

The mechanism of rot was **appending**. Every merge appended a wave narrative. Every incident
appended a warning. Append is frictionless and feels like diligence; nothing ever leaves. The
cure is not discipline — discipline is what failed — the cure is **budgets with rotation**:
a hard line cap, checked mechanically, whose failure message says *rotate to archive*, never
*trim to pass*. History is preserved; it just stops living in the routed path.

**The wisdom:** any instruction that cannot be followed is worse than no instruction, because
it trains the reader to ignore instructions generally. Before writing a rule, ask: *can this
actually be complied with, every time, at the moment it applies?* If not, don't write it —
build it.

---

## Chapter 3 — Capture without a consumer

Your failure ledger was a genuinely clever design: a hook that records every failed command,
sanitized, at zero token cost. Eight weeks later it held 314 entries — **all 314 unclassified,
all 314 open.** The nightly CI lane had been red five days straight; the mutation lane red
four consecutive weeks. Nobody noticed. Not because nobody cared — because *noticing was
nobody's job.*

This pattern repeated everywhere automatic capture existed without a scheduled consumer:
ledgers grew write-only, session logs piled into memory indexes until the "cheap" index cost
12.6KB per session, red lanes burned compute to produce alerts that desensitized rather than
alerted. A permanently red gate is worse than no gate: it teaches gate-ignoring, and the
disease spreads to the gates that still work.

**The wisdom:** capture is automatic; promotion must be *scheduled*. Any inbox without a named
consumer on a calendar becomes noise, always, without exception observed. This is why the
Gardener exists — and why the Gardener itself carries a dead-man's switch (two unmerged PRs →
it stops), because a maintenance loop nobody reads is the same disease one level up.

The human version of this law: your entire estate needs about **fifteen minutes a week** of
your ratifying attention. Every observed decay traces to that attention not being scheduled.

---

## Chapter 4 — Everything duplicated diverges

Ten of thirteen skill files mirrored between `.claude/` and `.codex/` had drifted apart —
one vendor's orchestrator was 151 lines, the other's 72, running visibly different procedures
for the same task. The review policy was restated in seven files; reconciling doc copies once
took *fourteen review rounds*. The four bootstrap scripts that generated repo scaffolds had
drifted from the evolved repos they were supposed to regenerate — a generator that lies about
its output is negative value. One sentence in AGENTS.md appears twice verbatim, a fossil of
append-without-reading.

Nobody decided any of this. Duplication diverges the way water flows downhill — silently, in
the direction of whoever edited last. Doc instructions to "keep mirrors aligned" have a
recorded success rate, in your estate, of zero.

**The wisdom:** every policy gets exactly one home; everything else links. If something truly
must be mirrored (a second vendor's plane), the mirror is either generated or CI-diffed —
never hand-maintained. And don't pre-build for growth that hasn't happened: the `.codex/memories/`
directory, numbered `00_` for a series, held one file for fourteen months. Structure arrives
with the second item.

---

## Chapter 5 — Tripwires and walls

Your old global deny list blocked `git push --force`. It did not block `git push -f`. Four
characters of spelling defeated the safety system, and this was not an edge case — prefix
matching *cannot* express "the force flag in any spelling," so the rule was always a picture
of a wall rather than a wall. Meanwhile Taskdeck's branch protection — a real wall — was
configured but **required nothing**, while seven documents restated the merge policy in prose.
Exactly backwards: the paper was thick where the steel was missing.

Then there were the walls built in the wrong place. Hooks that scanned commit-message *text*
for scary strings blocked agents from writing "this commit prevents rm -rf accidents" in a
commit message — repeatedly, across three repos — training agents into `--body-file`
workarounds. A safety system that mostly fires on innocents doesn't just fail; it manufactures
the evasion skills that defeat it.

Today provided the counter-story, twice, within minutes:

1. Ninety seconds after the new argv-aware floor was wired into the global settings, it
   **blocked its own author** — I ran an `rm -rf` on an absolute path outside the project (a
   legitimate cleanup, as it happens), and the floor denied it before anything executed. I
   switched to a reversible `mv` into a dated backups folder, which was the better action
   anyway. The floor's first catch was the person who built it. That is what a working wall
   feels like: brief, specific, and it makes you do the better thing.
2. Minutes later, Taskdeck's *old* text-scanning hook blocked a **read-only grep** because the
   search pattern contained the word "credential." Old world and new world, side by side.

**The wisdom:** know which of your safeties are tripwires (cheap, leaky, worth keeping,
never to be *counted on*) and which are walls (branch protection requiring named checks,
toolset-restricted agents, argv parsers with test suites). The fatal mistake is citing a
tripwire as a wall. And every wall needs a test suite — the floor shipped with 49 cases,
including the false-positive regressions, because an untested safety system is a tripwire
with confidence.

One more wall story, because it is the purest: an agent explicitly instructed "do NOT stash"
ran `git stash apply` anyway. Instructions do not restrain agents; *toolsets* do. The reviewer
agent that reviewed today's PR cannot run commands or write files — not because it promises
not to, but because it structurally can't. Its review found one HIGH and two MEDIUMs in a
four-file diff its own author considered trivial. Structure beat self-confidence, same day,
same session.

---

## Chapter 6 — The enforcement ladder

You discovered this law yourself, in Options, after an agent kept pausing mid-pipeline no
matter what the memory files said: *memory is guidance, CLAUDE.md is prominence, skills are
atomic procedures, hooks are hard stops.* The blueprint completes the ladder with CI (gates)
and structure (cannot-happen), and adds the assignment rule:

> Every rule lives at exactly ONE layer — the cheapest layer that actually enforces it.

Two corollaries carry most of the value:

- **Promote on recurrence, not on annoyance.** A rule becomes a hook only when its violation
  is objectively machine-detectable AND it has actually recurred. Promote too eagerly and you
  build the false-positive walls of Chapter 5; too lazily and you re-pay incidents.
- **Prose pays rent.** A rule that stays prose costs tokens every single session forever. That
  is a real budget line. Most standing prose in the estate was rules that should have been
  hooks (paying rent while enforcing nothing) or history that should have been archive
  (paying rent while informing nothing).

The deepest version of this chapter: **the harness exists because model compliance is a
convenience, not a guarantee.** Design every load-bearing protection as if the model were
weaker than it is, and model upgrades become pure upside instead of load-bearing assumptions.

---

## Chapter 7 — Blast radius, not ambition

The tier ladder's whole content is one question: *what breaks irreversibly if an agent goes
wrong here?* Nothing (tombstone). Only secrets/privacy/money (sandbox). Hours of your work
(daily driver). Expensive regressions (workshop). Other people's money (live wire).

Everything else — CI lanes, review ceremony, doc governance, worktree protocols — is an
*answer* to that question, and every answer must name the failure class it catches. A gate
that cannot name its failure class is theater, and theater is not free: it costs compute,
attention, and — worst — credibility that the real gates need.

Three practical teeth that make tiers real rather than aspirational:

- **Authority is declared, not negotiated.** You ran opposite git postures in different repos,
  discoverable only by tripping hooks. Now `tier.json` says it: push free, merge gated. An
  agent reads its authority instead of guessing it.
- **Demotion is a feature, not an admission.** Nothing in the estate had ever been de-gated:
  dead release YAML survived its own pivot by six weeks; red lanes burned nightly compute for
  a project heading to archive. Right-sizing downward must feel like honesty, because it is.
  The T4 review is *for demotion*.
- **Overlays beat tier inflation.** hq-private is trivial code with radioactive data —
  `sensitive_data` flag, not a higher tier. Wave-mode multi-agent work makes work-loss guards
  strict *temporarily* — a flag, not a permanent posture. Blast radius has more than one axis;
  don't flatten them into one number.

And remember the inversion from Chapter 1: without explicit tiers, protection follows
attention. Tiers exist to make it follow risk.

---

## Chapter 8 — Regions, and the economics of attention

A context window is not a warehouse; it is *attention*. Every token loaded is a claim on the
model's focus, and irrelevant tokens don't just cost money — they dilute judgment. The
80k-token read chain didn't only waste credits; it made every session slightly dumber at its
actual task.

The region system is the answer, and its parts are all cheap:

- a **seam map** (≤100 lines): domain → entry points → invariants → verification command;
- a **negative index**: what NOT to read by default — the cheapest token savings in existence;
- **directory-scoped CLAUDE.md** files that the harness auto-loads only when files there are
  touched — rules that appear exactly when relevant and cost nothing otherwise;
- a **write path**: updating the map is part of Definition of Done, so the repo grows its own
  navigation as a side effect of work. No crawler, no scheduled re-scan, no credits burned on
  "keeping docs fresh" as a standalone activity.

The fan-out economics follow the same attention logic. Spawning a subagent costs real tokens
in spin-up and handoff; it pays only when regions are disjoint, when needed context exceeds
what one window holds well, or when independence *is the point* (review). The estate's scars
also warn about the illusion of disjointness: worktree waves "isolated" by protocol leaked
5 times out of 6 when the underlying code was actually coupled. If a fan-out produces merge
conflicts, that is data: the regions aren't real yet.

**The wisdom:** the scarcest resource in this whole system is focused attention — the model's
and yours. Every mechanism in the blueprint is ultimately an attention router.

---

## Chapter 9 — Judgment and mechanics

Route work by *kind*, not size: judgment work (architecture, review, anything irreversible,
anything that writes laws) to the strongest model at high effort; mechanical work (rotation,
triage, formatting, classification) to cheap models at low effort. Effort is the cheaper dial
— turn it before swapping models. When unsure, route up: the cost of over-routing is money;
the cost of under-routing is confident wrong work that passes every mechanical gate.

> **SUPERSEDED (2026-07-25) — do not route from this paragraph.** Lumping *triage* and
> *classification* in with rotation and formatting was the error: deciding what matters is
> judgment wearing mechanical clothes, and that one misfiling is what kept the Gardener pinned
> to a cheap model through three separate prose bans. The live rule is BLUEPRINT §5 / SPECS §8 —
> triage and classification go to the **default** tier at low effort; only genuinely simple,
> well-specified, hard-to-get-wrong work goes to the **cheap** tier, and there at medium/high
> effort. The paragraph above is kept as the reasoning of the time, not as an instruction.
> This book is rationale only; when it and the blueprint disagree, the blueprint wins.

The rails matter more than the routing: a weak model never merges, never edits canon, never
touches the deny floor, never approves its own tier's gates. Where rails can be structural
(model pins in agent definitions, PR-only output), make them structural; where they can't,
say honestly that they are conventions.

And the Fable window: its acceptance test is not "Fable did impressive things." It is —

> **a weaker model completes a mapped-region task, end to end, without reading outside the
> region.**

If that passes, the strong model's judgment successfully soaked into the structure, and the
window was spent well. Everything built today aims at that test.

---

## Chapter 10 — The human's job

After all the automation, your role compresses into four verbs:

1. **Direct** — say what matters; set tiers; decide pivots. (Agents execute tracked issues
   and ignore prose plans; if you want something to happen, it gets an issue. Your own archive
   plan once lost to the tracker *from inside a gitignored file*.)
2. **Ratify** — merge or reject the Gardener's PRs; check off HUMAN_TODO items. Fifteen
   minutes, weekly, scheduled. This tiny ritual is load-bearing: every decay in the estate
   traces to its absence.
3. **Arbitrate recurrence** — when the same lesson shows up twice, decide which ladder rung it
   gets promoted to. That single decision, made ~weekly, is how the system learns.
4. **Tell the truth about status** — tombstone the dead, demote the shrunken, REVIVAL-note the
   dormant. The estate's worst context poison was never missing documentation; it was
   *confident stale documentation* — a 245-line rulebook for a machine layout that no longer
   exists. Misleading authority is worse than nothing, in docs, in memory, and in people.

Everything else — remembering, checking, sweeping, classifying — belongs to the machines now.
That is not a demotion of you. It is the whole point: your attention returns to the work
itself, which is where it was always supposed to be.

---

## Epilogue — If you forget everything else

1. Judgment is liquid; structure is the container. Spend strong models on structure.
2. A rule that can't be followed teaches that rules don't matter.
3. Whatever captures without a scheduled consumer becomes noise. Fifteen ratifying minutes a
   week is the cheapest infrastructure you own.
4. Everything duplicated diverges. One home per policy; link, don't restate.
5. Know your tripwires from your walls, and never cite a tripwire as a wall. Test the walls.
6. Instructions don't restrain agents; toolsets do.
7. Every rule lives at the cheapest layer that actually enforces it. Prose pays rent.
8. Protect by blast radius, not by where you happen to be working.
9. Context is attention. The negative index — what NOT to read — is the cheapest intelligence
   amplifier in the system.
10. Misleading authority is worse than nothing. Tombstone the dead; demote with pride.

*— written inside the window, so it outlasts it.*


---

## Historical blueprint records (preserved 2026-10-03)

The following blocks are copied verbatim from BLUEPRINT at main commit
`4bef9337a4d03dba329c07d007c650f628e0785a` during the #389 structure cleanup.
They preserve dated rationale and the original migration proposal. Their statements about
installed state, issue state, future work and timing are historical, not fresh verification.
Their imperative wording is quoted source material, not authorization to execute it now.
For current rules use [BLUEPRINT](./BLUEPRINT.md), the canonical global laws identified in
[SPECS §1](./SPECS.md#1-global-laws--pointer-not-a-mirror), and the current tracker/operator gates.
Old BLUEPRINT-law numbers map to the P1-P12 design-principle namespace; global-law numbering
is unchanged. No migration step is accepted or completed by this move.

### Original review and mission rationale

```text
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
```

### Dated floor decisions and measurements

```text
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

**Core posture (owner decision 2026-09-27, issue #356).** Measured that day: no Claude session ran
the floor, only six Codex roots did, and none of the floored repositories protected `main`
server-side. The owner approved default-branch rulesets (`non_fast_forward`, `deletion`) on all
of them and chose to shrink the client floor to LOCAL destruction, trading some security for
throughput. Since 1.7.0 the default below T4/`wave_mode` for a non-sensitive repository is
`floor_posture: core`: destructive deletes outside the project, secret-file mutation, downloaded
program text run directly and privilege elevation stay double-checks (a `sensitive_data`
repository never runs `core`: its declared `core` renders as `guide`); force-push, ref deletion, git config execution, work-loss and launcher verdicts
proceed (SPECS §5.4). The analyzer and the §6 matrix are unchanged, and any repo can declare
`guide` or `wall` to get the old rendering back.
```

### Original estate migration proposal

```text
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
```
