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
$excludeFile = Join-Path $repoRoot ".git\info\exclude"

# ---------------------------------------------------------------------------
# Global skills (shared across repos -- idempotent)
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Repo-specific skills
# ---------------------------------------------------------------------------

$repoOnramp = @'
---
name: ns-repo-onramp
description: Orient to the NavSentinel repo before editing. Use at session start, when scope is vague, or when entering an unfamiliar extension layer.
user-invocable: true
---

# NavSentinel Repo Onramp

Establish current truth before touching code or docs.

## Read first

1. `CLAUDE.md`
2. `AGENTS.md`
3. `CONTRIBUTING.md` for change-surface guidance
4. `docs/Execution_Tracker.md` for the active batch plan and what is in progress

Read when relevant:

- `docs/Architecture_and_Data_Flow.md` when touching runtime layers, bridge, or service worker
- `docs/Intent_Model_and_Scoring.md` when touching CDS or credential-risk heuristics
- `docs/Testing_and_Gym.md` when adding tests or Gym fixtures
- `docs/Real_World_Adversarial_Program.md` when adding adversarial scenarios

## Produce a working summary

Extract only what the task needs:

- likely change surface (content scripts, shared logic, popup/options UI, service worker, Gym, tests)
- current constraints from `AGENTS.md`
- whether the Execution Tracker batch plan is relevant
- whether the change requires a build/reload cycle

## Guardrails

- trust `AGENTS.md` and `docs/Execution_Tracker.md` as the active planning docs
- do not create parallel planning files or control-plane trees
- keep the first implementation slice small and measurable
'@

$repoSafeSlice = @'
---
name: ns-safe-slice
description: Implement one small, reviewable slice in NavSentinel without drifting across unrelated extension layers.
user-invocable: true
---

# NavSentinel Safe Slice

Use this when you are implementing or editing inside this repo.

## Workflow

1. Restate the task in one sentence.
2. Identify the smallest seam that advances it.
3. Read only the files needed to confirm that seam.
4. If the seam crosses content-script / service-worker / UI boundaries, check the architecture doc first.
5. Make one coherent change set.
6. Run the narrowest meaningful verification.
7. Summarize outcome, residual risk, and next slice.

## Preferred checks

- scoring or heuristic change -> `npm run test` (Vitest)
- content script or UI change -> `npm run build` then manual load or E2E
- type contract change -> `npm run typecheck`
- Gym fixture -> `npm run test:e2e` or targeted Playwright spec
- docs or workflow change -> validate paths and accuracy

## Extra repo guardrails

- edit source under `extension/src/`, not compiled output in `extension/dist/`
- do not mix navigation-guard logic changes with credential-guard logic changes in the same slice
- keep content-script, shared, popup, options, and service-worker modules focused and small
- if you touch scoring thresholds, verify in the Gym, not just in unit tests
'@

$repoVerifyHandoff = @'
---
name: ns-verify-handoff
description: Close a NavSentinel task properly: verify the changed seam, state what remains unverified, and call out build or reload implications.
user-invocable: true
---

# NavSentinel Verify Handoff

Use this after meaningful work or before ending a session.

## Verify first

1. Re-read the requested outcome.
2. Verify the changed seam directly.
3. State what was not verified.

## Call out operational fallout when relevant

Mention these explicitly when they apply:

- manifest or permission changes
- new content-script injection points or world changes
- storage schema or migration concerns
- service-worker lifecycle or alarm changes
- Gym fixture additions that need linking from `gym/index.html`
- docs that should be updated to reflect the change

## Guardrails

- do not claim verification you did not run
- do not bury reload or build requirements under a long changelog
- if the task only changed local workflow files, verify that tracked shared files stayed untouched
'@

$repoExtDev = @'
---
name: ns-ext-dev
description: Extension development workflow for NavSentinel. Use when adding features, fixing bugs, or changing runtime behavior in the Chrome MV3 extension.
user-invocable: true
---

# NavSentinel Extension Development

Use this when the task involves changing extension runtime behavior.

## Change surface map

From `CONTRIBUTING.md`:

- navigation scoring and click decisions: `extension/src/content/capture_isolated.ts`, `extension/src/shared/scoring.ts`
- main-world popup/redirect/form enforcement: `extension/src/content/main_guard.ts`
- credential risk and prompts: `extension/src/content/credential_guard.ts`, `extension/src/content/credential_modal.ts`, `extension/src/shared/domain.ts`
- storage and persistence: `extension/src/shared/storage.ts`, `extension/src/shared/allowlist.ts`
- popup and options UI: `extension/src/popup/*`, `extension/src/options/*`
- rollback and DNR sync: `extension/src/sw/sw.ts`

## Build and verify cycle

1. `npm run build` to bundle to `extension/dist/`
2. Reload the extension in `chrome://extensions`
3. `npm run test` for unit tests
4. `npm run typecheck` for type safety
5. `npm run test:e2e` for Playwright E2E (requires extension loaded)

Use `npm run watch` during development for automatic rebuilds.

## Gym testing

- Start the Gym: `npm run gym:serve`
- Levels 1-9: navigation scenarios
- Level 10: delayed redirects and form submits
- Level 11: risky password-submit prompt coverage
- Level 12: slow same-tab navigation legitimacy

## Guardrails

- keep logic local; no remote calls or telemetry
- content scripts must not exfiltrate data
- main-world patching must be minimal and defensible
- test heuristic changes in the Gym, not just unit tests
- respect MV3 service-worker lifecycle constraints
'@

# ---------------------------------------------------------------------------
# CLAUDE.md
# ---------------------------------------------------------------------------

$repoClaude = @'
# NavSentinel Personal Claude Workflow

This file is local-only. It gives Claude a stable repo-specific entrypoint without modifying the shared repository workflow.

## Working model

- Treat `AGENTS.md` as the primary repo contract.
- Treat this repo as a Chrome MV3 browser extension built with TypeScript and Vite.
- Treat `docs/Execution_Tracker.md` as the active batch plan for post-merge follow-up work.
- Keep diffs small and reviewable.
- For meaningful implementation work, create a branch scoped to the change before editing.

## Read order

1. `AGENTS.md`
2. `CONTRIBUTING.md` for change-surface guidance and style expectations
3. `docs/Execution_Tracker.md` for the active work plan
4. `docs/README.md` when deeper orientation into docs is needed

Read when relevant:

- `docs/Architecture_and_Data_Flow.md` for runtime layers and bridge design
- `docs/Intent_Model_and_Scoring.md` for CDS and credential-risk heuristics
- `docs/Testing_and_Gym.md` for test surfaces and Gym coverage
- `docs/Real_World_Adversarial_Program.md` for adversarial scenario backlog
- `docs/Demo_Showcase_Plan.md` for demo lane work

## Preferred skills

General skills from `~/.claude/skills`:

- `safe-shell`
- `small-safe-slice`
- `verification-closeout`

Repo-specific local skills in this checkout:

- `ns-repo-onramp`
- `ns-safe-slice`
- `ns-verify-handoff`
- `ns-ext-dev`

## Repo truths

- The active work plan is tracked in `docs/Execution_Tracker.md`, not in a separate control plane.
- The extension is local-first: no remote telemetry, no reputation lookups, no password-value storage.
- Source lives under `extension/src/`; build output goes to `extension/dist/`. Edit source, not output.
- Gym fixtures under `gym/` are the primary verification surface for heuristic changes.
- MV3 service worker is ephemeral; persist settings in `chrome.storage.local`.
- Content scripts run in isolated world by default; main-world patching is through `main_guard.ts`.

## Guardrails

- Do not rely on tracked `.gitignore` changes to privatize local workflow files.
- Keep `CLAUDE.md`, `.claude/`, and `.codex/` local-only in this repo.
- Never commit secrets, tokens, machine-specific `.env` values, or sensitive dumps.
- Do not mix navigation-guard and credential-guard logic changes in the same slice.
- Prefer concrete verification over broad explanation.
'@

# ---------------------------------------------------------------------------
# settings.local.json
# ---------------------------------------------------------------------------

$repoSettingsLocal = @'
{
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": [
      "Bash(rg:*)",
      "Bash(git status:*)",
      "Bash(git diff:*)",
      "Bash(npm install:*)",
      "Bash(npm ci:*)",
      "Bash(npm run:*)",
      "Bash(npx vitest:*)",
      "Bash(npx playwright:*)",
      "Bash(npx tsc:*)"
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
            "command": "echo 'NavSentinel. Read CLAUDE.md, AGENTS.md, and CONTRIBUTING.md before editing. Check docs/Execution_Tracker.md for active work plan.'",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
'@

# ---------------------------------------------------------------------------
# Write global skills (idempotent)
# ---------------------------------------------------------------------------

Ensure-Directory $globalSkillsRoot
Ensure-Directory (Join-Path $globalSkillsRoot "safe-shell")
Ensure-Directory (Join-Path $globalSkillsRoot "small-safe-slice")
Ensure-Directory (Join-Path $globalSkillsRoot "verification-closeout")

Write-FileIfNeeded -Path (Join-Path $globalSkillsRoot "safe-shell\SKILL.md") -Content $safeShell -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $globalSkillsRoot "small-safe-slice\SKILL.md") -Content $smallSafeSlice -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $globalSkillsRoot "verification-closeout\SKILL.md") -Content $verificationCloseout -ForceWrite:$Force

# ---------------------------------------------------------------------------
# Write repo-specific skills
# ---------------------------------------------------------------------------

Ensure-Directory $repoClaudeSkillsRoot
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "ns-repo-onramp")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "ns-safe-slice")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "ns-verify-handoff")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "ns-ext-dev")

Write-FileIfNeeded -Path $repoClaudeMd -Content $repoClaude -ForceWrite:$Force
Write-FileIfNeeded -Path $repoClaudeSettingsLocal -Content $repoSettingsLocal -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "ns-repo-onramp\SKILL.md") -Content $repoOnramp -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "ns-safe-slice\SKILL.md") -Content $repoSafeSlice -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "ns-verify-handoff\SKILL.md") -Content $repoVerifyHandoff -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "ns-ext-dev\SKILL.md") -Content $repoExtDev -ForceWrite:$Force

# ---------------------------------------------------------------------------
# Git exclude rules (keep local-only files out of tracking)
# ---------------------------------------------------------------------------

Add-ExcludeLine -ExcludeFile $excludeFile -Line "# Local-only Claude/Codex workflow for NavSentinel"
Add-ExcludeLine -ExcludeFile $excludeFile -Line "$excludePrefix/CLAUDE.md"
Add-ExcludeLine -ExcludeFile $excludeFile -Line "$excludePrefix/.claude/"
Add-ExcludeLine -ExcludeFile $excludeFile -Line "$excludePrefix/.codex/"

Write-Host "Bootstrapped Claude Code workflow for: $RepoPath"
Write-Host "Repo root: $repoRoot"
Write-Host "Local files are excluded through: $excludeFile"
Write-Host "Start Claude from the repo path above for the cleanest project context."
