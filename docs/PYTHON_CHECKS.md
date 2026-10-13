# Python check inventory

`scripts/python_check_files.json` is the single ordered list of Python files
checked by the root CI Verify job. Add a new module or test here once, rather
than editing three commands in `.github/workflows/ci.yml`.

Run the same commands locally from any working directory by naming the launcher:

```text
python scripts/python_checks.py ruff
python scripts/python_checks.py black
python scripts/python_checks.py compile
```

The launcher uses its active Python interpreter and the repository working
directory, passes filenames as separate arguments without a shell, and returns
the selected tool's exit status. Missing tools, missing files, malformed paths
and duplicate inventory entries fail rather than silently shrinking coverage.
The commands use development tools pinned in `requirements-dev.txt`; this helper
does not install tools or change the environment.

The migration retains all 76 previously curated paths in their original order,
then adds the launcher and its test. Black also keeps its pre-existing recursive
`replay_v0` argument. The separate replay jobs, three supported host runners,
unit/smoke commands, job timeouts, dependency pins and permissions are unchanged.
This remains a curated inventory, not automatic discovery of every Python file.
It removes repeated workflow edits; simultaneous additions to the inventory can
still require an ordinary merge reconciliation.
