# Active workstreams

Snapshot: 2026-08-08. Published `main` head: `a8ed1d481b8903e71b0d0443a67887274d692d92` (PR #240's
merge). The four lanes below were cut from `731624106fc38a9f46e21553c61b3cb0ee56dfeb` (PR #230's
merge); `main` then moved **four times** under them — `3ade22b` (a `.gitignore`-only direct push,
#236), then PR #234's merge `8a1a685`, PR #237's `8134cf4` and PR #240's `a8ed1d4` — so each
remaining lane rebases onto the current head and re-proves against it rather than inheriting. One bounded rollout workstream is blocked on human-only runtime
proof; implementation lanes are listed under "Active implementation" below.

Current runtime state, unchanged by this wave: canonical source, the producer marker, and deployed
global bytes are **1.6.27**; all runtime canaries remain at **1.6.26**, the last directly proved
version. Nothing merged on 2026-08-07/08 touched `templates/hooks/dispatch.py` — the one lane that
does (#201/PR #239) is still open — so `FLOOR_VERSION` is still 1.6.27 and no marker moved. The
changed producer marker and every later consumer-marker change require their own exact-root proof.

## Active rollout — issue #232, blocked on human-only runtime proof

Static deployment is complete and is NOT runtime proof:

- Claude-config PR #127 merged as `6aac87507c5afbb35da39f38628b880feb38921a`; both authoring
  and deployed checkouts are clean at that merge. The explicit `sync-global` dry run and apply were
  identity-only, and Doctor proves canonical == deployed 1.6.27 from clean published mains.

The remaining rollout is STRICTLY ORDERED. SPECS §5 fixes a five-phase order, and this file uses
that numbering and no other:

| Phase | SPECS §5 step | State |
|---|---|---|
| P1 | producer merge | **done** — PR #230 |
| P2 | reviewed clean-main install | **done** — claude-config PR #127, sync-global identity-only |
| P3 | producer exact-CWD re-trust and canaries | **NOT DONE** |
| P4 | consumer marker refresh | **NOT DONE — blocked by BOTH P3 and P3b** |
| P5 | each consumer's exact-CWD re-trust and canaries | **NOT DONE — blocked by P4** |

Only P1 and P2 are complete. Everything below is outstanding. Perform it in this sequence and never
out of it:

- **P3 — producer, first and alone.** In a new normal Codex TUI launched from the agent-harness
  exact repository root, complete `/hooks` review and re-trust of the sole project handler, confirm
  its enabled state, run `py -3 harness.py doctor --repo .` (bare `doctor` runs only the global
  checks and skips the producer adapter, activation, and project-floor checks), then collect BOTH
  1.6.27 canary legs — the harmless allow (`git status --short --branch`) and the inert local deny
  probe (`git push --dry-run --no-verify --force . HEAD:refs/heads/codex-h2-deny-canary`).
- **P3b — fresh global Claude proof**, independently, against the deployed 1.6.27 bytes. Claude and
  Codex are distinct runtimes; neither proves the other.
- **P4/P5 — only after P3 and P3b both succeed.** The three consumer marker PRs — EvidenceDeck #21,
  collaborative-hill-lab #5, SwarmingLilMen #52 — were closed unmerged at the producer-first gate;
  their reviewed branches and heads are preserved. Reopen them one at a time, each for its own
  exact-root proof. SwarmingLilMen additionally carries a separate owner gate under its own issue
  #91.

Refreshing or validating any consumer marker before P3 and P3b both pass is out of order and is not
authorized by this file. No runtime proof is inherited from deployment, from Doctor, or from the
completed 1.6.26 wave.

## Active implementation

Four bounded lanes were dispatched 2026-08-07, each in its own isolated worktree with a declared
region boundary. Exactly one touched `templates/hooks/dispatch.py`; the other three were forbidden
from it, so no two lanes could collide on `FLOOR_VERSION`, the adapter marker, or the charter
digests. **Two landed, two remain open with confirmed blockers.**


| Lane | PR | Outcome |
|---|---|---|
| #110 cross-product gate | **#240** | **MERGED `a8ed1d4`** at head `f06b304`. Nine green, adversarial review MERGE with zero blocking findings and every claim reproduced. |
| #130 secret-file reading | **#237** | **MERGED `8134cf4`** at head `c1da78a`. Nine green, adversarial review MERGE with zero blocking findings. `Refs #130`, not `Closes` — the charter ruling is the owner's. |
| #201 numeric `push.followTags` | **#239** | **OPEN, blocked.** Nine green at `6b93c9a`, but review verdict FIX with two blocking findings: it conflicts with `main` after #234, and its `plans/ACTIVE.md` asserted "1.6.27 was never deployed", which is false. |
| #139 nested logical root | **#238** | **OPEN, blocked.** Nine green at `5e7aa28` and all seven acceptance criteria met, but two independent reviewers converged on three P1 correctness defects in `harness.py`. |

Neither open PR is parked: each has one fix round remaining within law 2's budget, and the exact
blockers are recorded on the PR thread. Do not restart either lane from scratch — the evidence
already gathered is sound and was independently reproduced.

**Permitted regions for the two OPEN lanes.** A resuming worker must not exceed these. Both open
lanes exceeded theirs once already, and that — not code overlap — is what conflicted:

| Lane | Permitted files |
|---|---|
| #201 / PR #239 | `templates/hooks/dispatch.py`, `templates/hooks/smoke_test.py`, `tests/test_sensitive_push_narrowing.py`, `FLOOR_VERSION`, the `.codex/hooks.json` marker |
| #139 / PR #238 | `harness.py`, `tests/test_harness.py` |

The shared ledgers — `README.md`, `ROADMAP.md`, `docs/SYSTEM_STATE.md`, `plans/ACTIVE.md`,
`CLAUDE.md`, `SPECS.md` — are in NEITHER region. The coordinator records every lane's outcome in one
pass, so a lane that edits them creates exactly the conflict this wave hit.

**#239's blockers, precisely.** (1) **Drop the branch's ledger edits entirely** — `README.md`,
`docs/SYSTEM_STATE.md` and `plans/ACTIVE.md` are outside its permitted region (see the table above)
and are exactly what conflicts with `main`. Resolve the rebase by taking `main` for all three; do
not port the branch's versions forward and do not add the 1.6.28 facts here. **The coordinator
records the 1.6.28 state after the lane merges**, in one pass, which is the whole point of the
ownership rule. The lane keeps only its in-region files. (2) The branch's ledger text asserted
"1.6.27 was never deployed", which is false — the correct state is **deployed 1.6.27, runtime-proved
1.6.26**, and those are materially different. Dropping the ledger edits under (1) disposes of this
automatically; it is recorded so the claim is not reintroduced from the branch's history. (3) A base
change counts as a head change, so CI and review are owed again on the rebased head. `dispatch.py`
itself does not conflict, so the parser evidence carries; the documentation evidence does not.
Residual toolchain-dependent over-block tracked as #243.

**#238's blockers, precisely.** (1) `harness.py:3988` — Windows junctions are followed by the
nested-root search although SPECS §2.1 and the new docstring both promise they are skipped;
`entry.is_dir(follow_symlinks=False)` classifies a junction as an ordinary directory, and the repo
already owns the correct predicate in `path_is_alias()` at `harness.py:471`. (2) `harness.py:3999`
— the downward search can select a nested independent Git repository or submodule, so `git status`
and `git remote` answer for the wrong repository, contradicting SPECS §2.1's "Git facts stay the
checkout's" which this PR wrote. (3) `harness.py:8018` — Doctor's canonical adapter is retargeted to
a downward-resolved root while the layer walk still runs to the requested path, so
`canonical_root_floor_count` is structurally 0 for exactly the new case and a previously-certified
configuration regresses. Plus a non-blocking P2 (`frontier.pop(0)` is quadratic).

**Declared-cap divergence, tracked as #233.** `README.md` declares this file as allowing "at most
two active, executable workstreams"; this wave ran four lanes plus the blocked rollout. The count was
not rewritten to fit. **Assumption: a region-disjoint lane does not consume a workstream slot.
Reason: the cap protects against colliding edits to `dispatch.py`/`FLOOR_VERSION`/the adapter marker,
and exactly one lane could touch those.** The full measurement — which boundaries held, the four
`main` movements, and the corrected reversal path — is in
[`docs/archive/status-2026-08.md`](../docs/archive/status-2026-08.md). Until #233 rules, the declared
count in `README.md` stands as written.

## Completed work

The completed record for this period is rotated to
[`docs/archive/status-2026-08.md`](../docs/archive/status-2026-08.md) under SPECS §3's 150-line cap
on the routed "now" document. Most recent: PR #234 (`8a1a685`) published the 1.6.27 ledger,
PR #240 (`a8ed1d4`) closed #110, PR #237 (`8134cf4`) advanced #130, PR #230 (`7316241`) closed #227.

## Parked or queued, not active

- #160 closed through PR #219: effective disablement suppresses only a cross-layer mixed-transport
  conflict; same-table conflict remains invalid and a later re-enable fails closed. Doctor reports
  static topology only, not complete Codex parser acceptance for inactive definitions.
- #201 is no longer held. The hold read "while dispatcher/smoke ownership is occupied", and #227
  released that ownership when PR #230 shipped, so #201 is dispatched as the sole dispatcher lane
  under "Active implementation" above. It remains bounded exactly as before: it is not permission to
  reopen #193/#196 or to broaden the parser beyond `push.followTags`.
- #186 is owned by the canonical `review-and-ship` skill in `claude-config`, not this runtime.
  #188 awaits an owner-reviewed consumer manifest; #190 awaits a real generated launcher call
  site. #185/#191/#192 remain mapped follow-ups. Replay slices remain held while the replay-tool
  worktree is occupied; `tooling/corpus-replay` remains at preserved `afb1c0a`, one local commit
  ahead, and is ineligible until that checkpoint receives tests, review, and an explicit publish
  decision.
- H-2 is closed after the exact current-consumer marker/review/trust/canary wave. AH-10 extraction
  and a public replay repository remain deferred.
