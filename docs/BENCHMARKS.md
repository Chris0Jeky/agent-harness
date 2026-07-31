# Benchmarks and measured evidence

Snapshot: 2026-07-31. An entry belongs here only when its input, method, numeric result, and
limitation are recorded. Historical results are not silently promoted to current baselines.

## Recorded results

| ID | Subject and environment | Measured result | Evidence | Limitation |
|---|---|---|---|---|
| B-001 | Legacy floor 1.5.4, offline replay of 63,668 unique commands / 109,464 invocations: 45,235 Codex and 18,433 Claude | Non-allow by unique command: T1 7,584 (11.91%); T2 7,584 (11.91%); T3 7,604 (11.94%, including 23 asks); T4 7,611 (11.95%) | [Issue #21](https://github.com/Chris0Jeky/agent-harness/issues/21) | Private transcript-derived corpus is not committed here; commands over 20k characters were skipped; offline resolver was stubbed; this is not a 1.6.21 result. |
| B-002 | One T4 consumer comparison over 80,315 unique commands / 128,781 invocations | Floor 1.2.0: 99 blocked (0.12%); floor 1.6.0: 11,528 (14.35%); transition added 11,444 blocked unique commands / 13,463 invocations and allowed 15 | [Issue #39](https://github.com/Chris0Jeky/agent-harness/issues/39) | `sensitive_data` and the consumer overlay were excluded; the old signature needed a local compatibility patch; this blocks rollout inference beyond that consumer and snapshot. |
| B-003 | One 2026-07-26/27 implementation session | Eight blocked incidents; six concerned work on the floor itself | [Issue #118](https://github.com/Chris0Jeky/agent-harness/issues/118) | Incident ledger, not a rate; one incident was a classifier rather than the floor; no population denominator. |
| B-004 | One 2026-07-27 overnight session against deployed floor 1.6.17 | Three false-positive shapes recorded: read-only Git plumbing, hermetic Git setup, scratch cleanup | [Issue #120](https://github.com/Chris0Jeky/agent-harness/issues/120) | Incident evidence without a denominator; not remeasured on 1.6.21. |
| B-005 | Replay v0 synthetic charter at `fd87e06` | Approximately 0.4 seconds wall time; 50/50 unchanged decisions; no source failures; 2 corpus files / 22,469 bytes; 2 recorded-source files / 9,466 bytes | [PR #140](https://github.com/Chris0Jeky/agent-harness/pull/140) | Fixture evidence on one recorded run, not a performance claim or live-policy equivalence proof. Charter composition is 20 safe, 20 dangerous, 10 ambiguous events. |

## Interpretation boundaries

- B-001, B-002, B-003, and B-004 are evidence for AH-8 and bounded AH-3 design. They do not
  authorize universal-parser expansion or a current estate rollout.
- B-005 proves deterministic report behavior for the checked synthetic inputs. It does not prove
  process sandboxing, production policy quality, or public-product readiness.
- Warning, ask/approval, deny, source failure, and indeterminate outcomes remain separate metrics.

## Not yet benchmarked

- Current floor 1.6.21 over a pinned, privacy-safe estate corpus.
- Pattern Guard v2 hazard recall, benign near-miss rate, and shadow interruption rate.
- Doctor finding precision and recurrence after remediation.
- End-to-end task completion or workaround cost with a stable sampling protocol.
- Replay behavior on approved private historical inputs.

The next benchmark slice must commit or privately pin its input digest, environment, command,
result artifact, and comparison baseline before adding a number here.
