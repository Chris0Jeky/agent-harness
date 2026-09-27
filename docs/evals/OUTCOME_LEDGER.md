# Outcome ledger

Status: implemented, experimental, 2026-09-27. Parent: [#299](https://github.com/Chris0Jeky/agent-harness/issues/299)
(E1 taxonomy: this is the *development* outcome dataset). Tool: `scripts/outcome_ledger.py`.

The Muse swarm produces a JSON receipt per job and a coordinator item table per lane, but neither
answers "which recipe finds real defects", "which effort level wastes turns" or "did the PR stick".
The coordinator also prunes decided items after 30 days and keeps only its last 200 turns, so
its own history is lossy. The ledger is the durable, normalised record the swarm's learning
(Thompson-sampling posteriors per repo x recipe x runtime, later GEPA prompt optimisation) is
judged against. It lives outside both producers so neither can grade itself.

## Contract

- **Read-only over the swarm.** Inputs are `<root>/<lane>/state/waves/<NNN>/run/<repo>--<entry>/result.json`
  and `<root>/<lane>/coordinator/state.json`. `extract` refuses an `--out` inside the runs root.
- **A data contract, not an import.** Nothing from claude-config is loaded (AH-9). The one
  producer rule restated here is the coordinator's item id, `"f-" + sha1(repo|file|claim[:200])[:10]`,
  pinned by a test against a live item. If the producer changes it, the summary's
  `unjoined_items` rises instead of the join silently failing.
- **Deterministic.** The same inputs and `--observed-at` give byte-identical JSONL, sorted by
  record type then id.
- **Private output.** The ledger carries claim and evidence text from private repositories. Keep
  it outside every repository (suggested: `%USERPROFILE%\.estate\outcome-ledger\`); never commit it.
- **Labels are judgments, not proof.** A verdict is the coordinator judge's triage decision.
  Every finding keeps `judge` and `judge_verified`; precision is "judge-agreed precision" until
  the reviewer-calibration corpus exists.

## Records (`outcome-ledger/v1`)

| type | id | carries |
|---|---|---|
| `job` | `<lane>/<wave>/<job>` | mode, recipe, runtime, model, effort, status, terminal reason, elapsed, base SHA, finding count, verify exit, tool failures |
| `turn` | `<lane>/turn/<dir>` | coordinator turn kind (triage/publish/land), runtime, status, seconds, faults, timeout, outcome counts |
| `finding` | `<lane>/<item id>` | origin job (recipe/runtime/model/effort/base SHA), `fingerprint`, `cluster`, `split`, verdict, judge, worker, PR URL, publication, joined PR state, sightings |

Every record has `provenance {producer, source, source_sha256, observed_at}`. With `--prior`,
a record the runs root no longer holds is carried forward with `carried: true`. A finding whose
receipt survives but whose coordinator item was pruned keeps the prior ledger's richer label
(a decided item beats a turn verdict, which beats a pending item, which beats none) and its PR
fields, marked `labels_carried: true`. A live item-table observation is never overridden, and PR
states are re-joined after the merge so carried PR URLs are observed too. A record whose content changed names the prior content
digest in `supersedes`. Reusing `--prior` on every run is what makes the ledger outlive the
coordinator's 30-day item pruning and 200-turn window.

Verdicts from coordinator status: `new`/`classified` -> `pending`, `fixing` -> `confirmed`,
`dropped` -> `refuted`, `deferred` -> `deferred`; any other status is kept in `status_raw` and
labelled `unknown`, never guessed. An item already pruned from the table recovers its verdict
from the retained turn outcomes (`status_raw: pruned`) and still joins its worktree and PR.
Findings from lanes with no coordinator are `unjudged`. A receipt or state file that is
unreadable, or whose coordinator overlay fails, is listed under `problems` and the lane falls back
to receipt-only findings; wrong-typed fields degrade to nulls rather than aborting the run.

`fingerprint` is autonomy-v2 C8's identity: sha256 of repo | recipe | normalised path | line
bucket (`line // 20`) | first 12 normalised claim words, truncated to 12 hex. The coordinator
does not compute it yet; this is the reference definition. `cluster` is the same without the
recipe.

## Sealed hold-out

`split` is a salted hash of `cluster`, 20% hold-out. Keying on the recipe-free cluster keeps a
finding re-reported by another recipe with the same path, line bucket and first twelve
normalised claim words on one side. It does not catch the same defect described in different
words or 20+ lines apart; that leakage is bounded, not excluded. `metrics` reads only `dev`
unless `--split holdout|all` comes with `--unseal REASON`, which is echoed in the output. Every
metrics run prints a `holdout_manifest` (cluster count and digest of the hold-out cluster set,
no labels), so a tuning run can show which hold-out it never read. The set grows as the swarm
finds more; compare digests only between runs over the same ledger.

## Metrics

- **Precision** = confirmed / (confirmed + refuted), with `beta = [1 + confirmed, 1 + refuted]`
  for a Thompson sampler, by recipe, by repo x recipe x runtime x effort, and by judge.
- **Coordinated fraction** = findings that reached a coordinator (any status) / all findings;
  **decided fraction** = confirmed + refuted / all findings. The `precision_by_*` groups cover
  coordinated findings and show pending/deferred counts beside the decided ones.
- **Closure rate** = terminal findings / coordinated findings. Terminal: refuted, or confirmed
  with its PR merged or closed unmerged.
- **Matured merge**: `reverted: false` observed at least 7 days after the merge (each PR entry
  records its own `observed_at`). Merged less than 7 days before `--as-of` is
  `merged_maturing`; anything else unproven is `merged_revert_unchecked`, never matured.
- **Rediscovery**: repeat sightings, and sightings of a refuted finding in jobs that started after
  the verdict (the waste C8 verdict memory removes).
- **Jobs** by mode x recipe x runtime x effort: failure rate, elapsed p50/p90, findings per job,
  top terminal reasons. **Turns** by kind x runtime: not-ok, timeouts, seconds p50.
- **Not measured, stated in the output:** avoidable idle (needs supervisor idle intervals) and
  seeded-fault review recall (needs a seeded corpus).

## PR state and reverts

`fetch-pr-states` is the one networked step: GitHub REST through `gh api`, one pull read per PR
and one search per merged PR, paced under the search rate limit. A revert is recognised only by
GitHub's own revert-PR body ("Reverts owner/repo#N", searched `in:body`) on a merged PR. A failed
probe or a non-object response leaves the state null with the error.
`extract --pr-states` joins that file on PR URL.

```powershell
$L = "$env:USERPROFILE\.estate\outcome-ledger"
py -3 scripts\outcome_ledger.py extract --runs-root "$env:USERPROFILE\muse-swarm-runs" --out "$L\ledger.jsonl" --prior "$L\ledger.jsonl"
py -3 scripts\outcome_ledger.py fetch-pr-states --ledger "$L\ledger.jsonl" --out "$L\pr-states.json"
py -3 scripts\outcome_ledger.py extract --runs-root "$env:USERPROFILE\muse-swarm-runs" --out "$L\ledger.jsonl" --prior "$L\ledger.jsonl" --pr-states "$L\pr-states.json"
py -3 scripts\outcome_ledger.py metrics --ledger "$L\ledger.jsonl"
```

## First baseline (B-015, 2026-09-27)

Measured over the owner's live runs root at 18:15Z, with PR states fetched the same minute. The
ledger stays private; its sha256 was
`adb1b90fb1ed045e107dbf5f3521034ae3b7c4dca33704069b3ea389e69b3da1`. Numbers are over all splits
(`--unseal "B-015 baseline"`), because this is the baseline record, not a tuning run.

- 1,148 jobs, 18 coordinator turns across 3 coordinated lanes, 3,417 findings. Every coordinator
  item joined to its receipt (`unjoined_items` 0).
- **88.6% of findings never reached a coordinator** (3,029 in lanes without one). Coordinated
  fraction 11.4%; **decided fraction 2.0%** (67 findings), with 319 still pending triage.
- Judge-agreed precision 0.343 (23 confirmed / 44 refuted). By recipe: **bug-hunt 0.818 (9/11),
  test-gaps 0.333 (12/36), review-range 0.25 (1/4), doc-drift 0.062 (1/16).**
- By judge: muse 0.526, codex 0.286, grok 0.25. Confounded by which lanes each judged, so it is
  a calibration question, not a ranking.
- Job failure rate by effort: high 1.6% (16/1,013), xhigh 3.6% (3/84), **max 21.2% (7/33)**,
  mostly stream idle timeouts and missing terminal events.
- Closure 0.142 (55/388). All 11 swarm PRs merged on 2026-09-27 while the coordinator still
  recorded them as `published`; all 11 are `merged_maturing`.

What this means for routing: doc-drift lenses cost triage turns for almost no confirmed
defects, and `max` effort buys a failure rate thirteen times that of `high`. Both are small
samples; the Beta parameters say how small. The largest lever is not precision but throughput
of judgment: 98% of findings carry no verdict yet.
