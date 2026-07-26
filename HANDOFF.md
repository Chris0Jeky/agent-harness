# agent-harness — session handoff (2026-07-25 → 26)

Floor **1.6.5 → 1.6.12 on `main`**, seven PRs merged, one open. The theme: the floor was blocking
real work at a measured 12% while a five-character prefix disarmed it. This session closed the
bypass, cut false positives, and built the gate that makes both directions a CI property.

## Merged

| PR | What | Closes |
|---|---|---|
| #53 | `#46`: a leading redirection or `--%` defeated head resolution, so a five-character prefix disarmed **every** charter deny at every tier. Floor 1.6.11. | #46 |
| #70 | Three git-argv false positives (`update-index --refresh`, `hash-object` operands, a redirect after the refspec breaking `--force-with-lease`) + bash named descriptors `{log}>out`. Floor 1.6.12. | #44 #45 #55 |
| #64 | Corpus replay bound `check()` to each floor's own signature — an old baseline is measurable again (before: every command raised `TypeError` and read as a block, so "1.2.0 blocks 100%" was a tool artifact). | — |
| #57 | Hermetic floor fixtures + a guard that fails when any suite calls raw `check()`. | #54 |
| #66 | Four doctor false-greens/false-reds; Codex adapter contract gaps now reported; the adapter marker settled as explicitly audit-only. | #30 #35 #18 |
| #72 | `audit` verifies declarations against **reality** (a `sensitive_data` repo on a public remote now fails loudly); dropped the unread `model_routing` field. | #60 #47 |
| #61 | Model-routing docs retargeted to the current standard; the runnable `--model haiku` removed. | #50 |

## Open: PR #71 — the cross-product gate (#63)

The structural fix behind every bypass this repo has had. It crosses the ~1,071-case deny corpus
with 102 prefix/wrapper shapes and asserts **both** directions — charter denies survive every
shape, and a benign corpus stays allowed under every shape. ~50s, runs on every PR.

It has already paid for itself three times over:
- Found **#67** (perl/python/node/awk execute an argv-visible payload never unwrapped), **#68**
  (head-anchored rules stop firing under a launcher the floor otherwise covers, 187 verified
  pairs), **#69** (`cmd /c` does not recurse a nested POSIX interpreter).
- Confirmed **all eight** of #56's suspected-but-unverified container forms.
- Caught a false positive that smoke, review and the corpus replay all missed, and **#81** — 34
  over-blocks where #70's git-argv rules do not survive a child re-parse (reproduced on `main`,
  not introduced by the branch).

**State at `922cde3`:** merged with main (floor 1.6.12), three-OS CI **green**, and green locally
— 661 tests, **2121/2121 smoke**, lint clean, both pins matching the post-bump dispatcher.

**It is NOT ready to merge.** It carries **13 untriaged Codex connector threads** (1×P1, 12×P2)
raised against its latest heads. Under the bounded pipeline (global law 2 / BLUEPRINT law 11,
ratified in issue #92 after this handoff was first written), they get ONE severity-bar triage:
findings confirmed CRITICAL/HIGH by their CONTENT earn fix commits — the connector's P1/P2
label never decides; a P2 naming a confirmed correctness, security, or data-loss defect meets
the bar (this repo has seen a HIGH charter regression arrive mid-review) — and everything
else becomes a tracked issue or a one-line decline on the thread. **That single pass is the PR's next
step.** The full thread text is saved at
`.../scratchpad/pr71-open-threads.md`, or re-fetch with:

```
gh api graphql -f query='{repository(owner:"Chris0Jeky",name:"agent-harness"){pullRequest(number:71){reviewThreads(first:60){nodes{isResolved path line comments(first:3){nodes{body}}}}}}}'
```

Its recorded baselines are deliberate — a documented bypass that starts passing fails the gate as
"UNEXPECTEDLY FIXED", so nothing silently improves or silently rots.

**The review treadmill, and why it is over.** The connector re-reviews every pushed head, so
each fix round draws a new round of comments; one branch this session went six rounds, every
round finding genuine second-order defects in the previous round's fixes. That treadmill is
exactly the loop law 11 now terminates: two rounds is the ceiling — re-request the review
after the final fix round, triage what arrives once, then ship or park.

**Superseded (2026-07-26, issue #92):** the zero-skip rule this section used to state is
replaced by the bounded pipeline — one review round + one fix round; fix commits only for
confirmed CRITICAL/HIGH defects; everything else a tracked issue or a one-line decline, never
a silent drop. Global CLAUDE.md law 2 is the home (mirrored in SPECS §1).

## The redesign, ratified

The RFC is at issue **#21**'s 2026-07-25 comment. One sentence: *a hard deny requires proof of
irreversibility; everything the parser merely cannot prove safe is graduated (allow/log → ask →
deny by tier), and every ask-class outcome carries a self-service unstick path on both runtimes.*

What the architecture map changed about the plan:
- The ask channel barely exists — ~168 `deny` literals against **five** real `ask` returns, all
  Git work-loss guards, all reachable only at T3-without-relaxation. `respond()` rewrites every
  ask to deny for Codex.
- Rule identity is 3 of 168 sites. Every downstream mechanism (ledger, overrides, ACK) needs ids
  first — that is why #26 leads.
- Bounded `git` probes are an established pattern, not a new capability (the `sensitive_data`
  resolver already spawns them under a 3.5s budget with an injected runner). That settles the
  objection to conditional worktree logic. **Constraint:** any new probe must take
  `command_runner` as a default argument, or `replay_corpus.py` spawns real git per command.

**Slice order:** #26 (rule ids + FLOOR_ACK both runtimes + opt-in ledger) → #41 (worktree
graduation) → #62 (re-tier the opacity family; folds #32, #17) → #24 (literal variable
resolution — the only lever that also helps T4) → #38/#58 (here-string/heredoc bodies are data)
→ #48/#59 (sensitive_data target-aware).

For **#41** specifically: plain `git worktree remove` already refuses a dirty tree — git does the
clean check the floor cannot — so plain removal can allow below T4 and only `--force` needs the
ask channel. Two bugs to fix in the same slice: the match is positional-blind (`git worktree add
../remove` denies) and `prune` falls through unhandled.

## Human gates (only you can do these) — reconciled 2026-07-26
(`HUMAN_TODO.md` is authoritative; it also carries H-5 and H-6, which have no numbered gate in this list.)

1. **Deploy the floor** — **DONE and doctor-verified** (canonical 1.6.12 == deployed 1.6.12;
   the owner-directed `sync-global --apply` also refreshed `~/.codex/AGENTS.md` — backup under
   `~/.codex/backups/20260726T195246Z` — and three shared skills in `~/.agents/skills`, whose
   backups live under `~/.agents/skills/.harness-backups/20260726T195246Z`). HUMAN_TODO H-1
   carries the evidence; the tick is yours.
2. **Re-trust and canary the deployed bytes** — STILL OPEN (the one verification gate left;
   H-4 stays an ongoing manual chore): fresh Codex
   session per repo in its exact CWD, `/hooks` shows the expected adapter, then the allow/deny
   canary on BOTH runtimes — the Claude-side hook has live DENY evidence (two `[floor 1.6.12]`
   banners on 2026-07-26), but no deliberate ALLOW canary has run anywhere.
3. **`~/.claude` pushes** — **DONE**: `e42e211` and the follow-on memory commit are on pushed
   `main`; `settings.json` stayed uncommitted by design. See HUMAN_TODO H-3 for the
   branch-rule-bypass note that push surfaced.
4. **Worktrees still accumulate** (#41). Pruning remains manual until that slice lands.

## What was NOT verified

- Live hook execution is limited to two observed Claude-side denies on 2026-07-26
  (`[floor 1.6.12]` banners, mid-session — not a scripted canary). No Codex-side live
  execution at all; every other floor result is from calling `check()` in-process or from CI.
- The corpus replay for #53 showed **0 newly blocked / 1 newly allowed** across 91,300 unique
  commands — but the corpus contains no command using the shapes #53 changed most, so that zero
  is *unmeasured*, not *safe*. #70 and #71 had no replay at their final heads.
- #39 (olb T4 rollout) was auto-closed by #64's merge and **reopened** — the replay fix unblocks
  its measurement, not the rollout decision.

## Method note

Every PR went through 2–4 rounds of independent adversarial review plus the Codex connector,
which re-reviews each new head. That found real defects at every round, including a **HIGH
charter regression inside the fix for #46** (a quoted `> '.env'` went deny→allow) that green
smoke and a clean replay both missed.
