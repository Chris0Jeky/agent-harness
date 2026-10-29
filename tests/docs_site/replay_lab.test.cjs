const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const root = path.resolve(__dirname, '../..');
const implementation = path.join(root, 'scripts/docs_site/assets/js/replay-lab.js');
assert.ok(fs.existsSync(implementation), 'The replay lab implements report exploration');
const lab = require(implementation);
const report = JSON.parse(fs.readFileSync(path.join(root, 'examples/toy-guard/report/report.json'), 'utf8'));

test('the recorded public fixture has four newly allowed and one newly denied case', () => {
  const rows = lab.validateReport(report);
  assert.equal(rows.length, 50);
  assert.deepEqual(lab.summarize(rows), {
    unchanged: 45, 'newly-allowed': 4, 'newly-denied': 1,
    'newly-indeterminate': 0, 'resolved-indeterminate': 0
  });
});

test('filters reveal the destructive newly allowed case and benign improvements separately', () => {
  const rows = lab.validateReport(report);
  const dangerous = lab.filterRows(rows, {change: 'newly-allowed', caseClass: 'dangerous', query: ''});
  assert.deepEqual(dangerous.map(row => row.event.event_id), ['danger-clean-ignored']);
  const benign = lab.filterRows(rows, {change: 'newly-allowed', caseClass: 'benign', query: ''});
  assert.equal(benign.length, 3);
  assert.equal(lab.filterRows(rows, {change: 'all', caseClass: 'all', query: 'DRY-RUN'}).length, 4);
  assert.equal(lab.filterRows(rows, {change: 'all', caseClass: 'all', query: '<no results>'}).length, 0);
});

test('the gate uses the full corpus independently of visible filters', () => {
  const rows = lab.validateReport(report);
  assert.deepEqual(lab.gateResult(rows, ['newly-allowed', 'newly-indeterminate']), {
    status: 'fail', triggered: ['newly-allowed'], count: 4
  });
  assert.equal(lab.filterRows(rows, {change: 'unchanged', caseClass: 'all', query: ''}).length, 45);
  assert.equal(lab.gateResult(rows, ['newly-allowed']).status, 'fail');
  assert.deepEqual(lab.gateResult(rows, []), {status: 'disabled', triggered: [], count: 0});
  assert.equal(lab.gateResult(rows, ['newly-indeterminate']).status, 'pass');
});

test('a malformed, partial, duplicate or non-public report cannot produce a passing display', () => {
  for (const mutate of [
    value => { value.results.pop(); },
    value => { value.results[0].event.source = 'private-transcript'; },
    value => { value.results[1] = value.results[0]; },
    value => { value.results[0].candidate.event_id = 'different-event'; },
    value => { value.results[0].classification = 'passed'; },
    value => { value.counts['newly-allowed'] = 0; },
    value => { value.results[0].event.command = null; }
  ]) {
    const changed = structuredClone(report);
    mutate(changed);
    assert.throws(() => lab.validateReport(changed), /report/i);
  }
  assert.throws(() => lab.validateReport({results: []}), /report/i);
});
