# Active workstreams

## Floor and replay repairs — 2026-10-30

| Work | Source scope and remaining boundary |
|---|---|
| [#589](https://github.com/Chris0Jeky/agent-harness/pull/589) | Process identity v12 binds the name, bytes and mode of each library copied beside the executable, and snapshot checks cover the whole executable directory. `sha256_file` refuses non-regular files. Closes [#524](https://github.com/Chris0Jeky/agent-harness/issues/524). Native loader behaviour for a real adjacent library is not separately proven. |
| [#590](https://github.com/Chris0Jeky/agent-harness/pull/590) | Floor source 1.8.2: the public-synthetic route refuses every force spelling ([#467](https://github.com/Chris0Jeky/agent-harness/issues/467)), and mirror config reads through the floor's git-accurate boolean parser ([#468](https://github.com/Chris0Jeky/agent-harness/issues/468) items 3 and 4). Source only: installed floors, consumer markers, trust and canaries are unchanged, and H-22 still gates deployment. |

Both floor repairs are charter regressions as literally written, so the freeze stands.
#468's other items and [#491](https://github.com/Chris0Jeky/agent-harness/issues/491) are
documented limitations in [FLOOR_LIMITATIONS](../FLOOR_LIMITATIONS.md). No thaw is proposed:
any repair would stay undeployed behind H-22.
[#513](https://github.com/Chris0Jeky/agent-harness/issues/513) stays parked: a minimum share of
recall-testing cases is a promotion-policy threshold, and
[LEARNING_EVAL_SAFETY](../docs/LEARNING_EVAL_SAFETY.md) records that a repair does not invent one.

## Source maintenance checkpoint — 2026-10-29

Baseline inspected: [`main@471ff6c`](https://github.com/Chris0Jeky/agent-harness/commit/471ff6c92457986b30da1091eea8e4e67613896a).
The source PRs below have independent reviews with no confirmed findings. Their linked heads,
checks, follow-up fixes and merge receipts own current completion status.
This record claims no installation, trust change, live canary or consumer adoption.

| Work | Source scope and remaining boundary |
|---|---|
| [#579](https://github.com/Chris0Jeky/agent-harness/pull/579) | Observational canary comparisons and corrected outcome weighting. Trusted assignment/execution evidence remains [#520](https://github.com/Chris0Jeky/agent-harness/issues/520); ingestion and event identity remain [#511](https://github.com/Chris0Jeky/agent-harness/issues/511). |
| [#580](https://github.com/Chris0Jeky/agent-harness/pull/580) | Actionable bundle recovery maps and native lookup of absent path names; carries closure of [#278](https://github.com/Chris0Jeky/agent-harness/issues/278). Native bind-mount proof passed in #587. |
| [#581](https://github.com/Chris0Jeky/agent-harness/pull/581) | Replay cleanup, isolated startup and bounded regex worker evidence; carries closure of [#578](https://github.com/Chris0Jeky/agent-harness/issues/578) and [#576](https://github.com/Chris0Jeky/agent-harness/issues/576). Native platform checks own the remaining proof. |
| [#582](https://github.com/Chris0Jeky/agent-harness/pull/582) | Portable smoke and Doctor test fixtures. Local root suite passes: 2,114 tests, 68 skips; native CI owns platform proof. |
| [#583](https://github.com/Chris0Jeky/agent-harness/pull/583) | Interactive recorded replay lab and visual docs entry point. Python/JavaScript tests, Pages deployment and desktop/mobile browser checks passed; see its deployed verification receipt. |
| [#584](https://github.com/Chris0Jeky/agent-harness/pull/584) | Platform/quote-aware Doctor anchors and one shared canonical-reference probe; carries closure of [#78](https://github.com/Chris0Jeky/agent-harness/issues/78), including its wrapper-variable follow-up. |
| [#587](https://github.com/Chris0Jeky/agent-harness/pull/587) | Real private bind-mount qualification: seven native CI tests passed with zero skips. Carries closure of [#523](https://github.com/Chris0Jeky/agent-harness/issues/523); full exact-head CI and merge receipts remain the acceptance gate. |

#580's Windows CI exposed test assumptions about collision wording and CRLF fixture bytes.
Its correction retains refusal and byte-preservation checks; follow the PR for the resulting head.

The dispatcher remains frozen under [BLUEPRINT](../BLUEPRINT.md).
Remaining source defects and parked consumer contracts are
mapped in [ROADMAP](../ROADMAP.md); [SYSTEM_STATE](../docs/SYSTEM_STATE.md) records proof limits.

## Backlog reconciliation

[#565](https://github.com/Chris0Jeky/agent-harness/pull/565) closed advisory-ledger JSON parsing
(#558) and programmatic string-key validation (#563); [#566](https://github.com/Chris0Jeky/agent-harness/pull/566)
closed repeated preflight tree walks (#556). These are shipped source repairs.

[#191](https://github.com/Chris0Jeky/agent-harness/issues/191) now records that
[Taskdeck #1551](https://github.com/Chris0Jeky/Taskdeck/pull/1551) merged. Separating its portable
create/initialize contract remains work. [#201](https://github.com/Chris0Jeky/agent-harness/issues/201)
stays open: its portable numeric core shipped in #239, while #243 retains the toolchain-dependent
fail-closed cases. No new deployment follows from either reconciliation.

## Human gates

[HUMAN_TODO](../HUMAN_TODO.md) owns the exact steps and close conditions:

- **H-18:** private-repository Actions billing; prove a private-repository run starts.
- **H-19:** charter-replay's PyPI trusted publisher and successful package installation.
- **H-22:** per-root adapter proof, fresh-session review, individual trust, enabled state and
  canaries. The extract-api prerequisite and other-workstation steps remain explicit there.

## Owner decisions in force

- **Merge gate:** exact-head green proving checks, global law 2 review, the three-minute aging
  floor and merge commits only. No squash. Source acceptance does not establish runtime state.
- **Extraction:** the 2026-09-29 decision approved the public `charter-replay` repository,
  Apache-2.0 and demo GIF. The 2026-10-04 decision made the extraction manifest path-pinned.
  [REPLAY_TOOL_PRODUCT](../REPLAY_TOOL_PRODUCT.md) owns the product scope; blueprint-plugin
  extraction stays deferred. Record a source-direction decision before the two trees diverge.
- **Repository licence:** owner-authored content is GPL-3.0-only; the curl-derived fixture keeps
  its own licence. See [LICENSING](../LICENSING.md). The replay product decision is separate.

Earlier source, rollout and runtime observations are preserved in the
[dated archive](../docs/archive/status-2026-10.md). Its open/closed and deployed/proven labels
apply only to their historical checkpoints.
