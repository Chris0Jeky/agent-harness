# Active workstreams

Snapshot: 2026-09-02. Published `main` head: `d6392dd7959cd887bd83551bf43ddd53b96e97bf` (PR #260's merge
`d6392dd`). The 2026-08-07 lanes are all closed: PR #238 and PR #239 merged today after their
blockers were fixed, and two new floor lanes merged with them (PR #257 = 1.6.29, PR #260 = 1.6.31).
The rollout workstream below is re-owed at 1.6.31 and stays blocked on human-only runtime proof.

Current runtime state: canonical source and the producer marker are **1.6.31**; deployed bytes
(claude-config `hooks/`, the owner's `~/.claude/hooks`) are **1.6.29**, authored consumer-side by
the owner on 2026-08-18 and upstreamed by #257; runtime canaries remain at **1.6.26**. Canonical
is therefore two versions AHEAD of deployed. The consumer sync and every marker change require
their own exact-root proof — **H-15** in `HUMAN_TODO.md`.

## Active rollout — issue #232, blocked on human-only runtime proof

Static deployment is NOT complete and is NOT runtime proof: claude-config `hooks/dispatch.py` and
the owner's `~/.claude/hooks` carry **1.6.29** (the owner's consumer-side authoring of
2026-08-18), canonical is **1.6.31** (PR #260) with **1.6.32** in PR #262, and the last runtime
canaries were 1.6.26. The 1.6.27 record (claude-config PR #127, identity-only `sync-global`) is
historical.

The remaining rollout is STRICTLY ORDERED. SPECS §5 fixes a five-phase order, and this file uses
that numbering and no other:

| Phase | SPECS §5 step | State (re-owed at 1.6.31, 2026-09-02) |
|---|---|---|
| P1 | producer merge | **done** — PR #260 (1.6.31) on top of #257 (1.6.29) and #239 (1.6.30) |
| P2 | reviewed clean-main install | **NOT DONE** — claude-config `hooks/` is at 1.6.29; sync 1.6.31 bytes in by PR, then `sync-global --apply` |
| P3 | producer exact-CWD re-trust and canaries | **NOT DONE** — add the 1.6.31 canary trio (SPECS §5.4): harmless allow, opacity allow, double-check |
| P4 | consumer marker refresh | **NOT DONE — blocked by BOTH P3 and P3b** |
| P5 | each consumer's exact-CWD re-trust and canaries | **NOT DONE — blocked by P4** |

Only P1 is complete. Everything below is outstanding. Perform it in this sequence and never out of
it (H-15 in `HUMAN_TODO.md` is the human-side record):

- **P2 — reviewed clean-main install (agent lane).** Sync the canonical bytes of the version being
  rolled out (`templates/hooks/dispatch.py` + `smoke_test.py`) into claude-config `hooks/` by PR
  (its ritual: `git diff --check` + `py -3 hooks/smoke_test.py`), then from clean published mains
  run `py -3 harness.py sync-global --config-root <claude-config> --apply` and confirm Doctor
  reports canonical == deployed at that version.
- **P3 — producer, first and alone.** In a new normal Codex TUI launched from the agent-harness
  exact repository root, complete `/hooks` review and re-trust of the sole project handler, confirm
  its enabled state, run `py -3 harness.py doctor --repo .` (bare `doctor` runs only the global
  checks and skips the producer adapter, activation, and project-floor checks), then collect the
  canary TRIO of SPECS §5.4: the harmless allow (`git status --short --branch`), an opacity allow
  (`& $py -m build` at this T3 repo), and a double-check — the inert local deny probe
  (`git push --dry-run --no-verify --force . HEAD:refs/heads/codex-h2-deny-canary`) must be denied
  once with a `FLOOR_ACK` key and pass when re-run with that key as a trailing comment.
- **P3b — fresh global Claude proof**, independently, against the deployed bytes, with the same
  trio. Claude and Codex are distinct runtimes; neither proves the other.
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
| #201 numeric `push.followTags` | **#239** | **MERGED `d07f911`** as floor 1.6.30 at head `33faedf`: rebased by merge commits onto #238 + #257, ledger edits dropped per the ownership rule below, re-proved (smoke 2264/2264, 940 unit tests, nine green). #243 carries the toolchain-dependent edges. |
| #139 nested logical root | **#238** | **MERGED `000268b`** at head `5221b54`: the three P1s fixed (junction-aware search, nested-Git boundary, doctor's layer walk and nearest-adapter rule), fresh-context review MERGE, #258 tracks the LOW. |
| 1.6.29 upstream | **#257** | **MERGED `2b793f2`**: the owner's claude-config decisions brought back to the producer, byte-faithful plus black; four carve-out defects its review found are fixed in #260 (#259). |
| guide posture / FLOOR_ACK | **#260** | **MERGED `d6392dd`** as floor 1.6.31 after two review rounds (the second closed the masked-charter-spelling hole). |

No implementation lane is open. The one queued follow-up is **PR #262** (floor 1.6.32: an
opacity-first deny re-checks every later command segment with the analyzer, the late Codex P1 on
#260); it merges on nine green checks plus one independent review, and the rollout above then
carries 1.6.32 rather than 1.6.31.

**The ownership rule that this wave established stays in force.** A lane's permitted region is
its code and tests only; the shared ledgers — `README.md`, `ROADMAP.md`, `docs/SYSTEM_STATE.md`,
`plans/ACTIVE.md`, `CLAUDE.md`, `SPECS.md` — belong to the coordinator's single pass after the lane
merges (the exception: a floor lane updates the README shipped-state paragraph it moves). Both
2026-08-07 lanes exceeded their regions once, and that — not code overlap — is what conflicted.

How the two 2026-08-07 blockers were closed, for the record: #239 dropped its ledger edits outright
(taking `main` for all three files disposed of the false "1.6.27 was never deployed" claim) and was
re-versioned to 1.6.30 because 1.6.28/1.6.29 were taken by the owner's claude-config decisions;
#238's three P1s (junctions followed, nested Git repos selectable, Doctor's layer walk) were fixed
in one commit and pinned by tests. The full blocker text is in the PR threads.

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
- #201 shipped in PR #239 (1.6.30); #243 holds its two toolchain-dependent edges. #258 (doctor's
  rule-2 wrapper session model, LOW) and the residual `FLOOR_LIMITATIONS.md` lines from the #257 and
  #260 reviews are queued, not active. #26, #62 and #259 closed with PR #260.
- #186 is owned by the canonical `review-and-ship` skill in `claude-config`, not this runtime.
  #188 awaits an owner-reviewed consumer manifest; #190 awaits a real generated launcher call
  site. #185/#191/#192 remain mapped follow-ups. Replay slices remain held while the replay-tool
  worktree is occupied; `tooling/corpus-replay` remains at preserved `afb1c0a`, one local commit
  ahead, and is ineligible until that checkpoint receives tests, review, and an explicit publish
  decision.
- H-2 is closed after the exact current-consumer marker/review/trust/canary wave. AH-10 extraction
  and a public replay repository remain deferred.
