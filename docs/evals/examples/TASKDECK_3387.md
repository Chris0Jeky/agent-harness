# Worked evidence packet: Taskdeck #3387

Inspection: 2026-09-23. Kind: **partial retrospective Markdown companion** to
[review under flood](../REVIEW_UNDER_FLOOD.md), not an execution receipt or complete
PR review. Parent [#299](https://github.com/Chris0Jeky/agent-harness/issues/299);
follow-through [#301](https://github.com/Chris0Jeky/agent-harness/issues/301) and
[#308](https://github.com/Chris0Jeky/agent-harness/issues/308).

**FACT** below means retrieved source or hosted observation. **INFER** labels
interpretation. No product command was run in this documentation session.

## Read first: claim and remaining gaps

[Taskdeck #3387][PR] changes buffered-export representation accounting. The hosted
Application suite reports **4,892 passed, zero failed, zero skipped** for the
identified test-merge revision [JOB]. Three added tests were inspected in source
[TESTS]; their individual result records were not retrieved.

This does **not** establish whole-process memory bounds, real database concurrency,
current Taskdeck merge readiness, or READY-cohort membership. It illustrates how
aggregate success, inspected assertions, and unavailable evidence stay distinct.

The case was chosen from a previously inspected scout discovery lead, after its
outcomes were known. It is a convenience example, **excluded from every live READY
cohort denominator**. READY status and security Priority II eligibility are unknown.
The related issue [#3371][CONTRACT] carried a **Priority III** label when inspected;
that label does not establish a PR's triage status or a security cohort.

## Identity and contract

| Item | Observed identity / bounded meaning |
|---|---|
| Repository / PR | `Chris0Jeky/Taskdeck`, [#3387][PR], open and non-draft at inspection |
| Inspected source head | `ec5f86f11c3eab0604279c6a0020faf28e935949` |
| Target base recorded by this run | `cfec757fe6eb5a830b62e3f9581744c08d802623` |
| Actual tested CI merge | `45b69b3155ce542084e2ca1869e472356f26cea2` |
| Mapping evidence | Run metadata [RUN] and checkout log [JOB] bind the merge to that source head and target base |
| Merge base / local dirty state | Not separately inspected; do not substitute the target base or assume a local checkout |
| Run / attempt / job | `35806166106` / `1` / `107007589011` |
| Check source | [Reusable backend-unit workflow at the tested revision][WORKFLOW]; source tests [TESTS] |
| Test source blob | `403bbd9b3d5a7cc2d618357379d39bd0e4d88ff4` identical at the inspected source head and tested merge; not a digest of materialized runtime fixtures |
| Required behavior | [#3371][CONTRACT]: account for escaped metadata, revalidate concurrent additions, retain streaming for rejected buffered exports |
| Changed seam / risk | Export admission and loaded representation accounting; service callers, stored content, and error/audit behavior |
| Explicit recovery boundary | Streaming remains an alternate route in the source contract; this read-through did not qualify deployment or operational recovery |

**FACT:** The production diff [SOURCE] adds selected-metadata admission, loaded
content rechecks, and a shared remaining budget for original-source rows. It
explicitly limits the 25 MiB policy to charged artefact/source representations.
The PR records [#3386][RESIDUAL] for extraction-history batch materialization before
the post-load check. That residual was not independently reproduced here.

## Planned evidence versus observations

This manifest scopes the **worked example**, not all checks required to merge the
Taskdeck PR. It must not be used to mark omitted repository requirements optional.

| Evidence item | Inspection outcome | What it supports / what remains unknown |
|---|---|---|
| Contract and changed assertions | Source inspected [CONTRACT], [TESTS], [SOURCE] | Expectations and implementation seam, not execution |
| Candidate Application suite | Hosted log retrieved [JOB] | Assembly-level PASS at the actual tested revision |
| Named test result records | Not retrieved | Backend-result upload step was skipped [JOBS]; a runner-local TRX path is not a retrieved artifact |
| Known-good / named-broken controls | No separate execution evidence retrieved | Streaming assertions exist in a candidate test; no bad-revision rejection or independent control run is claimed |
| Earlier local attempt | Author report only [PR] | Retain the reported interruption; do not relabel it PASS or infer its exact source/environment |
| Full PR requirements and review dispositions | Not exhaustively inspected | This example is not complete acceptance evidence or a merge decision |
| Optional trace / model / computer-use evidence | Not inspected | No inference of zero activity, and no new merge blocker |

### Recorded candidate execution

**FACT:** The retrieved Ubuntu backend job uses .NET SDK `8.0.425`, VSTest `17.11.1`,
and `net8.0` assemblies [JOB]. The Application step ran:

```text
dotnet test backend/tests/Taskdeck.Application.Tests/Taskdeck.Application.Tests.csproj --configuration Release --no-restore --logger "trx;LogFileName=application.trx" --results-directory "backend/TestResults/backend-unit/ubuntu-latest/application"
```

This is a **transcription of a retrieved execution**, not authorization to run it.
The command group starts at `2026-09-23T01:26:18.6169215Z`; its result line at
`2026-09-23T01:28:04.8523824Z` records 4,892 passed, zero failed, zero skipped.
The same job reports Domain 1,687 and CLI 243 passed with zero failures/skips.
Compiler warnings were present; success is not a warning-free claim.

The run is marked successful [RUN]. Its backend upload step is skipped [JOBS];
the pinned workflow uploads only on failure [WORKFLOW]. This is an intentional
artifact policy, not a failure inferred from missing uploads.
The log names a generated `application.trx`, but that file was not retrieved.
Consequently the packet preserves the suite result without inventing individual
test receipts or claiming the absence of every possible artifact.

**FACT:** The PR body separately reports a local full-gate interruption and 4,889
Application passes [PR]. Its precise tested identity was not established here.
Do not merge that count with the hosted 4,892, overwrite the interrupted attempt,
or assume why the counts differ. No exhaustive attempt-history census was made.

## Oracle inspection and independence limits

All three named methods below are in [the inspected test source][TESTS].
These are test definitions, not individually retrieved execution records.

| Test suffix after `ExportUserDataAsync_` | Expected discrimination in source | Limit |
|---|---|---|
| `RejectsManyEscapedArtefactMetadataRows_WhileStreamStillWorks` | 3,000 rows with maximum-length backslash names/origins yield `PayloadTooLarge` before blob fetch; streaming succeeds and JSON contains all 3,000 artefacts | Actual service with mocked repositories; array count is not byte parity or persistent database proof |
| `RejectsUploadCommittedAfterAggregateEstimateBeforeBlobLoad` | A synchronized late 7 MiB artefact yields `PayloadTooLarge`; blob fetch is never invoked | Controlled mock interleaving, not two real database transactions |
| `RejectsSourceUploadCommittedAfterEstimateBeforeSourceLoad` | Source rows arrive after an estimate of zero; result is `PayloadTooLarge`, and `DataExported` is not logged | Mocked source store and audit service; no durable transaction or whole-process RSS assertion |

**INFER:** These are plausible existing deterministic service-contract oracles:
they assert error and forbidden-call behavior rather than a model score.
Candidate gate eligibility still depends on owning policy and applicable evidence;
this documentation does not enroll a check or inspect branch-protection settings.

The source uses synchronization signals with ten-second watchdogs. A watchdog or
setup timeout is a failure to obtain the expected observation, not a successful
regression control. Generated identifiers and fixtures are source-defined inputs;
their materialized bytes were not captured here. No historical broken-state run
was performed, so defect sensitivity remains unproven by this read-through.

## Applying the existing anti-LGTM checklist

This is an author's bounded source-and-log read-through using the
[existing checklist](../../REVIEW_EVIDENCE.md#anti-lgtm-theater-check-inside-the-existing-review-budget).
It is not independent product acceptance, a new review round, or measured time savings.

| Question | Disposition and next action |
|---|---|
| Do assertions reach the changed seam? | Source inspection shows calls through `DataExportService`; distinguish the mock boundary from HTTP/database integration |
| Would no-op rejection or skipped streaming satisfy everything? | The streaming-success/count assertions address that limited counterexample; other no-op or parity failures were not experimentally tested |
| Do green parents prove all child actions ran? | No: [JOBS] records dependency-enforcement and full-history secret-scan steps as skipped despite successful jobs; preserve scope without calling those skips defects |
| Is the secret-scan scope clear? | Job metadata records a PR-commits scan, not the skipped full-history scan; scanner findings/logs were not independently inspected here |
| Can named test success be reconstructed from counts alone? | No individual receipts retrieved; retain assembly-level results and explicit missingness |
| Are known limitations hidden? | Keep the reported local interruption, mock-only concurrency, representation-only budget and unqualified extraction-history residual |
| Can this finish E4? | No: the authoritative READY frame and real-cohort application remain [#307](https://github.com/Chris0Jeky/agent-harness/issues/307)/#308 |

No confirmed new product defect is asserted. The evidence gaps above are not
automatically implementation failures. To extend this example, retrieve any
available case-level evidence and control history using existing read-only
interfaces; record unavailable results rather than altering Taskdeck CI to create
an artifact. Do not execute packet commands or open Taskdeck PRs in this lane.

## Sources and publication boundary

Sources were retrieved through the GitHub connector on 2026-09-23. Source URLs are
pinned where possible; issue/PR bodies and run metadata are mutable observations.
Logs can expire. A later inaccessible link means unavailable evidence, not PASS.
Only selected public repository identifiers, assertion descriptions and counts
are reproduced; no full logs, credentials, personal workstation paths, or user
export data are copied. No signed-receipt or cryptographic provenance claim is made.

[PR]: https://github.com/Chris0Jeky/Taskdeck/pull/3387
[CONTRACT]: https://github.com/Chris0Jeky/Taskdeck/issues/3371
[RESIDUAL]: https://github.com/Chris0Jeky/Taskdeck/issues/3386
[TESTS]: https://github.com/Chris0Jeky/Taskdeck/blob/ec5f86f11c3eab0604279c6a0020faf28e935949/backend/tests/Taskdeck.Application.Tests/Services/DataExportServiceTests.cs#L216-L357
[SOURCE]: https://github.com/Chris0Jeky/Taskdeck/blob/ec5f86f11c3eab0604279c6a0020faf28e935949/backend/src/Taskdeck.Application/Services/DataExportService.cs
[RUN]: https://github.com/Chris0Jeky/Taskdeck/actions/runs/35806166106
[JOBS]: https://api.github.com/repos/Chris0Jeky/Taskdeck/actions/runs/35806166106/jobs
[JOB]: https://github.com/Chris0Jeky/Taskdeck/actions/runs/35806166106/job/107007589011
[WORKFLOW]: https://github.com/Chris0Jeky/Taskdeck/blob/45b69b3155ce542084e2ca1869e472356f26cea2/.github/workflows/reusable-backend-unit.yml
