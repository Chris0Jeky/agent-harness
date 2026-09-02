# System state

> **Licence decision (2026-08-12):** Owner-authored repository content is now
> `GPL-3.0-only`, with the curl-derived fixture retained under curl's licence.
> See `LICENSE`, `LICENSING.md`, and `THIRD_PARTY_NOTICES.md`. This does not
> decide the licences of possible future extracted plugin or replay products.

Snapshot: 2026-09-02, published `main@d6392dd7959cd887bd83551bf43ddd53b96e97bf` (PR #260's merge `d6392dd`).
Refresh Git, GitHub, deployed bytes, and live runtime evidence before relying on this snapshot.

**`templates/hooks/dispatch.py` moved four versions on 2026-09-02**, all through the PR lane with
nine green checks and an independent adversarial review each: PR #257 upstreamed **1.6.29** (the
owner's 2026-08-18 claude-config decisions 1.6.28/1.6.29, which had been authored in the consumer
and left canonical trailing the deployed bytes — closed #59); PR #239 landed #201 as **1.6.30**
(Git numeric booleans in the exact `--no-follow-tags` narrowing; #243 carries the two
toolchain-dependent edges); PR #260 landed **1.6.31**, the owner's guide posture and the
`FLOOR_ACK` double-check (SPECS §5.4; closes #26, #62, #259) plus the hardening of the 1.6.29
carve-outs its reviews found. PR #238 landed #139's nested logical repo root in `harness.py` with
its three review defects fixed (#258 tracks one LOW follow-up). The 2026-08-07/08 wave before it
(PR #234, #237, #240) was documentation and tests only.

One commit on `main` from this period did NOT arrive through the PR lane: `3ade22b`, which adds only
`/.claude/worktrees` to `.gitignore`, was pushed directly by the worktree-isolation machinery. That
direct push is what #236 tracks. PR #230's merge `7316241` and every merge above went through the
normal lane.

## Runtime state: 2026-09-02

Canonical source is **1.6.32** (PR #262 on #260's 1.6.31); the producer marker moved with each of
1.6.29, 1.6.30, 1.6.31 and 1.6.32. Deployed bytes: claude-config `hooks/` (PR #196, byte-identical,
its smoke 2361/2361) and the owner's `~/.claude/hooks` (hooks-only install with backup, digest
`9bdb630e…` == canonical) are **1.6.32**. Runtime proof: the **Claude** canary trio passed live on
2026-09-02 in the deploying session (SPECS §5.4: `rm -rf` outside the project denied once with a
key and allowed when acknowledged; a dynamic redirect target allowed). The **Codex** exact-CWD
`/hooks` re-trust and canaries are still owed — **H-15** in `HUMAN_TODO.md`. Nothing below is
inferred from source merges.

### Runtime state as recorded on 2026-08-07

The owner explicitly lifted the 2026-08-02 PreTool pause and authorized rollout. PR #230 merged
canonical source 1.6.27 and changed the agent-harness producer marker. Claude-config PR #127 merged
the byte-identical consumer as `6aac87507c5afbb35da39f38628b880feb38921a`; both authoring and
deployed checkouts are clean at that merge, the explicit `sync-global` dry run/apply were
identity-only, and Doctor proves canonical == deployed 1.6.27 from clean published mains. Global
Claude proof and the prior producer/three-consumer Codex canaries remain at 1.6.26 and are historical
for the changed marker.

The remaining 1.6.27 proof is human-only and strictly ordered per SPECS §5: the agent-harness
**producer** exact-CWD re-trust and both canary legs first, then fresh global Claude proof, and only
then any consumer marker refresh. The three consumer marker PRs (EvidenceDeck #21,
collaborative-hill-lab #5, SwarmingLilMen #52) were closed unmerged at that gate with their branches
preserved. Issue #232 is the durable tracker; `plans/ACTIVE.md` carries the exact resume sequence.
No agent may reorder those steps or infer any of them from static deployment or from Doctor.

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
| Legacy deny-floor source | implemented, frozen; guide posture since 1.6.31 | PR #262 merged `c34c74c`; canonical `templates/hooks/dispatch.py` reports 1.6.32 with normalized digest `9bdb630e77f55882373d38f9b9a0efc10ceae1c820a1adf16cef6ce89dc181f2`; 1.6.31 (PR #260, `d6392dd`), 1.6.29 (PR #257) and 1.6.30 (PR #239) precede it; the 1.6.27 valueless `push.followTags` repair and the 1.6.24 #184/#196 repairs remain; immutable `floor-v1-final` object `5a939540bdce51e511d6b3bae98358e3e2ad9148` still peels to the preserved 1.6.21 commit `02bd14cfe094f9b6af85b966de481ff3f45264cf` | The exception keeps `sensitive_data` active and grants only one exact public-synthetic remote/repository route with one explicit refspec, no configured `core.gitProxy`/`core.sshCommand` or declared-remote `receivepack`/`vcs`, and no command-line `--receive-pack`/`--exec`; it does not inspect Git content. The feature freeze resumes after this contract. 1.6.32 is deployed and Claude-proven; the Codex half of its rollout (H-15) is the only open step, and none of it is inferred from source merge. |
| Shared Claude-hook floor | deployed at 1.6.32; Claude runtime-proven at 1.6.32 (live trio 2026-09-02); Codex runtime-proven at 1.6.26 | claude-config PR #196 merged the byte-identical 1.6.32 `hooks/` (its smoke 2361/2361); the hooks-only install into `~/.claude/hooks` kept a backup (`.harness-backups/20260902T182855Z`) and the deployed digest `9bdb630e…` equals canonical; the Claude canary trio passed live on 2026-09-02. The owner's consumer-side 1.6.28/1.6.29 (`4078905`/`3c6069e`, upstreamed by PR #257) and the following are historical: claude-config PR #127 merged the byte-identical 1.6.27 consumer as `6aac87507c5afbb35da39f38628b880feb38921a`; both clean `main` checkouts reached that merge, supported `sync-global` dry-run/apply were identity-only, and Doctor proves canonical == deployed with normalized digest `1cc8fb92090d972ae6daab01cf526301eb9ec24b9d1ccfaa24d655c7d403f343`. | Static deployment and the Claude runtime proof are complete at 1.6.32; the Codex exact-CWD re-trust and canaries (H-15) are not inferred from either. |
| Replay v0 / Policy Lab | implemented, benchmarked, experimental | PR #140 merged the core; PRs #159/#163 closed report and manifest defects; PRs #174/#176 closed #152/#156; PR #187 aligned surrogate schema/runtime behavior and closed #177; runs `30639136818`, `30642286808`, and `30660359254` passed | Internal evidence tool only. It is not a sandbox, global blocker, public repository, or universal policy language. Supported-engine proof used `jsonschema` 4.26.0 independently; the checked-in contract remains dependency-free. |
| Audit and Doctor foundation | implemented, benchmarked, experimental | `harness.py audit` and `doctor`; PR #161 added static MCP topology diagnosis and closed #87; PRs #175/#178 closed shared-source identity and Docker command-position defects #164/#165; PR #204 closed #89 with static Windows Git command-fidelity diagnosis; PR #205 closed #189 with diagnosis-only static Claude-hook topology reporting; PR #212 closed #98 by requiring a clean published claude-config source before byte comparison (run `30731418878`, nine jobs passed); PR #219 closed #160 with selected disabled mixed-transport precedence (run `30759942880`, nine jobs passed). After PR #127 deployment Doctor reported canonical/deployed 1.6.27; since 2026-09-02 canonical and deployed are 1.6.32 (marker `9bdb630e…`). | Static inspection still cannot prove runtime trust; exact-CWD `/hooks` and canaries supply that separate evidence, and the three consumer markers remain on 1.6.26 until their own reviewed changes. |
| Codex trust and linked-worktree guidance | implemented; 1.6.26 inventory proven | PRs #208/#209 establish the exact-CWD/root-checkout contracts. Agent-harness plus EvidenceDeck (`5be9d1d`), SwarmingLilMen (`56cff63`), and collaborative-hill-lab (`7565572`) each received an individual normal-TUI review/trust/enable sequence and fresh 1.6.26 allow/deny canaries. | H-2 remains closed for that dated inventory. The changed 1.6.27 producer marker and later consumer-marker changes inherit none of its proof and require the active exact-root rollout. |
| Estate seed/sync/closeout operations | implemented, benchmarked, experimental | `seed`, `audit`, `doctor`, and backed-up `sync-global` are on `main`; PRs #162/#169/#180 established fail-closed closeout; PR #183 batched recovery reachability and closed #171; PR #194 made fingerprint expiry suspend-aware and closed #167; PR #197 retained direct non-commit `ORIG_HEAD` identity and closed #172; PR #198 skipped synthetic native-Windows executable-mode deltas while retaining POSIX mode-only drift and closed #170; PR #206 published the tailored new-repo contract and closed #131; runs `30655263274`, `30665083220`, `30670171402`, `30704657392`, and `30717285862` passed | The lease is cooperative, not process authentication. #188 awaits an owner-reviewed consumer manifest; #190 awaits a real generated launcher call site; #191/#192 remain queued. The bounded H-2 consumer rollout is complete; no unrelated estate cleanup ran. |
| Pattern Guard v2 | implemented, unverified | PR #193 is a bounded AH-3 security-preservation exception; PR #200 closed #196 with five retained narrowing cases, and PR #202 restored fail-closed behavior for the unprovable sixth case; measured design inputs remain #21/#118/#120 | No general Pattern Guard v2 or shadow result exists. #201 is bounded fail-closed usability follow-up evidence, not authorization for universal-parser expansion. |
| Integrated measurement | benchmarked, unverified; gate coverage now pinned | Historical and bounded correctness/CI measurements B-001 through B-014 in `docs/BENCHMARKS.md`. PR #240 closed #110: `_composable()` detects executable separators outside inert quoted spans instead of by raw substring, so the SPECS §6 flagship must-allow class is measured rather than dropped (`SMOKE_BENIGN_CORPUS` 416 → 459; swept `(case, shape)` pairs 107,699 → 111,342), and `CHARTER_RULE_DENY_PAIRS` pins 569 exact `(probe, shape)` pairs across 8 postures in place of nine aggregate integer floors | No current 1.6.27 estate baseline, continuous benchmark store, Doctor precision series, or task-completion metric is verified. The gate now measures 69 pre-existing over-blocks it previously could not see (#235); those are recorded, not fixed, and their `cmd-c` subset needs per-row dialect adjudication before it can support any #21 relaxation. |
| Claude-config integration | experimental, unverified | `CLAUDE_CONFIG_OPERATIONS.md`; AH-9 boundary; claude-config `hooks/dispatch.py` is at 1.6.32 (PR #196) | Private evidence stays private. The Codex half of the 1.6.32 rollout (H-15) is outstanding. |
| Public extraction and plugin products | frozen | `REPLAY_TOOL_PRODUCT.md` and `BLUEPRINT_PLUGIN_PRODUCT.md` are explicitly deferred under AH-10 | Do not create a public replay repository or extract a plugin until internal stability and demand are demonstrated and approved. |

## Canonical homes and stale evidence

- Mission: `AGENT_HARNESS_AGENT_BRIEF.md`.
- Current state: this file.
- Roadmap and issue ownership: `ROADMAP.md`.
- Active work: `plans/ACTIVE.md`.
- Measurements: `docs/BENCHMARKS.md`.
- Legacy limitations: `FLOOR_LIMITATIONS.md`.
- Human-action record: `HUMAN_TODO.md`; no H-2 action remains at this snapshot.
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
