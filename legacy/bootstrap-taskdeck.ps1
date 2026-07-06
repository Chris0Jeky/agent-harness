param(
  [string]$RepoPath = $PWD.Path,
  [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# NOTE: In Taskdeck, CLAUDE.md, AGENTS.md, .claude/settings.json, .claude/skills/,
# and .codex/ are all tracked (committed). This script recreates them from scratch,
# which is useful after a fresh clone, on a new machine, or to reset to known-good
# state. It does NOT create git exclude rules because these files are committed.
#
# AGENTS.md is NOT managed by this script -- it evolves through normal development.
# ---------------------------------------------------------------------------

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

$globalSkillsRoot = Join-Path $env:USERPROFILE ".claude\skills"
$repoClaudeSkillsRoot = Join-Path $RepoPath ".claude\skills"
$repoClaudeSettings = Join-Path $RepoPath ".claude\settings.json"
$repoClaudeMd = Join-Path $RepoPath "CLAUDE.md"
$repoCodexRoot = Join-Path $RepoPath ".codex"

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
# Repo-specific skills (.claude/skills/ -- tracked)
# ---------------------------------------------------------------------------

$repoOnramp = @'
---
name: taskdeck-repo-onramp
description: Orient to the Taskdeck repo before editing. Use when starting a session, entering an unfamiliar area, reconciling a broad request against current reality, or turning a vague task into a scoped plan.
---

# Taskdeck Repo Onramp

Establish current Taskdeck truth before editing code or docs.

## Read first

1. `CLAUDE.md`
2. `AGENTS.md`
3. `docs/STATUS.md`
4. `docs/IMPLEMENTATION_MASTERPLAN.md`
5. `docs/GOLDEN_PRINCIPLES.md`
6. `docs/ISSUE_EXECUTION_GUIDE.md`
7. `docs/TESTING_GUIDE.md`

Read when relevant:

- `docs/START_HERE.md` for product-facing or UX work
- `docs/GITHUB_PROJECT_AUTOMATION.md` for issue, PR, or project-ops work
- feature-specific docs for the touched slice

## Produce a working summary

Extract only what the current task needs:

- current thesis and near-horizon priorities
- shipped path versus planned breadth
- constraints that must not be broken
- likely files, layers, tests, and docs affected

Fixed truths unless the task explicitly changes them:

- capture should stay low-friction
- automation stays review-first
- no silent or destructive apply by default
- novice-first product legibility beats breadth
- active docs beat archive docs on conflict

## Plan before edits

Write a short plan covering:

- files likely touched
- approach
- risks
- tests to run
- docs that may need sync

## Multi-agent split

If work spans concerns, split by ownership:

- backend implementation agent
- frontend implementation agent
- docs or verification agent

Keep one coordinator responsible for synthesis and final verification.

## Do not use this skill when

- the task is already tightly scoped in a familiar area
- you only need final verification or doc sync
'@

$repoBackendSlice = @'
---
name: taskdeck-backend-slice
description: Implement Taskdeck backend changes safely. Use when changing .NET API, application, domain, infrastructure, worker, auth, provider-runtime, import-export, notification, archive, or persistence behavior.
---

# Taskdeck Backend Slice

Implement the smallest backend slice that fits the existing layering and contract rules.

## Read first

1. `CLAUDE.md`
2. `AGENTS.md`
3. `docs/STATUS.md`
4. `docs/GOLDEN_PRINCIPLES.md`
5. `docs/TESTING_GUIDE.md`

Read as needed:

- `docs/ISSUE_EXECUTION_GUIDE.md` for backlog-driven work
- feature docs for the touched slice

## Placement rules

Respect the existing layering:

- `Taskdeck.Domain`: core rules and entities only
- `Taskdeck.Application`: use cases, orchestration, service contracts
- `Taskdeck.Infrastructure`: persistence and adapters
- `Taskdeck.Api`: HTTP wiring and transport concerns

Do not move logic outward just to make a controller easier to write.

## Backend guardrails

- keep claims-first identity and authz intact
- preserve `ApiErrorResponse` behavior and stable `401/403/404/409` semantics
- do not trust caller-supplied actor identity
- handle failure branches explicitly
- keep local and test posture deterministic; use mock providers unless live behavior is the explicit task

## Workflow

1. Find the existing pattern before inventing a new one.
2. Put the change in the narrowest correct layer.
3. Add or update the nearest tests.
4. Run targeted tests first, then broaden only as blast radius requires.

## Test routing

- domain rules -> `Taskdeck.Domain.Tests`
- application and service logic -> `Taskdeck.Application.Tests`
- HTTP contracts, authz, and error mapping -> `Taskdeck.Api.Tests`
- CLI behavior -> `Taskdeck.Cli.Tests`
- architecture constraints -> `Taskdeck.Architecture.Tests`

## Multi-agent split

If the task is broad, split by non-overlapping ownership:

- implementation in one layer or feature family
- API contract or regression tests
- docs or handoff verification

## Do not use this skill when

- the task is frontend-only, docs-only, or purely demo-evidence work
- the task is really about capture/review semantics and needs the capture-review-loop skill as primary guide
'@

$repoFrontendSlice = @'
---
name: taskdeck-frontend-workspace-slice
description: Implement Taskdeck frontend shell and workspace changes. Use when changing Vue routes, stores, components, Home, Today, Boards, workspace-mode flows, keyboard behavior, help states, or novice-first product legibility outside the core capture-review semantics.
---

# Taskdeck Frontend Workspace Slice

Strengthen the shipped Taskdeck workspace without drifting into disconnected surface breadth.

## Read first

1. `docs/STATUS.md`
2. `docs/START_HERE.md`
3. `docs/TESTING_GUIDE.md`

Read as needed:

- relevant docs under `docs/product` and `docs/manual`
- `frontend/taskdeck-web/package.json`

## Product framing

Prefer changes that reinforce the shipped path:

- `Home -> Inbox or capture -> Review -> Board`
- `Today` as the daily reset and routing surface
- advanced surfaces remain secondary unless the task explicitly targets them

## Frontend guardrails

- preserve board-centered continuity across routes
- preserve review-first trust in copy and action design
- favor readable and actionable empty states
- keep keyboard and escape behavior sane
- do not claim product breadth that is not actually shipped

## Workflow

1. Identify the primary surface and the supporting routes, stores, and components.
2. Reuse existing patterns before adding new state or abstractions.
3. Add or update unit tests for the changed behavior.
4. Use Playwright when route flow, keyboard behavior, or multi-step UX changes.

## Pairing rule

If the task changes capture, proposal review, provenance, or explicit board handoff semantics, use `taskdeck-capture-review-loop` alongside this skill.

## Multi-agent split

Good parallel splits:

- route or component implementation
- store or API adjustments
- Playwright or docs follow-through

## Do not use this skill when

- the task is backend-only
- the main risk is in capture, proposal, execute, or provenance semantics rather than workspace UX
'@

$repoCaptureReview = @'
---
name: taskdeck-capture-review-loop
description: Protect Taskdeck's core capture-review-apply-board loop. Use when touching Inbox, capture, triage, automation proposals, proposal summaries, approve-reject-execute behavior, provenance, or board handoff semantics across backend or frontend.
---

# Taskdeck Capture Review Loop

Protect the central Taskdeck loop:

`capture -> review -> explicit apply -> continue on a board`

## Read first

1. `docs/STATUS.md`
2. `docs/START_HERE.md`
3. `docs/TESTING_GUIDE.md`

Read as needed:

- feature docs for capture, review, or first-run flows
- the relevant backend or frontend files for the touched slice

## Non-negotiable guardrails

- no silent board mutation from triage or model output
- review remains the trust gate
- provenance stays visible and navigable
- capture stays low-friction
- product language should make the loop easier to understand, not more system-shaped

## Evaluate before changing code

Answer these questions:

- does this reduce or increase capture friction?
- does this keep proposal review explicit?
- does this preserve provenance from capture to proposal to board or card?
- does this make the outcome easier for a user to understand?

## Pairing rule

Use this skill as the semantic guide, then pair it with:

- `taskdeck-backend-slice` when the change lands in API, services, queueing, or execution logic
- `taskdeck-frontend-workspace-slice` when the change lands in UI, routing, or product language

## Verification bias

Prefer a mix of:

- targeted backend or frontend tests for the touched slice
- Playwright coverage when route or interaction behavior changes
- manual sanity check of the golden path when the change is user-facing

## Do not use this skill when

- the work is generic shell or navigation polish with no impact on capture, review, execute, provenance, or board handoff semantics
- the work is only demo harness evidence
'@

$repoDemoRegression = @'
---
name: taskdeck-demo-regression
description: Validate Taskdeck with the smallest evidence path that proves the change. Use when a task needs seeded demo state, Playwright proof, screenshots, or stakeholder walkthrough evidence.
---

# Taskdeck Demo Regression

Use Taskdeck's demo and regression tooling as evidence, not as a substitute for product truth.

## Read first

1. `docs/TESTING_GUIDE.md`
2. `docs/START_HERE.md`
3. `docs/product/DEMO_PLAYBOOK.md`
4. `docs/product/SCENARIOS.md`

## Evidence ladder

Choose the smallest path that proves the change:

1. targeted unit or integration tests
2. targeted Playwright coverage
3. `npm run demo:director:smoke`
4. full seeded or manual demo flow only when stakeholder-proof is actually needed

## Default bias

- prefer deterministic checks first
- prefer the smoke path over a full manual walkthrough
- use screenshots only when they add signal

## Capture for handoff

Record:

- commands run
- pass or fail result
- whether the run used targeted tests, Playwright, smoke path, or full demo flow
- screenshots or artifacts only when they materially help

## Do not use this skill when

- a small code-path change is already fully proven by nearby automated tests
- the task is final doc sync rather than evidence gathering
'@

$repoVerifyDocSync = @'
---
name: taskdeck-verification-doc-sync
description: Finish a Taskdeck change with the right checks and doc updates. Use at the end of implementation to choose verification scope, decide whether canonical docs changed, and prepare the required handoff summary.
---

# Taskdeck Verification And Doc Sync

Finish the work completely: verify what changed, update the right docs, and report the result cleanly.

## Read first

1. `AGENTS.md`
2. `docs/TESTING_GUIDE.md`
3. `docs/STATUS.md`
4. `docs/IMPLEMENTATION_MASTERPLAN.md`

Read when relevant:

- `docs/MANUAL_TEST_CHECKLIST.md`
- product or manual docs touched by the change

## Verification workflow

1. Run targeted checks for the touched area.
2. Broaden only if the blast radius justifies it.
3. Decide whether shipped reality or roadmap sequencing actually changed.
4. Update the right docs.
5. Prepare the required Taskdeck handoff summary.

## Canonical doc rule

Update `docs/STATUS.md` and `docs/IMPLEMENTATION_MASTERPLAN.md` only when one of these is true:

- shipped product or engineering reality changed
- the active roadmap or next-step sequencing changed

Do not touch them for narrow local-tooling changes, draft-doc improvements, or evidence-only work.

## Required handoff shape

Provide:

- summary of changes
- files touched
- tests added or updated
- commands run and results
- docs updated
- notable risks or follow-ups

## Do not claim

- a path is verified if you only reasoned about it
- a feature is shipped if only demo tooling changed
- canonical docs are current if implementation changed and the source-of-truth docs were left stale
'@

$repoIssueToPr = @'
---
name: issue-to-pr
description: End-to-end issue implementation. Takes a GitHub issue number, creates a branch, implements the change, runs tests, opens a PR linking the issue, and reports back for review.
user-invocable: true
---

# Issue to PR

Autonomous workflow: GitHub issue -> branch -> implementation -> tests -> PR.

## Input

The user provides a GitHub issue number (e.g., `#350` or just `350`).

## Workflow

### 1. Understand the issue

```bash
gh issue view <number> --json title,body,labels,assignees,milestone
```

Read the issue thoroughly. Identify:
- what needs to change
- acceptance criteria
- labels (which layers are involved: backend, frontend, docs, testing)
- linked issues or dependencies

### 2. Orient to current state

Use the `taskdeck-repo-onramp` skill mentally:
- read `docs/STATUS.md` for current constraints
- identify affected files and layers

### 3. Create a branch

```bash
git checkout main
git pull origin main
git checkout -b issue-<number>/<short-slug>
```

Branch naming: `issue-<number>/<2-4 word slug>` (e.g., `issue-350/capture-validation`).

### 4. Implement

- follow the relevant skill for the layer being changed (backend-slice, frontend-workspace-slice, capture-review-loop)
- make incremental commits, one per logical change
- run tests after each significant change

### 5. Verify

Run the appropriate checks based on what changed:

- `.cs` files: `dotnet test backend/Taskdeck.sln -c Release -m:1`
- `.ts`/`.vue` files: `cd frontend/taskdeck-web && npx vitest --run --reporter=verbose && npm run typecheck`
- both: run both
- E2E-relevant: `npx playwright test` with targeted spec

### 6. Push and open PR

```bash
git push -u origin issue-<number>/<short-slug>
```

Open PR with:

```bash
gh pr create --title "<concise title>" --body "$(cat <<'EOF'
## Summary
<what changed and why>

Closes #<number>

## Changes
<bullet list of key changes>

## Test plan
<what was verified and how>
EOF
)"
```

### 7. Report back

Provide the PR URL and the handoff summary from `taskdeck-verification-doc-sync`.

## Guardrails

- do not merge the PR -- leave it for human review
- do not skip tests
- if the issue is ambiguous, ask the user before implementing
- if the issue is too large for one PR, propose a split and implement the first slice
'@

# ---------------------------------------------------------------------------
# CLAUDE.md (tracked)
# ---------------------------------------------------------------------------

$repoClaude = @'
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Is Taskdeck

A local-first execution workspace for developers. Core thesis: near-zero-friction capture with review-first (proposal-based) automation -- no silent or destructive mutations. Local persistence via SQLite.

## Required Reading Before Changes

1. `docs/STATUS.md` -- source of truth for current shipped state (always read first)
2. `docs/IMPLEMENTATION_MASTERPLAN.md` -- delivery history, planned work, roadmap sequencing, and strategic intentions
3. `docs/GOLDEN_PRINCIPLES.md` -- stable invariants and guardrails
4. `AGENTS.md` -- full contributor protocol, definition of done, output expectations

Precedence when instructions conflict: `docs/STATUS.md` > `AGENTS.md` > this file.

## Essential Commands

### Backend (.NET 8)

```bash
dotnet restore backend/Taskdeck.sln
dotnet build backend/Taskdeck.sln -c Release
dotnet run --project backend/src/Taskdeck.Api/Taskdeck.Api.csproj
dotnet test backend/Taskdeck.sln -c Release -m:1
```

Run a single backend test class:
```bash
dotnet test backend/Taskdeck.sln -c Release --filter "FullyQualifiedName~MyTestClassName"
```

### Frontend (Vue 3 + Vite, Node 24.x)

```bash
cd frontend/taskdeck-web
npm install
npm run dev          # dev server on :5173
npm run typecheck    # vue-tsc type checking
npm run build        # typecheck + vite build
npx vitest --run --reporter=verbose   # unit tests
npx vitest --run -t "test name"       # single test by name
npm run lint         # eslint
```

E2E (Playwright):
```bash
cd frontend/taskdeck-web
TASKDECK_E2E_DB=taskdeck.e2e.local.db npx playwright test --reporter=line
npx playwright test tests/e2e/some-spec.spec.ts   # single E2E file
```

### Docker (from repo root)

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile baseline up -d --build
```

### Default URLs

- API: `http://localhost:5000` | Swagger: `http://localhost:5000/swagger` | Frontend: `http://localhost:5173`

## Architecture

### Backend -- Clean Architecture layers in `backend/src/`

- **Taskdeck.Domain**: Core entities and business rules. No infrastructure dependencies -- keep it pure.
- **Taskdeck.Application**: Use cases and services. Depends only on Domain.
- **Taskdeck.Infrastructure**: Persistence (EF Core + SQLite), external adapters. Implements interfaces defined in Application/Domain.
- **Taskdeck.Api**: ASP.NET Core HTTP endpoints, integration layer, auth, SignalR hubs. Wires everything up via DI.
- **Taskdeck.Cli**: CLI entry point (separate from API).

Tests mirror this layout in `backend/tests/` with an additional `Taskdeck.Architecture.Tests` project for structural enforcement.

### Frontend -- `frontend/taskdeck-web/src/`

- **views/**: Route-level pages (BoardView, InboxView, ReviewView, TodayView, HomeView, etc.)
- **store/**: Pinia stores -- boardStore, captureStore, queueStore, sessionStore, workspaceStore, notificationStore, etc.
- **api/**: HTTP client modules for backend communication
- **composables/**: Shared Vue composition functions
- **components/**: Reusable UI components
- **router/**: Vue Router configuration

Uses Tailwind CSS, TypeScript, and Vue 3 composition API (`<script setup>`).

### Key Data Flow

1. User captures input → captureStore → backend inbox API
2. System generates a proposal (structured board change)
3. User reviews proposal in ReviewView
4. Explicit approval applies changes to board via boardStore

### Realtime

SignalR (`@microsoft/signalr`) provides realtime board collaboration.

### LLM Providers

Mock provider is default. OpenAI and Gemini supported behind config gates. See `docs/platform/LLM_PROVIDER_SETUP_GUIDE.md`.

## Work Protocol

- Before edits: write a short plan (files, approach, risks, tests).
- Keep diffs small and scoped; avoid large mixed refactors.
- After edits: run required checks and report results.
- For product-facing slices, ensure scope aligns with the thesis (reduce maintenance overhead/capture friction, preserve review-first trust).

## Definition of Done

- Behavior changes ship with tests (unit/integration/E2E as appropriate).
- Handle error cases explicitly; do not swallow failures.
- Update docs when reality changes: `docs/STATUS.md` for current state, `docs/IMPLEMENTATION_MASTERPLAN.md` for delivery history and planned work.
- HTTP semantics: use stable codes (401/403/404/409). Claims-first identity.

## Coding Conventions

- **Backend**: C# conventions, 4-space indent, PascalCase for public members, camelCase for locals. Respect layer boundaries (Domain must not reference Infrastructure).
- **Frontend**: TypeScript + Vue SFCs in PascalCase. Use `<script setup>` and composition API. Meaningful names over abbreviations.
- **Commits**: Present-tense, small, focused. One commit per file when spanning multiple files. File move/rename batches are fine as single commits.

## Testing Guidelines

- Mirror production namespaces in test namespaces and file names.
- Backend tests: project-per-layer in `backend/tests/` (Domain.Tests, Application.Tests, Api.Tests, Architecture.Tests).
- Frontend: vitest for unit tests, Playwright for E2E. See `docs/TESTING_GUIDE.md`.

## CI

Reusable GitHub Actions workflows under `.github/workflows/`. `ci-required.yml` is the gate for PRs. Nightly extended checks in `ci-nightly.yml`.

## Architecture Decision Records (ADRs)

ADRs live in `docs/decisions/`. See `docs/decisions/README.md` for the template and conventions.

**When to create an ADR**: Write one when a decision chooses between competing approaches, establishes a project-wide constraint, has hard-to-reverse consequences, or would surprise a future contributor. This includes technology selections, data model choices, security posture changes, automation safety boundaries, and strategic product pivots.

**How to create an ADR**: Use the next available number (`ADR-NNNN`), follow the template (Context, Decision, Alternatives, Consequences, References), and add the entry to `docs/decisions/INDEX.md`. Mark status as `Proposed` until ratified, then `Accepted`.

**Do not skip ADRs** for decisions that affect architecture, security posture, or cross-cutting conventions -- even when the change is small, the reasoning matters for future contributors who weren't in the conversation.

## Key Docs

- `docs/STATUS.md` -- current shipped reality (what is true now)
- `docs/IMPLEMENTATION_MASTERPLAN.md` -- delivery history, roadmap, and planned work (what was done and what comes next)
- `docs/GOLDEN_PRINCIPLES.md` -- stable invariants
- `docs/decisions/INDEX.md` -- architecture decision records
- `docs/TESTING_GUIDE.md` -- test operations reference
- `docs/ISSUE_EXECUTION_GUIDE.md` -- dependency-aware issue execution order
- `docs/MCP_TOOLING_GUIDE.md` -- MCP tool selection rules
- `AGENTS.md` -- full contributor protocol

## Worktree Isolation for Parallel Agents

When launching subagents with `isolation: "worktree"`, follow the protocol in `docs/WORKTREE_AGENT_PROTOCOL.md`. Key rules:
- NEVER include absolute paths to the main checkout in worktree agent prompts
- First agent action: run the inline worktree guard from the protocol
- All file paths must use the exported `$WT_PROJECT_DIR` variable
- Shell state does not persist between Bash tool calls -- agents must use absolute paths
- After agents complete, verify main checkout is still clean on the default branch

## Windows Notes

- Run `bash scripts/check-git-env.sh` to validate git resolution and index.lock state before a work session.
- If `git` resolves to Cygwin or fails with signal errors, use `C:\Program Files\Git\cmd\git.exe` explicitly (or add `C:\Program Files\Git\cmd` to the front of `PATH`).
- Do not chain commands with `&&` in PowerShell; use `;` and check `$LASTEXITCODE`.
- If `.git/index.lock` blocks commits, check for active git processes before removing it. The `check-git-env.sh` script automates this check.
'@

# ---------------------------------------------------------------------------
# settings.json (tracked -- note: settings.json not settings.local.json)
# ---------------------------------------------------------------------------

$repoSettings = @'
{
  "includeCoAuthoredBy": false,
  "enableAllProjectMcpServers": true,
  "worktree": {
    "symlinkDirectories": ["node_modules", "frontend/taskdeck-web/node_modules"]
  },
  "permissions": {
    "defaultMode": "bypassPermissions",
    "allow": [
      "Bash(dotnet --version)",
      "Bash(dotnet --version:*)",
      "Bash(dotnet clean:*)",
      "Bash(dotnet restore:*)",
      "Bash(dotnet build:*)",
      "Bash(dotnet test:*)",
      "Bash(dotnet run:*)",
      "Bash(dotnet tool install:*)",
      "Bash(dotnet tool uninstall:*)",
      "Bash(dotnet nuget:*)",
      "Bash(dotnet ef migrations:*)",
      "Bash(dotnet ef database:*)",
      "Bash(dotnet format:*)",
      "Bash(node --version:*)",
      "Bash(npm --version:*)",
      "Bash(npm install:*)",
      "Bash(npm ci:*)",
      "Bash(npm run:*)",
      "Bash(npm test:*)",
      "Bash(npx vitest:*)",
      "Bash(npx playwright:*)",
      "Bash(npx vue-tsc:*)",
      "Bash(npx eslint:*)",
      "Bash(git status:*)",
      "Bash(git log:*)",
      "Bash(git diff:*)",
      "Bash(git branch:*)",
      "Bash(git show:*)",
      "Bash(git stash:*)",
      "Bash(git checkout:*)",
      "Bash(git switch:*)",
      "Bash(git add:*)",
      "Bash(git commit:*)",
      "Bash(git merge:*)",
      "Bash(git fetch:*)",
      "Bash(git remote:*)",
      "Bash(git push:*)",
      "Bash(gh :*)",
      "Bash(ls:*)",
      "Bash(pwd:*)",
      "Bash(docker compose:*)",
      "Bash(docker build:*)",
      "Bash(docker ps:*)",
      "Bash(docker :*)",
      "Bash(taskkill:*)"
    ],
    "deny": [
      "Bash(git push --force:*)",
      "Bash(git push --force-with-lease:*)",
      "Bash(rm -rf /:*)",
      "Bash(git reset --hard:*)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'INPUT=$(cat); CMD=$(echo \"$INPUT\" | jq -r \".tool_input.command // empty\"); if echo \"$CMD\" | grep -qiE \"(git\\s+push\\s+--force|rm\\s+-rf\\s+/|DROP\\s+TABLE|DROP\\s+DATABASE)\"; then echo \"BLOCKED: Destructive command detected: $CMD\" >&2; exit 2; fi; exit 0'",
            "timeout": 5
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "if": "Bash(git commit *)",
            "command": "bash -c 'INPUT=$(cat); CMD=$(echo \"$INPUT\" | jq -r \".tool_input.command // empty\"); STAGED=$(git diff --cached --name-only 2>/dev/null); HAS_CS=false; HAS_VUE=false; if echo \"$STAGED\" | grep -qE \"\\.cs$\"; then HAS_CS=true; fi; if echo \"$STAGED\" | grep -qE \"\\.(vue|ts)$\"; then HAS_VUE=true; fi; ERRORS=\"\"; if [ \"$HAS_CS\" = true ]; then RESULT=$(dotnet build backend/Taskdeck.sln -c Release --nologo -v q 2>&1); if [ $? -ne 0 ]; then ERRORS=\"Backend build failed:\\n$RESULT\"; fi; fi; if [ \"$HAS_VUE\" = true ]; then RESULT=$(cd frontend/taskdeck-web && npx vue-tsc --noEmit 2>&1); if [ $? -ne 0 ]; then ERRORS=\"$ERRORS\\nFrontend typecheck failed:\\n$RESULT\"; fi; fi; if [ -n \"$ERRORS\" ]; then echo \"PRE-COMMIT CHECK FAILED:\" >&2; echo -e \"$ERRORS\" >&2; exit 2; fi; exit 0'",
            "timeout": 120,
            "statusMessage": "Running pre-commit checks..."
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'INPUT=$(cat); FILE=$(echo \"$INPUT\" | jq -r \".tool_input.file_path // empty\"); if echo \"$FILE\" | grep -qE \"\\.(vue|ts)$\"; then if echo \"$FILE\" | grep -q \"frontend/taskdeck-web\"; then echo \"{\\\"hookSpecificOutput\\\": {\\\"hookEventName\\\": \\\"PostToolUse\\\", \\\"additionalContext\\\": \\\"Vue/TS file edited: $FILE -- consider running typecheck if making multiple related edits.\\\"}}\"; fi; fi; exit 0'",
            "timeout": 5
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'Taskdeck repo. Read CLAUDE.md for context. Read docs/STATUS.md for current state before making changes.'",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
'@

# ---------------------------------------------------------------------------
# .codex/config.toml (tracked -- Codex MCP configuration)
# Machine-specific paths are computed dynamically from $RepoPath and $env:USERPROFILE.
# ---------------------------------------------------------------------------

$runtimeCodex = "$RepoPath\.runtime-codex"
$repoPathEscaped = $RepoPath.Replace('\', '\\')
$runtimeEscaped = $runtimeCodex.Replace('\', '\\')
$userProfileEscaped = $env:USERPROFILE.Replace('\', '\\')

$repoCodexConfig = @"
# Project-scoped Codex MCP configuration for Taskdeck.
# This file is loaded when the repository is a trusted project.

approval_policy = "on-request"
sandbox_mode = "workspace-write"

[features]
multi_agent = true

[shell_environment_policy]
inherit = "all"

[windows]
sandbox = "elevated"

[shell_environment_policy.set]
PATH = "${runtimeEscaped}\\bin;C:\\Users\\Public\\codex-shell-home\\bin;C:\\Program Files\\Docker\\Docker\\resources\\bin;${userProfileEscaped}\\AppData\\Local\\Microsoft\\WindowsApps;C:\\Program Files\\Git\\cmd;C:\\Program Files\\dotnet;C:\\Program Files\\nodejs;C:\\Program Files\\GitHub CLI;C:\\Windows\\system32;C:\\Windows;C:\\Windows\\System32\\Wbem;C:\\Windows\\System32\\WindowsPowerShell\\v1.0;C:\\Windows\\System32\\OpenSSH"
HOME = '${runtimeCodex}\home'
DOTNET_CLI_HOME = '${runtimeCodex}\dotnet-home'
NUGET_PACKAGES = '${runtimeCodex}\nuget\packages'
GIT_CONFIG_GLOBAL = '${runtimeCodex}\home\.gitconfig'

[mcp_servers.openaiDeveloperDocs]
url = "https://developers.openai.com/mcp"
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.ripgrep]
command = "npx"
args = ["-y", "mcp-ripgrep@latest"]
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.playwright]
command = "npx"
args = ["-y", "@executeautomation/playwright-mcp-server"]
startup_timeout_sec = 30
tool_timeout_sec = 180

[mcp_servers.chromeDevTools]
command = "npx"
args = ["-y", "chrome-devtools-mcp@latest"]
startup_timeout_sec = 30
tool_timeout_sec = 180

[mcp_servers.docker]
command = "docker"
args = ["mcp", "gateway", "run", "--servers", "docker,docker-docs,openapi,time,jetbrains,filesystem,SQLite,terraform", "--transport", "stdio"]
startup_timeout_sec = 60
tool_timeout_sec = 240

[mcp_servers.github]
url = "https://api.githubcopilot.com/mcp/"
bearer_token_env_var = "GITHUB_PAT"
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.github.tools.add_issue_comment]
approval_mode = "approve"
"@

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
# Write repo-specific Claude skills
# ---------------------------------------------------------------------------

Ensure-Directory $repoClaudeSkillsRoot
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "taskdeck-repo-onramp")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "taskdeck-backend-slice")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "taskdeck-frontend-workspace-slice")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "taskdeck-capture-review-loop")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "taskdeck-demo-regression")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "taskdeck-verification-doc-sync")
Ensure-Directory (Join-Path $repoClaudeSkillsRoot "issue-to-pr")

Write-FileIfNeeded -Path $repoClaudeMd -Content $repoClaude -ForceWrite:$Force
Write-FileIfNeeded -Path $repoClaudeSettings -Content $repoSettings -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "taskdeck-repo-onramp\SKILL.md") -Content $repoOnramp -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "taskdeck-backend-slice\SKILL.md") -Content $repoBackendSlice -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "taskdeck-frontend-workspace-slice\SKILL.md") -Content $repoFrontendSlice -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "taskdeck-capture-review-loop\SKILL.md") -Content $repoCaptureReview -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "taskdeck-demo-regression\SKILL.md") -Content $repoDemoRegression -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "taskdeck-verification-doc-sync\SKILL.md") -Content $repoVerifyDocSync -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoClaudeSkillsRoot "issue-to-pr\SKILL.md") -Content $repoIssueToPr -ForceWrite:$Force

# ---------------------------------------------------------------------------
# Write .codex config (tracked -- for Codex/OpenAI agent compatibility)
# ---------------------------------------------------------------------------

Ensure-Directory (Join-Path $repoCodexRoot "skills\taskdeck-repo-onramp")
Ensure-Directory (Join-Path $repoCodexRoot "skills\taskdeck-backend-slice")
Ensure-Directory (Join-Path $repoCodexRoot "skills\taskdeck-frontend-workspace-slice")
Ensure-Directory (Join-Path $repoCodexRoot "skills\taskdeck-capture-review-loop")
Ensure-Directory (Join-Path $repoCodexRoot "skills\taskdeck-demo-regression")
Ensure-Directory (Join-Path $repoCodexRoot "skills\taskdeck-verification-doc-sync")

Write-FileIfNeeded -Path (Join-Path $repoCodexRoot "config.toml") -Content $repoCodexConfig -ForceWrite:$Force

# Mirror skills to .codex/skills/ (same SKILL.md content, no openai.yaml -- those are agent-specific)
Write-FileIfNeeded -Path (Join-Path $repoCodexRoot "skills\taskdeck-repo-onramp\SKILL.md") -Content $repoOnramp -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoCodexRoot "skills\taskdeck-backend-slice\SKILL.md") -Content $repoBackendSlice -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoCodexRoot "skills\taskdeck-frontend-workspace-slice\SKILL.md") -Content $repoFrontendSlice -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoCodexRoot "skills\taskdeck-capture-review-loop\SKILL.md") -Content $repoCaptureReview -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoCodexRoot "skills\taskdeck-demo-regression\SKILL.md") -Content $repoDemoRegression -ForceWrite:$Force
Write-FileIfNeeded -Path (Join-Path $repoCodexRoot "skills\taskdeck-verification-doc-sync\SKILL.md") -Content $repoVerifyDocSync -ForceWrite:$Force

Write-Host "Bootstrapped Claude Code + Codex workflow for: $RepoPath"
Write-Host ""
Write-Host "NOTE: In Taskdeck, CLAUDE.md, .claude/, and .codex/ are all TRACKED (committed)."
Write-Host "No git exclude rules were added -- these files should be committed."
Write-Host ""
Write-Host "Machine-specific: .codex/config.toml contains hardcoded paths."
Write-Host "Update the PATH and HOME entries after cloning on a new machine."
