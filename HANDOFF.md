# agent-harness session handoff - 2026-07-26

This is the single resume source for the unfinished PR #71 repair. The session was
explicitly stopped before the branch was review-ready.

## Resume here

- Repository: `C:\Users\jekyt\source\agent-harness`
- Writer worktree:
  `C:\Users\jekyt\source\agent-harness\.worktrees\crossproduct-gate`
- Branch: `test/crossproduct-gate`
- Local base before the checkpoint commit: `61478e3f4ba5e93fd385983912ab79f96d2fb934`
- Remote PR: [#71](https://github.com/Chris0Jeky/agent-harness/pull/71)
- Remote PR head: `922cde3eb5d619558b71daba5af8dfa4c819a963`
- Current `origin/main`: `4b7d81b811b6336d9ec44fba294b39e0eb96ff43`

The writer worktree is the only checkout that owns these edits. Do not reset, clean,
restore, stash, or recreate it. Start with:

```powershell
Set-Location -LiteralPath 'C:\Users\jekyt\source\agent-harness\.worktrees\crossproduct-gate'
git status --short --branch
git log -3 --oneline --decorate
```

## Status

PR #71 is open and non-draft. Its remote head `922cde3` has green historical
three-OS CI, but that evidence applies only to the old remote bytes. The repair work
below is local-only. It has not been pushed, connector-reviewed, or checked by hosted
CI. Do not merge.

The local branch merged current `origin/main` at `61478e3`, then accumulated the
review repair across:

- `SPECS.md`
- `templates/hooks/dispatch.py`
- `templates/hooks/smoke_test.py`
- `tests/test_command_prefixes.py`
- `tests/test_prefix_wrapper_crossproduct.py`
- this handoff

The session closes with a local WIP checkpoint commit. It is intentionally not pushed
because the broad cross-product still has known failures.

## What the local repair contains

The repair addresses the 13 unresolved Codex threads on the old PR head and the
second-order findings exposed by adversarial Terra review:

- Honest 99-shape prefix/wrapper composition with explicit deny and benign
  applicability, exact reason ledgers, live/disjoint exception ledgers, and
  bidirectional coverage.
- Redirect-target provenance across quoting, descriptors, process substitution, and
  nested interpreter dialects.
- Literal redirect operators preserved as argv data through launcher, scriptblock,
  direct-process, `eval`, `call`, `cmd /c`, and job boundaries.
- `watch` default mode modeled as argv concatenation followed by `sh -c`; `watch
  -x/--exec` remains direct argv.
- A paired marker now keeps a cmd double-quoted redirect span from widening over an
  adjacent suffix. Focused tests cover adjacent `$`, backtick, and literal-quote
  characters.
- Invalid stop-parsing shapes and several inaccurate wrapper templates were removed or
  corrected.

The hook floor version in the working dispatcher is 1.6.16. The checked-in Codex hook
pin has not been refreshed because dispatcher bytes are not final.

## Exact verification at stop

Verified on the final checkpoint bytes:

- `py -3 -m unittest tests.test_command_prefixes.LiteralRedirectionOperatorTests -v`
  - 11/11 passed.
- Black reported `dispatch.py` and `test_command_prefixes.py` already formatted.

Verified before the final paired-marker patch, so stale and mandatory to rerun:

- `py -3 -m unittest tests.test_command_prefixes -v`
  - 48/48 passed.
- Black, Ruff, Python compile, and `git diff --check` were clean.

Known failing broad run before the final paired-marker patch:

- `py -3 -m unittest tests.test_prefix_wrapper_crossproduct -v`
  - 39 tests run; 37 passed and 2 failed.
  - The deny direction reported 32 `watch` failures plus 19 `watch` entries that
    became unexpectedly fixed.
  - The benign direction reported 50 failures. Some taskset/flock failures came from
    the adjacent-suffix marker defect now covered by the 11/11 focused test; the suite
    has not been rerun to prove which remain.

Not verified on the final checkpoint bytes:

- Full `tests.test_command_prefixes`
- Full cross-product
- Full unittest discovery
- Canonical smoke suite
- `harness.py doctor`
- Current Ruff/compile/diff check
- Hook hash pins
- Luna read-only audit
- Hosted CI or connector review
- Live `/hooks` activation and allow/deny canaries

## First technical decision next session

Do not paper over the remaining `watch` failures with broad baselines. Default GNU
`watch` concatenates argv and reparses it with `sh -c`, so it does not preserve all
payload quoting:

- A nested interpreter program that was one quoted argv word may be split into a
  different command.
- `watch echo ">" .env` becomes active redirection after argv concatenation; denying
  that composition is correct even though the bare command allows.
- Direct brace/glob/refspec payloads now reach more charter rules, so the 19 old
  `watch` case-bypass entries may genuinely be removable.

Tighten the `watch` shape's applicability to compositions that are semantically
equivalent, or model default and `--exec` as distinct shapes. Then remove only
exceptions the bidirectional tests prove obsolete.

Terra's final review also established:

- The Git inline-alias `shlex.join` path is unreachable because every literal
  `alias.*` inline config is denied earlier. Leave that dead path out of this repair.
- A nested PowerShell expandable-string/subexpression false deny is pre-existing on
  `origin/main`; it belongs in a searched/deduplicated follow-up issue, not a claim
  that PR #71 fixed it.

## Counts and documentation

Before the final marker test addition, the read-only count audit measured:

- 25 prefix + 74 wrapper = 99 shapes
- 1,077 deny cases; 461 benign cases (443 from smoke)
- 71 enforced shapes; 90 transparent shapes
- 68,227 applicable enforced/deny pairs
- 38,992 applicable transparent/benign pairs

`SPECS.md` still contains stale counts and ambiguous wording. Recompute after the
`watch` predicates and smoke corpus are final. Also update the worst-shape comments:
the pre-checkpoint measurement was 72.61% deny reach and 81.13% benign reach.

## Resume sequence

1. Reconcile this handoff with live Git/GitHub state and inspect the checkpoint diff.
2. Run the full command-prefix and cross-product modules.
3. Repair only the remaining semantic failures, beginning with `watch` applicability.
4. Ask Terra for a fresh exact-tree adversarial review; run the unavailable Luna route
   through a read-only ephemeral Codex invocation if it is still available.
5. Freeze corpus counts and update `SPECS.md` and this handoff.
6. Compute the normalized dispatcher hash and update both pins in
   `.codex/hooks.json`.
7. Run all required checks:

   ```powershell
   py -3 -m unittest discover -s tests -v
   py -3 templates\hooks\smoke_test.py
   py -3 harness.py doctor
   ```

   Also run Black, Ruff, Python compile, and `git diff --check`.
8. Commit any final repair as a small present-tense commit, push normally, and update
   PR #71 without changing its issue linkage (`Closes #63` only).
9. Request `@codex review`, triage every existing and new thread, and require
   independent review plus exact-head three-OS CI after the last head change.
10. Stop at the human merge gate. Do not merge.

Only after PR #71 is merge-ready should issue work resume. The latest suggested order
is #75, #80, #79, #82, #77, then #26, #41, #62, #24, #38/#58, and #48/#59. Search for
duplicates before creating the PowerShell nested-dialect follow-up.

## Human-owned actions

These remain open in `HUMAN_TODO.md`; only the human checks them off:

1. H-1: deploy floor 1.6.12 to `~/.claude/hooks`.
2. H-2: after deployment, open a fresh exact-CWD session, verify `/hooks`, and run
   live allow/deny canaries.
3. H-3: resolve dirty `~/.claude/settings.json`, then push pending commit
   `e42e211`.
4. H-4: prune accumulated worktrees manually until #41 lands.
