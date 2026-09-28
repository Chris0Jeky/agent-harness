# Active workstreams

Snapshot: 2026-09-02. Published `main` head: `d6392dd7959cd887bd83551bf43ddd53b96e97bf` (PR #260's merge
`d6392dd`). The 2026-08-07 lanes are all closed: PR #238 and PR #239 merged today after their
blockers were fixed, and two new floor lanes merged with them (PR #257 = 1.6.29, PR #260 = 1.6.31).
The rollout workstream below is re-owed at 1.6.31 and stays blocked on human-only runtime proof.

Current runtime state (2026-09-03): canonical source, the producer marker, claude-config `hooks/`
(PR #199) and the owner's `~/.claude/hooks` are all **1.6.33** (PR #267 on top of #262's 1.6.32);
`doctor` proves canonical == deployed; the Claude runtime canary trio plus the 1.6.33-specific
`gh … --help` pair passed live in the deploying session on 2026-09-03; the Codex exact-CWD
re-trust and Codex canaries are still owed — **H-15** in `HUMAN_TODO.md`.

2026-09-03: the owner directed `guide` posture for claude-config. Its `tier.json` declares it
(claude-config PR #197, merge `1594f9c`), and `~/.claude` — a deployment checkout of that same
repository — was fast-forwarded to it with the hook bytes unchanged. Below the fail-closed
`dispatcher error` deny, nothing in either surface is a wall now; the irreversible core is an
acknowledgeable double-check there. The runtime home is level on paper and unproven in a real
session — **H-16**, which does not close with H-15.

## Active rollout — issue #232, blocked on the Codex half of the runtime proof

Static deployment of **1.6.33** is complete (claude-config PR #199; `sync-global --apply` into
`~/.claude/hooks`, `doctor` canonical == deployed) and the **Claude** runtime proof is done (live
canary trio plus the 1.6.33 `gh … --help` pair, 2026-09-03). Static deployment is never runtime
proof for the OTHER runtime: the Codex exact-CWD re-trust and Codex canaries are outstanding. The
1.6.32 record (claude-config PR #196), the 1.6.27 record (claude-config PR #127) and the 1.6.29
consumer-side authoring are historical.

The remaining rollout is STRICTLY ORDERED. SPECS §5 fixes a five-phase order, and this file uses
that numbering and no other:

| Phase | SPECS §5 step | State (1.6.33, 2026-09-03) |
|---|---|---|
| P1 | producer merge | **done** — PR #267 (1.6.33) on #262 (1.6.32), #260 (1.6.31), #239 (1.6.30), #257 (1.6.29) |
| P2 | reviewed clean-main install | **done** — claude-config PR #199 (byte-identical, smoke 2383/2383); `sync-global --apply` into `~/.claude/hooks` with backup, `doctor` canonical == deployed; Claude canary trio plus the 1.6.33 pair passed live |
| P3 | producer exact-CWD re-trust and canaries | **VOID 2026-09-07** — the producer is floorless by owner decision (claude-config HUMAN_TODO q-22, PR #274): `.codex/hooks.json` retired to `templates/codex/hooks.json`, `tier.json` declares `floor_wiring: none`. There is no producer canary station any more. |
| P4 | consumer marker refresh | **NOT DONE — unblocked 2026-09-07** (P3 void, P3b done); proceed one root at a time, merge-first per H-14 step 3 |
| P5 | each consumer's exact-CWD re-trust and canaries | **NOT DONE — per root, after that root's P4 merge** |

P1 and P2 are complete. Everything below is outstanding. Perform it in this sequence and never out of
it (H-15 in `HUMAN_TODO.md` is the human-side record):

- **P2 — reviewed clean-main install (agent lane).** Sync the canonical bytes of the version being
  rolled out (`templates/hooks/dispatch.py` + `smoke_test.py`) into claude-config `hooks/` by PR
  (its ritual: `git diff --check` + `py -3 hooks/smoke_test.py`), then from clean published mains
  run `py -3 harness.py sync-global --config-root <claude-config> --apply` and confirm Doctor
  reports canonical == deployed at that version.
- **P3 — VOID since 2026-09-07 (owner decision: floorless producer; see the table).** The text
  below is kept as the historical procedure only. Original: **producer, first and alone.** In a new normal Codex TUI launched from the agent-harness
  exact repository root, complete `/hooks` review and re-trust of the sole project handler, confirm
  its enabled state, run `py -3 harness.py doctor --repo .` (bare `doctor` runs only the global
  checks and skips the producer adapter, activation, and project-floor checks), then collect the
  canary TRIO of SPECS §5.4: the harmless allow (`git status --short --branch`), an opacity allow
  (`& $py -m build` at this T3 repo), and a double-check — the inert local deny probe
  (`git push --dry-run --no-verify --force . HEAD:refs/heads/codex-h2-deny-canary`) must be denied
  once with a `FLOOR_ACK` key and pass when re-run with that key as a trailing comment.
- **P3b — fresh global Claude proof: DONE 2026-09-02** against the deployed 1.6.32 bytes, in the
  deploying Claude session (`rm -rf` on a nonexistent outside path denied once with a key and
  allowed when acknowledged; a dynamic redirect target allowed). Claude and Codex are distinct
  runtimes; this does not prove Codex.
- **P4/P5 — no longer gated on P3 (void); each root proves its own bytes.** The three consumer marker PRs — EvidenceDeck #21,
  collaborative-hill-lab #5, SwarmingLilMen #52 — were closed unmerged at the producer-first gate;
  their reviewed branches and heads are preserved. Reopen them one at a time, each for its own
  exact-root proof. SwarmingLilMen additionally carries a separate owner gate under its own issue
  #91.

P3 is void since 2026-09-07; consumer marker refreshes proceed one root at a time, each root
proving its own bytes in its own exact CWD (H-14 step 3), merge first. No runtime proof is inherited from deployment, from Doctor, or from the
completed 1.6.26 wave.

## 2026-09-27 evals lanes: learning from outcomes, proving gates

| Lane | PRs | Outcome |
|---|---|---|
| Outcome ledger over swarm receipts (#299/E1) | #354, #360 | **MERGED** `59db399`, `8434156`. #354's round 1 fixed 1 HIGH + 4 MEDIUM; its single reopen fixed one HIGH regression the fix introduced; Codex P2s closed by #360. |
| Merge-gate model and checker (claude-config #432) | #355, #361 | **MERGED** `92d5795`, `91a31b9`. Round 1 found the spec trusted the table's own bookkeeping (three mutants certified lawful); fixed with an event-driven observer. A repo-wide raw-check guard turned CI red once (the model's `check()`), fixed by renaming. |

Floor finding (issue #356, owner decision **H-17**): no Claude session runs the deny floor and only six Codex roots do; before the decision, none of the floored public repositories, nor this one, protected `main` server-side. Owner decision 2026-09-27 (H-17, closed): default-branch rulesets are live on six repositories; the client floor shrinks to local destruction next.

## 2026-09-28 floor lane: core posture and its rollout (#356, owner decisions H-17 and core)

| Lane | PRs | Outcome |
|---|---|---|
| Core posture, floor 1.7.0 | #363 | **MERGED** `a545fb9`. Round 1: one HIGH (a sensitive repo declaring core could leak a public push) and one MEDIUM fixed; round 2 caught a quadratic hint (fixed). |
| Long-form rm hint, 1.7.1 | #372 | **MERGED** `f683e54`. A Codex P1 found on claude-config#461. Two review rounds; two Codex comments declined and recorded in FLOOR_LIMITATIONS. |
| Audit: default-branch protection | #369 | **MERGED** `96068ca`. Muse drafted it and timed out; finished here. The check is advisory only. |
| Doctor: `rules/laws.md` byte check | #371 | **MERGED** `43a6134` (closes #366). |
| SPECS §1 law pointer | #364 | **MERGED** `dc90bfb` (closes #358). |
| Rollout | claude-config#461; EvidenceDeck#35, SwarmingLilMen#79, collaborative-hill-lab#10, Pulseboard#167 | claude-config#461 **MERGED** `f0431b3` and deployed (doctor: canonical == deployed). Marker PRs **MERGED**: SwarmingLilMen#79 (`7e7b26e`), collaborative-hill-lab#10 (`8ad50d7`), Pulseboard#167 (`134ab8d`). EvidenceDeck#35 is parked: its CI cannot start (billing, H-18). The per-consumer re-trust is H-14. |

## Active implementation

Four bounded lanes were dispatched 2026-08-07, each in its own isolated worktree with a declared
region boundary. Exactly one touched `templates/hooks/dispatch.py`; the other three were forbidden
from it, so no two lanes could collide on `FLOOR_VERSION`, the adapter marker, or the charter
digests. **All four landed**, two on 2026-08-07/08 and two on 2026-09-02, alongside the three
floor PRs of 2026-09-02.

| Lane | PR | Outcome |
|---|---|---|
| #110 cross-product gate | **#240** | **MERGED `a8ed1d4`** at head `f06b304`. Nine green, adversarial review MERGE with zero blocking findings and every claim reproduced. |
| #130 secret-file reading | **#237** | **MERGED `8134cf4`** at head `c1da78a`. Nine green, adversarial review MERGE with zero blocking findings. `Refs #130`, not `Closes` — the charter ruling is the owner's. |
| #201 numeric `push.followTags` | **#239** | **MERGED `d07f911`** as floor 1.6.30 at head `33faedf`: rebased by merge commits onto #238 + #257, ledger edits dropped per the ownership rule below, re-proved (smoke 2264/2264, 940 unit tests, nine green). #243 carries the toolchain-dependent edges. |
| #139 nested logical root | **#238** | **MERGED `000268b`** at head `5221b54`: the three P1s fixed (junction-aware search, nested-Git boundary, doctor's layer walk and nearest-adapter rule), fresh-context review MERGE, #258 tracks the LOW. |
| 1.6.29 upstream | **#257** | **MERGED `2b793f2`**: the owner's claude-config decisions brought back to the producer, byte-faithful plus black; four carve-out defects its review found are fixed in #260 (#259). |
| guide posture / FLOOR_ACK | **#260** | **MERGED `d6392dd`** as floor 1.6.31 after two review rounds (the second closed the masked-charter-spelling hole). |
| masked later segments | **#262** | **MERGED `c34c74c`** as floor 1.6.32 (the late Codex P1 on #260): an opacity-first deny re-checks every later command segment with the analyzer; one review round. |

Done (2026-09-28): the client floor's local-destruction `core` posture and its rollout (#356; see the
2026-09-28 floor lane above). Still open there: EvidenceDeck#35 behind H-18, and H-14's re-trusts.

**The ownership rule that this wave established stays in force.** A lane's permitted region is
its code and tests only; the shared ledgers — `README.md`, `ROADMAP.md`, `docs/SYSTEM_STATE.md`,
`plans/ACTIVE.md`, `CLAUDE.md`, `SPECS.md` — belong to the coordinator's single pass after the lane
merges (the exception: a floor lane updates the README shipped-state paragraph it moves). Both
2026-08-07 lanes exceeded their regions once, and that — not code overlap — is what conflicted.

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
