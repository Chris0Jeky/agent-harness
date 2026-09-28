# charter-replay (provisional name)

Compare coding-agent command policies against a pinned replay corpus and catch decision regressions before release.

<!-- Demo GIF placeholder: a 60-90 second recording is not made yet. -->

```bash
python -m pip install .
```

```bash
charter-replay hooks   --baseline "python examples/toy-guard/guard_v1.py"   --candidate "python examples/toy-guard/guard_v2.py"   --corpus replay_v0/corpora/charter   --output reports/demo
```

> This re-evaluates recorded command events and decisions. It does not reproduce the original agent, environment, shell effects, or operating-system boundary.

## Measure a hook

`charter-replay hooks` runs two PreToolUse command hooks over a corpus and
diffs their decisions: newly blocked, newly allowed, unchanged, and newly
indeterminate (errors and timeouts), broken down by case class and family. It
exits 1 when a class named by `--fail-on` appears (default: newly allowed or
newly indeterminate). `record` runs one hook and writes a recorded decision
source that the kernel `replay` command accepts as `recorded:<path>`.

Each hook runs once per command, as the runtime runs it: shell-free argv, the
PreToolUse JSON on stdin, `cwd` inside a fresh workspace (optionally copied
from `--workspace`), and `CLAUDE_PROJECT_DIR` set to that workspace. A hook
command is a JSON array or POSIX-quoted words. On Windows, `py -3` works as the
interpreter and forward slashes avoid quoting trouble.

| hook reply | outcome | replay effect |
|---|---|---|
| exit 2 (stderr is the reason) | deny | deny |
| exit 0, no output, or JSON with no decision | allow | allow |
| `permissionDecision` allow / deny | allow / deny | allow / deny |
| `permissionDecision` ask | ask | `--ask-as` (default deny) |
| legacy `decision` approve / block | allow / deny | allow / deny |
| `continue: false` | stop | deny |
| any other exit code | crash | indeterminate |
| exit 0 with unreadable output | invalid-output | indeterminate |
| no reply within `--hook-timeout` | timeout | indeterminate |
| executable cannot start | start-failed | indeterminate |

The outcome is the prefix of each recorded reason, and `outcomes.jsonl` keeps
the exit code and latency per event. The runtime itself lets a command proceed
after a crash or timeout; indeterminate keeps those visible instead. With
`--runtime codex`, `ask` becomes deny, because Codex has no ask decision; the
payload is the same PreToolUse shape, which is only verified against hooks that
accept both runtimes.

`charter-replay import` builds a private corpus from local Claude Code and
Codex transcripts. It scrubs credentials, home paths, the local user, host and
Git identity, email addresses, private hosts and repository names, and it
refuses to write inside a Git work tree unless Git ignores the target. The
output is private even after scrubbing: never commit it.

## Kernel reference

The comparison kernel, its schemas, exit codes and reproducibility limits are
documented in [README.md](README.md).
