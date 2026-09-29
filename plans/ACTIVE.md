# Active workstreams

Snapshot: 2026-09-29. `main` head `f29f0ab` (PR #384's merge). The 2026-09-02 snapshot and
everything older now live in `docs/archive/status-2026-09.md`; git history holds the rest.

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

## Merged 2026-09-29

#376 (floor 1.7.2), #380 (Doctor Codex launcher probe), #381 (status_doc budget), #345 (Doctor
controlled-dispatcher checks; #339 closed as superseded), #382 (tier.json wrong-type reporting) and
#384 (replay adapter). The conflicts #345/#380 and #382/#381 were resolved on the PR branches; the
combined tree passed 1,322 unit and 186 replay tests locally before the sequential merges.

## Open pull requests

| PR | State |
|---|---|
| #386 | the two late Codex P2s on #384 (relative hook executable, non-HTTP private hosts) |
| #332 | older parked lane from another session; not touched here |

## Open follow-ups

- #365: remaining core false positives (57 T3 denies in the decider; `py`/`python3.12` heads;
  gh body-heredoc; prose punctuation as path shape).
- #370 and #375: audit protection and sync follow-ups.
- #378: wrapped downloaders (taskset, flock, watch, wsl) under the feature freeze.
- #383: an unreadable or non-UTF-8 budgeted doc aborts `audit` (from #381's Codex review).

## Human items

`HUMAN_TODO.md` holds them: H-14 (re-trust and canaries, now for 1.7.2), H-18 (Actions billing for
private repositories), H-19 (PyPI trusted publisher for charter-replay).
