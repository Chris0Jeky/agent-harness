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
