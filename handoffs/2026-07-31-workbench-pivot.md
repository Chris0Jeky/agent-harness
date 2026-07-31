# Handoff: workbench pivot continuity — 2026-07-31

Refresh refs, PRs, issues, checks, reviews, comments, threads, worktrees, and tier declarations
before acting. This is a factual checkpoint, not authority to reuse stale gate evidence. Root
`HANDOFF.md` is historical pre-pivot context and was intentionally not rewritten.

## Objective and invariants

- Operate `agent-harness` as the agent-operations workbench: frozen legacy floor, internal Policy
  Lab, Doctor, estate operations, bounded Pattern Guard v2, measurement, adapters, and private
  integration through small executable slices.
- Authority at this snapshot is T3 with `push: free` and `merge: free`. Preserve commits with merge
  commits; never squash, use admin/auto merge, or delete a PR branch during merge.
- Every changed head or base gets scoped proof, three-minute aging, one bounded review pipeline,
  green required CI, and one final snapshot of reviews, threads, inline comments, and conversation
  comments. Do not post routine `@codex review`.
- Keep at most two active workstreams and one writer per checkout. Never race an occupied checkout.
- Do not expand the universal parser, activate global blocking, start blueprint-plugin extraction,
  or create a public replay repository.
- H-2 is the only open `HUMAN_TODO.md` item and is owner-parked. Do not restart estate-wide
  canaries or disable the harness.

## Exact published checkpoint

- `origin/main` was `b2c2fd40a1e3d99821983b6ad38a1fecd1d22809`, the merge commit for PR #193.
- PR #194 preserved head `5b5cfbfc6179ac577e157b6c520c2ebaf6258608` as its second parent;
  `origin/main` contains that head; #167 is closed; run `30665083220` passed all nine jobs; the
  one-time post-merge comments/reviews/threads refresh found no late feedback.
- The protected `floor-v1-final` tag remains object
  `5a939540bdce51e511d6b3bae98358e3e2ad9148`, peeled commit
  `02bd14cfe094f9b6af85b966de481ff3f45264cf`.
- GitHub had 69 open issues and one open PR (#195). `ROADMAP.md` maps every open issue exactly once.
  Refresh both counts before selecting work.
- Canonical state: `docs/SYSTEM_STATE.md`; issue/PR ownership: `ROADMAP.md`; active work:
  `plans/ACTIVE.md`; measurements: `docs/BENCHMARKS.md`; legacy limitations:
  `FLOOR_LIMITATIONS.md`; human action: `HUMAN_TODO.md`.

## Completed and directly verified

- PR #140 merged deterministic replay v0 as `81125c57ec6d1a750ddd43b0110c6928f9f4a860`;
  `origin/main` contains `fd87e06c1c55ceed5cef3c736710b513317f3c89`; #148/#149 closed; all
  original threads were resolved. Replay remains internal/experimental.
- PRs #159/#161/#163/#162/#169 merged bounded replay, Doctor, and guarded-closeout foundations;
  #153/#87/#144/#151/#166 closed. PRs #173–#180 then published continuity and closed
  #152/#164/#156/#165/#168. Their exact commits, runs, limitations, and measurements remain in Git,
  prior PR records, and `docs/BENCHMARKS.md`.
- PR #181 merged the prior continuity checkpoint as
  `914b2d4f9547a9f8efe64b0f5a65c6f2df510552`, preserving head
  `a39cb3b7510a5cec499ba5d2fa2d05ab205a8810`; run `30650615847` passed.
- PR #182 changed only the aggregate Verify timeout from 15 to 20 minutes, merged as
  `c625e4b3d98114da67db70ffe435dc9f909d100f`, preserved head
  `94c28e52c2d9cb1ba690ed3df719ea9f13b1177e`, passed run `30652837868`, and closed #179.
  The 24-job Windows cohort measured median 11m18.5s, p95 12m34s, maximum 13m01s.
- PR #183 replaced up to five reachability subprocesses with one stdin-fed `rev-list`, merged as
  `7786386931cfbb204221832b102ed8bb1db8381a`, preserved head
  `4c9389cab998c2a428eac5aa2783d1fbd2bd2016`, passed run `30655263274`, and closed #171.
  Nine paired disposable runs preserved verdicts and measured a 4.99× median improvement.
- PR #187 aligned PolicyDecision surrogate schema/runtime behavior, merged as
  `9deb1eba9c70b8cf42dcc253e4ca6afa6be8853a`, preserved head
  `35bacdb3799c2b506e9b22d8cc36f4ba4421fa01`, passed run `30660359254`, and closed #177.
  Independent Draft 2020-12 `jsonschema` 4.26.0 proof matched 14/14 cases; the checked-in test remains
  dependency-free, so engine portability is explicit rather than claimed.
- PR #194 made closeout fingerprint expiry suspend-aware, detected and latched backwards UTC movement,
  stopped later removals on any fingerprint invalidity, and sampled before/after final lease
  inspection. It merged as `a6a1c847392899ad0e6d0709c44ea2aa67760979`, with parents `9deb1eb`
  and `5b5cfbf`; #167 closed. Exact-head local proof passed 855 tests with 13 declared skips,
  47 closeout tests with one expected NTFS skip, and 2237/2237 smoke cases. No live apply ran.
- PR #193 merged the four owner-authorized #184 public-push security repairs as
  `b2c2fd40a1e3d99821983b6ad38a1fecd1d22809`, with parents `a6a1c84` and `8648e5c`, preserving
  both topic commits. Run `30666338126` passed all nine jobs; the first HIGH was fixed once and the
  exact-head fix-diff review found no remaining CRITICAL/HIGH issue. Five pre-merge connector
  findings and one late post-merge P2 were classified as fail-closed usability defects, recorded in
  #196, replied to, and resolved once. #184 then closed manually with exact producer proof because
  the PR had no closing reference.
- PRs #154/#155 were closed unmerged after exact inventory proved them stale/conflicting and
  superseded. Their remote branches and historical threads were preserved; no branch was deleted.

## Reproduced but owner-blocked

- Issue #160 validly reproduces when TOML string values are quoted: a layered server with effective
  `enabled = false` still raises the redacted mixed-transport error. Existing tests do not define
  precedence. No code, configuration, Docker, or runtime state was changed.
- Recommended bounded rule: effective disablement suppresses only a cross-layer transport conflict;
  same-table `command` plus `url` stays structurally invalid, and a later re-enable exposes the
  retained conflict. The owner must choose the policy before implementation.
- Evidence comment: https://github.com/Chris0Jeky/agent-harness/issues/160#issuecomment-5146563160

## PR #193 post-merge boundary

- Canonical floor source is now 1.6.22, but deployed global Claude bytes remain measured 1.6.21.
  No live install, trust/config mutation, or consumer sync was authorized or performed.
- Issue #196 owns the six fail-closed usability findings: branch-name ambiguity, submodule topology,
  empty boolean, subdirectory common-dir resolution, tracking alias, and explicit
  `--no-follow-tags` precedence. Do not reopen #193 or expand #196 into universal-parser work.
- The registered `.worktrees/issue184-push-narrowing` checkout remains owned by its coordinator
  until that coordinator inspects ignored content and removes it with plain `git worktree remove`.

## Occupied state to preserve

- Primary checkout was tracked-clean and fast-forwarded to `main@b2c2fd4`; ignored IDE/test/worktree
  caches remain.
- `crossproduct-gate`: tracked-clean historical branch; remote is gone; ignored caches remain.
- `issue27-temporal-config`: tracked-clean occupied historical floor branch; ignored caches remain.
- `replay-tool`: user-owned staged `scripts/replay_corpus.py`; never reset, restore, stash, or remove.
- `replay-v0-freeze`: ignored `.local/` evidence/recovery plus caches; never remove without separately
  proving and copying everything that must survive.
- `continuity-20260731`: sole writer for the five continuity documents until its PR merges.
- Empty, unregistered `.worktrees/replay-platform-reproduction-20260731` remains externally locked;
  leave it alone unless separately proving it safe to remove.
- `C:\Users\Public\codex-shell-home\pr183-review-probe` and `pr183-review-probe-sha256` each retain
  only a disposable `.git` directory after the floor refused agent cleanup. They are not evidence
  inputs; do not bypass the floor to remove them.

## Exact next safe slice — #172

Start only after this continuity PR has merged or parked, then use a fresh detached
`origin/main` worktree and branch. The slice is additive AH-6 evidence, not estate mutation.

- **Observable outcome:** guarded closeout retains a worktree whose direct `ORIG_HEAD` target is an
  annotated-tag or blob object and reports its exact OID/type rather than treating it as absent.
- **Evidence:** #172 records independent PR #169 reproduction; current commit-peeling loses tag
  identity and treats a blob target as missing, while `git fsck` shows those objects may already be
  unreachable before removal.
- **In:** direct OID/type probe, one fingerprinted evidence field, fail-closed keep verdict,
  annotated-tag/blob disposable fixtures, and preservation after synthetic apply.
- **Out:** ordinary commit reachability, reflog parsing, garbage collection, ref pruning, force
  removal, or live estate cleanup.
- **Architecture seam:** `harness.py` guarded worktree recovery evidence and schema-v3 fingerprint.
- **Tests/fixtures:** disposable linked worktrees with direct tag/blob `ORIG_HEAD`; assert audit
  evidence, keep verdict, revalidation, and post-apply identity.
- **Measurement:** correctness matrix only; record case counts and subprocess cost if measured, but
  do not infer estate prevalence.
- **Limitation:** these require deliberate noncanonical mutation and may point to objects already
  outside ordinary Git reachability.
- **Exact verification:** `py -3 -m unittest tests.test_harness.WorktreeCloseoutTests -v`, followed by
  full unit, smoke, audit, Doctor, formatting, hosted CI, aging, and bounded review gates.
- **Next handoff:** one PR closing only #172, with merge-commit preservation and no live apply.

Issue #170 remains useful but additionally requires a real mode-capable POSIX/WSL positive control.
Issues #185/#186/#188–#192/#196 are mapped follow-ups, not workbench-wide priorities.

## Refresh commands

```powershell
git fetch origin --prune
git rev-parse origin/main
git show-ref -d refs/tags/floor-v1-final
gh pr list --repo Chris0Jeky/agent-harness --state open --limit 100
gh issue list --repo Chris0Jeky/agent-harness --state open --limit 200
py -3 -B harness.py audit . --offline
py -3 -B harness.py doctor --repo . --offline
git diff --check origin/main...HEAD
```
