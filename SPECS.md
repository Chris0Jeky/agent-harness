# Harness Specs

Last Updated: 2026-07-13 · Concrete schemas and drafts referenced from [BLUEPRINT.md](./BLUEPRINT.md).

## §1 Global `~/.claude/CLAUDE.md` — literal draft (~40 lines)

```markdown
# Global laws — all repos, all tiers

## Non-negotiable
1. Never merge a PR with failing CI. Investigate every failure; never dismiss as flaky.
2. Reviews are zero-skip: post findings on the PR, fix EVERY severity, address ALL existing
   comments (bots included), post fix evidence. Never pause mid-pipeline to ask whether to
   continue — the answer is yes. Out-of-scope findings become tracked issues.
3. Never claim done/verified without running the thing that proves it. Always state what was
   NOT verified. Close with: changed / verified / NOT verified / residual risk.
4. GitHub hygiene: "Closes #N" fires even quoted or negated — verify links after body edits.
   Never `--delete-branch` a stacked base PR (cascade-closes children unreopenably).
   Merge the oldest PR in a stack, never the newest.
5. Surface the repo's human-action file (HUMAN_TODO.md or its declared alias) in every
   summary. Only the human checks items off.
6. Questions: batch true blockers into ONE question; otherwise proceed on a named assumption
   ("Assumption: X. Reason: Y. Reversible by Z.").
7. Worktrees: guard preamble is the first action; $WT_PROJECT_DIR paths only; create with
   --detach origin/main, never branch refs; coordinator verifies main is clean after waves.
8. Structure arrives with the second item. Don't build speculative scaffolding; when a lesson
   recurs, promote it up the enforcement ladder (memory→CLAUDE.md→skill→hook→CI→structure)
   to the cheapest layer that actually enforces it.
9. Before working in an unfamiliar repo: check the estate registry (junk wrappers and frozen
   snapshots exist) and the repo's `.agent-harness/tier.json` — authority is declared, not negotiated.
10. Weak-model rails: if you are not the top routed model, never merge, never edit canonical
    docs, the deny floor, or gates. Open PRs.

## Tier ladder (blast radius)
T0 tombstone · T1 sandbox · T2 daily driver · T3 workshop · T4 live wire
Details: the active `agent-harness/BLUEPRINT.md` checkout
```

Ship in the same commit that deletes the graduated per-repo memory duplicates
(feedback_never_merge_failing_ci, feedback_review_fix_everything, feedback_always_check_pr_comments,
zero-skip twins in NavSentinel/Options/extract-api, close-keyword and stacked-PR memories, …).

## §2 `.agent-harness/tier.json` schema

```json
{
  "tier": 3,
  "name": "workshop",
  "authority": { "push": "free", "merge": "gated" },
  "flags": { "sensitive_data": false, "wave_mode": false, "dormant_production": false,
             "relaxed_work_loss_guards": false },
  "model_routing": { "harness_and_review": "top", "slices": "mid", "maintenance": "cheap" },
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
- Read by: dispatcher hook, Gardener, bootstrapper, CI templates. The dispatcher also reads
  legacy `.claude/tier.json` files so existing estates can migrate without a flag day.
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
| directory CLAUDE.md | ≤30 lines | move detail to region map |
| global CLAUDE.md | ≤60 lines | it's the law layer, not a manual |
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
  system/base-user/every stored profile config, and the legacy managed config file. Missing files
  are absent; unreadable or malformed sources and failed profile enumeration fail closed. On
  Windows the system layer uses the ProgramData known folder with the same default fallback as
  Codex. Inactive profile files and direct legacy-profile tables are audited conservatively because
  the invoking profile is not part of the Python process context.
  Managed-cloud and MDM requirements/config, session flags, and plugin hooks remain an explicit
  runtime boundary for exact-session `/hooks`; the static check never represents those sources as
  inspected.
- Codex project adapters must pass `--event pre --runtime codex` directly, or invoke a repo-owned
  wrapper that binds both values. The POSIX and Windows commands must independently invoke the
  shared dispatcher or that wrapper, bind the normalized dispatcher hash pin to a named variable,
  and use a matcher that positively includes Bash. `doctor --repo` uses the Git-root layer walk
  only when all inspectable top-level and direct legacy-profile `project_root_markers` declarations
  in system, base-user, and stored profile-file configs are absent or exactly `[".git"]`. Any
  non-default, conflicting, malformed, or unreadable declaration fails the marker and project-floor
  checks.
  CLI and managed-cloud marker overrides are explicitly outside static inspection. Under that
  qualified topology, `doctor` audits every active `.codex` layer from the checkout root through
  the requested directory and both declaration forms Codex loads: `hooks.json` and inline
  `[hooks]` in `config.toml`. Across all active sources it requires exactly one candidate, one
  conservatively recognized execution shape, and one current pin. The recognized current floor
  must reside in the canonical root `.codex/hooks.json`; nested layers that contain configuration
  but no hooks are valid. Commented or output-only marker carriers are not valid adapters. This is
  static topology validation: it does not execute the hook, prove OS-level integrity, or grant
  Codex trust. Review the adapter in the exact CWD and activate it with `/hooks` in a new Codex
  session, then run a live safe/deny canary.
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
with `sensitive_data`: `git push <public-remote>`, `gh repo create --public`.

MUST BLOCK only at T4 / `wave_mode`: `git reset --hard`, `git clean -fd`, `git checkout -- .`
(warn at T3, allow T1–T2).

MUST ALLOW (false-positive regression tests): commit/PR bodies *describing* dangerous commands
(`git commit -m "block rm -rf in hook"`), `gh pr create --body-file …`, `git push --force-with-lease`
with an explicit non-shared feature-branch refspec at T1–T2, and compound commands where the
dangerous-looking text is inside quotes. Lease pushes to shared/default branch names, selectors,
or ambiguous `HEAD` destinations remain blocked.

Parsing notes: tokenize argv (shlex for POSIX; separate lightweight matcher for PowerShell
pipe forms — shlex won't parse `| Remove-Item`); split on `;`, `&&`, `|` and check each
segment; NEVER match against `-m`/`--body` string arguments.

## §7 Stop-hook verification (T3 warn / T4 block)

Fire ONLY on narrowly detectable states; never on research-only sessions:
- `gh pr create` succeeded this session AND `gh pr view <n> --json comments` shows no
  review-findings comment → "run the review pipeline before stopping".
- Files under source roots were edited AND no test command ran this session → T3 warn,
  T4 block.
- T4 only: uncommitted changes or an undeclared unpushed queue at stop → block with summary.
Stated override: the user saying `SKIP-CHECKS: <reason>` — logged to the failure ledger.
False positives train hook-disabling; when in doubt, don't fire.

## §8 Model & effort routing (full table)

| Task class | Model | Effort | Walls vs tripwires |
|---|---|---|---|
| Deny floor / dispatcher changes, promotion audits | top | xhigh | wall: `.claude/agents` pins + review requirement |
| Adversarial review, merge decisions | top | xhigh | wall at T4 (gate), tripwire below |
| Region maps, skills, ADRs, global laws | top | xhigh | convention |
| Feature slices in mapped regions | mid | medium–high | convention |
| Bulk mechanical edits, test running | mid/cheap | low–medium | convention |
| Gardener triage, doc rotation, formatting, tombstones | cheap | low | wall: gardener.md model pin + PR-only output |

Effort is the first dial (cheaper than a model swap). Default-up when unsure. Interactive
sessions: pick per the table at session start; don't leave xhigh pinned globally for
maintenance work.

The current concrete calibration — which named model at which effort, any temporary access
window, and the fan-out fleet caps — lives in the `model-effort-routing` global skill, not here.
This table is the durable judgment-vs-mechanical shape; the skill carries the model-specific
detail so it updates without a SPECS edit.

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

Deferred until earned by repeated use: `tier-up`, estate-wide mutation, and Gardener scheduling.

Template layout: `templates/tier1..tier4/` overlays + `templates/hooks/` + `templates/skills/`.

`~/.claude/ESTATE.md` schema (one row per repo, ALL roots — source/, Desktop/, …):
`| repo | root | live path | tier | flags | status | human-todo alias | last reviewed | notes (wrapper warnings, vendor decision, plugin-vs-skill choice) |`

## §10 Gardener spec

- Invocation: Claude Code scheduled routine (or Windows Task Scheduler fallback:
  `claude -p "/gardener" --model haiku` with effort low), weekly per ACTIVE repo only.
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
- 5 global process skills: safe-shell, small-safe-slice, verification-closeout (≤40 lines each,
  keep as-is); plus two ≤80-line workflow-mode skills — `guided-walkthrough` (backlog→numbered-q-N
  guided mode: per item context + suggested action + owner tag + step-by-step for human-only items)
  and `model-effort-routing` (effort→model→fan-out ladder; Opus 4.8 default reach, Fable-with-fallback
  for the hardest work, fleet caps ≤3–5 / ≤8–12). These are the single home for their behavior;
  global CLAUDE.md (law 5 + Working style) and the T2 SessionStart nudge only point at them.
- 4 `bootstrap-*.ps1` (2,664 lines, Apr 9, drifted): salvage text into `templates/`, then delete.
- Plugins: keep pr-review-toolkit/code-review/feature-dev ONLY where a repo hasn't chosen its
  local skill for that verb (record per-repo in ESTATE.md); delete disabled marketplace clones.
- MCP: keep MCP_DOCKER global; remove dead per-repo entries (e.g. the forbidden ripgrep MCP in
  olb's config.toml) during migration.
