# Harness Specs

Last Updated: 2026-07-26 · Concrete schemas and drafts referenced from [BLUEPRINT.md](./BLUEPRINT.md).

## §1 Global `~/.claude/CLAUDE.md` — the shipped law set

Ratified 2026-07-26 (issue #92; mirrored from claude-config branch `policy/autonomy-first`,
tip `734d007`). The claude-config repo (`~/.claude`, its own T3 repo) is the CANONICAL home;
this section is a dated reference mirror so the harness repo reads stand-alone. On any drift,
claude-config wins and this copy is the bug — refresh the mirror, never fork it. The named
models inside the mirror belong to claude-config's file; this repo's own routing text (§8)
still names no routing-tier assignments (its one model mention is the declared family-wide
Haiku ban). The per-repo memory duplicates the law set graduated are deleted — the last two in
this repo's own memory were folded 2026-07-26. NO shipped check yet measures which guidance
text `~/.claude` actually serves (#98 tracks that gap): this mirror asserts nothing about
deployment.

```markdown
# Global laws — all repos, all tiers

Blueprint: the active sibling `agent-harness/BLUEPRINT.md` checkout · Estate registry: `~/.claude/ESTATE.md`

**What the harness is for.** The harness guards against catastrophe, not against capability.
Hard walls exist only for the irreversible: secret exposure, destroyed work, rewritten shared
history, public leaks. Everything reversible is yours to do autonomously — tiers scale
*verification* with blast radius, they never subtract autonomy. A small or new repo runs free;
a production repo earns extra checks. An autonomous session is judged by finished tasks, and
when ceremony and throughput conflict outside the irreversible core, throughput wins and the
ceremony is the bug — file it as an issue and keep working. Declared authority
(`tier.json`) and the irreversible core are never ceremony.

## Non-negotiable

1. Never merge a PR with failing CI. Investigate every failure; never dismiss as flaky.
2. Every PR gets one real review — and no review loops. Post findings on the PR; triage every
   comment once (bots included). Fix only what blocks a merge: confirmed correctness, security, or data-loss defects (CRITICAL/HIGH). Then
   one verification pass scoped to the fix diff. Everything else — style, MEDIUM/LOW, ideas,
   out-of-scope findings — becomes a tracked issue or a one-line decline on the thread, never a
   fix-commit cascade and never a silent drop; explicitly classify informational / non-finding
   notices without inventing a commit. Two rounds is the ceiling: after them, ship or park —
   only a new CRITICAL introduced by the fixes reopens the pipeline — once, and only for that
   defect; a second reopen parks the PR. Never pause mid-pipeline
   to ask whether to continue — the answer is yes. Publish ready-for-review, never parked in
   draft: draft only while the work is still being written, marked ready the moment it is
   complete, never merged from draft — a draft PR does not invite the bot reviewers. At T3+
   request the Codex review (Codex only, never Copilot) at ready-for-review and once more
   after the final fix round; triage its comments by the same severity bar (optional below
   T3 — but comments that do arrive get the same one-pass triage). Operational detail: the
   `review-and-ship` skill.
3. Never claim done/verified without running the thing that proves it. Always state what was
   NOT verified. Close work with: changed / verified / NOT verified / residual risk.
4. GitHub hygiene: "Closes #N" fires even quoted or negated — verify issue links after body
   edits. Never `--delete-branch` a stacked base PR (cascade-closes children unreopenably).
   In a PR stack, merge the oldest first, never the newest; after a base lands, retarget its
   children and confirm via the API before merging them.
5. Surface the repo's human-action file (HUMAN_TODO.md or its declared alias — see ESTATE.md)
   in every summary. Only the human checks items off. When items accumulate or the human asks
   to be guided, walk the backlog via the `guided-walkthrough` skill (numbered q-N items:
   context + suggested action + step-by-step guide for human-only ones).
6. Questions: batch true blockers into ONE question; otherwise proceed on a named assumption
   ("Assumption: X. Reason: Y. Reversible by Z.").
7. Worktrees: guard preamble is the first action; `$WT_PROJECT_DIR` paths only; create with
   `--detach origin/main`, never branch refs, then `git switch -c <branch>` before committing —
   a detached worktree's commits are held only by its own HEAD and die with its removal; plain
   `git worktree remove` only, never `--force`: a refusal means work is still in there;
   coordinator verifies main is clean after waves.
8. Structure arrives with the second item. Don't build speculative scaffolding. When a lesson
   recurs, promote it up the enforcement ladder (memory → CLAUDE.md → skill → hook → CI →
   structure) to the cheapest layer that actually enforces it — and prune the old copy.
9. Before working in an unfamiliar repo: check `~/.claude/ESTATE.md` (junk wrappers and
   frozen snapshots exist) and the repo's `.agent-harness/tier.json` — a legacy
   `.claude/tier.json` survives in some older repos, and where both exist the strictest
   declaration binds (higher tier, union of tightening overlays; a work-loss guard relaxes
   only when every declaration agrees). Authority is declared, not negotiated. An unregistered
   repo with no production signals (deploys, other users or published consumers, money,
   sensitive data) runs at
   sandbox autonomy — do the work, propose a tier in the handoff; with such signals, propose
   the tier first.
10. Weak-model rails: if you are not the top routed model, never merge, never edit canonical
    docs, the deny floor, or gates. Open PRs and let the gate decide.
11. Every gate loop terminates. Two review rounds (law 2); three genuinely different attempts
    at a red check; one re-measure of a disputed fact; a task parks at roughly twice its
    budget. Then ship what is sound, park what is
    not — tracked issue plus a one-line handoff — and move to the next task. Circling a gate
    is not diligence; it is the failure mode this law exists to stop.
12. Mission first. Harness, floor, gate, and doc work happens when it IS the mission, never as
    a detour from it — friction found mid-task becomes a one-line tracked issue, not a fix.
    A session that polishes evidence but finishes nothing has failed, whatever its rigor.

## Tier ladder (by blast radius)

T0 tombstone · T1 sandbox · T2 daily driver · T3 workshop · T4 live wire
Tiers add verification, never permission: T1/T2 ship on green checks, T3 adds one bounded
independent review, T4 runs the repo's full declared gate.
Overlays tighten posture regardless of tier: `sensitive_data`, `wave_mode`,
`dormant_production`. Details in the blueprint.

## Working style

- **Commit in small, logical increments as you work** — standing authorization; don't wait to be
  asked, and don't bundle unrelated changes. No `Co-Authored-By` / "Generated with" trailers
  (`includeCoAuthoredBy:false` is the settings default — keep it off in every repo).
- **Publish autonomously; merge within your tier's gate.** Standing authorization covers pushing
  scoped branches, opening ready-for-review PRs after relevant local checks, and merging once the
  tier's gate is met: **T1/T2** — proving checks green at the head and comments triaged; that is
  the whole gate, no independent review and no waiting required. **T3** — plus one independent
  review pass at the current head (bot or agent), bounded per law 2. **T4** — the repo's declared
  full gate. These are per-tier defaults — a repo's declared `.agent-harness/tier.json`
  authority binds over them (`merge: gated` / `human-only` means exactly that at any tier, and
  floor/dispatcher changes stay T4-class everywhere). Evidence is scoped, not global: a head
  change re-proves what changed — re-run the checks that exercise it; a fresh review round is
  owed only when the fixes went beyond the reviewed findings or touched new logic. A base
  change counts as a head change: a retarget or a landed stack base moves the merge base while
  the head SHA stays put — re-prove CI and review against the new base before merging. Where no
  CI exists, proving checks are the narrowest commands that exercise the change plus the repo's
  declared gate ritual; a run that never reads the changed files is not a green.
- **Never squash-merge — preserve full commit history and count.** Merge PRs with a merge commit
  (`gh pr merge --merge`, or the GitHub "Create a merge commit" option), never `--squash`. Rebase is
  acceptable (keeps the count) but a merge commit is preferred (original SHAs + a merge marker).
  Squash-merge was disabled repo-side across the estate (2026-07-18); if a repo re-enables it, turn
  it back off. `atlasan/series_tools_python` still needs an admin to disable it.
- **Right-size compute cheapest-dial-first (effort → model → agent count).** The standard:
  **Opus 5 low** is the generalist default; **Opus 5 high** for code implementation, reviews, and
  anything else judgment-heavy — Opus 5 costs what Opus 4.8 did, is far more effective, and per
  *successful* task at low effort is level with Sonnet. **Sonnet 4.6 medium/high** is therefore for work
  genuinely *beneath* Opus 5 low, not a way to save money (**never Haiku** — quality too low; no
  agent pin, CLI flag, config key or env var may select it — `tests/check-agent-models.ps1` enforces
  all four); avoid Sonnet 5 as a
  default. **Fable 5 at high or xhigh** for the really difficult calls that need the most
  intelligence — reserved by value, not rationed by access. Start
  **inline**; fan out only when regions are disjoint / context >20k / an independent lens is needed;
  right-size fleets (≤3–5; ≤8–12 for a sweep) — never a reflexive fleet. Full ladder: the
  `model-effort-routing` skill.

## Machine

Windows quirks and environment fixes live in `~/.claude/MACHINE.md` — read it before fighting
a tool failure that smells environmental (git resolution, PowerShell chaining, vitest OOM).
Its "RAM & MCP hygiene" section binds long or looped sessions on this box: never declare the
same MCP server at two scopes (user + project = two gateways, not one), and a relaunching loop
sweeps leaked MCP stacks between runs (`tools/mcp-hygiene.ps1` in the claude-config repo).
```

## §2 `.agent-harness/tier.json` schema

```json
{
  "tier": 3,
  "name": "workshop",
  "authority": { "push": "free", "merge": "gated" },
  "flags": { "sensitive_data": false, "wave_mode": false, "dormant_production": false,
             "relaxed_work_loss_guards": false },
  "budgets": { "standing_context_tokens": 6000, "session_baseline_tokens": null },
  "human_todo": "HUMAN_TODO.md",
  "last_reviewed": "2026-07-06"
}
```

- `authority.push` / `.merge`: `free` | `gated` | `human-only` (the dial: leave-PRs-open →
  push-gated-like-merge → merge-behind-full-gate).
- `flags.relaxed_work_loss_guards`: declared relaxed-git posture — work-loss guards
  (`reset --hard`, `clean -f`, `checkout -- .`, `restore .`) stay ALLOW below T4/wave_mode
  instead of the T3 ask. IGNORED at T4 and under `wave_mode`; the irreversible floor is
  unaffected. Reference repo: wealthlens-hq (the estate's written sub-T4 git-freedom spec).
- `model_routing` is NOT part of the schema: `seed` no longer emits it. The model ladder lives
  in ONE place (BLUEPRINT §5 / SPECS §8); a per-repo copy is a third place for it to go stale.
  Repos seeded before 2026-07-25 still carry a `model_routing` block — it is inert, read by
  nothing, and `audit`/`doctor` ignore it rather than failing on it.
- Read by: dispatcher hook (`tier`, `flags`), Gardener, bootstrapper, CI templates. The
  dispatcher also reads legacy `.claude/tier.json` files so existing estates can migrate
  without a flag day.
- Two co-located declarations bind to the STRICTEST union, never to the first one found
  (law 9; `dispatch.load_tier`; `harness.merge_tier_declarations`): highest `tier` wins,
  tightening flags and the strictest `authority` dial are unioned, and the one relaxation
  (`relaxed_work_loss_guards`) applies only when EVERY declaration sets it. Non-posture fields
  (`name`, `human_todo`, `budgets`, `last_reviewed`) come from `.agent-harness/tier.json` when
  it declares them; each file is still validated on its own.
- The human-readable `Tier: workshop (T3) — authority: push free / merge gated` line at the
  top of repo CLAUDE.md is GENERATED from this file by `harness audit` (never hand-edited);
  the budget script fails if they disagree.

## §3 Budget table (enforced by `check-budgets.mjs`, ~80 lines)

| Artifact | Cap | On overflow |
|---|---|---|
| repo CLAUDE.md | T1 ≤40 / T2 ≤100 / T3+ ≤150 lines | rotate detail to linked docs |
| AGENTS.md (rulebook, T3+) | ≤80 lines | one home per policy; link out |
| "now"/STATUS doc head | ≤150 lines | rotate to `docs/archive/status-YYYY-MM.md` |
| MEMORY.md index | ≤30 lines / ≤3KB | fold + prune (Gardener) |
| SKILL.md | ≤80 lines (target 60) | split or demote to doc |
| AGENT_MAP.md | ≤100 lines | split into `docs/regions/*.md` |
| FLOOR_LIMITATIONS.md (deny-floor ledger) | ≤120 lines | rotate to `archive/floor-limitations-<year>.md` |
| directory CLAUDE.md | ≤30 lines | move detail to region map |
| global CLAUDE.md | ≤130 lines | it's the law layer, not a manual — rotate working-style detail into skills |
| total standing harness (T3) | ≤500 lines | demote something |

Failure message contract: emit a **ROTATE instruction naming the archive target** — never
"trim to pass". Enforcement points: CI job (T3+) and a PostToolUse(Edit) nudge ("over budget:
split/rotate, don't append").

## §4 Skeletons

**Skill anatomy** (every SKILL.md):
```markdown
---
name: <kebab>
description: <1-2 sentence "Use when..." trigger>
---
# <Name>
## Use when / Do NOT use when   <- anti-trigger section is mandatory (routing disambiguator)
## Guardrails                    <- verbatim guard phrases, e.g. "Do not claim a path is
                                    verified if you only reasoned about it"
## Workflow                      <- numbered, atomic; never pauses mid-pipeline
## Read first                    <- ONLY region map + STATUS head; never >200-line docs;
                                    never auto-injected files
```

**AGENT_MAP.md row**: `| domain | entry points | invariants | verify command | do-not-read |`
plus the Minimum Handoff Shape: `Changed / Verified / NOT verified / Failures+workarounds /
Docs sync / Next safe slice`.

**Directory CLAUDE.md** (≤30 lines): what this region is, its invariants, its verification
command, `Region map: docs/regions/<domain>.md`, and any region-local rules. Nothing global.

**HUMAN_TODO.md**: IDs (`H-1`, `H-2`…), one line each + link; `## Changelog` at bottom;
rules header: read at session start, surface in every summary, human-only check-off.

**Tombstone CLAUDE.md** (3 lines): `Tier: T0 TOMBSTONE` / `FROZEN <date> — do not develop
here.` / `Live successor: <path or "none">`.

**REVIVAL.md** (≤20 lines): how to run, known hazards, data locations/backups, re-seed tier.

## §5 Dispatcher hook wiring

The shared dispatcher owns exactly one event: the `PreToolUse(Bash)` deny floor. Claude wires it
globally. Each active Codex repo wires exactly one project `.codex/hooks.json` adapter that pins
the shared `~/.claude/hooks/dispatch.py`; Codex has no global floor matcher. Repo-tier lifecycle
hooks (`PostToolUse`, `PostToolUseFailure`, `SessionStart`, and `Stop`) are separate, repo-owned
executables when a tier actually implements them. Never route those events through the floor
dispatcher or stack global and project floor matchers.

Claude global adapter schematic (Codex project adapters must use the stricter contract below):

```json
{
  "hooks": {
    "PreToolUse": [{ "matcher": "Bash", "hooks": [{ "type": "command",
      "command": "python \"$HOME/.claude/hooks/dispatch.py\" --event pre", "timeout": 5 }] }]
  }
}
```

- For PRE safety decisions with a hook payload `cwd`, deletion containment uses the nearest
  declared ancestor on the payload chain. If that chain is undeclared, an environment
  `CLAUDE_PROJECT_DIR` that lexically encloses `cwd` becomes the boundary even when undeclared;
  otherwise `cwd` itself is the boundary. When the payload omits `cwd`, the nearest declaration
  above `CLAUDE_PROJECT_DIR` (or that directory itself when undeclared) is the boundary.
- Every declaration on both the payload and environment ancestor chains contributes authority,
  even when the chains are unrelated: the highest tier wins, boolean tightening flags are ORed,
  and `relaxed_work_loss_guards` applies only when every applicable declaration enables it.
  Thus a stale or unrelated environment value can tighten policy but cannot widen containment;
  an enclosing environment project intentionally defines the boundary for an undeclared nested
  `cwd`.
- A present `tier.json` must be a readable JSON object with integer `tier` 0-4 and boolean flag
  values. Invalid authority fails closed on PRE; only an absent declaration receives T1 defaults.
- Recursive-delete operands are quote-aware, environment-expanded, and resolved from payload
  `cwd` before canonical containment. Unresolved dynamic/provider paths and relative deletes after
  a location change fail closed; only strict descendants of the native OS temp root are scratch.
  On Windows, ambiguous MSYS/WSL `/c/...` and `/mnt/c/...` spellings fail closed because the same
  text has different PowerShell filesystem semantics.
- `doctor` requires zero deny-floor copies across all statically inspectable global hook sources:
  user and system `hooks.json`, managed hooks in system `requirements.toml`, inline hooks in
  system/base-user and every selectable profile-v2 config, and the legacy managed config file.
  Missing files are absent; unreadable or malformed sources and failed profile enumeration fail
  closed. On Windows the system layer uses the ProgramData known folder with the same default fallback as
  Codex. Every selectable profile-v2 file is audited conservatively because the invoking profile
  is not part of the Python process context.
  A floor is counted only after the complete hook subtree and the source-specific hook metadata
  inspected by the harness pass their static boundaries: the supported JSON object form rejects
  duplicate known fields, non-standard constants, invalid known strings, and invalid wrapper
  fields while traversing ignored unknown values iteratively; every supported event and handler is
  schema-valid; inline config hook state and managed requirements hook paths have their
  source-specific shapes. A managed hook directory must be absolute, and its existence is
  probed — the only filesystem access in the parse path — for a value the running platform
  resolves. A UNC value is exempt from that probe, so an audit never blocks on an unreachable
  network share and that directory's existence stays unproven. Python's stdlib decoder imposes an explicit fail-closed boundary at
  pathological JSON nesting depths before ignored-value inspection. One malformed hook sibling
  invalidates the layer instead of leaving a countable `PreToolUse` floor. The harness does not
  fully schema-validate unrelated ConfigToml or requirements fields; exact Codex startup and
  `/hooks` remain the authority for those fields.
  Managed-cloud and MDM requirements/config, session flags, and plugin hooks remain an explicit
  runtime boundary for exact-session `/hooks`; the static check never represents those sources as
  inspected.
- **The adapter's `expected=<sha256>` value is an AUDIT-ONLY marker, not runtime enforcement.**
  Nothing exports it to the dispatcher and `dispatch.py` takes no expected-hash argument, so it
  proves only that the trusted hook *definition* was written against those dispatcher bytes.
  Consequences, which are mandatory, not advisory: changing `templates/hooks/dispatch.py` obliges
  bumping `FLOOR_VERSION`, refreshing the marker in **every** consumer `.codex/hooks.json`, and a
  fresh-session `/hooks` re-trust per repo in its exact CWD; a rollout PR must enumerate and
  sequence those consumers rather than let their markers go stale silently. `doctor` reports
  marker currency; runtime byte integrity and definition-hash trust are separate evidence, proved
  only by `/hooks` plus a live safe/deny canary. No doc, PR, or commit may describe the marker as
  runtime pin enforcement.
- Codex project adapters must pass `--event pre --runtime codex` directly, or invoke a repo-owned
  wrapper that binds both values. The POSIX and Windows commands must independently invoke the
  shared dispatcher or that wrapper, declare the normalized dispatcher hash marker in a named
  variable, and use a matcher that positively includes Bash. Because Codex runs a hook command
  from the SESSION cwd rather than the hook source root, a repo-relative wrapper path certifies
  only when those directories are the same; from a subdirectory cwd or a linked worktree, `doctor`
  fails that adapter closed and names it. A HOME-anchored wrapper path (`~/…`, `$HOME/…`,
  `$env:USERPROFILE/…`) names the same file from every cwd and certifies everywhere; only literal
  path components are allowed after the anchor, so a `$PWD`-style expansion cannot ride in behind
  it. From the source root itself the same adapter certifies,
  but the cwd dependency is still reported as an adapter-contract note, because it is a property
  of the adapter text rather than of the audit's cwd. The canonical `commandWindows` field and its
  official `command_windows` alias are equivalent; declaring both fails closed. `doctor --repo`
  uses the Git-root layer walk
  only when all inspectable top-level `project_root_markers` declarations in system, base-user, and
  stored profile-v2 configs are absent or exactly `[".git"]`. Any non-default, conflicting,
  malformed, or unreadable declaration fails the marker and project-floor checks.
  CLI and managed-cloud marker overrides are explicitly outside static inspection. Under that
  qualified topology, `doctor` audits every active `.codex` layer from the checkout root through
  the requested directory and both declaration forms Codex loads: `hooks.json` and inline
  `[hooks]` in `config.toml`. Across all active sources it requires exactly one candidate, one
  conservatively recognized execution shape, and one current audit marker. It also reports, per
  candidate handler and platform command, whether the adapter declares no marker, declares a stale
  marker, or never passes `--event pre --runtime codex`; a vendored dispatcher and wrapper flag
  delegation are recorded as inventory notes, not failures. The recognized current floor
  must reside in the canonical root `.codex/hooks.json`; nested layers that contain configuration
  but no hooks are valid. The project floor also fails when inspectable system requirements allow
  only managed hooks or pin the hook feature off, an active persisted canonical/legacy feature
  setting disables hooks, or the exact canonical handler state is disabled. A managed requirements
  pin of the hook feature ON does not clear such a disable: Codex publishes no merge order for
  `[features]` across managed requirements and stored config, so that contest is UNPROVEN and
  fails closed with both declarations named. Stored legacy
  `profile` selectors are rejected;
  feature values in their inactive legacy profile maps are schema-checked but never applied.
  Project-local `profile` and `profiles` values are ignored with Codex's denylist. Commented or
  output-only marker carriers are not valid adapters. A CLI profile-v2 selection colliding with an
  inactive legacy profile name remains runtime-only. This is static topology and activation
  validation: it does not execute the hook, prove OS-level integrity, grant Codex trust, or inspect
  CLI/session/managed-cloud overrides.
  Review the adapter in the exact CWD and activate it with `/hooks` in a new Codex session, then
  run a live safe/deny canary.
- In a linked Git worktree, Codex maps every active hook layer to the same relative `.codex`
  directory in the root checkout that owns Git's common directory. `doctor --repo` discovers that
  root from Git common-dir/worktree facts, reports every mapped source, and fails when a local
  `hooks.json` or inline-hook declaration would false-green or differs from the authoritative
  source. An identical tracked copy is permitted but is inactive. Static discovery fails closed
  for a linked worktree whose primary checkout uses `--separate-git-dir`, and when the common Git
  directory has no checkout, such as a bare repository. Configure, review, and trust the
  root-checkout source with `/hooks`; never alter a trust hash manually or use a bypass flag.
- Codex 0.144.1 does not support the Claude `ask` decision, so the dispatcher conservatively
  translates `ask` to `deny`. The historical Claude global adapter still omits `--runtime` and
  therefore selects the Claude default, retaining interactive `ask` behavior; it still passes
  `--event pre` explicitly.
- **Fail-closed contract**: after a Bash payload and authority context are identified, an
  unhandled PRE rule-evaluation error returns deny-with-message ("dispatcher error — floor
  unavailable, fix hooks before proceeding"). Unparseable stdin cannot identify a tool or
  command and therefore exits without a decision; installation checks and live canaries must
  detect that wiring failure. Unsupported, missing, or duplicate event wiring fails closed after
  Bash identification. A supplied empty, unsupported, or duplicate runtime also fails closed;
  runtime omission selects Claude only for the historical global adapter. Codex wiring must name
  `--runtime codex` explicitly. No non-PRE hook may invoke this dispatcher.
- The canonical dispatcher lives in this repo (`templates/hooks/dispatch.py`). `harness.py seed`
  writes only the runtime-neutral tier declaration. `harness.py sync-global` previews or installs
  global guidance, managed skills, and the shared Claude-home dispatcher/smoke bytes only with
  explicit `--apply`; it prunes the obsolete managed global Codex matcher. Project hook adapters
  remain repo-owned and trust-gated.
- Self-tested: `python templates/hooks/smoke_test.py` runs the §6 allow/deny matrix plus payload,
  authority, runtime-adapter, and remote-resolution regressions for the PRE event. A
  floor/dispatcher change is T4-class work in any repo.
  The matrix defines a bounded parser contract, not exhaustive shell-language coverage. The
  dispatcher is a defense-in-depth tripwire, not a shell sandbox or a substitute for runtime/OS
  permissions, restricted toolsets, and branch protection.

## §6 Deny-floor bypass test matrix (must-block / must-allow)

MUST BLOCK (all tiers): `git push -f`, `git push --force`, `git push origin +main`,
`rm -rf /`, `rm -rf ~`, `rm -rf` outside repo/scratch, `... | Remove-Item`, `... | del`,
`curl … | sh`, `wget … | sh`, `sudo …`, write to `.env`/`*credentials*`/`*secret*` files;
with `sensitive_data`: `git push <public-remote>`, `gh repo create --public` — with the single
ratified issue-#48 exception (BLUEPRINT §1) for a public push ATTRIBUTABLE to a non-sensitive
repository. That exception is narrow and every condition is enforced, so these stay MUST BLOCK
under `sensitive_data` even though the destination is that repository's own remote: any
repository-redirecting git global (`--work-tree`, `--git-dir`, `-c core.worktree`, in any spelling
git accepts), a repository that does not EXPLICITLY declare `sensitive_data: false`, a repository
whose checkout or primary checkout sits inside a directory declaring `sensitive_data`, a
destination that does not resolve to one of the repository's configured remotes, a refspec-less
push inheriting a configured `remote.*.push`, and any multi-ref, tag-publishing or deletion
selector (`--all`, `--tags`, `--follow-tags`, `--mirror`, `--delete`, `-d`, and their
abbreviations).

MUST BLOCK only at T4 / `wave_mode` (warn at T3, allow T1–T2): `git reset --hard`,
`git clean -fd`, `git checkout -- .`, `git worktree remove --force` — and the LAUNDERED
force spellings of a worktree removal, which ride the identical ladder because an opaque
spelling must never score better than the literal form it might be: a runtime-computed
action word (`git worktree $ACT …`, issue #117 — `[worktree-action-opaque]`), a dynamic
option or separator-free operand token in a removal (`-$X`, bare `$A` —
`[worktree-remove-opaque]`; law 7's `$WT_PROJECT_DIR/<name>` compounds keep the plain
score — braced and quoted spellings included, but NOT the Windows `$VAR\<name>` one, whose
backslash a POSIX lexer eats, costing the token the separator that pins it out of option
space, so it lands on the ask/deny rung instead: issue #128), and argv-visible config that
blinds git's clean check
(`-c status.showUntrackedFiles=no` and its `--config-env`/opaque twins, issue #123 —
`[worktree-remove-config]`; literal `normal`/`all` values stay plain).

Plain `git worktree remove` is allowed at EVERY tier, `wave_mode` included (owner ruling
2026-07-27, issues #41/#117): git refuses a worktree holding tracked modifications or
untracked files, and removal leaves a checked-out branch behind — **not** because it is
harmless. Git's clean check (`git status --porcelain --ignore-submodules=none`) does not
consider gitignored content: it reports a worktree holding `.env`, `local.db`, `vendor.cfg`
and `node_modules/` as clean, and removal then deletes all of it. The branch guarantee is
scoped to a worktree that has one: a clean **detached** worktree passes git's pre-removal
check and its commits — held only by that worktree's HEAD — leave `git log --all` with the
removal, which is why law 7 mandates `git switch -c` before committing (issue #122; the
floor cannot see detached-ness in argv). All measured on git 2.45.1 and pinned by
`ignored_worktree_removal_is_destructive` in `smoke_test.py`, including the
`status.showUntrackedFiles=no` blinding of the untracked-file refusal.
Keep no `.env` that must outlive its worktree.

MUST ALLOW (false-positive regression tests): commit/PR bodies *describing* dangerous commands
(`git commit -m "block rm -rf in hook"`), `gh pr create --body-file …`, `git push --force-with-lease`
with an explicit non-shared feature-branch refspec at T1–T2, and compound commands where the
dangerous-looking text is inside quotes. Lease pushes to shared/default branch names, selectors,
or ambiguous `HEAD` destinations remain blocked.

Parsing notes: tokenize argv (shlex for POSIX; separate lightweight matcher for PowerShell
pipe forms — shlex won't parse `| Remove-Item`); split on `;`, `&&`, `|` and check each
segment; NEVER match against `-m`/`--body` string arguments.

### §6.1 Cross-product gate — where the tripwire ends (issue #63)

The matrix above tests each command in canonical form. `tests/test_prefix_wrapper_crossproduct.py`
crosses it with the shapes real command lines carry — 28 prefix spellings (leading
redirections, `--%`, `VAR=value`, combinations) and 74 wrapper spellings (launchers,
container/remote exec, nested interpreters, scriptblock/evaluator forms) — and asserts BOTH
directions: charter denies stay denied, curated benign commands stay allowed.

A shape the floor does not cover is recorded in that module's baselines with the issue it
belongs to, so the repo states where the tripwire ends instead of leaving it unstated:
`DOCUMENTED_BYPASSES` (whole shapes: #46, #56, #37, #9, #67), `DOCUMENTED_CASE_BYPASSES`
(individual rules disarmed by an otherwise-covered wrapper: #68, #69, #79, #80),
`DOCUMENTED_OVER_BLOCKS` (shapes that deny EVERY benign payload: #21 plus the charter's
own privilege-transition denials) and `DOCUMENTED_CASE_OVER_BLOCKS` (its payload-granular
mirror). A baseline entry that starts behaving correctly fails the gate as UNEXPECTEDLY
FIXED, so a fix has to be promoted into the enforced set rather than left un-guarded
against a later re-break. That promotion is the mechanism, not a formality: 21 of the 22
#46 shapes and 3 of the #68 case entries were retired this way once main closed them, and
`stop-parsing-glued` is all that remains of #46.

UNEXPECTEDLY FIXED and the corpus sweep are reported TOGETHER. They were sequential
`self.fail` calls, and `fail` raises, so a recorded entry that started behaving correctly
suppressed every live bypass in the same run — three case-level entries were hiding 81
corpus failures that no run had ever printed.

Two properties keep a baseline from meaning less than it looks. A SHAPE-level entry must
record which probes it lets through or denies — an empty evidence list would exempt a
shape from ~955 corpus checks while asserting nothing — and a shape's composed line must
be a command that actually runs: a payload embedded inside an interpreter's own quoted
program (`perl -e`, `python -c`, `node -e`, `awk`, `expect -c`) is a string literal of
that LANGUAGE, never a second layer of shell quoting, which would close the template's
span and compose a syntax error. Both are asserted, not conventions.

## §7 Stop-hook verification (T3 warn / T4 block)

Fire ONLY on narrowly detectable states; never on research-only sessions:
- `gh pr create` succeeded this session AND `gh pr view <n> --json comments` shows no
  review-findings comment → "run the bounded review pipeline (`review-and-ship`, §14) before
  stopping".
- Files under source roots were edited AND no test command ran this session → T3 warn,
  T4 block.
- T4 only: uncommitted changes or an undeclared unpushed queue at stop → block with summary.
Stated override: the user saying `SKIP-CHECKS: <reason>` — logged to the failure ledger.
False positives train hook-disabling; when in doubt, don't fire.

**No new stop-hooks.** The states above are the grandfathered set (BLUEPRINT law 12 — the
meta-gate cap, issue #92 P5): a stop-hook is a gate, and a new gate about process compliance
arrives only as a ratified mission, never as a session detour. A proposed addition must
displace one of the states above or start life as a tracked issue.

## §8 Model & effort routing (full table)

Model tiers (`top` / `default` / `cheap`) are ROUTING tiers — unrelated to the T0–T4
blast-radius ladder.

| Task class | Model tier | Effort | Walls vs tripwires |
|---|---|---|---|
| Deny floor / dispatcher changes, promotion audits | top | xhigh | wall: agent `model:` pins + review requirement |
| Region maps, skills, ADRs, global laws | top | xhigh | convention |
| Adversarial review, merge decisions | top | high (xhigh only if irreversible / wide blast radius) | wall at T4 (gate), tripwire below |
| Code implementation, debugging, feature slices in mapped regions | default | high | convention |
| Gardener triage, tombstone classification, promotion routing | default | low | wall: `~/.claude/agents/gardener.md` pin + PR-only output |
| Judgment-bearing subagent work (a lens, a call, a triage), lookups, conversation | default | low | convention |
| Bulk mechanical sweeps, doc rotation, formatting, test running — INCLUDING when fanned out across subagents | cheap | medium–high (never low) | convention |

Effort is the first dial (cheaper than a model swap). Default-up when unsure. Interactive
sessions: pick per the table at session start; don't leave xhigh pinned globally for
maintenance work.

**Triage and classification are judgment, not mechanics** — deciding what matters is a call, so
they sit on the default tier even though they run on a schedule. A cheap tier only earns work
that is genuinely simple, well-specified, and hard to get wrong; and when it does, it runs at
medium/high effort, because a cheap model at low effort compounds two handicaps.

**Delegation is not a task class.** A subagent is routed by the work it does, not by the fact
that it was delegated: wide mechanical fan-out follows the cheap row above and BLUEPRINT §3
(medium/high effort, never low); a subagent asked for an independent lens or a call follows the
default row. If a task matches both rows, the DEFAULT row wins: the ladder routes up when the
class is unclear, because a cheap model on judgment work is the expensive mistake.

**The tiers above are deliberately unnamed, and this table does not restate the ladder.** Which
model fills `top` / `default` / `cheap`, and the fan-out fleet caps (≤3–5, ≤8–12 for a sweep),
live in the `model-effort-routing` global skill — the single home. A named model written in two
files is how a stale routing row survives repeated prose bans; if this table and the skill ever
disagree, the skill wins and the local copy is the bug. The one model-level statement that is law
rather than calibration — the standing family-wide Haiku ban — is declared in BLUEPRINT §5 and
enforced by the config repo's `tests/check-agent-models.ps1`; it is deliberately not restated here. This table is the durable judgment-vs-mechanical shape and
changes only when that shape changes.

## §9 Bootstrapper CLI + ESTATE.md

Home: this repo. Implemented in the dependency-free `harness.py` (one implementation, no
`.sh`/`.ps1` twins):
- `harness.py seed <path> --tier N` — writes only the runtime-neutral tier germ and refuses
  overwrite. Repo instructions remain judgment work and are not generated blindly.
- `harness.py audit <path>` — validates tier schema, instruction/skill budgets, Git state, and
  stale user-profile paths.
- `harness.py sync-global --config-root <claude-config> [--apply]` — previews or installs global
  Codex guidance, managed skills, and shared Claude-home floor bytes with timestamped backups;
  removes only the obsolete managed global Codex matcher.
- `harness.py doctor [--repo <path>]` — checks live global guidance/floor topology, core
  executables, and optionally one repo-local Codex floor definition.
- `harness.py worktrees --repo <path> [--refresh] [--apply] [--json]` — reports every registered
  linked worktree and only removes a candidate after an explicit all-remote refresh, exact physical
  containment under the primary checkout's `.worktrees/`, clean tracked/untracked/ignored status,
  no assume-unchanged/skip-worktree index flags, remote-ref reachability, and a same-run 60-second
  fingerprint revalidation. The default performs no fetch or mutation; `--apply` requires
  `--refresh` and uses only plain `git worktree remove`.
  Git-locked worktrees and the requested/current checkout are retained. Arbitrary external-process
  occupancy is not portable to prove, so a plain-removal refusal remains a keep verdict. Pruning
  runs only after a successful removal; branch deletion and ignored-path exceptions are outside
  this command.

Deferred until earned by repeated use: `tier-up`, estate-wide mutation, and Gardener scheduling.

Template layout: `templates/tier1..tier4/` overlays + `templates/hooks/` + `templates/skills/`.

`~/.claude/ESTATE.md` schema (one row per repo, ALL roots — source/, Desktop/, …):
`| repo | root | live path | tier | flags | status | human-todo alias | last reviewed | notes (wrapper warnings, vendor decision, plugin-vs-skill choice) |`

## §10 Gardener spec

- Invocation: a Claude Code scheduled routine configured with the default-tier model at effort
  low, weekly per ACTIVE repo only. Windows Task Scheduler fallback: `claude -p "<gardener
  prompt>"` with the SESSION model bound through the routine/settings model setting, resolved
  from the `model-effort-routing` skill at configuration time (rule 4 below explains why the
  command line is not an option). Binding it is not optional: a headless `claude -p` run is a
  TOP-LEVEL session, so the `model:` pin in `~/.claude/agents/gardener.md` binds the delegated
  SUBAGENT, not the session that starts it, and a run that passes nothing inherits the ambient
  default — the top tier — and §6's scheduled-spend cap silently does not apply.
- **Where the model name may live (the derivation contract).** The `model-effort-routing` skill
  is the SOURCE: it alone defines which named model fills `default`. Prose — this spec, the
  blueprint, the scheduled-routine description — carries the tier name and points at the skill,
  never a model name (the §1 mirror's QUOTED text is the one exemption — see §13). Agent definitions are the ONE permitted DERIVED copy, because `model:` in
  `~/.claude/agents/gardener.md` is a machine-read field that cannot hold an indirection. Being
  permitted, that copy is governed rather than trusted:
  1. Changing which model fills a tier in the skill is NOT DONE until every agent definition
     pinned to that tier is re-pinned in the same change — one commit, both surfaces.
  2. Nothing today records WHICH tier a given `model:` derives from, so the copy is currently
     conventional rather than checkable. Making it checkable — a declared tier next to the pin,
     and a check that compares the two — is the substance of issue #76.
  3. `tests/check-agent-models.ps1` in the config repo is the enforcement surface. Today it
     asserts only that no definition pins a banned model (the family-wide Haiku ban); extending
     it to assert that each `model:` equals the skill's model for the declared tier is tracked
     in agent-harness issue #76. Until that lands, rule 1 is a convention with a review step,
     and this spec says so rather than implying a check that does not exist.
  4. A command line (`claude -p … --model …`) is NOT a permitted copy: it is transient config
     no check can see. Bind the scheduled session through the routine/settings model setting
     resolved from the skill at configuration time.
  The failure this replaces was exactly a stale second copy: a literal `--model haiku` sat in
  this line while Haiku was banned in prose elsewhere in the estate.
- Runs in its own worktree — never the live checkout (one-writer rule; scheduled agents must
  not race interactive sessions or wave agents).
- Output contract: exactly ONE branch + PR, ≤100 changed lines, title `gardener: <repo> <date>`,
  body reporting: ledger triage counts (4-way classification), budget results, stale stamps,
  memory folds, tier-mismatch flags, and its own token spend.
- Red-lane check inside the same pass: `gh run list --workflow=<w> --limit 2 --json conclusion`
  per scheduled lane; two consecutive failures → file a `fix-or-delete` issue.
- Kill switch: two consecutive unmerged gardener PRs → auto-pause for that repo + a
  tier-mismatch line in ESTATE.md.

## §11 Skill-forge pipeline (automated skill creation, human-ratified)

1. Inputs: ≥3 clustered failure-ledger entries with the same signature, or a second-occurrence
   memory line tagged `promote-candidate`.
2. Draft from the §4 anatomy template; must include the anti-trigger section and at least one
   verbatim guard phrase; ≤60 lines.
3. Validate: frontmatter parses, caps hold, no read-first ladder, no restatement of a policy
   that has a home (law 2).
4. Output: branch + PR (part of the Gardener PR or standalone). Agents NEVER self-install
   skills; the human merge is the trust gate.
5. Decay twin: skills with zero invocations in a quarter are archived by the same pipeline.

## §12 Session concurrency rules

- One writer per checkout: interactive session OR wave coordinator OR gardener — never two.
- Scheduled agents always use worktrees; wave agents follow the worktree protocol; the
  coordinator (not workers) touches the root checkout.
- SessionStart state (nudges, triage warnings) must be derived from files, not assumed
  exclusive; hooks must tolerate concurrent readers.

## §13 Disposition of existing global assets

- `~/.claude/prompts/ORCHESTRATOR_PROMPT.md` (13KB proto-blueprint): fold its state-file /
  task-lifecycle / dual-review / merge-gate content into the T3+ wave-mode skill and
  `.claude/agents/` definitions; retire the paste variant once those exist.
- 6 global process skills: safe-shell, small-safe-slice, verification-closeout (≤40 lines each,
  keep as-is); plus three ≤80-line workflow-mode skills — `guided-walkthrough` (backlog→numbered-q-N
  guided mode: per item context + suggested action + owner tag + step-by-step for human-only items),
  `model-effort-routing` (effort→model→fan-out ladder and fleet caps ≤3–5 / ≤8–12), and
  `review-and-ship` (the §14 bounded review pipeline in executable form). These are
  the single home for their behavior — in particular, `model-effort-routing` is the ONLY place that
  names models and their effort bindings (the dated §1 mirror QUOTES claude-config's file,
  which names models in its working style — a quotation, not a second home: the skill stays
  authoritative for model names even where the mirror's text disagrees, and claude-config stays
  authoritative for law text); §8 above and BLUEPRINT §5 carry the task-class→tier shape
  and point here. Global CLAUDE.md (law 5 + Working style) and the T2 SessionStart nudge only point
  at them.
- 4 `bootstrap-*.ps1` (2,664 lines, Apr 9, drifted): salvage text into `templates/`, then delete.
- Plugins: keep pr-review-toolkit/code-review/feature-dev ONLY where a repo hasn't chosen its
  local skill for that verb (record per-repo in ESTATE.md); delete disabled marketplace clones.
- MCP: keep MCP_DOCKER global; remove dead per-repo entries (e.g. the forbidden ripgrep MCP in
  olb's config.toml) during migration.

## §14 The bounded review pipeline (`review-and-ship`)

BLUEPRINT §1's T3 "bounded review pipeline" slot is filled by the `review-and-ship` skill,
shipped from claude-config for both runtimes. Reference, don't restate: the skill file is the
single home for the step-by-step, and law 2 of the §1 mirror plus BLUEPRINT law 11 are the
law it executes — one review round, one severity-bar triage (confirmed CRITICAL/HIGH fix
commits only; the rest tracked or declined on the thread), one fix round verified against the
fix diff — at T3+ the re-requested Codex review after that fix round IS the verification pass,
not a new round — then ship or park. Tier changes WHO reviews and how many eyes the single
round gets (T3 one independent pass, T4 two adversarial reviews), never how many rounds run.
