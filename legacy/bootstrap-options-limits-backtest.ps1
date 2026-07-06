param(
  [string]$RepoPath = $PWD.Path,
  [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Directory {
  param([string]$Path)
  New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Write-FileIfNeeded {
  param(
    [string]$Path,
    [string]$Content,
    [switch]$ForceWrite
  )

  $shouldWrite = $true
  if ((Test-Path $Path) -and -not $ForceWrite) {
    $existing = Get-Content -Raw -Path $Path
    if ($existing -eq $Content) {
      $shouldWrite = $false
    }
  }

  if ($shouldWrite) {
    Set-Content -Path $Path -Value $Content -NoNewline
  }
}

function Add-ExcludeLine {
  param(
    [string]$ExcludeFile,
    [string]$Line
  )

  if (-not (Test-Path $ExcludeFile)) {
    Ensure-Directory (Split-Path -Parent $ExcludeFile)
    Set-Content -Path $ExcludeFile -Value "# git ls-files --others --exclude-from=.git/info/exclude`n"
  }

  $existing = Get-Content -Path $ExcludeFile
  if ($existing -notcontains $Line) {
    Add-Content -Path $ExcludeFile -Value $Line
  }
}

$repoRoot = (git -C $RepoPath rev-parse --show-toplevel).Trim()
$repoRootNormalized = [IO.Path]::GetFullPath($repoRoot).TrimEnd('\', '/').Replace('/', '\')
$repoPathNormalized = [IO.Path]::GetFullPath($RepoPath).TrimEnd('\', '/').Replace('/', '\')

if ($repoPathNormalized.StartsWith($repoRootNormalized, [System.StringComparison]::OrdinalIgnoreCase)) {
  $relativeRepoPath = $repoPathNormalized.Substring($repoRootNormalized.Length).TrimStart('\', '/')
} else {
  throw "RepoPath must be inside repo root. Repo root: $repoRootNormalized Repo path: $repoPathNormalized"
}

$relativeRepoPath = $relativeRepoPath.Replace("\", "/")

$globalSkillsRoot = Join-Path $env:USERPROFILE ".claude\skills"
$bootstrapTarget = $RepoPath
$repoClaudeSkillsRoot = Join-Path $bootstrapTarget ".claude\skills"
$repoClaudeSettingsLocal = Join-Path $bootstrapTarget ".claude\settings.local.json"
$repoClaudeMd = Join-Path $bootstrapTarget "CLAUDE.md"
$excludeFile = Join-Path $repoRoot ".git\info\exclude"

$safeShell = @'
---
name: safe-shell
description: Use before proposing or running shell commands. Prefer safe reads and narrow verification. Escalate mentally before anything destructive, credential-related, or broad.
user-invocable: true
---

# Safe Shell

Use this skill whenever command safety is even slightly unclear.

## Safe by default

- read-only inspection: `pwd`, `ls`, `rg`, `git status`, `git diff`, `git show`
- targeted verification: test, lint, build, typecheck
- creating new local files or directories for the task

## Pause and reassess

- deleting files or directories
- recursive moves or broad rewrites
- touching secrets, credentials, or environment files
- force-push, hard reset, history edits
- system-wide installs or service changes

## Required behavior

1. Prefer the narrowest command that proves the point.
2. Prefer dry runs, diffs, or previews before state-changing commands.
3. Never rely on `.gitignore` to hide already tracked files.
4. Keep machine-specific paths and secrets out of committed files.

## Output

State:

- what you plan to run
- why it is safe
- what safer fallback exists if risk rises
'@

$smallSafeSlice = @'
---
name: small-safe-slice
description: Turn a request into one reviewable implementation slice with explicit verification and minimal collateral change.
user-invocable: true
---

# Small Safe Slice

Default execution loop for coding work.

## Workflow

1. Restate the task in one sentence.
2. Identify the smallest seam that materially advances it.
3. Read only the files needed to confirm that seam.
4. Make one coherent change set.
5. Run the narrowest meaningful verification.
6. Summarize outcome, residual risk, and next slice.

## Guardrails

- prefer one seam, one guardrail, or one behavior change per slice
- avoid opportunistic refactors
- if the request is broad, implement the first safe slice rather than sprawling
- if you discover unrelated breakage, report it separately unless it blocks the slice

## Verification

Choose the smallest check that matches the change:

- route change -> targeted tests or smoke
- UI contract change -> targeted build or typecheck
- docs or workflow change -> path and syntax validation

## Output

- files touched
- verification run
- what remains for the next slice
'@

$verificationCloseout = @'
---
name: verification-closeout
description: Close work rigorously. Verify the changed seam, call out remaining risk, and sync any required docs or status artifacts.
user-invocable: true
---

# Verification Closeout

Use this after meaningful work or before handing a task back.

## Checklist

1. Re-read the requested outcome.
2. Verify the changed seam directly.
3. Confirm no broader rewrite slipped in.
4. Note any unrun checks and why.
5. Sync required docs or status files if the repo expects it.

## Report clearly

- what was changed
- what was verified
- what was not verified
- residual risks or likely follow-up work

## Guardrails

- do not claim verification you did not run
- do not bury open risk under a long changelog
- when docs or workflow files are part of the definition of done, update them in the same slice
'@

$repoClaude = @'
# Options Limits Backtest Personal Claude Workflow

This file is local-only and is meant to keep Claude aligned with the repo's real control plane without modifying the shared team workflow.

## Working model

- Treat `AGENTS.md` as the primary repo contract.
- Treat `.codex/README.md` and `.codex/memories/00_ACTIVE.md` as the active execution control plane.
- Treat root `memories/` and the tracked `.claude/` docs as shared team reference material, not the default execution board.
- Keep diffs small and reviewable.
- For backlog-style implementation work, create a branch scoped to the slice before editing.

## Read order

1. `AGENTS.md`
2. `.codex/README.md`
3. `.codex/memories/00_ACTIVE.md`
4. `.codex/memories/program/00_READ_THIS_FIRST.md`
5. `.codex/memories/phase6/STATUS.md`
6. the relevant track `00__Start.md` or active ExecPlan

Read only when relevant:

- tracked `.claude/skills/i18n-manager.md` for frontend text and translation work
- tracked `.claude/skills/ui-ux-manager.md` for theme, accessibility, and UI consistency work
- tracked `.claude/skills/documentation-manager.md` only when the task explicitly targets the older root `memories/` system

## Preferred skills

General skills from `~/.claude/skills`:

- `safe-shell`
- `small-safe-slice`
- `verification-closeout`

Repo-specific local skills in this checkout:

- `olb-repo-onramp`
- `olb-safe-slice`
- `olb-verify-and-sync`
- `olb-issue-to-pr`

## Repo truths

- Phase 6 is the active implementation phase unless `.codex/memories/00_ACTIVE.md` says otherwise.
- The current delivery system is under `.codex/`, not the older root `memories/` workflow.
- Shared `.claude/` docs remain useful references for i18n and UI discipline, but they are not the default execution lane.
- If behavior, security posture, testing posture, or operational workflow changes, sync the required `.codex` status and decision artifacts.

## Guardrails

- Do not assume `.gitignore` can privatize tracked files.
- Do not edit the tracked `.claude/` team docs unless the task explicitly asks for it.
- Keep machine-specific or personal workflow files local-only.
- Prefer concrete verification over broad explanation.
'@

$repoSettingsLocal = @'
{
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": [
      "Bash(rg:*)",
      "Bash(make:*)",
      "Bash(py -3 scripts/docs_control_plane_check.py:*)",
      "Bash(python -m pytest:*)",
      "Bash(backend/.venv/Scripts/python.exe -m pytest:*)",
      "Bash(npm ci:*)",
      "Bash(npm run:*)"
    ],
    "deny": [
      "Bash(git push --force:*)",
      "Bash(git push --force-with-lease:*)",
      "Bash(git reset --hard:*)",
      "Bash(rm -rf /:*)"
    ]
  },
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'Options Limits Backtest. Read CLAUDE.md, AGENTS.md, .codex/README.md, and .codex/memories/00_ACTIVE.md before editing.'",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
'@

$repoOnramp = @'
---
name: olb-repo-onramp
description: Orient to the current Options Limits Backtest control plane before editing. Use at session start, when scope is vague, or when crossing into an unfamiliar area.
user-invocable: true
---

# Options Limits Backtest Repo Onramp

Establish current truth before editing code or docs.

## Read first

1. `CLAUDE.md`
2. `AGENTS.md`
3. `.codex/README.md`
4. `.codex/memories/00_ACTIVE.md`
5. `.codex/memories/program/00_READ_THIS_FIRST.md`
6. `.codex/memories/phase6/STATUS.md`

Read when relevant:

- the matching phase track `00__Start.md`
- the relevant ExecPlan under `.codex/memories/phase6/execplans/`
- tracked `.claude/skills/i18n-manager.md` for frontend text work
- tracked `.claude/skills/ui-ux-manager.md` for theme or accessibility work

## Produce a working summary

Extract only what the task needs:

- current active phase and lane
- constraints that must not be broken
- likely files, tests, and docs affected
- whether this is a shared control-plane task or only a local workflow task

## Guardrails

- trust active `.codex` docs over older reference material when they conflict
- do not default to the root `memories/` system for active implementation work
- keep the first implementation slice small and measurable
'@

$repoSafeSlice = @'
---
name: olb-safe-slice
description: Implement one small, reviewable slice in Options Limits Backtest without drifting across layers or docs.
user-invocable: true
---

# Options Limits Backtest Safe Slice

Use this when you are implementing or editing inside this repo.

## Workflow

1. Confirm the active phase in `.codex/memories/00_ACTIVE.md`.
2. Identify the smallest seam that advances the request.
3. If the work maps to a backlog-style slice, read the relevant issue seed or track docs first.
4. Keep the diff within one coherent seam.
5. Run the narrowest meaningful verification.
6. If the change affects behavior, workflow, security, testing, or docs expectations, queue the required `.codex` sync work before closing.

## Preferred checks

- backend change -> targeted `pytest`
- frontend change -> targeted `npm run build` or type-aware check
- docs or workflow change -> path, syntax, and ignore-state validation

## Extra repo guardrails

- do not accidentally change product semantics while touching plumbing
- do not mix the active `.codex` workflow with the older root `memories/` flow unless explicitly required
- if you touch user-visible frontend text, make the i18n pass in the same slice
'@

$repoVerifyAndSync = @'
---
name: olb-verify-and-sync
description: Close an Options Limits Backtest task properly: verify the changed seam and sync required `.codex` status artifacts when needed.
user-invocable: true
---

# Options Limits Backtest Verify And Sync

Use this after meaningful work or before ending a session.

## Verify first

1. Re-read the requested outcome.
2. Verify the changed seam directly.
3. State what was not verified.

## Sync when required

Update these only when the work actually changes their truth:

- `.codex/memories/phase6/STATUS.md`
- relevant ExecPlan under `.codex/memories/phase6/execplans/`
- relevant track backlog
- `.codex/memories/program/08_IMPLEMENTATION_LEDGER.csv`
- `.codex/memories/phase6/decisions/` for meaningful decisions

## Guardrails

- keep status updates factual and short
- do not rewrite large reference packs just to mirror the code change
- if the task is local workflow only, verify that no tracked shared files were unintentionally changed
'@

$repoIssueToPr = @'
---
name: olb-issue-to-pr
description: Take one Options Limits Backtest issue or backlog slice from understanding to branch, implementation, verification, and PR-ready handoff without drifting outside the intended seam.
user-invocable: true
---

# Options Limits Backtest Issue To PR

Use this for end-to-end implementation when the work should land as one reviewable PR slice.

## Input

The task can be given as:

- a GitHub issue number
- a Phase 6 or Phase 7 issue id such as `6D-002`
- a clearly named backlog slice or PR slice

## Workflow

### 1. Orient before branching

1. Read `CLAUDE.md`.
2. Read `AGENTS.md`.
3. Read `.codex/README.md`.
4. Read `.codex/memories/00_ACTIVE.md`.
5. Read `.codex/memories/program/00_READ_THIS_FIRST.md`.
6. Read `.codex/memories/phase6/STATUS.md` unless the active gate says otherwise.

Then identify:

- the active phase and lane
- the matching issue seed, track doc, or ExecPlan
- the intended `pr_slice`
- the smallest deliverable that moves the slice forward

### 2. Resolve the task source

If the input is a GitHub issue:

- inspect it with `gh issue view <number> --json title,body,labels,assignees,milestone`
- map it to the relevant `.codex` issue seed or track doc if one exists

If the input is a Phase issue id such as `6D-002`:

- find the matching issue seed under `.codex/memories/phase6/concrete/issues/` or `.codex/memories/phase7/issues/`
- read the relevant track `00__Start.md` and any active ExecPlan

## 3. Branch

Create a fresh branch before editing when the task is a real implementation slice.

Preferred format:

- `phase6/<issue-id>-<short-slug>`
- `phase7/<issue-id>-<short-slug>` for planning or future-gated design work only when allowed
- `issue-<number>/<short-slug>` if the GitHub issue is the primary identifier

Examples:

- `phase6/6d-002-provider-timeouts`
- `phase6/6i-001-minimal-fixture-spec`
- `issue-58/admin-authz-regression`

### 4. Implement one reviewable slice

- keep the diff inside the intended seam
- prefer one guardrail, one behavior fix, or one operational capability per PR
- avoid broad cleanup while implementing
- if you discover the issue is too large for one PR, stop and restate the first safe slice

### 5. Verify narrowly and concretely

Run the narrowest meaningful checks for the changed seam.

Typical checks in this repo:

- backend: `make backend-test` or targeted `pytest`
- backend lint/type: `make backend-lint`
- frontend: `make frontend-build`
- docs/control plane: `make docs-lint` or `py -3 scripts/docs_control_plane_check.py`

Do not claim checks you did not run.

### 6. Sync required `.codex` artifacts

If the work changed real repo truth, update only what applies:

- `.codex/memories/phase6/STATUS.md`
- relevant ExecPlan in `.codex/memories/phase6/execplans/`
- relevant track backlog
- `.codex/memories/program/08_IMPLEMENTATION_LEDGER.csv`
- ADR under `.codex/memories/phase6/decisions/` when a real tradeoff was made

### 7. Prepare PR handoff

Use `gh` CLI by default for GitHub operations in this repo.

PR body should include:

- summary
- impacted folders
- tests or verification
- migration notes if relevant
- compatibility or breakage notes if a hack or unsafe shortcut was removed

Suggested structure:

```markdown
## Summary
<what changed and why>

## Scope
- <slice 1>
- <slice 2>

## Verification
- <command and outcome>

## Notes
- <migration, compatibility, or operator note if relevant>
```

## Guardrails

- do not skip the active phase gate
- do not let a single issue silently expand into a rewrite
- do not use tracked `.gitignore` changes as a way to privatize local workflow files
- prefer `gh` over GitHub MCP for this repo unless the access issue is known to be resolved
- if the task is blocked or ambiguous, restate the blocker before coding

## Output

At handoff, provide:

- branch name
- files changed
- verification run
- synced docs or status artifacts
- what remains for review or the next slice
'@

Ensure-Directory $globalSkillsRoot

Ensure-Directory (Join-Path $globalSkillsRoot "safe-shell")
Ensure-Directory (Join-Path $globalSkillsRoot "small-safe-slice")
Ensure-Directory (Join-Path $globalSkillsRoot "verification-closeout")

Write-FileIfNeeded -Path (Join-Path $globalSkillsRoot "safe-shell\SKILL.md") -Content $safeShell -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $globalSkillsRoot "small-safe-slice\SKILL.md") -Content $smallSafeSlice -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $globalSkillsRoot "verification-closeout\SKILL.md") -Content $verificationCloseout -ForceWrite:$Force

Ensure-Directory $repoClaudeSkillsRoot
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "olb-repo-onramp")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "olb-safe-slice")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "olb-verify-and-sync")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "olb-issue-to-pr")

Write-FileIfNeeded -Path $repoClaudeMd -Content $repoClaude -ForceWrite:$Force
Write-FileIfNeeded -Path $repoClaudeSettingsLocal -Content $repoSettingsLocal -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "olb-repo-onramp\SKILL.md") -Content $repoOnramp -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "olb-safe-slice\SKILL.md") -Content $repoSafeSlice -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "olb-verify-and-sync\SKILL.md") -Content $repoVerifyAndSync -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "olb-issue-to-pr\SKILL.md") -Content $repoIssueToPr -ForceWrite:$Force

Add-ExcludeLine -ExcludeFile $excludeFile -Line "# Local-only Claude workflow for $relativeRepoPath"
Add-ExcludeLine -ExcludeFile $excludeFile -Line "/$relativeRepoPath/CLAUDE.md"
Add-ExcludeLine -ExcludeFile $excludeFile -Line "/$relativeRepoPath/.claude/settings.local.json"
Add-ExcludeLine -ExcludeFile $excludeFile -Line "/$relativeRepoPath/.claude/skills/olb-issue-to-pr/"
Add-ExcludeLine -ExcludeFile $excludeFile -Line "/$relativeRepoPath/.claude/skills/olb-repo-onramp/"
Add-ExcludeLine -ExcludeFile $excludeFile -Line "/$relativeRepoPath/.claude/skills/olb-safe-slice/"
Add-ExcludeLine -ExcludeFile $excludeFile -Line "/$relativeRepoPath/.claude/skills/olb-verify-and-sync/"

Write-Host "Bootstrapped Claude workflow for: $RepoPath"
Write-Host "Repo root: $repoRoot"
Write-Host "Local files are excluded through: $excludeFile"
Write-Host "Start Claude from the repo path above for the cleanest project context."
