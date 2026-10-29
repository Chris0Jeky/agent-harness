# Replay lab

**See what a policy change actually changes.** Explore 50 recorded public-fixture command cases through two versions of a toy guard. Follow a case, filter the differences, then adjust a sample regression gate.

The corpus has 40 synthetic cases and 10 fully re-authored historical/opaque shapes. This is a teaching example, separate from the current deny floor. It displays checked-in decisions; it does not run commands, contact a model, or measure a live deployment.

<div data-replay-lab class="replay-lab">
  <p class="lab-eyebrow">RECORDED EVIDENCE / PUBLIC FIXTURE</p>
  <p id="lab-status" role="status">The interactive report is loading. The recorded summary and reproduction commands below work without JavaScript.</p>
  <noscript><p>JavaScript is disabled. Read the recorded results below, or reproduce the comparison with the CLI.</p></noscript>
  <div data-lab-ready hidden>
    <p id="lab-provenance" class="lab-provenance"></p>
    <div class="lab-stats">
      <div><strong id="lab-total">—</strong><span>recorded cases</span></div>
      <div><strong id="lab-allowed">—</strong><span>newly allowed</span></div>
      <div><strong id="lab-denied">—</strong><span>newly denied</span></div>
      <div><strong id="lab-unchanged">—</strong><span>unchanged</span></div>
    </div>
    <div id="lab-distribution" class="lab-distribution" role="img" aria-label="Recorded changes"></div>
    <div id="lab-legend" class="lab-legend"></div>
  </div>

  <section id="lab-case-inspector" class="lab-panel" aria-labelledby="lab-case-title">
    <h2 id="lab-case-title">1. Follow a case</h2>
    <p>Guard v2 exempts help and dry runs, but accidentally drops its <code>git clean</code> rule. Start with the regression, then compare a benign improvement.</p>
    <fieldset disabled>
      <legend class="lab-sr-only">Choose a recorded case</legend>
      <div class="lab-presets">
        <button type="button" data-lab-example="danger-clean-ignored">A regression</button>
        <button type="button" data-lab-example="benign-clean-dry-run">A benign improvement</button>
        <button type="button" data-lab-example="danger-force-lease-release">A tighter rule</button>
      </div>
      <label for="lab-case">Recorded case</label>
      <select id="lab-case"></select>
      <div class="lab-steps" aria-label="Replay stages">
        <button type="button" data-lab-step="0" aria-pressed="true">1 · Input</button>
        <button type="button" data-lab-step="1" aria-pressed="false">2 · Baseline</button>
        <button type="button" data-lab-step="2" aria-pressed="false">3 · Candidate</button>
        <button type="button" data-lab-step="3" aria-pressed="false">4 · Compare</button>
      </div>
    </fieldset>
    <div data-lab-ready hidden>
      <p id="lab-class" class="lab-provenance"></p>
      <pre><code id="lab-command"></code></pre>
      <div class="lab-comparison"><span>v1 <strong id="lab-before"></strong></span><span aria-hidden="true">→</span><span>v2 <strong id="lab-after"></strong></span><span id="lab-change" class="lab-badge"></span></div>
      <p id="lab-rationale"></p>
      <p id="lab-step-detail" class="lab-explanation" aria-live="polite"></p>
    </div>
  </section>

  <section class="lab-panel" aria-labelledby="lab-gate-title">
    <h2 id="lab-gate-title">2. Try a regression gate</h2>
    <p>Choose which transitions fail this sample gate. It always checks all 50 cases. These controls change only this browser demonstration.</p>
    <fieldset disabled class="lab-gate-options">
      <legend>Fail when a case is…</legend>
      <label><input type="checkbox" data-fail-on="newly-allowed" checked> Newly allowed</label>
      <label><input type="checkbox" data-fail-on="newly-denied"> Newly denied</label>
      <label><input type="checkbox" data-fail-on="newly-indeterminate" checked> Newly indeterminate</label>
    </fieldset>
    <div id="lab-gate-result" class="lab-verdict" aria-live="polite" data-lab-ready hidden>
      <strong id="lab-gate-verdict"></strong>
      <p id="lab-gate-detail"></p>
    </div>
    <p class="lab-note">A transition is not a verdict about safety. Newly allowed help can be an improvement; newly allowed destructive cleanup can be a regression. The case rationale supplies that context.</p>
  </section>

  <section class="lab-panel" aria-labelledby="lab-results-title">
    <h2 id="lab-results-title">3. Inspect the evidence</h2>
    <fieldset disabled>
      <legend class="lab-sr-only">Filter recorded cases</legend>
      <div class="lab-filters">
        <label for="lab-filter-change">Change<select id="lab-filter-change"><option value="all">All transitions</option><option value="newly-allowed">Newly allowed</option><option value="newly-denied">Newly denied</option><option value="unchanged">Unchanged</option><option value="newly-indeterminate">Newly indeterminate</option><option value="resolved-indeterminate">Resolved indeterminate</option></select></label>
        <label for="lab-filter-class">Corpus label<select id="lab-filter-class"><option value="all">All labels</option><option value="benign">Benign</option><option value="dangerous">Dangerous</option><option value="opaque">Opaque</option></select></label>
      </div>
      <label for="lab-search">Find a command, family or rationale</label>
      <input id="lab-search" type="search" placeholder="Try dry-run or worktree" autocomplete="off">
      <button id="lab-reset" type="button" class="lab-reset">Reset the example</button>
    </fieldset>
    <p id="lab-filter-status" role="status"></p>
    <div class="lab-table-wrap" data-lab-ready hidden>
      <table class="lab-table"><caption>Select a command to inspect its recorded decisions.</caption><thead><tr><th scope="col">Command</th><th scope="col">Label</th><th scope="col">v1 → v2</th><th scope="col">Change</th></tr></thead><tbody id="lab-rows"></tbody></table>
      <p id="lab-empty" hidden>No matching cases. Clear the filters or reset the example.</p>
    </div>
  </section>
</div>

## What the recorded run shows

| Transition | Cases | How to read it |
|---|---:|---|
| Newly allowed | 4 | Three benign cases improve; one dangerous cleanup case regresses. |
| Newly denied | 1 | The candidate catches the corpus's force-with-lease case. |
| Unchanged | 45 | An unchanged decision can still be wrong. Inspect the corpus label. |
| Newly indeterminate | 0 | Neither toy hook fails to produce a determinate decision here. |

The default gate **fails** because it rejects any newly allowed case. These are the toy guards' recorded decisions on `charter-v0.1`, not measurements of the current floor. The labels describe this teaching corpus; they are not universal shell-command classifications.

Sources: [recorded report](../examples/toy-guard/report/report.json), [toy guard walkthrough](../examples/toy-guard/README.md), [baseline source](../examples/toy-guard/guard_v1.py), [candidate source](../examples/toy-guard/guard_v2.py).

## Reproduce it locally

From the repository root, Python 3.11 or newer can reproduce the comparison from recorded decisions:

```bash
python -m replay_v0.app replay \
  --baseline recorded:examples/toy-guard/report/baseline/decisions.jsonl \
  --candidate recorded:examples/toy-guard/report/candidate/decisions.jsonl \
  --corpus replay_v0/corpora/charter \
  --output reports/toy-guard-recorded
```

Expect exit **1** with `newly-allowed: 4` in `summary.json`: the comparison ran and its regression gate failed. The [toy guard walkthrough](../examples/toy-guard/README.md) also shows how to invoke the two hooks afresh. Replay sends command text to the policies; it does not execute the recorded commands.

## Put the tools together

![Declare a policy, inspect its wiring, compare decisions and review the evidence](assets/policy-workflow.svg)

Use [`doctor` and `audit`](../README.md#quickstart) to inspect the declaration and wiring. Use replay to measure a proposed policy change on a pinned corpus. Review the changed cases before shipping. Runtime trust and live canaries remain separate evidence; see the [floor limits](../FLOOR_LIMITATIONS.md) and [capability ledger](SYSTEM_STATE.md).
