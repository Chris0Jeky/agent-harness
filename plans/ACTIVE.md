# Active workstreams

## Workspace reference qualification (2026-10-02)

- #414 and #417 are merged: the handoff pack is an advisory authoring profile and the SQLite receipt lab is a single-owner reference, not native adoption.
- The receipt suite now backs up one leased fictional row into two independent databases and demonstrates that copied epoch/fence values allow both owners to accept divergent local results. Receiver fencing and old-writer isolation still require native proof.
- The handoff profile maps generic conformance cases to their native proof owners and separates cancellation request, admission stop, process acknowledgement and effects reconciliation. Native receipts remain with adopters; no runner, permission checker or gate is added.
- #410 remains open for its remaining profile cases/acceptance; #416's source acceptance is qualified separately from native adoption. Human gates remain in `HUMAN_TODO.md`.

Snapshot: 2026-10-01 13:18 UTC, before quality integration. Observed `main` head `7c10099`
(PR #409's merge). The 2026-09-02 snapshot and
everything older now live in `docs/archive/status-2026-09.md`; git history holds the rest.

## Quality pass (2026-10-01)

Eight Muse review lenses completed with two file-only worker candidates, at two-worker capacity
and a 2048 MB memory floor. The coordinator reproduced accepted defects and ran each candidate's
required checks; the supervisor is stopped with no in-flight jobs. Raw reports and logs remain
outside Git. No estate process, installed floor or consumer marker was changed.

- **#408 merged:** out-of-range UTC normalization in worktree leases now follows the malformed
  lease/keep path rather than raising; real Git fixtures prove plan/apply preserve the tree.
- **#409 merged:** re-recording stages all artifacts and recovers prior outputs after a later
  write failure, while preserving a later writer and retaining recovery bytes when necessary.
- **#412, reviewed source PR:** private Docker/Podman login endpoints and additional credential forms are
  scrubbed. Independent review caught an escaped-quote regression, fixed before publication.
- **#413, reviewed source PR:** malformed receipt/coordinator JSON is isolated by the outcome ledger, including
  nesting, duplicate keys and non-finite/overflow floats.
- **Integration branch:** includes the reviewed #412/#413 commits and floor 1.7.3, which restores
  the existing unscaled dispatcher-error deny for errors
  in later-fragment checks. Its separator semantics remain pinned by #267/#268 controls. The
  pathological quoted-brace availability edge is tracked in #365; #411 tracks positional
  `gh repo` selector scrubbing. Neither is a claim that scrubbed corpora are public-safe.

Floor 1.7.2 remains deployed. The 1.7.3 producer source may merge under the gate, but deployment,
consumer marker refresh and live trust/canaries still wait on H-14. Recording recovery does not
claim process-crash atomicity or exclusion of concurrent writers. Public replay extraction/release
is a separate step; H-19 remains open.

## Owner decisions in force (2026-09-29)

- **Merge autonomy.** Agents may merge any PR once its requirements are met: green proving checks
  at the exact head, law 2's review gate, the three-minute aging floor, merge commits only. The
  2026-09-28 "nobody merges" rule for the replay and merge-gate briefs is withdrawn.
- **AH-10 unlocked for the replay tool.** The owner approved a clean public repository, the name
  `charter-replay`, Apache-2.0, publication and the demo GIF (REPLAY_TOOL_PRODUCT RP-004/RP-005,
  AGENT_HARNESS_OPERATIONS AH-006). The source of truth stays `replay_v0/` here; the public
  repository is a clean extraction with fresh history.
- **Floor posture.** `core` is the default below T4/`wave_mode` for non-sensitive repositories
  (1.7.0, #356); rulesets protect default-branch history on every floored repository.

## Floor 1.7.2 rollout (SPECS §5.3)

| Step | State |
|---|---|
| Producer merge | **done**: #376, merge `e6973e8`, marker `326afdad…84b2af` |
| claude-config vendoring | **done**: claude-config#530 (merge `2f658f1`); smoke 2443/2443, fast gate green |
| Global deployment | **done**: `~/.claude/hooks` holds 1.7.2 (normalized digest equals the marker; backups `*.bak-20260928T235143Z`) |
| Consumer markers | **merged**: SwarmingLilMen#80, collaborative-hill-lab#14, Pulseboard#168. EvidenceDeck#35 is moved to 1.7.2 but blocked by H-18 |
| Consumer re-trust and canaries | **human**: H-14, per root, after its marker merge |

Codex's late review of the 1.7.2 bytes (claude-config#530) raised two P1s that are documented
limitations (FLOOR_LIMITATIONS lines on the inline-program tripwire and on core heredocs as data)
and one P2 false positive, now tracked in #365.

## Replay product ("measure your hook")

- **#384** (merged) adds the hook adapter, `charter-replay` entry point, private transcript importer,
  charter-v0.2 corpus (494 events) and examples. Review was two rounds, both closed.
- The clean public repository `Chris0Jeky/charter-replay` exists (public, private vulnerability
  reporting on, squash merges off). Extraction runs from merged `main`: package renamed to
  `charter_replay`, Apache-2.0, CI on Ubuntu/Windows/macOS, a trusted-publishing release workflow.
- PyPI publication needs a trusted publisher on pypi.org; that is a human step (H-19).
- Private corpus measurement (local only, aggregates in #384): 130,624 unique scrubbed commands;
  on a 10,000 sample, the floor at 1.7.2 denies 1.18% at tier 3 and 9.12% at tier 4.
- charter-replay v0.1.0 is released on GitHub (wheel and sdist); PyPI waits on H-19.
- Source of truth: still `replay_v0/` here, extracted to the public repository. Once product
  work lands in `Chris0Jeky/charter-replay` directly (the owner is starting an outside
  architecture effort there), the direction flips; decide it before the two trees diverge.

## Merged 2026-09-29

#376 (floor 1.7.2), #380 (Doctor Codex launcher probe), #381 (status_doc budget), #345 (Doctor
controlled-dispatcher checks; #339 closed as superseded), #382 (tier.json wrong-type reporting) and
#384 (replay adapter). The conflicts #345/#380 and #382/#381 were resolved on the PR branches; the
combined tree passed 1,322 unit and 186 replay tests locally before the sequential merges.

Morning, also merged: #386 (the late Codex P2s on #384: relative hook executables, non-HTTP private
hosts) and #388 (another session: BLUEPRINT and SPECS follow the laws changes).

Afternoon wave (Muse workers and lenses, one Sonnet helper, merges after a fresh-context review
and exact-head CI): #390 (ledger fingerprint parity, #387), #391 (unreadable budget docs, #383),
#392 (terminal-only policy stderr, #141), #393 (hook adapter test gaps), #394 (hook CLI
hardening), #398 (secret-path coverage table, #244), #399 (CLAUDE.md lint list) and #400
(`seed` gitignores `/.claude/worktrees/`, #236), then #403 (CI: Verify lints
first with a 30-minute budget, #402) and, last, #396 (importer scrub leaks).

## PR checkpoint (2026-10-01, before integration)

| PR | State |
|---|---|
| #332 | older parked lane from another session; not touched here |
| #406 | another session's draft architecture synthesis; not touched here |
| #412 | reviewed quality privacy source; commits included in the integration branch |
| #413 | reviewed quality ledger source; commits included in the integration branch |

## Open follow-ups

- #233 (open): the declared two-workstream cap versus region-disjoint lanes. Until it
  rules, a region-disjoint lane does not consume a workstream slot (the assumption recorded in
  `docs/archive/status-2026-09.md`).

- #365: remaining core false positives (57 T3 denies in the decider; `py`/`python3.12` heads;
  gh body-heredoc; prose punctuation as path shape).
- #370 and #375: audit protection and sync follow-ups (#370 status comment 2026-09-29: the
  empty-leg item is resolved).
- #395 (owner): relax the extraction manifest's byte pin to a path pin.
- #397 and #401: importer scrub speed on long inputs, and the remaining bare-host gaps.
- #378: wrapped downloaders (taskset, flock, watch, wsl) under the feature freeze.

## Human items

`HUMAN_TODO.md` holds them: H-14 (re-trust and canaries, now for 1.7.2), H-18 (Actions billing for
private repositories), H-19 (PyPI trusted publisher for charter-replay).
