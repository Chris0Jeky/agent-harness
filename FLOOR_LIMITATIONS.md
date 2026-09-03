# Deny-floor known limitations

The floor is **FEATURE-FROZEN** (BLUEPRINT §2; decision record: issue #96, ratified in #92).
This file is the ledger of its known bypass families: shapes the argv parser does not model
and — under the freeze — will not grow to model. The SPECS §6 charter matrix still blocks in
canonical form (CI-asserted by the smoke suite). PR #71 merged as `21485bc`; its
`tests/test_prefix_wrapper_crossproduct.py` now pins the named families in both directions and
fails `UNEXPECTEDLY FIXED` if a documented bypass starts blocking. A new discovery gets one line
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

- **Cross-segment state is lost by the masked-segment re-check** — when an early segment denies as pure opacity under the guide posture, `masked_segment_verdict` re-checks each LATER segment on its own, so the alias, process-environment, cwd and repository state `check()` builds while walking one command text is not there. A verdict that depends on an earlier segment therefore does not fire: measured on 1.6.31, 1.6.32 and 1.6.33 alike, `alias gc='git config core.sshCommand helper'; gc` denies as a double-check while `echo hi > $target; alias gc='git config core.sshCommand helper'; gc` allows. Not a 1.6.32 regression — the parent allowed both masked forms — and a segment that is guarded on its own (`export GIT_EDITOR=helper`) still reaches the analyzer. The reporter's `EDITOR=helper; git commit` example does not reproduce in either direction: `EDITOR`/`VISUAL` are inherited fallbacks, not mutations, and that command allows bare too (#266).

## Scope limits of modelled rules

A rule the parser DOES run, whose pattern set is narrower than the charter sentence naming it.
Not a shape gap: the shapes were crossed and made no difference.

- **Secret-file detection matches NAMES, not extensions** — `is_secret_path` / `_SECRET_FILENAME` match `.env`/`.envrc` and their `.env.<suffix>` spellings, any path containing `credential`, an UNANCHORED `secret.`/`secrets.` substring, the `id_rsa|id_dsa|id_ecdsa|id_ed25519` key names, and exactly one extension, `*.pem`. The `secrets?\.` fragment carries no `^`/boundary anchor, so it fires at ANY position, not only as a prefix — measured: `my-secret.txt`, `app-secrets.json` and even `notsecret.txt` all match, so real coverage is WIDER than a prefix reading suggests. Every other conventional secret EXTENSION is unmatched, so mutating one allows at every tier. Measured on floor 1.6.27 through `smoke_test.run_case` (the smoke suite's own subprocess entry point): `rm prod.key`, `rm prod.secret`, `rm prod.p12`, `rm prod.pfx`, `rm prod.jks`, `rm prod.keystore`, `rm prod.crt`, `rm prod.ppk`, `rm prod.asc`, `rm prod.gpg`, `rm prod.kdbx`, `rm prod.netrc` and `rm prod.env` ALLOW at T1/T3/T4, and so does each in its `echo x >` write form; `rm prod.pem`, `rm .env`, `rm .env.production`, `rm .envrc`, `rm credentials.json`, `rm secret.txt`, `rm secrets.json`, `rm key.pem` and `rm id_ed25519` DENY at T1/T3/T4. Crossing the uncovered payloads with the canonical, quoted-operand, `bash -lc`, `pwsh -Command`, `env`-prefix and pipeline shapes moved no verdict except where the unrelated pipe-delete rule fires (`echo start | rm deploy.key` denies as `Piping into Remove-Item/del`, for any operand — `rm notes.txt` denies identically), so this is a pattern-set boundary, not laundering (#130).
- **SPECS §6's `*secret*` glob is honoured only where `secret`/`secrets` is followed by a dot** — the match is positional-free but requires the trailing `.`, so `my-secret.txt` denies while the extension spelling does not. Read as a literal glob the charter's `*secret*` matches `my.secret`, and the floor does not: `echo tok > my.secret` allows at every tier while `echo tok > secret.txt` denies. This is a day-one divergence, never a regression — the repo's first commit `c87e906` already spelled the rule `secrets?\.|…|\.pem$` and its SPECS §6 already said `` `*credentials*`/`*secret*` `` — so BLUEPRINT §2 class (c), "a listed must-block form NEWLY allowed", is not met and the freeze's default (a ledger line, never a fix) governs. **Assumption: §6's `*credentials*`/`*secret*` are read as NAME patterns, matching the shipped implementation, so the extension spelling is out of scope rather than broken. Reason: the OPERATIVE FRAGMENTS have been stable together since commit 1 — `c87e906` spelled the rule as a local `secret_rx` whose overall text has since changed materially, but its `secrets?\.` and `\.pem$` fragments and §6's `` `*credentials*`/`*secret*` `` wording are unchanged throughout — which makes the implementation better evidence of intent than a strict glob reading. The surrounding regex was NOT byte-stable, and this line no longer claims it was. Reversible by: the owner ruling the other way on #130, which reclassifies this line as a class-(c) charter repair.** `.key` in particular is not free to add — it collides with non-secret files in real ecosystems — so a tightening would owe a false-positive sweep first (#130, open for that ruling).

- **`gh api` request bodies and GraphQL under `sensitive_data`** — the 1.6.28 narrowing reads only
  argv: a visibility flip inside `--input file.json` / `--input -`, a quoted GraphQL
  `createRepository(... visibility: PUBLIC)`, a REST force-update (`PATCH .../git/refs/heads/main
  -F force=true`) and repo `transfer`/`forks`/`generate` are not seen (#259; measured on PR #257).
- **A bare tag name in a remote deletion** — `git push origin --delete v1.0` with no branch of that
  name deletes the tag; whether a bare name is a branch or a tag is repository state, not argv
  (#259). The `tags/`/`heads/` prefix spellings are a defect, not a limitation, and are fixed
  producer-first in the floor version after 1.6.29.

## What stays actionable under the freeze

False-positive fixes (`floor-fp` label: #12, #65, #77, #81, #90), the ratified #21 slice
sequence (`floor-slice` label: #26 → #41 → #62 [folds #17, #32] → #24 → #38/#58 → #48/#59),
charter-scoped #3 (repairable under freeze class (c)),
and everything outside the floor's rules (doctor, docs, adapter contract, measurement — e.g.
#74, whose fix rides PR #71). Decision record and full triage: issue #96.
