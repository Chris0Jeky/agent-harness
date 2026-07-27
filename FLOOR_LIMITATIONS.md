# Deny-floor known limitations

The floor is **FEATURE-FROZEN** (BLUEPRINT §2; decision record: issue #96, ratified in #92).
This file is the ledger of its known bypass families: shapes the argv parser does not model
and — under the freeze — will not grow to model. The SPECS §6 charter matrix still blocks in
canonical form (CI-asserted by the smoke suite). Once open PR #71 lands, several families
below will additionally be pinned in both directions by its
`tests/test_prefix_wrapper_crossproduct.py`, which fails `UNEXPECTEDLY FIXED` if a documented
bypass starts blocking — until then the pin is pending, not live. A new discovery gets one line
here plus a closed issue, never a fix — unless it regresses the charter matrix as literally
written. The walls remain branch protection and restricted toolsets (BLUEPRINT law 5); the
floor is a tripwire, not a sandbox. Budget: this ledger caps at 120 lines; overflow rotates
to `archive/floor-limitations-<year>.md` (laws 3/4).

## Surfaces the floor never sees (it inspects only Bash argv)

- **Non-shell secret writers** — the floor inspects only Bash argv, so secret-file mutation via structured Write/Edit/notebook/file-MCP payloads or a native-API writer inside an interpreter is not seen; shell-form secret writes remain blocked (#2). The native Claude PowerShell tool surface is the same boundary, tracked open as #88 because its remedy is adapter/matcher wiring, not a floor rule.
- **Environment inherited from outside the inspected command** — in-line `GIT_CONFIG_*`/env forms are parsed, but an argv-only PreToolUse hook cannot see configuration or refspec overrides exported by a parent process or an earlier session (#6).
- **Git ref/object-selection environment on pushes** — a scope declaration rather than a recorded bypass: variables such as `GIT_NAMESPACE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_REPLACE_REF_BASE` and `GIT_SHALLOW_FILE` can change what an allowed push reads or transmits without changing the resolved remote, and are outside the parser contract (#8).
- **Detached-worktree state behind a plain removal** — whether the target of `git worktree remove <path>` holds a detached HEAD (whose commits die with the tree) is repository state, not argv; the graduated allow leans on law 7's `git switch -c` mandate as the guard, and the loss is measured and pinned by the fixture's detached leg rather than gated (#122).
- **Repository/user config that blinds the removal clean check** — `status.showUntrackedFiles=no` set in repo-local, user, or system configuration disables the untracked-file refusal that plain `worktree remove`'s allow leans on, invisibly to argv. A catch-all `core.excludesFile` blinds the identical check the same way. The argv-visible spellings are gated on the work-loss ladder (1.6.20): both keys, every `-c`/`--config-env` form, and **any dynamic `-c`/`--config-env` argument whatever key it names** — an unquoted value resplits after expansion, so an unwatched key proves nothing about what git actually runs. The ambient-config remainder is this line (#123). Scoped deliberately narrowly: under the feature freeze a limitation line is how this repo declines a fix, so one that over-states the limit ships a fixable gap as a documented non-fix.

- **Object provenance behind an attributed sensitive-root push** — the issue-#48 narrowing lets a
  repository declaring `sensitive_data: false` push its own named local branches to its own
  configured remote even when the session root is sensitive. Whether those branch objects were
  first fetched from somewhere else is repository state, not argv: a branch deliberately created
  from foreign objects rides the exemption. The ratification accepted this residual — the floor
  attributes names, it does not audit provenance (#48; pinned as allowed by
  `tests/test_sensitive_push_narrowing.py`).

## Wrapper, launcher, and interpreter laundering

- **Wrapper / launcher and uninspectable-file laundering (the standing catch-all)** — the argv-only floor models a bounded set of command wrappers and file-writing tools, so charter-irreversible commands relaunched via unmodelled launchers (`screen -dm`, `firejail`, `parallel`, `tmux new-session`, `at`, `script -qc`, `expect -c`), via unmodelled writers, or via `xargs -a <file>` (a mutating operand supplied by a file or stdin, never visible in argv) are not seen — `source` and `bash <file>` forms instead FAIL CLOSED as opaque shell input — and canonical forms still block (#9; #5's residual `xargs`/stdin case is this line).
- **Wrapper and shell-shape laundering generally** — `bash -c --`, multi-heredoc receivers, `cmd start`, exported Git config, and attached `gh api` methods are now handled, but the parser models a bounded set of shapes and new wrapper/interpreter/encoding forms are expected to pass through unmodelled (#7).
- **Container-exec and remote-shell wrappers** — `docker exec|run`, `docker compose exec`, `podman/nerdctl/lxc exec`, `kubectl exec`, `distrobox enter` and `ssh [-t] host CMD` are not unwrapped, so ~961 of 1,181 deny-corpus payloads pass through them at every tier; only the whole-command secret-file scan survives (#56).
- **Inline-program interpreters** — `perl -e`, `python -c`, `node -e` and `awk 'BEGIN{system()}'` are not unwrapped, so an argv-visible payload passes: ~986–990 of 1,181 deny-corpus cases stop denying, and a payload quoted as a string literal of the embedding language also evades the whole-command secret-file-write scan; two quote-bearing charter probes are unmeasured (#67).
- **Launcher-prefix head anchoring** — rules that resolve the command head (git trace-env poisoning, tool `-o`/`--output` secret writes, brace-expansion secret targets, glob/regex refspecs, arity confusion) stop firing once `nohup`/`nice`/`timeout`/`env`/`taskset`/`flock`/`watch`/`wsl` or a leading `VAR=value` occupies argv 0; 187 verified pairs, all denying in bare form (#68).
- **`cmd /c` + nested POSIX interpreter** — a payload inside `cmd /c "bash -c '…'"` (or `sh`/`dash`/`pwsh`/`wsl`, and `-c`-taking launchers like `flock`/`script`/`trap`/`ssh ProxyCommand`) is treated as inert single-quoted data by the quote-strip and is not judged; 25 verified pairs, all denying at one nesting level (#69).
- **Unquoted path-qualified Windows launcher (DOS 8.3 / backslash paths)** — POSIX shlex eats the backslashes, so `C:\Progra~1\Git\bin\bash.exe --noprofile --norc -lc '<cmd>'` is not recognized as a POSIX-shell head and its payload skips nested inspection (a force-push canary allows); bare `bash` and quoted long paths still deny (#82).

## Shell-shape gaps in modelled rules

- **Quote-masked payloads inside unmodelled PowerShell scriptblock/expression shapes** — `if ($true) { iex '<cmd>' }`, `… -and (iex '<cmd>')`, and compound assignment `$x += iex '<cmd>'` reach neither body-inspection call site nor the assignment unwrap, so any charter command (force-push, `rm -rf` outside project, pipe-to-shell) is allowed wrapped while denied bare; ~1,062 of the 1,071 smoke deny cases bypass this way on 1.5.3/1.6.0/1.6.1, re-confirmed live against 1.6.12 in the 2026-07-26 triage (#37).
- **Leading redirection before a shell head** — `has_opaque_posix_shell_input` reads its evidence after `strip_leading_command_redirections` has consumed it, so `< payload.sh bash`, `<<<'…' bash` and `< <(…) bash` hand a POSIX shell uninspected program text while the canonical `bash < payload.sh` denies (#75; non-freeze sub-items spun out to #95).
- **Unterminated process-substitution operand under a prefix** — the fail-closed deny for an undecidable `< <(printf \( )` operand fires only when the redirect is token 0; a leading newline, a subshell, or `taskset`/`flock`/`watch`/`wsl` in front of it drops the deny (#79).
- **Clobber-redirect prefix (`>|`) + glob/character-class force refspec** — a `>|` write-redirect prefix desynchronizes the push argument walk, so glob-spelled force refspecs (`git push origin [+]main`, `--for* main`) allow; the explicit `--force` flag and the five other redirect spellings still deny (#80).
- **Raw file writes to `.git/config` / `.git/hooks/*`** — the floor guards `git config`, `git -c` and `GIT_CONFIG_*` but not a redirect/`Set-Content`/`tee` into the config or hooks files, so execution- or destination-bearing keys (`core.fsmonitor`, `core.hooksPath`, `remote.*.push`, `diff.external`, aliases) can be planted and fire on a later benign git command; push-time force on a refspec-less push is still caught by `configured_bare_push_is_dangerous()` — a bounded residual: it covers bare pushes only and fails open when the resolver deadline is exhausted (#27).

## What stays actionable under the freeze

False-positive fixes (`floor-fp` label: #12, #65, #77, #81, #90), the ratified #21 slice
sequence (`floor-slice` label: #26 → #41 → #62 [folds #17, #32] → #24 → #38/#58 → #48/#59),
charter-scoped #3 (repairable under freeze class (c)),
and everything outside the floor's rules (doctor, docs, adapter contract, measurement — e.g.
#74, whose fix rides PR #71). Decision record and full triage: issue #96.
