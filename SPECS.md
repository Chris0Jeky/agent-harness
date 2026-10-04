# Harness Specs

Last Updated: 2026-10-03 · Concrete schemas and drafts referenced from [BLUEPRINT.md](./BLUEPRINT.md).

## §1 Global laws — pointer, not a mirror

The global law set lives in the claude-config repository, and it is the only copy. Claude loads
`rules/laws.md`, deployed as `~/.claude/rules/laws.md`; Codex reads the same contract as
`codex/AGENTS.md`, and claude-config's `tests/check-law-parity.ps1` keeps those two in step. This
section used to hold a dated verbatim mirror (ratified 2026-07-26, issue #92). The mirror drifted
from global laws 2f/2g, and the drift misled a review (issue #358), so global law 8 pruned it.
A `global law N` or `CLAUDE.md law N` pointer means law N of that canonical file.
BLUEPRINT §0 uses the separate design-principle namespace `P1` through `P12`.
Operational references must name the namespace; there is no default meaning for a bare
`law N`. Historical `BLUEPRINT law N` citations mean the correspondingly numbered `PN`.
Review and termination remain canonical in global laws 2 and 11; P11 points there rather
than defining another review-round count.

**Transition note (issue #429).** Operational citations were written before the P1-P12 / global-law
split, so an unconverted bare `law N` must never be read as whichever namespace is convenient.
Read it by where it lives:
- **Pinned floor text** (`templates/hooks/dispatch.py`, the `templates/hooks/smoke_test.py` matrix
  beside it, and any vendored copy whose bytes a test or a marker pins): a bare `law N` there means `global law N`
  (in practice law 7, worktrees, whose `git switch -c` mandate the floor's comments cite). These
  bytes change only through an authorized floor version and digest change, never for prose
  consistency, so the bare spelling is a documented legacy form and not an invitation to
  re-read it as `PN`.
- **Historical records** (`HANDOFF.md`, `handoffs/`, dated `HUMAN_TODO.md` log entries, `ROADMAP.md`
  deltas, `legacy/`): they keep their original wording. A bare `law N` there means the law as
  numbered when it was written; `BLUEPRINT law N` means `PN`.
- **Everything else** (active scripts, plans, docs, tests): qualify as `global law N` or `PN` when
  touched. A bare number whose canonical source cannot be confirmed is left as written and is not
  converted mechanically.
New text never relies on a bare `law N`.

`doctor --config-root <claude-config>` compares each canonical guidance file with its deployed copy
byte for byte, as separate checks: source `CLAUDE.md` against `~/.claude/CLAUDE.md`, source
`rules/laws.md` against `~/.claude/rules/laws.md` (the law set Claude actually loads, #366), and
source `codex/AGENTS.md` against `~/.codex/AGENTS.md`. The supplied directory must be the clean,
published `main` checkout of the harness origin's `claude-config` sibling, with all three guidance
paths tracked and visible to Git; otherwise the checks are `UNPROVEN`. A readable byte mismatch
fails.

This repository's own deltas from the global merge rules:
- `templates/hooks/dispatch.py` changes are T4-class whatever this repository's tier. They need the
  smoke suite, the unit tests, and an independent read-only review, per CLAUDE.md's change rules.
- Everything else follows the global laws at this repository's declared tier (T3 workshop, push
  and merge free).

## §2 `.agent-harness/tier.json` schema

```json
{
  "tier": 3,
  "name": "workshop",
  "authority": { "push": "free", "merge": "gated" },
  "flags": { "sensitive_data": false, "wave_mode": false, "dormant_production": false,
             "relaxed_work_loss_guards": false },
  "floor_posture": "guide",
  "public_synthetic_publication": {
    "remote": "origin", "repository": "OWNER/REPOSITORY"
  },
  "budgets": { "standing_context_tokens": 6000, "session_baseline_tokens": null },
  "human_todo": "HUMAN_TODO.md",
  "status_doc": "plans/ACTIVE.md",
  "last_reviewed": "2026-07-06"
}
```

- `authority.push` / `.merge`: `free` | `gated` | `human-only` (the dial: leave-PRs-open →
  push-gated-like-merge → merge-behind-full-gate).
- `flags.relaxed_work_loss_guards`: declared relaxed-git posture — work-loss guards
  (`reset --hard`, `clean -f`, `checkout -- .`, `restore .`) stay ALLOW below T4/wave_mode
  instead of the T3 ask. IGNORED at T4 and under `wave_mode`; the irreversible floor is
  unaffected. Reference repo: wealthlens-hq (the estate's written sub-T4 git-freedom spec).
- `floor_posture` (optional): `wall` | `guide` | `core` — how the deny floor RENDERS its
  verdicts (§5.4). Absent, the tier decides: T4 and `wave_mode` are always `wall`;
  `sensitive_data` defaults to `wall`; everything else defaults to `core` (since 1.7.0; `guide`
  before). Co-located and chained declarations merge strictest-wins (`wall` beats `guide` beats
  `core`; no declared posture relaxes T4/wave).
- `floor_wiring` (optional): `none` — the owner's declaration that this repository runs WITHOUT a
  floor: no `.codex/hooks.json` adapter and no global Claude `PreToolUse` hook (§5). It is a
  relaxation, so it binds only when every co-located declaration carries it. `doctor --repo`
  then reads a missing adapter as the declared state and a lingering floor handler — or a Claude
  home `settings.json` that still registers the global dispatcher — as a contradiction;
  lifecycle-only hooks stay allowed, and without a VALID declaration a missing adapter stays a
  failure.
- `public_synthetic_publication` is an optional, remote-bound relaxation for the owner-ratified
  public-source/private-runtime split. It contains exactly a literal Git remote name and GitHub
  `OWNER/REPOSITORY`. It authorizes only an explicit named-branch/`HEAD` push to that remote's
  single matching push URL; it does not authorize a refspec-less or forced push and does not
  disable any other `sensitive_data` rule.
- `status_doc` (optional, issue #247): repo-relative path (or `null`) of the routed "now"/STATUS
  doc. When declared, `audit` holds it to the §3 head budget and reports a missing file as a
  MISMATCH; a non-string, absolute or `..`-escaping value is an audit issue; absent, no check.
- `model_routing` is NOT part of the schema: `seed` no longer emits it. The model ladder lives
  in ONE place (BLUEPRINT §5 / SPECS §8); a per-repo copy is a third place for it to go stale.
  Repos seeded before 2026-07-25 still carry a `model_routing` block — it is inert, read by
  nothing, and `audit`/`doctor` ignore it rather than failing on it.
- Read by: dispatcher hook (`tier`, `flags`), Gardener, bootstrapper, CI templates. The
  dispatcher also reads legacy `.claude/tier.json` files so existing estates can migrate
  without a flag day.
- Two co-located declarations bind to the STRICTEST union, never to the first one found
  (global law 9; `dispatch.load_tier`; `harness.merge_tier_declarations`): highest `tier` wins,
  tightening flags and the strictest `authority` dial are unioned, and the one relaxation
  (`relaxed_work_loss_guards`) applies only when EVERY declaration sets it. The publication
  relaxation likewise applies only when EVERY declaration contains the exact same valid object.
  Non-posture fields
  (`name`, `human_todo`, `status_doc`, `budgets`, `last_reviewed`) come from `.agent-harness/tier.json` when
  it declares them; each file is still validated on its own.
- The human-readable `Tier: workshop (T3) — authority: push free / merge gated` line at the
  top of repo CLAUDE.md is GENERATED from this file by `harness audit` (never hand-edited);
  the budget script fails if they disagree.

### §2.1 Logical repo root selection (issue #139)

A declaration binds to a LOGICAL repo, which is usually — but not always — the Git checkout
root. One checkout can carry several products, each declaring its own posture, while the
checkout root itself deliberately declares none. `harness audit <path>` and
`harness doctor --repo <path>` resolve the logical root of the requested path with this rule,
in order (`harness.logical_repo_root`):

1. **Nearest declared ancestor wins.** Walking from the requested directory up to the Git
   checkout root inclusive, the first directory that carries BOTH `AGENTS.md` AND a tier
   declaration (`.agent-harness/tier.json` or legacy `.claude/tier.json`) is the logical root.
   Containment breaks the tie, so a product's own declaration binds for a path inside it even
   when an outer umbrella also declares one.
2. **A fully undeclared directory may resolve downward.** If the requested directory carries
   NEITHER half, declared roots below it are searched (breadth-first, max depth 4, skipping
   dot-directories, vendor directories, anything reached through a symlink or junction — the
   junction-aware `path_is_alias` predicate decides, not `is_dir` — and any child that carries
   its own `.git`, which is another checkout's repository or submodule; a declared root ends
   the descent on its branch). Exactly one match is selected. **Two or more
   competing roots are ambiguous and raise** — the operator re-runs against one of them — and
   the tool never picks a product silently.
3. **Otherwise the Git checkout root is the repo**, exactly as before. A HALF-declared
   directory (one of the two files) is a repo missing the other half, never an umbrella: it
   takes this branch so the missing declaration is still reported.

Consequences, all of which the tests pin:

- An ordinary repository whose logical and Git roots are identical takes rule 1 at the root
  itself. Nothing about it changes, whatever its subdirectories declare.
- The tier, `AGENTS.md`, doc budgets, stale-path scan and every reality check are scoped to
  the LOGICAL root, so a sibling product's artifacts are not reported against this one.
- Git facts stay the checkout's: `git status`, remotes and remote visibility are read by
  running Git from inside the logical root, which answers for the checkout that owns it.
  `audit --json` reports both, as `repo` (logical) and `checkout` (Git).
- `doctor --repo` walks every active `.codex` layer from the checkout root to the requested
  path as before — or down to the logical root when rule 2 selected a descendant, exactly as
  a session started inside that product would load layers. The CANONICAL adapter is the
  NEAREST `.codex/hooks.json` at or above the logical root: the product's own when it has one,
  otherwise the umbrella layer Codex loads for every cwd beneath it; for an ordinary repository
  that is the Git root's, unchanged. In a linked worktree the authoritative source is that same
  logical relative subpath in the root checkout, not the Git root's `.codex`.

## §3 Budget table (enforced by `check-budgets.mjs`, ~80 lines)

| Artifact | Cap | On overflow |
|---|---|---|
| repo CLAUDE.md | T1 ≤40 / T2 ≤100 / T3+ ≤150 lines | rotate detail to linked docs |
| AGENTS.md (rulebook, T3+) | ≤80 lines | one home per policy; link out |
| "now"/STATUS doc head (the declared `status_doc`; enforced by `harness.py audit`) | ≤150 lines | rotate to `docs/archive/status-YYYY-MM.md` |
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
rules header: read at session start, surface in every summary, check off per global law 5 (direct
evidence; a human decision is never inferred).

**Tombstone CLAUDE.md** (3 lines): `Tier: T0 TOMBSTONE` / `FROZEN <date> — do not develop
here.` / `Live successor: <path or "none">`.

**REVIVAL.md** (≤20 lines): how to run, known hazards, data locations/backups, re-seed tier.

## §5 Dispatcher hook wiring

The shared dispatcher owns exactly one event: the `PreToolUse(Bash)` deny floor. Claude wires it
at user scope on hosts that keep one (none on the primary workstation; a repo may declare
`floor_wiring: none`). Each active Codex repo wires exactly one project `.codex/hooks.json` adapter that pins
the shared `~/.claude/hooks/dispatch.py`; Codex has no global floor matcher. A repository's owner
may declare it floorless (agent-harness itself and claude-config, owner decision 2026-09-07): it then
wires no adapter and no global Claude hook, and no floor runs there — declared as tier.json
`"floor_wiring": "none"` (§2 schema) and recorded in the repo's instruction files, not drift for a
sync or a doctor run to repair. Repo-tier lifecycle
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
  values. A present `public_synthetic_publication` must contain exactly a literal remote name and
  GitHub `OWNER/REPOSITORY`; co-located declarations must agree exactly. Invalid authority fails
  closed on PRE; only an absent declaration receives T1 defaults. The publication object is
  repository-specific and is re-read from the pushed repository during attribution rather than
  inherited as a contextual relaxation.
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
  bumping `FLOOR_VERSION`, refreshing the marker in `templates/codex/hooks.json` and in **every**
  consumer `.codex/hooks.json`, and a
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

### Codex project-hook trust bootstrap

`doctor` can diagnose only the static adapter and inspectable activation blockers. Its
exact-CWD `/hooks` remediation message is deliberately not proof that Codex has accepted a
project or handler for a particular session. Use this supported bootstrap procedure instead:

1. Start the normal interactive Codex TUI from the exact project CWD that will run the hook. If
   Codex asks for project trust, accept trust for that exact project; do not substitute a parent,
   sibling, or different worktree CWD. When that CWD is a linked worktree, stay there while
   reviewing the authoritative root-checkout adapter identified by `doctor`.
2. In that same TUI and CWD, open `/hooks`. Before trusting anything, review the intended handler's
   current source path, matcher, command (including `--event pre --runtime codex`), timeout,
   current definition hash, and any `expected=<sha256>` audit marker. Trust only that reviewed
   handler, not every listed handler.
3. Confirm in the same exact-CWD `/hooks` view that the intended handler is enabled and trusted
   with no relevant warning or error. The app-server `hooks/list` result may corroborate the
   source, command, enabled state, hash, warnings, errors, and trust status, but is inspection
   only. Noninteractive `codex exec` can exercise an already trusted handler; neither interface
   grants project or per-hook trust.
4. Immediately collect runtime evidence: run a declared harmless allow canary such as
   `git status --short --branch`, then an inert deny canary that cannot perform a real mutation.
   For example, the force-push-shaped probe
   `git push --dry-run --no-verify --force . HEAD:refs/heads/codex-h2-deny-canary` must be denied
   before Git executes; its dry run and local `.` destination leave no remote update if the hook
   is unavailable. Capture the intended floor's distinctive denial banner/version and verify in
   `/hooks` that no other enabled matching handler could account for it; an unattributed deny is
   not proof. Record the exact CWD, reviewed definition/hash, handler attribution, and both results.

Never hand-edit Codex trust state or definition hashes, use a blanket “trust all” action without
reviewing every handler, or pass `--dangerously-bypass-hook-trust`. These shortcuts erase the
review boundary rather than repairing it. This procedure was established on Codex CLI 0.145.0;
if the normal TUI, `/hooks`, or `hooks/list` contract changes in a later version, record that
version-specific difference and re-establish the supported path before relying on it.

### Candidate validation from linked worktrees

A linked-worktree dispatcher or adapter-marker change is a source candidate, not a live hook
candidate. Its candidate-local `.codex/hooks.json` copy is inactive: Codex uses the matching
adapter under the checkout that owns the common Git directory. The expected `doctor --repo`
diagnostic therefore names the root-checkout source and rejects a worktree-only or differing local
copy. Keep that fail-closed result as evidence of the topology; do not make it green by copying the
candidate into the root checkout, hand-editing trust state or hashes, or passing a hook-trust bypass
flag.

Validate an unmerged candidate in separate evidence lanes:

1. Record the candidate's full `git rev-parse HEAD` SHA, then run the source gates that read its
   dispatcher and adapter seam in the candidate worktree:
   `py -3 -m unittest discover -s tests -v` and
   `py -3 templates\hooks\smoke_test.py`. These prove source behavior only.
2. Make a standalone full clone at that exact SHA; do not make another linked worktree. For a local
   source, `git clone --no-local <source-repository> <scratch>` forces an independent object copy.
   Run `git -C <scratch> checkout --detach <candidate-sha>`, then prove that
   `git -C <scratch> rev-parse HEAD` is that SHA, `git -C <scratch> status --porcelain` is empty,
   `git -C <scratch> rev-parse --path-format=absolute --git-common-dir` is inside the scratch clone,
   and `git -C <scratch> worktree list --porcelain` names only the scratch checkout. The selected
   source must contain the exact committed candidate; an uncommitted working-tree copy is not a
   substitute.
3. From the scratch root run the named static audit,
   `py -3 .\harness.py doctor --repo . --json`, and record `Codex project root markers`,
   `Codex hook source`, `Codex adapter contract`, `Codex project hook activation`, and
   `project Codex floor` separately. A detached or feature-branch candidate is not published
   `main`, and its template can differ from the installed global copy, so the overall Doctor result
   may also contain an expected `UNPROVEN` canonical-reference leg or a shared-floor mismatch.
   Record every result; never recast one as green or bypass it. A successful named adapter check
   proves only its stated static scope. It neither grants trust nor executes the dispatcher.
4. Do not start a normal session in that pre-merge scratch clone as a shortcut to candidate runtime
   evidence. The normal project adapter invokes the installed `~/.claude/hooks/dispatch.py` bytes,
   so a canary there can execute the installed dispatcher rather than the candidate
   `templates/hooks/dispatch.py`. Do not deploy dirty, in-review, or unmerged bytes globally to
   change that fact.

Only after the producer change is merged, review a clean-main `sync-global` dry run and separately
authorize installation of the reviewed clean-main bytes. In a new normal TUI from the producer's
exact CWD, use the [project-hook trust bootstrap](#codex-project-hook-trust-bootstrap) to review and
re-trust the installed handler. Then, and only then, collect runtime evidence with both a harmless
allow canary (`git status --short --branch`) and the inert local dry-run deny probe
`git push --dry-run --no-verify --force . HEAD:refs/heads/codex-h2-deny-canary`. The deny must occur
before Git executes and show the intended floor banner/version; the local `.` destination and
`--dry-run` leave no remote mutation. This exact-CWD step proves runtime attribution, not merely
the static marker.

The rollout order is fixed: **producer merge → reviewed clean-main install → producer exact-CWD
re-trust and canaries → consumer marker refresh → each consumer's exact-CWD re-trust and canaries**.
Consumer marker updates and their runtime validation are separate reviewed rollout work; neither a
producer PR nor a standalone scratch audit performs them.

### §5.4 Posture and FLOOR_ACK (owner decisions 2026-09-02 and 2026-09-27; #21 slices #26 / #62; #356)

The analyzer's verdict (`check()`: allow / ask / deny) is computed exactly as before and then
RENDERED by the effective posture (`floor_posture`, resolved by `dispatch.floor_posture`):

| Analyzer verdict | `wall` | `guide` | `core` |
|---|---|---|---|
| allow | allow | allow | allow |
| deny whose reason is pure opacity — `cannot be inspected`, `cannot safely`, `opaque`, `malformed`, `nesting`/`depth exceeds`, `comment inside a scriptblock`, `[push-config-unverifiable]` — but never one naming a `secret-looking` target or an unresolved delete/removal/pathspec operand (`rm -rf $dir`, a splatted `Remove-Item`, `find -delete`, `git rm --pathspec-from-file`): those are #62's GUARDED opacity and take the row below. **And only when the command text, quotes included, carries no charter hint** (`dispatch._CHARTER_HINT`: force spellings or any `git push`, deletion verbs, `sudo`/`doas`/`su`, program text piped or substituted into an interpreter, nested program text such as `-c`/`eval`/`-x`/`foreach`/`bisect run`, brace expansion, secret-looking names, copy/move/write verbs) — the analyzer returns its FIRST deny, so `git push --force origin $BRANCH` is denied as a dynamic refspec before the force check, and the hint keeps it a double-check | deny | **allow** — the parser's uncertainty is not the agent's fault (#21) | **allow**, unless the command carries a CORE hint (`dispatch._CORE_HINT`: the charter hint's deletion verbs, privilege heads, downloaded program text piped or substituted into an interpreter, and secret-looking names — never git push/force, gh, nested program text or work-loss spellings) or a later segment earns a core verdict: then double-check |
| a CORE deny (`dispatch.verdict_is_core`): `rm -rf`/`Remove-Item` outside the project or at a root, an unresolved delete operand, `find -delete`, pipe-to-Remove-Item, a secret-looking target, downloaded program text run directly, privilege elevation, the tag guard (`[tag-guard]`, 1.8.0: a forced or deleting push of a tag, `--mirror`) (a `sensitive_data` repository never runs `core`; see below) | deny | **double-check**: deny once with a key; allow when the identical command carries `# FLOOR_ACK=<key>` | **double-check**, same mechanism |
| any other deny — git config/environment execution, launchers, T4 work-loss spellings, and the git pathspec-file opacity guide keeps as guarded (`git rm --pathspec-from-file`). Branch force, `+refspec` and branch deletion are no longer analyzer denies since 1.8.0 | deny | **double-check** | **allow**, unless the command carries a core hint or a later segment earns a core verdict: then double-check |
| ask (T3 work-loss guards) | ask (Codex: deny) | double-check, same mechanism, both runtimes | **allow**, with the same core-hint and later-segment exception |
| dispatcher error (fail-closed) | deny | deny — never scaled, never acknowledgeable | deny — never scaled |

- Effective posture: T4 or `wave_mode` → `wall`, whatever is declared. Otherwise a declared
  `floor_posture` binds; absent one, `sensitive_data` → `wall`, else `core` (1.7.0). In the merge
  across co-located and chained declarations an undeclared `sensitive_data` declaration VOTES
  `wall`, so a nested or co-located `guide` or `core` cannot relax an outer tightening overlay;
  only the same declaration saying both `sensitive_data` and a posture is the owner's explicit
  choice. A `sensitive_data` repository never runs `core`: a declared `core` renders as `guide`
  there, because the analyzer returns its FIRST deny and a given-up push verdict (an opaque
  refspec, a force spelling) can precede the public-remote privacy check (review of #363).
- Why `core` (owner decision 2026-09-27, issue #356): default-branch history is protected
  SERVER-side by repository rulesets (`non_fast_forward` + `deletion`, no bypass actors) on every
  repository that runs the floor. A ruleset sees every runtime — Claude, Codex, the Muse swarm,
  Grok and humans — and has no parser to fool, while the client floor ran in six Codex roots and
  paid the #21 false-positive tax for history families the server now covers. So below T4/wave
  the client keeps only what no server can protect: local destruction. Floor 1.8.0 (owner
  decision 2026-10-04, #356 step 2) went further and deleted the branch-history families from
  the analyzer at every tier and posture, `sensitive_data` included; the rulesets protect the
  default branch only, so a forced or deleting tag push and `--mirror` stay a core double-check. Security given up, by the
  owner's explicit productivity-first choice: a force-push to a NON-default branch (recoverable
  from the reflog and the PR record, and nothing merges without the gate), local work-loss
  (`reset --hard`, `clean -fdx`, `checkout -- .`, `worktree remove --force`), git
  config/environment execution laundering, and non-sensitive publication (`gh repo create
  --public`). Invariant, test-pinned: `core` never denies what `guide` allows.
- Under `core` the masked-segment re-check runs whenever the whole-command verdict is not core
  (not only for opacity), and keeps the first CORE verdict among the later segments, sharing the
  invocation's remote cache and deadline.
- The key is the first 10 hex characters of SHA-256 over `<reason>\n<command without the marker>`,
  so it binds to that exact command AND verdict: a corrected command, or the same command denied
  for a new reason, is a fresh double-check. The marker is a trailing shell comment
  (`# FLOOR_ACK=<key>`, case-insensitive, on its own last line after a heredoc) because a comment
  is inert in bash and PowerShell and cannot change what runs. It is stripped BEFORE analysis, so
  the analyzer sees the denied text unchanged; a `wall` posture ignores it.
- `smoke_test.py` pins the ANALYZER under an explicit `wall` fixture and the posture layer in its
  own `floor-posture` section; `tests/test_floor_posture.py` asserts every deny literal in
  `dispatch.py` classifies deliberately — a reason the opacity table does not recognise stays on
  the double-check path under `guide`. Under `core` the direction flips by design: only a reason
  the core table recognises is double-checked, so a NEW deny site that should be core must add its
  wording to `_CORE_REASON` (the test pins every current core family by its reason text).
- What this is not: a wall. Below T4/wave the floor is, by owner decision, a speed bump: the
  irreversible core is protected by one deliberate re-read of the exact command, not by refusal.
  A repository that wants the old walls declares `"floor_posture": "wall"`.

## §6 Deny-floor bypass test matrix (must-block / must-allow)

This matrix pins the ANALYZER (every fixture declares `wall`). How a verdict renders below
T4/wave is §5.4's posture table.

Branch history is not in this matrix since floor 1.8.0 (owner decision 2026-10-04, #356 step 2):
the default branch of every floored repository is protected server-side by a ruleset, so
`git push -f`, `git push --force`, `git push origin +main`, `--force-with-lease`, branch deletion
and `--prune` over branches are MUST ALLOW at every tier, `sensitive_data` included (whose
public-remote privacy guard still judges the destination).

MUST BLOCK (all tiers): the tag guard — a forced or deleting push whose destination may be a tag
(`git push --force origin v1.0` where `v1.0` is a local tag, `+refs/tags/*`, `:refs/tags/v1`,
`--delete origin tags/v1`, `git push --force origin tag v1`, `--force`/`--prune` with `--tags`, a
pattern destination outside an explicit non-tag namespace such as `refs/*`), `git push --mirror`
in any abbreviation, and a refspec-less push that inherits a configured mirror or a forced or
deleting tag refspec;
`rm -rf /`, `rm -rf ~`, `rm -rf` outside repo/scratch, `... | Remove-Item`, `... | del`,
`curl … | sh`, `wget … | sh`, `sudo …`, write to `.env`/`*credentials*`/`*secret*` files;
with `sensitive_data`: `git push <public-remote>`, `gh repo create --public` — with the two
ratified BLUEPRINT §1 exceptions: issue #48 for a push ATTRIBUTABLE to a non-sensitive repository,
and the 2026-08-03 exact-route public-synthetic declaration. Both are narrow and every condition
is enforced, so these stay MUST BLOCK
under `sensitive_data` even though the destination is that repository's own remote: any
repository-redirecting git global (`--work-tree`, `--git-dir`, `-c core.worktree`, in any spelling
git accepts), a repository that does not EXPLICITLY declare `sensitive_data: false`, a repository
whose checkout or primary checkout sits inside a directory declaring `sensitive_data`, a
destination that does not resolve to one of the repository's configured remotes, a refspec-less
push inheriting a configured `remote.*.push`, and any multi-ref, tag-publishing or deletion
selector (`--all`, `--tags`, `--follow-tags`, `--mirror`, `--delete`, `-d`, and their
abbreviations). A self-sensitive repository additionally stays MUST BLOCK unless every co-located
declaration grants the same valid `public_synthetic_publication`, the command explicitly names its
declared remote plus one local branch/`HEAD`, that remote has exactly one push URL matching the
declared GitHub repository, no configured `core.gitProxy`/`core.sshCommand` or declared-remote
`receivepack`/`vcs` overrides its transport/receiver, and no command-line `--receive-pack`/`--exec`
or force-with-lease is requested. The declaration never relaxes public repo/gist creation,
visibility changes, or the `gh api` exfiltration surfaces (since 1.6.28 the `sensitive_data`
`gh api` guard is narrowed to those surfaces plus non-branch DELETEs; routine PR/issue/comment
mutations pass).

Secret-file scope, measured not asserted: `` `.env`/`*credentials*`/`*secret*` `` above is
implemented as a NAME test, not an extension test. Its one authoritative coverage statement is the
measured table in `tests/test_secret_path_coverage.py` (#244); `FLOOR_LIMITATIONS.md` records the
divergences. Whether `*secret*` was ever meant as a suffix glob is an open owner reading, so this
records the divergence without changing it (issue #130).

MUST BLOCK only at T4 / `wave_mode` (warn at T3, allow T1–T2): `git reset --hard`,
`git clean -fd`, `git checkout -- .`, `git worktree remove --force` — and the LAUNDERED
force spellings of a worktree removal, which ride the identical ladder because an opaque
spelling must never score better than the literal form it might be: a runtime-computed
action word (`git worktree $ACT …`, issue #117 — `[worktree-action-opaque]`), a dynamic
option or separator-free operand token in a removal (`-$X`, bare `$A` —
`[worktree-remove-opaque]`; global law 7's `$WT_PROJECT_DIR/<name>` compounds keep the plain
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
removal, which is why global law 7 mandates `git switch -c` before committing (issue #122; the
floor cannot see detached-ness in argv). All measured on git 2.45.1 and pinned by
`ignored_worktree_removal_is_destructive` in `smoke_test.py`, including the
`status.showUntrackedFiles=no` blinding of the untracked-file refusal.
Keep no `.env` that must outlive its worktree.

MUST ALLOW (false-positive regression tests): commit/PR bodies *describing* dangerous commands
(`git commit -m "block rm -rf in hook"`), `gh pr create --body-file …`, branch force, lease,
`+refspec`, deletion and `--prune` at every tier (1.8.0), a non-forced push of a tag (git refuses
to move an existing tag without force), and compound commands where the dangerous-looking text is
inside quotes.

Parsing notes: tokenize argv (shlex for POSIX; separate lightweight matcher for PowerShell
pipe forms — shlex won't parse `| Remove-Item`); split on `;`, `&&`, `|` and check each
segment; NEVER match against `-m`/`--body` string arguments.

### §6.1 Cross-product gate — where the tripwire ends (issue #63)

The matrix above tests each command in canonical form. `tests/test_prefix_wrapper_crossproduct.py`
crosses it with the shapes real command lines carry — 25 prefix spellings (leading
redirections, `VAR=value`, separators, and combinations) and 74 wrapper spellings (launchers,
container/remote exec, nested interpreters, scriptblock/evaluator forms) — and asserts BOTH
directions: charter denies stay denied, curated benign commands stay allowed.

A shape the floor does not cover is recorded in that module's baselines with the issue it
belongs to, so the repo states where the tripwire ends instead of leaving it unstated:
`DOCUMENTED_BYPASSES` (whole shapes: #56, #37, #9, #67), `DOCUMENTED_CASE_BYPASSES`
(individual rules disarmed by an otherwise-covered wrapper: #68, #69, #79, #80),
`DOCUMENTED_OVER_BLOCKS` (shapes that deny EVERY benign payload: #21 plus the charter's
own privilege-transition denials) and `DOCUMENTED_CASE_OVER_BLOCKS` (its payload-granular
mirror). A baseline entry that starts behaving correctly fails the gate as UNEXPECTEDLY
FIXED, so a fix has to be promoted into the enforced set rather than left un-guarded
against a later re-break. That promotion is the mechanism, not a formality: every executable
#46 prefix shape and 3 of the #68 case entries were retired this way once main closed them.
Command-leading `--%` rows were removed instead of being credited as executable coverage.

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

**No new stop-hooks.** The states above are the grandfathered set (BLUEPRINT P12 — the
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
| Merge decisions; second lens on high-risk work | top | high (xhigh only if irreversible / wide blast radius) | wall at T4 (gate), tripwire below |
| Adversarial review gate | default | high | convention |
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
disagree, the skill wins and the local copy is the bug. Model bans and admissions are declared in the
`model-effort-routing` skill and enforced by the config repo's `tests/check-agent-models.ps1`;
they are deliberately not restated here. This table is the durable judgment-vs-mechanical shape and
changes only when that shape changes.

## §9 Bootstrapper CLI + ESTATE.md

Home: this repo. Implemented in the dependency-free `harness.py` (one implementation, no
`.sh`/`.ps1` twins):
- `harness.py seed <path> --tier N` — writes only the runtime-neutral tier germ and refuses
  overwrite, plus one `/.claude/worktrees/` line appended to `.gitignore` when no line already
  ignores that root (#236: otherwise worktree isolation commits it straight to the default branch).
  Repo instructions remain judgment work and are not generated blindly.
- `harness.py audit <path>` — validates tier schema, instruction/skill budgets, Git state, and
  stale user-profile paths, and default-branch server-side history protection
  (`non_fast_forward` + `deletion` ruleset or classic equivalent) on the remote `git push` targets, reported as an advisory
  when the effective floor posture is `core` or `floor_wiring` is `none` (issues #356, #370).
  Explicit push-remote configuration wins over the implicit sole-remote fallback; each GitHub
  push URL is measured independently of non-GitHub neighbours. Unresolved URL-valued selections
  remain `UNPROVEN` (#438). Fallback counts include URL-less remotes, and a successfully read
  empty selector is explicit invalid configuration rather than an unset key.
- `harness.py sync-global --config-root <claude-config> [--apply]` — previews or installs global
  Codex guidance, managed skills, and shared Claude-home floor bytes with timestamped backups;
  removes only the obsolete managed global Codex matcher. New Codex skill backups are stored under
  `<codex-home>/backups/<timestamp>/skills/`, outside the recursively scanned `skills-home`; custom
  overlapping home/source layouts fail before writes, and legacy `skills-home/.harness-backups/`
  trees are neither migrated nor deleted.
  Selected skill roots (`skill:` and `claude-skill:`) are probed together across both families with
  name-only directories on each shared destination parent before either family applies changes.
  Recovery-name checks run only for changed existing Codex targets and changed Claude staging
  targets (including new trees); identical trees never require a backup-name probe. Roots the
  destination's own lookup merges (for example `Foo` and `foo` on a case-insensitive volume) are
  refused before any live or backup write, dry run included. Destination parents group by
  filesystem identity (an existing parent by `samefile`; absent parents by their nearest existing
  ancestor plus that directory's own lookup of the absent names, via a removed probe tree), never
  by casefolding. A Codex target nested inside a Claude target, or the reverse, is refused the
  same way (`selected skill destinations overlap`). Qualifications, not guarantees: an
  installed skill holding a hard link to a case-variant entry stays an ambiguous-spelling refusal
  (the message names the entries; remove the extra link or stale entry and re-run), and a destination
  that fakes mode bits (exFAT/FAT on POSIX) fails the post-copy digest check, which compares
  executable bits, rather than being treated as installed.
- `harness.py sync-global --config-root <claude-config> --only claude-skill:<name>
  [--only claude-skill:<name> ...] [--apply]` — previews or installs only the named Claude-native
  skill trees from `<config-root>/skills/` to `<claude-home>/skills/`. It preflights every selected
  tree before writing, refuses aliases/reparse points, overlapping roots, traversal selectors, and
  destination paths the source does not own, and backs up each complete existing destination tree
  before replacement. Different bytes at a source-owned relative path are replaceable under
  explicit `--apply`; the backup is the recovery boundary rather than an inferred local-edit
  detector. Apply stages every changed source outside skill discovery and verifies its preflight
  digest before moving a live target atomically into the backup. The moved snapshot is revalidated;
  detected late writes refuse replacement and remain live or backed up. Promotion failure restores
  a live copy while retaining the recovery backup. This does not claim lock-free writer exclusion.
  This selector does not expand the no-`--only` default set.
- `harness.py sync-global --config-root <claude-config> --only bundle:muse-runtime
  [--user-bin-home <path>] [--apply]` — previews or installs only schema-1 components in
  `<config-root>/.agent-harness/sync-global.json` under `bundles.muse-runtime`. A component is an
  exact ordinary `file` or `tree` source plus a destination containing a logical root
  (`claude-home` or `user-bin-home`) and a canonical relative path. The selector is exclusive and
  never joins the default sync set. All manifest paths, component kinds, aliases/reparse points,
  source/target overlaps, destination collisions, source bytes, and target bytes are preflighted;
  apply stages and digest-checks every source, then revalidates every source and target before the
  first live move. Existing targets become complete backups. A successful install atomically
  publishes a schema-1 receipt below
  `<claude-home>/.harness-backups/sync-global-bundles/<run>/receipt.json`; it contains logical roots
  and relative paths, never trusted absolute targets. The reviewed Muse manifest must exclude
  vendor executables, runtime settings, credentials, policy, repository declarations, and
  noncanonical launchers.
- `harness.py sync-global --config-root <claude-config> --only bundle:muse-runtime
  --rollback-receipt <path> [--apply]` — previews or executes receipt rollback. Before any target
  moves, every live target must still equal its installed digest and every present-state backup
  must equal its recorded digest. Present targets are restored and originally absent targets are
  removed; the installed candidates are retained under a rollback recovery directory. Receipt
  source, destination, and backup locations are re-parsed as canonical relative paths under the
  current logical roots or receipt directory. Rollback is compare-and-swap recovery, not a claim
  of lock-free exclusion, runtime health, or successful native Muse execution.
- `harness.py doctor [--repo <path>]` — checks live global guidance/floor topology, core
  executables, and optionally one repo-local Codex floor definition plus the static base-user and
  active-project MCP topology. It rejects active command-backed names duplicated across those
  scopes, active layered mixed command/URL transports, and Docker MCP gateways with neither
  `--servers` nor `--profile`; an effective disabled state suppresses only a cross-layer transport
  conflict, while a same-table conflict remains malformed and a later re-enable fails closed. This
  is topology validation, not proof that Codex's full configuration loader accepts every inactive
  definition; it never renders arguments, mutates configuration, or probes runtime processes.
- `harness.py worktree-lease --repo <linked-worktree> --action
  <status|acquire|renew|release> [--claimant <id>]` — manages the cooperative owner record stored
  in the linked worktree's Git administrative directory. Acquire requires absence, or
  `--replace-stale` for a structurally valid expired record; renew and release require the same
  self-declared claimant. The record is scoped to the canonical common-Git directory, canonical
  worktree, and plain-removal operation, with bounded creation/renewal and expiry timestamps.
- `harness.py worktrees --repo <path> [--refresh] [--claimant <id>] [--apply] [--json]` — reports
  every registered linked worktree and only removes a candidate after an explicit complete branch
  namespace refresh for every remote, one canonical physical identity from discovery through the
  removal operand, exact containment under the primary checkout's `.worktrees/`, no configured
  work-tree redirection, clean tracked/staged/untracked/ignored state, no observable
  executable-mode-only difference, no assume-unchanged/skip-worktree index flags or resolve-undo
  recovery records, no pending `COMMIT_EDITMSG` differing from the current commit message, no
  worktree-local refs,
  non-baseline administrative/operation state, or non-regular candidate HEAD reflog, no direct
  `ORIG_HEAD` target whose object type is not `commit`, no recovery commit held only by either
  object-ID side of a raw candidate HEAD reflog record or by `ORIG_HEAD`, an attached
  `refs/heads/*` local branch, an unmodified commit graph after scrubbing
  inherited graft
  overrides, remote-ref reachability, an active exactly scoped
  lease owned by the supplied claimant, and same-run fingerprint plus lease revalidation while
  holding the lease-mutation lock through plain removal. Fingerprints expire when either monotonic
  active-runtime age or suspend-inclusive UTC age exceeds the declared lease; UTC rollback refuses
  safely. Missing,
  malformed, mismatched, stale, nearly expired, changed, differently
  owned leases refuse safely. The default performs no fetch or mutation; `--apply` requires
  `--refresh --claimant`, uses only plain `git worktree remove`, never prunes repository-wide
  worktree metadata, and never deletes a branch. Git-locked, current, primary, outside, unavailable,
  detached, administratively stateful, and cooperatively occupied worktrees are retained.
  If a later candidate's fresh registry revalidation fails after an earlier removal, APPLY stops,
  retains current and remaining candidates, reports the partial result, and never retries or rolls back.
  Recovery reachability uses one bounded stdin-fed Git traversal for a non-empty object set and no
  traversal for an empty set.
  Canonical identity collapses Windows short/long paths and macOS `/var` aliases. JSON schema
  version 3 carries the mode, index-recovery, pending-message status, local-ref,
  administrative-state, direct-`ORIG_HEAD` object identity/type, and recovery-retention evidence
  without emitting commit-message content.
  Native Windows skips only the forced executable-mode comparison because its working tree cannot
  represent Git's Unix executable bit and otherwise synthesizes `100755` to `100644` differences
  for clean files. POSIX forces that comparison even when repository `core.fileMode=false`,
  preserving genuine mode-only drift; a POSIX filesystem that cannot expose the bit may still
  conservatively retain a candidate.

The owner lease is coordination, not authentication or an OS lock. It proves nothing about a
process that does not follow the protocol. A non-cooperating process or watcher may still write
after revalidation, including an ignored file that plain removal would delete; text and JSON output
carry that limitation, and the command does not claim arbitrary external-process occupancy
detection.

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
  never a model name (§1 no longer quotes the law text, so there is no exemption). Agent definitions are the ONE permitted DERIVED copy, because `model:` in
  `~/.claude/agents/gardener.md` is a machine-read field that cannot hold an indirection. Being
  permitted, that copy is governed rather than trusted:
  1. Changing which model fills a tier in the skill is NOT DONE until every agent definition
     pinned to that tier is re-pinned in the same change — one commit, both surfaces.
  2. Nothing today records WHICH tier a given `model:` derives from, so the copy is currently
     conventional rather than checkable. Making it checkable — a declared tier next to the pin,
     and a check that compares the two — is the substance of issue #76.
  3. `tests/check-agent-models.ps1` in the config repo is the enforcement surface. Today it
     asserts only that no definition pins a banned model (the set the `model-effort-routing` skill declares); extending
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
   that has a home (BLUEPRINT P2).
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
  names models and their effort bindings (claude-config's `rules/laws.md` also names models in
  its working style; the skill stays authoritative for model names where the two disagree, and
  claude-config stays authoritative for law text); §8 above and BLUEPRINT §5 carry the task-class→tier shape
  and point here. Global CLAUDE.md (global law 5 + Working style) and the T2 SessionStart nudge only point
  at them.
- 4 `bootstrap-*.ps1` (2,664 lines, Apr 9, drifted): salvage text into `templates/`, then delete.
- Plugins: keep pr-review-toolkit/code-review/feature-dev ONLY where a repo hasn't chosen its
  local skill for that verb (record per-repo in ESTATE.md); delete disabled marketplace clones.
- MCP: keep MCP_DOCKER global; remove dead per-repo entries (e.g. the forbidden ripgrep MCP in
  olb's config.toml) during migration.

## §14 The bounded review pipeline (`review-and-ship`)

BLUEPRINT §1's T3 "bounded review pipeline" slot is filled by the `review-and-ship` skill,
shipped from claude-config for both runtimes. Reference, don't restate: the skill file is the
single home for the step-by-step, and global law 2 (claude-config `rules/laws.md`) plus BLUEPRINT P11 are the
contract it executes — one review round, one severity-bar triage (confirmed CRITICAL/HIGH fix
commits only; the rest tracked or declined on the thread), one fix round verified against the
fix diff (a fresh-context pass is owed only when the fixes changed logic or the risk boundary,
global law 2g; a manual `@codex review` is never a per-fix step, global law 2f) — then ship or park. Tier changes WHO reviews and how many eyes the single
round gets (T1-T3 one independent pass, with a second distinct lens at T3 only for genuinely
high-risk work; T4 two adversarial reviews), never how many rounds run.
