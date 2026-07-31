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
| B-006 | Replay reproduction rendering on Windows PowerShell 5.1.26100.8894 and Python 3.14.3 | One supported vector covering nine named path/syntax categories had 0 direct-argv versus rendered-argv differences; nine-job run `30639136818` passed | [PR #174](https://github.com/Chris0Jeky/agent-harness/pull/174) | Unsupported empty, multiline, quote, trailing-backslash, and smart-quote values intentionally omit executable rendering; no `cmd.exe` or general-shell claim. |
| B-007 | MCP source-identity classification, two cases | Before PR #175, the shared-source case was 1 false positive / 2 cases; after the fix both expected classifications passed (2/2); run `30640903741` passed | [PR #175](https://github.com/Chris0Jeky/agent-harness/pull/175) | `Path.resolve` plus Windows case-fold identity only; no hardlink or runtime-topology claim. |
| B-008 | PolicyDecision reason schema/runtime boundary, eight cases | Agreement improved from 7/8 to 8/8; run `30642286808` passed | [PR #176](https://github.com/Chris0Jeky/agent-harness/pull/176) | Covers the published CR/LF and length constraints; lone-surrogate parity remains #177. |
| B-009 | Docker MCP gateway static boundary on Docker 29.6.2 | The original three-case matrix improved from 2/3 to 3/3 correct classifications; the final root-option/subcommand matrix passed 25/25; run `30645532130` passed all nine jobs after one Windows failed-job rerun | [PR #178](https://github.com/Chris0Jeky/agent-harness/pull/178) | Static Docker 29.6.2 root-option contract only; not runtime-topology, gateway-plugin, or performance evidence. |
| B-010 | PR #178 exact-head Windows hosted CI, two attempts | Attempt 1 canceled at 15m05s after unit 6m18s, replay 2m53s, and 5m07s of smoke; attempt 2 passed in 11m33s with unit 5m32s, replay 9s, and smoke 5m17s | [Issue #179](https://github.com/Chris0Jeky/agent-harness/issues/179) | Two same-head GitHub-hosted Windows attempts prove budget exposure, not a long-run duration distribution or a product performance regression. |

## Interpretation boundaries

- B-001, B-002, B-003, and B-004 are evidence for AH-8 and bounded AH-3 design. They do not
  authorize universal-parser expansion or a current estate rollout.
- B-005 proves deterministic report behavior for the checked synthetic inputs. It does not prove
  process sandboxing, production policy quality, or public-product readiness.
- B-006–B-009 are bounded correctness matrices, not continuous precision or performance series.
- B-010 is CI proving-substrate evidence for AH-1; it does not justify skipping or allowing failure
  in any current gate.
- Warning, ask/approval, deny, source failure, and indeterminate outcomes remain separate metrics.

## Not yet benchmarked

- Current floor 1.6.21 over a pinned, privacy-safe estate corpus.
- Pattern Guard v2 hazard recall, benign near-miss rate, and shadow interruption rate.
- Longitudinal Doctor finding precision and recurrence after remediation.
- End-to-end task completion or workaround cost with a stable sampling protocol.
- Replay behavior on approved private historical inputs.

The next benchmark slice must commit or privately pin its input digest, environment, command,
result artifact, and comparison baseline before adding a number here.
