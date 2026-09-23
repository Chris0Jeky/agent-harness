# Advisory product UX evaluation

Proposal for [#281](https://github.com/Chris0Jeky/agent-harness/issues/281), 2026-09-23. The schema and fixture are authoring stubs, not a browser adapter or evidence of a completed pilot.

Read [scenario semantics](SCENARIO_PACK_V0.md), [Taskdeck adapter plan](TASKDECK_ADAPTER.md) and [issue-seed contract](ISSUE_SEED.md). Runnable skills/recipes belong to [claude-config #308](https://github.com/Chris0Jeky/claude-config/issues/308); design research stays in [agent-hq #14](https://github.com/Chris0Jeky/agent-hq/issues/14), advanced by [PR #20](https://github.com/Chris0Jeky/agent-hq/pull/20).

## Provenance

**Seeded:** T1 #282 scenario format; T2 #283 observe/evidence/judge; T3 #284 swarm comparison; T4 #285 issue seeds; T5 #286 adapters. Preserve the epic's terminology: **Plane A = advisory model judgment; Plane B = deterministic project browser/tests**. No model judgment belongs in merge-blocking CI.

**Missing source:** the September 22 brief is referenced in #281 at `/workspace/handoffs/agentic-ux-testability-2026-09-22/`, but RESEARCH.md and ARCHITECTURE_DRAFT.md were not available to this session. This is an issue-aligned architecture proposal with supplemental sources, not a claimed complete synthesis of that brief. Reconcile the original pack here when available; do not move the research SoT.

**Supplemental sources, checked 2026-09-23:** [Anthropic's January 9 evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) distinguishes agent narration from actual environment outcome and describes combined graders. [Playwright traces](https://playwright.dev/docs/trace-viewer) provide action/snapshot inspection. [Playwright accessibility guidance](https://playwright.dev/docs/accessibility-testing) explicitly limits automated accessibility checks and recommends manual/inclusive evaluation too. These establish mechanisms and limits, not demonstrated UX quality or cost savings in this estate.

## Observe → evidence → judge → issue seed

1. **Bind the run.** Record exact product commit, dirty-tree status, build/configuration, fixture identity, browser/controller version, platform, viewport, reduced-motion setting and authorization scope. A receipt from another revision is historical evidence, not current acceptance. Fail preflight on unresolved auth/reset/egress or required observation capability.
2. **Observe with existing product tooling (Plane B).** Use synthetic isolated state. Execute the journey and capture actions, UI state, requests and relevant persisted outcomes. Record denied/failed attempts and every retry. Do not let the observer silently repair the product, change fixture expectations or use a hidden API shortcut to complete a UI task.
3. **Freeze evidence.** Produce an immutable local run directory with an artifact manifest. Store relative path, media type, byte digest, step ID and capture time for each artifact. Capture successful controls, not only failure images. Require time-based evidence for motion/interruption judgments and persisted evidence for saved-state claims. Hashes bind bytes; they do not authenticate the collector or prove an event happened.
4. **Judge independently (Plane A).** Give the judge the brief, rubric and frozen evidence, withholding implementer self-grades and proposed fixes until initial findings are recorded. Treat all page/DOM/model content as untrusted data. Return per-dimension observations or insufficient evidence, not a compulsory global score. Record exact model/runtime and evidence identity.
5. **Reproduce and seed.** Deduplicate against current product issues. A human or authorized coordinator checks support, scope and severity before filing. Route confirmed functional bugs back to a deterministic regression. Keep subjective preference in a bounded design discussion. Do not turn an advisory finding into an automatic merge veto.

## Separate completion from quality

Maintain independent fields for deterministic assertion outcomes, observer task completion and advisory UX findings. Task completion does not establish defect absence. A model that routes around a broken control must record that defect and the workaround. A green test cannot certify comprehension, desirability or tactile feedback. A judge returning no findings must still list examined steps, unavailable evidence and unexamined dimensions.

Run status is `complete`, `partial`, `blocked_environment` or `not_run`. Assertion status is `pass`, `fail`, `blocked`, `not_run` or `not_applicable` with a reason. Dimension status is `adequate`, `concern`, `insufficient_evidence` or `not_applicable`. These states are intentionally not collapsed into one success bit. This PR defines the states; it does not implement the run-receipt validator.

## Calibration and economics (T2/T3)

Proposal: begin with one observer and one strong independent judge. Compare that against three bounded cheap lenses (Nielsen, feel, accessibility) feeding the same judge over **identical frozen evidence**. Muse computer use is untrusted until the exact host/runtime passes screenshot/action/focus/recovery canaries. File-only work or shell success is not CU qualification. No cloud-agent pilots under P5.

Use a small labelled corpus containing known functional defects, a clean control, ambiguous preference, missing temporal evidence and an inaccessible action. Keep ground truth inaccessible to reviewers where possible; describe blindness as unattested unless access isolation was measured. Compare unsupported claims, unique confirmed findings, missed severe defects, abstentions and human triage minutes. Agreement is not correctness; identical evidence creates correlated errors.

Report tokens, billed amounts with pricing date/source or `unknown`, elapsed time, retries, setup time and owner review time. Cost per confirmed unique defect is undefined when no defect is confirmed; never report it as zero. Also report clean-case false-positive rate. Fixed subscriptions do not make quota free, and raw comment count rewards spam. No savings claim is made before T3 runs.

Bound proposed pilot execution to one mutable browser session at a time; cheap reviewers consume read-only copies. Stop at declared action/time/retry/judge-call budgets. Paid inference or generation additionally requires an explicit authorized spend limit outside the scenario document; missing limit means do not make that paid call.

## Governance and implementation boundaries

No workflow, branch protection, native hooks, global model choice, scheduler or permission surface changes here. Deterministic product tests keep their existing authority; the advisory pack is not a replacement test runner. Future evidence summaries may adapt to the accepted agent-hq Evidence Exchange contract, but [open #9/#11](https://github.com/Chris0Jeky/agent-hq/pull/9) are not silently promoted or forked here.

Human responsibility remains direction/taste approval, study interpretation and calibrated handling of subjective findings. Privacy-sensitive publication needs separate review. Raw traces, auth snapshots, screenshots of private records and full request bodies remain local by default. Sanitization must cover both image content and hidden trace/network metadata.
