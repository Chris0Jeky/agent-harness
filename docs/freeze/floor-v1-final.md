# Legacy deny-floor v1 freeze record

Status: **FROZEN — owner approved; annotated tag created and pushed**

Recorded: 2026-07-30

Immutable tag: `floor-v1-final`

## Frozen candidate

| Field | Recorded value |
|---|---|
| Freeze commit | `02bd14cfe094f9b6af85b966de481ff3f45264cf` |
| Annotated tag object | `5a939540bdce51e511d6b3bae98358e3e2ad9148` |
| Reviewed implementation head | `d5e93631a6bd76f9c313719608892f5ed1747205` |
| Merge provenance | [PR #132](https://github.com/Chris0Jeky/agent-harness/pull/132), merged by repository owner Cristian Tcaci on 2026-07-27 |
| Floor version | `1.6.21 (2026-07-27)` |
| Dispatcher | `templates/hooks/dispatch.py` |
| Dispatcher Git blob | `1dc7aff3724213b99ed055c0c4ddad2294e3d851` |
| Dispatcher line count | 11,753 |
| Canonical smoke matrix | `templates/hooks/smoke_test.py` |
| Unit suite | `tests/` |
| Known-limitation ledger | `FLOOR_LIMITATIONS.md` |
| Freeze decision records | GitHub issues [#92](https://github.com/Chris0Jeky/agent-harness/issues/92) and [#96](https://github.com/Chris0Jeky/agent-harness/issues/96) |

`02bd14c` is the last merge on `main` that changed the legacy dispatcher. The later
`8f468231cb02632b2f2062e501ce7ccdd708675c` commit added only
`AGENT_HARNESS_OPERATIONS.md`; a path-scoped Git diff confirms no change to the dispatcher,
smoke matrix, harness, tests, or replay script. The tag therefore points to the reviewed legacy
implementation merge, not to the later operations-only commit.

The owner approved the tag name and target on 2026-07-30. The annotated tag was created with
message `Freeze legacy deny floor v1 at 1.6.21`, pushed to `origin`, and verified by its remote tag
object. It is operationally immutable and must never be moved, replaced, or deleted.

## Preservation evidence

Evidence was refreshed on 2026-07-30 in an isolated worktree based on published `origin/main`.
The implementation paths at that head are byte-identical Git blobs to the proposed freeze
candidate.

| Check | Result |
|---|---|
| `py -3 -m unittest discover -s tests -v` | PASS — 800 tests in 128.315 s; 12 expected Windows skips |
| `py -3 templates/hooks/smoke_test.py` | PASS — 2237/2237 in 256.8 s |
| `py -3 harness.py doctor` from clean canonical `main` | PASS — canonical and deployed floor both 1.6.21; checkout level with published `origin/main` |
| PR #132 exact-head CI | PASS — Ubuntu, Windows, and macOS on `d5e9363`; [run 30308409884](https://github.com/Chris0Jeky/agent-harness/actions/runs/30308409884) |
| `git diff --check` | PASS |

The first local unit attempt hit a 124-second command timeout and produced no verdict. The same
command passed when rerun with the repository CI timeout. This was runner timeout noise, not a
test failure.

## Environment assumptions

- The dispatcher is dependency-free Python. Hosted preservation CI uses Python 3.11 on Windows,
  macOS, and Linux; the refreshed local evidence used CPython 3.14.3 on Windows with Git
  2.45.1.windows.1.
- The floor is an argv tripwire, not a shell or filesystem sandbox. It can judge only command
  text and the bounded repository/remote probes exposed to it.
- Claude and Codex have explicit runtime response formats. Codex activation additionally depends
  on a reviewed, hash-pinned project adapter, fresh `/hooks` trust in the exact CWD, and live
  allow/deny canaries. Static doctor output is not runtime interception proof.
- Remote visibility and repository-state checks can become `UNPROVEN` when their executable,
  network, deadline, config, or worktree topology cannot be resolved. The floor must not be
  represented as exhaustive containment.
- The legacy replay instrument is private-machine tooling. It scans real agent transcripts and
  can write raw command text to scratch JSON/cache outputs; it is not an extraction source for
  public v0.

## Known false-negative families

The full frozen ledger is `FLOOR_LIMITATIONS.md`. Its principal families are:

- mutation surfaces outside inspected shell argv, inherited environment, and repository state;
- unmodelled wrappers, launchers, inline interpreters, container/remote execution, stdin, and
  script-file laundering;
- quote-masked PowerShell expressions, redirection/prefix desynchronisation, and other bounded
  shell-shape gaps; and
- raw writes to Git config/hooks plus object-provenance and worktree-state gaps.

PR #132 also retains **11 unresolved automatic-review threads**, seven of them attached to current
lines at the merged head. They claim gaps involving configured push refspecs, no-argument pushes,
prior repository-path replacement, unqualified tag destinations, separate-Git-dir worktrees,
`push.followTags`, and configured receive-pack programs. Some overlap code or tests changed during
the PR and none was re-triaged after the final review. This record preserves them as unresolved
review evidence; it does not silently classify them as fixed, accepted, or reproduced. Under the
freeze they are evidence/corpus candidates, not authorization to modify the dispatcher.

## Known false-positive families

The live issue backlog and limitation ledger record the main classes:

- quoted here-string/heredoc documentation bodies and expression/variable opacity
  ([#21](https://github.com/Chris0Jeky/agent-harness/issues/21),
  [#32](https://github.com/Chris0Jeky/agent-harness/issues/32),
  [#38](https://github.com/Chris0Jeky/agent-harness/issues/38),
  [#58](https://github.com/Chris0Jeky/agent-harness/issues/58),
  [#135](https://github.com/Chris0Jeky/agent-harness/issues/135),
  [#136](https://github.com/Chris0Jeky/agent-harness/issues/136));
- redirections and configured push resolution
  ([#65](https://github.com/Chris0Jeky/agent-harness/issues/65),
  [#133](https://github.com/Chris0Jeky/agent-harness/issues/133)); and
- Windows/MSYS paths, worktree operands, and location-sensitive fixtures
  ([#119](https://github.com/Chris0Jeky/agent-harness/issues/119),
  [#125](https://github.com/Chris0Jeky/agent-harness/issues/125),
  [#128](https://github.com/Chris0Jeky/agent-harness/issues/128),
  [#129](https://github.com/Chris0Jeky/agent-harness/issues/129),
  [#137](https://github.com/Chris0Jeky/agent-harness/issues/137)).

The historical ~12% block-rate measurement is evidence about the measured corpus and synthetic
CWD, not a universal rate or safety claim.

## Recorded decisions and baseline gap

The repository contains three kinds of legacy evidence:

- executable policy source: `templates/hooks/dispatch.py` at the frozen commit;
- canonical expected decisions embedded in `templates/hooks/smoke_test.py` and focused unit
  fixtures under `tests/`; and
- private measurement tooling in `scripts/replay_corpus.py`, with a historical dispatcher fixture
  at `tests/fixtures/floor_1_2_0_dispatch.py`.

There is **no committed, privacy-reviewed JSONL decision recording** and no committed v0 corpus.
Raw replay JSON/cache output is intentionally scratch-only because it can contain private paths,
commands, repository identities, and credential-like values. The missing recorded baseline is an
explicit extraction gap for Tasks 4 and 9; the public replay repository must consume reviewed
recorded decisions and must never import or execute the legacy dispatcher.

## Missing governing references

`AGENT_HARNESS_OPERATIONS.md` names `CLAUDE_CONFIG_OPERATIONS.md` and
`REPLAY_TOOL_PRODUCT.md` as governing documents, but neither file exists in this repository, its
history, or the searched local authority locations as of 2026-07-30. Local freeze and inventory
work can remain fail-closed under the repository/global rules. Cross-repository autonomy, public
naming, licensing, launch, and continuation decisions remain unverified until the owner supplies
the authoritative paths.

Subsequent `main` commits added both governing references: `a35ff70` added
`REPLAY_TOOL_PRODUCT.md`, and `6d6e22e` added `CLAUDE_CONFIG_OPERATIONS.md`. H-9 is complete; both
authority sources are now directly inspectable at the repository root.

## Repository visibility decision

The GitHub API returned `private: false` and `visibility: public` for
`Chris0Jeky/agent-harness`, and the owner confirmed on 2026-07-30 that it remains public for now.
Every tracked file and proposed commit is therefore treated as immediately public. Private replay
output, transcript-derived commands, and unreviewed historical cases remain local regardless of a
future visibility change.

## Tag execution record

The owner explicitly authorized this procedure on 2026-07-30. It was executed once as recorded
below and must not be rerun to replace or move the tag.

```powershell
git fetch origin main
git status --short --branch
git show --no-patch --format=fuller 02bd14cfe094f9b6af85b966de481ff3f45264cf
git tag -a floor-v1-final 02bd14cfe094f9b6af85b966de481ff3f45264cf -m "Freeze legacy deny floor v1 at 1.6.21"
git show --no-patch floor-v1-final
git push origin refs/tags/floor-v1-final
```

Remote verification returned tag object `5a939540bdce51e511d6b3bae98358e3e2ad9148`, whose annotated
target is `02bd14cfe094f9b6af85b966de481ff3f45264cf`. Server-side tag protection was not verified, so
immutability still depends on repository policy and owner control.

## Deliberately not verified or performed

- No legacy parser change, repair, reformat, parser dependency change, or repository
  reorganisation was made as part of the freeze-tag action.
- No private transcript or raw replay output was opened, copied, or executed.
- No clean public-repository creation, licence, final name, or release action was performed.
- Fresh-session Codex `/hooks` trust and live canaries remain the existing human-owned H-2 gate.
