/* Recorded public-fixture replay explorer. No command parsing, execution or uploads. */
(function () {
  'use strict';
  const changes = ['unchanged', 'newly-allowed', 'newly-denied', 'newly-indeterminate', 'resolved-indeterminate'];
  const effects = ['allow', 'deny', 'indeterminate'];
  const classes = ['benign', 'dangerous', 'opaque'];

  function summarize(rows) {
    const counts = Object.fromEntries(changes.map(change => [change, 0]));
    rows.forEach(row => { counts[row.classification] += 1; });
    return counts;
  }

  function validateReport(report) {
    const fail = () => { throw new Error('The recorded report is incomplete or invalid.'); };
    if (!report || !report.corpus || !Array.isArray(report.results) ||
        !report.results.length || report.results.length > 1000 ||
        report.corpus.event_count !== report.results.length) fail();
    const seen = new Set();
    for (const row of report.results) {
      if (!row || !row.event || !row.case || !row.baseline || !row.candidate) fail();
      const id = row.event.event_id;
      if (typeof id !== 'string' || !id || seen.has(id) ||
          [row.case, row.baseline, row.candidate].some(value => value.event_id !== id) ||
          !['synthetic', 'historical-redacted'].includes(row.event.source) || row.case.provenance !== row.event.source ||
          !changes.includes(row.classification) || !classes.includes(row.case.case_class) ||
          !effects.includes(row.baseline.effect) || !effects.includes(row.candidate.effect) ||
          [row.event.command, row.case.case_family, row.case.rationale,
            row.baseline.reason, row.candidate.reason].some(value => typeof value !== 'string')) fail();
      seen.add(id);
    }
    const counts = summarize(report.results);
    if (!report.counts || changes.some(change => counts[change] !== report.counts[change])) fail();
    return report.results;
  }

  function filterRows(rows, filters) {
    const query = filters.query.trim().toLowerCase();
    return rows.filter(row =>
      (filters.change === 'all' || row.classification === filters.change) &&
      (filters.caseClass === 'all' || row.case.case_class === filters.caseClass) &&
      [row.event.command, row.event.event_id, row.case.case_family, row.case.rationale]
        .join(' ').toLowerCase().includes(query));
  }

  function gateResult(rows, failOn) {
    if (!failOn.length) return {status: 'disabled', triggered: [], count: 0};
    const counts = summarize(rows);
    const triggered = changes.filter(change => failOn.includes(change) && counts[change] > 0);
    return {status: triggered.length ? 'fail' : 'pass', triggered,
      count: triggered.reduce((sum, change) => sum + counts[change], 0)};
  }

  if (typeof module === 'object' && module.exports) {
    module.exports = {summarize, validateReport, filterRows, gateResult};
  }
  if (typeof document === 'undefined') return;
  const container = document.querySelector('[data-replay-lab]');
  if (!container) return;
  const byId = id => document.getElementById(id);
  const status = byId('lab-status');
  const script = document.querySelector('script[data-replay-report]');

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  async function start() {
    try {
      if (!script) throw new Error('Missing report location.');
      const response = await fetch(script.dataset.replayReport, {credentials: 'omit'});
      if (!response.ok) throw new Error('Report request failed.');
      const report = await response.json();
      const rows = validateReport(report);
      const counts = summarize(rows);
      let selected = rows.find(row => row.event.event_id === 'danger-clean-ignored') || rows[0];
      let step = 0;
      const selector = byId('lab-case');
      rows.forEach(row => {
        const option = element('option', row.event.event_id);
        option.value = row.event.event_id;
        selector.appendChild(option);
      });
      byId('lab-total').textContent = rows.length;
      byId('lab-allowed').textContent = counts['newly-allowed'];
      byId('lab-denied').textContent = counts['newly-denied'];
      byId('lab-unchanged').textContent = counts.unchanged;
      byId('lab-provenance').textContent = report.corpus.id + ' · recorded ' + report.generated_at.slice(0, 10) + ' · 40 synthetic + 10 re-authored historical cases';
      const bar = byId('lab-distribution');
      const legend = byId('lab-legend');
      changes.filter(change => counts[change] > 0).forEach(change => {
        const segment = element('span', '', 'lab-segment ' + change);
        segment.style.width = (100 * counts[change] / rows.length) + '%';
        bar.appendChild(segment);
        legend.appendChild(element('span', counts[change] + ' ' + change.replaceAll('-', ' '), 'lab-key ' + change));
      });
      bar.setAttribute('aria-label', changes.map(change => counts[change] + ' ' + change).join(', '));

      function showCase() {
        selector.value = selected.event.event_id;
        byId('lab-command').textContent = selected.event.command;
        byId('lab-class').textContent = selected.case.case_class + ' · ' + selected.case.case_family + ' · ' + selected.event.source;
        byId('lab-before').textContent = selected.baseline.effect;
        byId('lab-after').textContent = selected.candidate.effect;
        byId('lab-change').textContent = selected.classification.replaceAll('-', ' ');
        byId('lab-rationale').textContent = selected.case.rationale;
        const messages = [
          'Input: recorded command text from ' + selected.event.event_id + '. The browser does not execute it.',
          'Baseline, toy guard v1: ' + selected.baseline.reason,
          'Candidate, toy guard v2: ' + selected.candidate.reason,
          'Comparison: ' + selected.classification.replaceAll('-', ' ') + '. The corpus labels this case ' + selected.case.case_class + '.'
        ];
        byId('lab-step-detail').textContent = messages[step];
        container.querySelectorAll('[data-lab-step]').forEach(button => {
          const active = Number(button.dataset.labStep) === step;
          button.setAttribute('aria-pressed', String(active));
        });
      }

      function showGate() {
        const failOn = Array.from(container.querySelectorAll('[data-fail-on]:checked'), input => input.dataset.failOn);
        // Always use every row. A display filter cannot hide a failing case from the gate.
        const result = gateResult(rows, failOn);
        const panel = byId('lab-gate-result');
        panel.dataset.verdict = result.status;
        byId('lab-gate-verdict').textContent = result.status === 'disabled' ? 'No checks selected' : result.status === 'fail' ? 'Gate fails' : 'Selected checks pass';
        byId('lab-gate-detail').textContent = result.status === 'disabled'
          ? 'Select a failure condition to evaluate this example. Disabling every check is not evidence of safety.'
          : result.status === 'fail'
            ? result.count + ' of ' + rows.length + ' cases trigger: ' + result.triggered.join(', ') + '.'
            : 'None of the ' + rows.length + ' cases trigger the selected conditions. Inspect the changed cases before drawing a conclusion.';
      }

      function showRows() {
        const visible = filterRows(rows, {change: byId('lab-filter-change').value,
          caseClass: byId('lab-filter-class').value, query: byId('lab-search').value});
        const body = byId('lab-rows');
        body.replaceChildren();
        visible.forEach(row => {
          const tr = element('tr');
          const command = element('td');
          const button = element('button', row.event.command, 'lab-command-button');
          button.type = 'button';
          button.setAttribute('aria-label', 'Inspect ' + row.event.event_id + ': ' + row.event.command);
          button.addEventListener('click', () => {
            selected = row; step = 3; showCase();
            byId('lab-case-inspector').scrollIntoView({block: 'start'});
            selector.focus({preventScroll: true});
          });
          command.appendChild(button);
          tr.appendChild(command);
          tr.appendChild(element('td', row.case.case_class));
          tr.appendChild(element('td', row.baseline.effect + ' → ' + row.candidate.effect));
          tr.appendChild(element('td', row.classification.replaceAll('-', ' ')));
          body.appendChild(tr);
        });
        byId('lab-filter-status').textContent = visible.length + ' of ' + rows.length + ' cases shown. Gate checks still use all ' + rows.length + '.';
        byId('lab-empty').hidden = visible.length !== 0;
      }

      selector.addEventListener('change', () => {
        selected = rows.find(row => row.event.event_id === selector.value); showCase();
      });
      container.querySelectorAll('[data-lab-step]').forEach(button => {
        button.addEventListener('click', () => { step = Number(button.dataset.labStep); showCase(); });
      });
      container.querySelectorAll('[data-lab-example]').forEach(button => {
        button.addEventListener('click', () => {
          selected = rows.find(row => row.event.event_id === button.dataset.labExample) || rows[0];
          step = 3; showCase();
        });
      });
      container.querySelectorAll('[data-fail-on]').forEach(input => input.addEventListener('change', showGate));
      ['lab-filter-change', 'lab-filter-class'].forEach(id => byId(id).addEventListener('change', showRows));
      byId('lab-search').addEventListener('input', showRows);
      byId('lab-reset').addEventListener('click', () => {
        byId('lab-filter-change').value = 'all'; byId('lab-filter-class').value = 'all'; byId('lab-search').value = '';
        container.querySelectorAll('[data-fail-on]').forEach(input => {
          input.checked = ['newly-allowed', 'newly-indeterminate'].includes(input.dataset.failOn);
        });
        selected = rows.find(row => row.event.event_id === 'danger-clean-ignored') || rows[0];
        step = 0; showCase(); showGate(); showRows();
      });
      showCase(); showGate(); showRows();
      container.querySelectorAll('fieldset').forEach(fieldset => { fieldset.disabled = false; });
      container.querySelectorAll('[data-lab-ready]').forEach(node => { node.hidden = false; });
      status.textContent = 'Ready. Explore the recorded example below; all interactions stay in your browser.';
    } catch (error) {
      status.textContent = 'The interactive report could not load. Use the recorded summary and reproduction commands below.';
      status.setAttribute('role', 'alert');
    }
  }
  start();
})();
