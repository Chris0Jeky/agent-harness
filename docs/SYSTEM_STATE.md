# System state

Snapshot: 2026-07-31, after PR #178 merged as `576b540b0e856ed61dc1b062b1cdae0abbcd89dd`.
Refresh Git, GitHub, deployed bytes, and live runtime evidence before relying on this snapshot.

## Evidence vocabulary

- **implemented**: executable code or an authoritative operating contract exists on `main`.
- **deployed**: measured bytes or configuration exist at the runtime destination.
- **benchmarked**: a recorded input, method, and numeric result exist; scope limits still apply.
- **experimental**: usable for bounded internal evidence, not a production or compatibility promise.
- **frozen**: intentionally preserved; feature expansion is outside the active lane.
- **unverified**: a required observation has not been made or cannot be inferred from static proof.
- **stale**: historically useful evidence that no longer describes current state.

## Capability ledger

| Capability | Outcome state | Direct evidence | Limitation and next executable handoff |
|---|---|---|---|
| Repository mission and authority | implemented | `AGENT_HARNESS_AGENT_BRIEF.md`; `.agent-harness/tier.json` declares T3, push free, merge free | Authority can change; re-read every co-located tier declaration before mutation. The Windows aggregate CI budget defect is measured in #179. |
| Legacy deny-floor source | implemented, frozen | `templates/hooks/dispatch.py` reports 1.6.21; `floor-v1-final` tag object `5a939540bdce51e511d6b3bae98358e3e2ad9148` peels to `02bd14cfe094f9b6af85b966de481ff3f45264cf`; limitations live only in `FLOOR_LIMITATIONS.md` | No universal-parser expansion. Bounded false-positive fixes require the freeze exceptions and direct evidence. |
| Shared Claude-hook floor | deployed, unverified | On 2026-07-31 the canonical Git blob and LF-normalized deployed `~/.claude/hooks/dispatch.py` measured `EA4FB45DC71A44E80392E7EA423BC70DCB604538E956CB13CF34B750118974B5`; the deployed raw CRLF bytes measured `E1A4E7714913788DD801F0FA43A3E5B30EA0433709F97142509B56B1C442EF68`, version 1.6.21 | Normalized bytes match; raw line-ending differences are not drift. Static equality does not prove Codex activation or trust. H-2 is the sole open human action and is owner-parked. |
| Replay v0 / Policy Lab | implemented, benchmarked, experimental | PR #140 merged the core; PRs #159/#163 closed report and manifest defects; PR #174 published structured/platform-valid reproduction argv and closed #152; PR #176 aligned reason newline schema/runtime behavior and closed #156; nine-job runs `30639136818` and `30642286808` passed | Internal evidence tool only. It is not a sandbox, global blocker, public repository, or universal policy language. Lone-surrogate parity remains bounded follow-up #177. |
| Audit and Doctor foundation | implemented, benchmarked, experimental, unverified | `harness.py audit` and `doctor`; PR #161 added static MCP topology diagnosis and closed #87; PR #175 removed shared-source identity false positives and closed #164; PR #178 bounded Docker gateway subcommand detection and closed #165; runs `30640903741` and `30645532130` passed | Static inspection cannot prove every runtime layer. #160 remains a bounded correctness follow-up, not authorization for live mutation. The two Doctor matrices are bounded measurements, not a longitudinal precision series. |
| Estate seed/sync/closeout operations | implemented, experimental | `seed`, `audit`, `doctor`, and backed-up `sync-global` are on `main`; PR #162 added guarded worktree closeout and PR #169 repaired confirmed late-review preservation defects; exact-head runs `30629391405` and `30634860134` passed all nine jobs | The lease is cooperative, not process authentication. #167/#168/#170/#171/#172 are bounded correctness, reporting, false-keep, and performance follow-ups. No live estate cleanup was run. |
| Pattern Guard v2 | unverified | AH-3 contract in the brief; measured inputs #21, #118, #120 | No Pattern Guard v2 implementation or shadow result exists. Start with bounded catastrophic families, not the legacy universal parser. |
| Integrated measurement | benchmarked, unverified | Historical and bounded correctness/CI measurements in `docs/BENCHMARKS.md` | No current 1.6.21 estate baseline, continuous benchmark store, Doctor precision series, or task-completion metric is verified. |
| Claude-config integration | experimental, unverified | `CLAUDE_CONFIG_OPERATIONS.md`; AH-9 boundary | Private evidence stays private. No broad cross-repository mutation is active. |
| Public extraction and plugin products | frozen | `REPLAY_TOOL_PRODUCT.md` and `BLUEPRINT_PLUGIN_PRODUCT.md` are explicitly deferred under AH-10 | Do not create a public replay repository or extract a plugin until internal stability and demand are demonstrated and approved. |

## Canonical homes and stale evidence

- Mission: `AGENT_HARNESS_AGENT_BRIEF.md`.
- Current state: this file.
- Roadmap and issue ownership: `ROADMAP.md`.
- Active work: `plans/ACTIVE.md`.
- Measurements: `docs/BENCHMARKS.md`.
- Legacy limitations: `FLOOR_LIMITATIONS.md`.
- Human-only action: `HUMAN_TODO.md`; H-2 remains open and owner-parked.
- Root `HANDOFF.md` is a historical pre-pivot record. It is **stale** as current status and is
  preserved rather than rewritten; dated continuation records live under `handoffs/`.

## Refresh commands

```powershell
git fetch origin --prune
git rev-parse origin/main
git show-ref -d refs/tags/floor-v1-final
py -3 harness.py doctor
py -3 harness.py audit . --offline
gh pr list --repo Chris0Jeky/agent-harness --state open
gh issue list --repo Chris0Jeky/agent-harness --state open --limit 200
```
