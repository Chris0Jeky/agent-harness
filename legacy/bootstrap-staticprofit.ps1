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
$excludePrefix = ""
if ($relativeRepoPath) {
  $excludePrefix = "/$relativeRepoPath"
}

$globalSkillsRoot = Join-Path $env:USERPROFILE ".claude\skills"
$repoClaudeSkillsRoot = Join-Path $RepoPath ".claude\skills"
$repoClaudeSettingsLocal = Join-Path $RepoPath ".claude\settings.local.json"
$repoClaudeMd = Join-Path $RepoPath "CLAUDE.md"
$repoCodexRoot = Join-Path $RepoPath ".codex"
$repoCodexActivePath = Join-Path $RepoPath ".codex\memories\00_ACTIVE.md"
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
# Staticprofit Personal Claude Workflow

This file is local-only. It gives Claude a stable repo-specific entrypoint without modifying the shared repository workflow.

## Working model

- Treat `AGENTS.md` as the primary repo contract.
- Treat this repo as a Laravel 5.7 application with a small Vue 2 / Laravel Mix frontend.
- Treat `encore_custom/` as application-owned framework code, not third-party vendor code.
- Keep diffs small and reviewable.
- For meaningful implementation work, create a branch scoped to the change before editing.

## Read order

1. `AGENTS.md`
2. `readme.md` if repo-wide orientation is still unclear
3. `guide_and_commands.txt` when local command or operator context is needed

Read this workpack before touching HST auth, login, logout, session, Keycloak, SSO, or permission-flow code:

1. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/README.md`
2. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/MASTER_PLAN.md`
3. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/IMPLEMENTATION_TRACKER.md`
4. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/CODEBASE_AUDIT.md`
5. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/HST_HOOKS_AND_CHANGE_SURFACE.md`

## Preferred skills

General skills from `~/.claude/skills`:

- `safe-shell`
- `small-safe-slice`
- `verification-closeout`

Repo-specific local skills in this checkout:

- `sp-repo-onramp`
- `sp-safe-slice`
- `sp-verify-handoff`
- `sp-hst-sso-workpack`

## Repo truths

- The active documented workstream is HST centralized login / Keycloak / SSO on `stats_tools`.
- The HST SSO workpack under `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/` is the canonical planning pack for auth-flow work in this repo.
- Edit source files in `resources/` and rebuild assets when needed. Do not hand-edit compiled files in `public/`.
- PHPUnit is the configured test framework. Prefer focused regression coverage for touched behavior.
- There is no shared repo-local Codex planning system here yet; any `.codex/` content in this checkout is private/local-only unless the team later decides otherwise.

## Guardrails

- Do not rely on tracked `.gitignore` changes to privatize local workflow files.
- Keep `CLAUDE.md`, `.claude/`, and `.codex/` local-only in this repo.
- Never commit secrets, tokens, machine-specific `.env` values, or sensitive dumps.
- When changing auth or session behavior, preserve rollout safety and verify the downstream hooks described by the workpack before removing existing behavior.
'@

$repoSettingsLocal = @'
{
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": [
      "Bash(rg:*)",
      "Bash(git status:*)",
      "Bash(git diff:*)",
      "Bash(composer install:*)",
      "Bash(composer dump-autoload:*)",
      "Bash(php artisan:*)",
      "Bash(vendor/bin/phpunit:*)",
      "Bash(npm install:*)",
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
            "command": "echo 'staticprofit. Read CLAUDE.md and AGENTS.md. If touching HST auth or SSO, read storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/README.md first.'",
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
name: sp-repo-onramp
description: Orient to the staticprofit repo before editing. Use at session start, when scope is vague, or when entering unfamiliar Laravel or auth code.
user-invocable: true
---

# Staticprofit Repo Onramp

Establish current truth before touching code or docs.

## Read first

1. `CLAUDE.md`
2. `AGENTS.md`
3. `readme.md` if high-level orientation is still unclear
4. `guide_and_commands.txt` when local command or environment context matters

If the task touches auth, login, logout, session, SSO, Keycloak, impersonation, or permission flow, also read:

1. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/README.md`
2. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/MASTER_PLAN.md`
3. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/IMPLEMENTATION_TRACKER.md`
4. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/CODEBASE_AUDIT.md`
5. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/HST_HOOKS_AND_CHANGE_SURFACE.md`

## Produce a working summary

Extract only what the task needs:

- likely change surface in `app/`, `routes/`, `resources/`, `config/`, or `tests/`
- current constraints from `AGENTS.md`
- whether the HST SSO workpack is in scope
- whether assets must be rebuilt from `resources/`

## Guardrails

- trust the HST SSO workpack over ad hoc notes when auth-flow work is involved
- do not create a parallel planning tree under random temp files
- keep the first implementation slice small and measurable
'@

$repoSafeSlice = @'
---
name: sp-safe-slice
description: Implement one small, reviewable slice in staticprofit without drifting across unrelated Laravel, Vue, or deployment surfaces.
user-invocable: true
---

# Staticprofit Safe Slice

Use this when you are implementing or editing inside this repo.

## Workflow

1. Restate the task in one sentence.
2. Identify the smallest seam that advances it.
3. Read only the files needed to confirm that seam.
4. If the seam touches HST auth or session flow, read the workpack before editing.
5. Make one coherent change set.
6. Run the narrowest meaningful verification.
7. Summarize outcome, residual risk, and next slice.

## Preferred checks

- PHP behavior change -> targeted `vendor/bin/phpunit`
- route, session, or auth change -> focused feature test or explicit smoke path
- frontend source change -> rebuild with `npm run dev` or `npm run prod` only if needed for verification
- workflow or local-agent change -> validate paths, JSON, and ignore behavior

## Extra repo guardrails

- edit source under `resources/`, not compiled artifacts in `public/`
- do not opportunistically rewrite old Laravel code while fixing one seam
- avoid changing rollout posture for SSO unless the task explicitly requires it
'@

$repoVerifyHandoff = @'
---
name: sp-verify-handoff
description: Close a staticprofit task properly: verify the changed seam, state what remains unverified, and call out deployment or rollout implications.
user-invocable: true
---

# Staticprofit Verify Handoff

Use this after meaningful work or before ending a session.

## Verify first

1. Re-read the requested outcome.
2. Verify the changed seam directly.
3. State what was not verified.

## Call out operational fallout when relevant

Mention these explicitly when they apply:

- migrations or seeds
- config or `.env` expectations
- asset rebuild requirements
- auth/session rollout risks
- downstream consumers of cookies, tokens, or session keys

## Guardrails

- do not claim verification you did not run
- do not bury rollout risk under a long changelog
- if the task only changed the private agent layer, verify that tracked shared files stayed untouched
'@

$repoSsoSkill = @'
---
name: sp-hst-sso-workpack
description: Use the canonical HST SSO workpack before changing staticprofit auth, login, logout, session, impersonation, or permission-flow behavior.
user-invocable: true
---

# Staticprofit HST SSO Workpack

This skill is mandatory for HST auth-flow work.

## Read order

1. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/README.md`
2. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/MASTER_PLAN.md`
3. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/IMPLEMENTATION_TRACKER.md`
4. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/CODEBASE_AUDIT.md`
5. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/HST_HOOKS_AND_CHANGE_SURFACE.md`

## Extract before editing

- route entrypoints for login, logout, callback, and permission checks
- controllers, middleware, guards, helpers, and Blade templates involved
- session keys, cookies, and tokens that must be preserved or audited
- rollout flags and coexistence rules for password login vs SSO
- test, telemetry, and migration surface

## Guardrails

- preserve `session_id` and `sp_user_access_tokens` behavior until downstream consumers are identified and the workpack says it is safe to change them
- keep password login available during early rollout unless the task explicitly changes rollout policy
- gate new SSO entry points and UI affordances with config flags until session behavior is proven stable
- do not move the planning flow back into ad hoc `temp/` notes
'@

$repoCodexReadme = @'
# Staticprofit Local Codex Layer

This directory is local-only. It provides a lightweight Codex entrypoint for this checkout without introducing a shared repo planning system.

## Primary contract

- `AGENTS.md` is the repo contract.
- `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/` is the canonical planning pack for HST auth / SSO work.

## Read order

1. `.codex/memories/00_ACTIVE.md`
2. `AGENTS.md`
3. `readme.md` if repo-wide orientation is still unclear
4. the HST SSO workpack when auth, login, logout, session, SSO, or permission-flow work is in scope

## Intent

- keep local agent bootstrap and memory private to this checkout
- avoid creating a competing shared planning system unless the team explicitly wants one
- keep implementation slices small and branch-scoped
'@

$repoCodexActiveContent = @'
# Staticprofit Local Active State

This is a private local Codex entrypoint for the `staticprofit` checkout.

## Current repo truth

- There is no shared `.codex/` control plane in this repo.
- `AGENTS.md` is the authoritative repo contract.
- The active documented workstream is HST centralized login / Keycloak / SSO on `stats_tools`.

## Read next

1. `AGENTS.md`
2. `storage/docs/WORK/03_FEATURES/STATS_TOOL/HST_SSO/README.md` if the task touches auth, login, logout, session, SSO, impersonation, or permissions
3. the rest of the HST SSO workpack in the order described by `AGENTS.md`

## Local workflow

- keep changes small and reviewable
- branch before meaningful implementation work
- edit source files, not compiled assets
- keep `.claude/`, `.codex/`, and `CLAUDE.md` local-only in this checkout
'@

Ensure-Directory $globalSkillsRoot
Ensure-Directory (Join-Path $globalSkillsRoot "safe-shell")
Ensure-Directory (Join-Path $globalSkillsRoot "small-safe-slice")
Ensure-Directory (Join-Path $globalSkillsRoot "verification-closeout")

Write-FileIfNeeded -Path (Join-Path $globalSkillsRoot "safe-shell\SKILL.md") -Content $safeShell -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $globalSkillsRoot "small-safe-slice\SKILL.md") -Content $smallSafeSlice -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $globalSkillsRoot "verification-closeout\SKILL.md") -Content $verificationCloseout -ForceWrite:$Force

Ensure-Directory $repoClaudeSkillsRoot
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "sp-repo-onramp")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "sp-safe-slice")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "sp-verify-handoff")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "sp-hst-sso-workpack")
Ensure-Directory (Join-Path $repoCodexRoot "memories")

Write-FileIfNeeded -Path $repoClaudeMd -Content $repoClaude -ForceWrite:$Force
Write-FileIfNeeded -Path $repoClaudeSettingsLocal -Content $repoSettingsLocal -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "sp-repo-onramp\SKILL.md") -Content $repoOnramp -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "sp-safe-slice\SKILL.md") -Content $repoSafeSlice -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "sp-verify-handoff\SKILL.md") -Content $repoVerifyHandoff -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "sp-hst-sso-workpack\SKILL.md") -Content $repoSsoSkill -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoCodexRoot "README.md") -Content $repoCodexReadme -ForceWrite:$Force
Write-FileIfNeeded -Path $repoCodexActivePath -Content $repoCodexActiveContent -ForceWrite:$Force

Add-ExcludeLine -ExcludeFile $excludeFile -Line "# Local-only Claude/Codex workflow for $RepoPath"
Add-ExcludeLine -ExcludeFile $excludeFile -Line "$excludePrefix/CLAUDE.md"
Add-ExcludeLine -ExcludeFile $excludeFile -Line "$excludePrefix/.claude/"
Add-ExcludeLine -ExcludeFile $excludeFile -Line "$excludePrefix/.codex/"

Write-Host "Bootstrapped agent workflow for: $RepoPath"
Write-Host "Repo root: $repoRoot"
Write-Host "Local files are excluded through: $excludeFile"
Write-Host "Start Claude or Codex from the repo path above for the cleanest project context."
