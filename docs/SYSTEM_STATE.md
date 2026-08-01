# System state

Snapshot: 2026-08-01, implementation state through `main@e6d0558200d006de0b86630a1d31bb4ce8f06244`.
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
| Repository mission and authority | implemented | `AGENT_HARNESS_AGENT_BRIEF.md`; `.agent-harness/tier.json` declares T3, push free, merge free; PR #182 raised the unchanged aggregate Verify budget from 15 to 20 minutes and closed #179 | Authority can change; re-read every co-located tier declaration before mutation. #185 remains mapped; #186 is owned by the canonical `review-and-ship` skill in `claude-config`, not a harness runtime collector. |
| Legacy deny-floor source | implemented, frozen | Canonical `templates/hooks/dispatch.py` reports 1.6.24 with normalized digest `27562acc83a9544a1f440bdd202528837f8c70af18e4208625dd0755ab8cd8dd` after PR #200's bounded #196 usability repair and PR #202's fail-closed late-review correction; #184/#196 are closed; immutable `floor-v1-final` object `5a939540bdce51e511d6b3bae98358e3e2ad9148` still peels to the preserved 1.6.21 commit `02bd14cfe094f9b6af85b966de481ff3f45264cf` | No universal-parser expansion. #201 tracks the remaining bounded numeric-boolean edge. Further floor work still requires freeze-compliant authority and direct evidence. |
| Shared Claude-hook floor | deployed, stale, unverified | On 2026-08-01 deployed `~/.claude/hooks/dispatch.py` remained 1.6.21 with LF-normalized digest `EA4FB45DC71A44E80392E7EA423BC70DCB604538E956CB13CF34B750118974B5` and raw CRLF digest `E1A4E7714913788DD801F0FA43A3E5B30EA0433709F97142509B56B1C442EF68`; canonical source is now 1.6.24 | Doctor therefore remains expected-red on shared dispatcher/floor version. PRs #184/#196/#202 did not authorize deployment or trust mutation; static byte identity, if later restored, still would not prove Codex activation/trust. H-2 is owner-parked. |
| Replay v0 / Policy Lab | implemented, benchmarked, experimental | PR #140 merged the core; PRs #159/#163 closed report and manifest defects; PRs #174/#176 closed #152/#156; PR #187 aligned surrogate schema/runtime behavior and closed #177; runs `30639136818`, `30642286808`, and `30660359254` passed | Internal evidence tool only. It is not a sandbox, global blocker, public repository, or universal policy language. Supported-engine proof used `jsonschema` 4.26.0 independently; the checked-in contract remains dependency-free. |
| Audit and Doctor foundation | implemented, benchmarked, experimental, unverified | `harness.py audit` and `doctor`; PR #161 added static MCP topology diagnosis and closed #87; PRs #175/#178 closed shared-source and Docker command-position defects #164/#165; PR #204 closed #89 with static Windows Git command-fidelity diagnosis; PR #205 closed #189 with diagnosis-only static Claude-hook topology reporting; runs `30640903741`, `30645532130`, `30714604384`, and `30718502986` passed | Static inspection cannot prove every runtime layer. #160 is reproduced but owner-blocked on precedence policy. No Docker, hook removal, deployment, config, trust, live canary, or runtime mutation was made. |
| Estate seed/sync/closeout operations | implemented, benchmarked, experimental | `seed`, `audit`, `doctor`, and backed-up `sync-global` are on `main`; PRs #162/#169/#180 established fail-closed closeout; PR #183 batched recovery reachability and closed #171; PR #194 made fingerprint expiry suspend-aware and closed #167; PR #197 retained direct non-commit `ORIG_HEAD` identity and closed #172; PR #198 skipped synthetic native-Windows executable-mode deltas while retaining POSIX mode-only drift and closed #170; PR #206 published the tailored new-repo contract and closed #131; runs `30655263274`, `30665083220`, `30670171402`, `30704657392`, and `30717285862` passed | The lease is cooperative, not process authentication. #188 awaits an owner-reviewed consumer manifest; #190 awaits a real generated launcher call site; #191/#192 remain queued. No live estate cleanup, consumer rollout, or branch deletion was run. |
| Pattern Guard v2 | implemented, unverified | PR #193 is a bounded AH-3 security-preservation exception; PR #200 closed #196 with five retained narrowing cases, and PR #202 restored fail-closed behavior for the unprovable sixth case; measured design inputs remain #21/#118/#120 | No general Pattern Guard v2 or shadow result exists. #201 is bounded fail-closed usability follow-up evidence, not authorization for universal-parser expansion. |
| Integrated measurement | benchmarked, unverified | Historical and bounded correctness/CI measurements B-001 through B-014 in `docs/BENCHMARKS.md` | No current 1.6.24 estate baseline, continuous benchmark store, Doctor precision series, or task-completion metric is verified. |
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
