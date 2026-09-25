# EVAL_PROTOCOL — confirm Bug Hunt claims without full re-bench

**Goal:** Confirm or refute C1–C7 for Chris’s stack **without** spending $100+/arm on full Bug Hunt Bench.  
**Home:** extend `Chris0Jeky/agent-harness` only · parent [#299](https://github.com/Chris0Jeky/agent-harness/issues/299)  
**Hard rules:** deterministic oracles may gate merges · **no LLM merge CI** · cloud agents exception-only · no charter flip from Reddit alone.

## Arms of interest (featured preferred)

| Alias | Preferred row | fixed | cost_usd |
| --- | --- | ---: | ---: |
| Astra-6 max | GPT-6 Astra (max) mean of 3 | 45 | 33.03 |
| Sol-5.6 max | GPT-5.6 Sol (max) mean of 2 | 43.5 | 95.35 |
| Opus-5.5 max | Opus 5.5 (max) mean of 3 | 41.7 | 58.53 |
| Sol-6 max | GPT-6 Sol (max) mean of 3 | 29.3 | 9.33 |
| Sol-5.6 med | GPT-5.6 Sol (medium) | 29 | 15.77 |
| Luna-6 max | GPT-6 Luna (max) mean of 3 | 18.3 | 0.52 |
| Luna-5.6 max | GPT-5.6 Luna (max) mean of 3 | 31.3 | 3.15 |

---

## (A) Scoreboard snapshot re-verify — BH1

**Cost:** $0 (local JSON).  
**Input:** frozen `benchmark.json` + `CLAIM_CHECKS.json` + `KEY_RUNS.json`.  
**Steps:**

1. Hash / date-stamp the snapshot (`meta.updated`, file sha256).
2. Select **featured** rows; when notes say SUPERSEDES, use the superseding mean.
3. Reproduce the claim table in `CLAIMS.md` / `CLAIM_CHECKS.json` to ±0.1 score / ±$0.05.
4. Emit artifact: `evidence/BH1_scoreboard_verify.json` (+ short markdown diff if any drift).

**Pass:** All C1–C3, C5-score, C7-score match ledger.  
**Fail:** Drift → refresh ledger; do not invent new charter conclusions.

## (B) Cost / $ efficiency ratios — BH2

**Cost:** $0.  
**Metrics (list peers only; never mix `list` with billed unless labeled):**

- `pts_per_dollar = fixed / cost_usd`
- `dollars_per_pt = cost_usd / fixed`
- Pairwise: Astra-6 max vs Sol-5.6 max; Sol-6 max vs Sol-5.6 medium; Luna-6 max vs Luna-5.6 max

**Steps:** Script over KEY_RUNS / featured subset; include effort ladder (low→max) for Astra/Sol/Luna.  
**Artifact:** `evidence/BH2_efficiency_ratios.md` + `.csv`.  
**Pass:** C4 efficiency story holds on featured means.  
**Non-goal:** Claim API billed cost equals list estimate.

## (C) Estate microbench — planted-bug fixture + deterministic oracle — BH3

**Cost:** engineer time; optional small model spend later.  
**Design:**

1. Plant **N≤10** known bugs in a tiny fixture repo under `agent-harness` (or `fixtures/bughunt-micro/`).
2. Oracle = deterministic checks only: tests, linters, `rg` fingerprints, exit codes — **no LLM judge in gate path**.
3. Agent loop (Codex CLI / Claude Code / Muse) attempts fix; score = oracle pass count.
4. Record trajectory + cost if available as **telemetry**, not merge authority.

**Success criteria:** Fixture + oracle runnable in CI as **non-blocking** check or docs-gated job; evidence path `evidence/BH3_microbench/`.  
**Non-goals:** Replicate 105-bug Bug Hunt; LLM-as-merge-gate; cloud agent fan-out.

## (D) Optional Codex CLI A/B — BH4 (budget-capped)

**Only if Chris authorizes spend.**  
**Arms:** Sol-6 max · Astra max · Opus 5.5 max  
**n ≤ 5** fixed tasks from BH3 fixture (same prompts, same timeout, pinned CLI).  
**Cap:** pre-declare $ budget; abort when hit.  
**Artifact:** `evidence/BH4_codex_ab/` with per-arm oracle scores + $ spent.  
**Non-goals:** Full board parity; statistical significance theater; merge gating on LLM narrative.

## (E) Luna-6 vs Luna-5.6 feel — BH5 (advisory)

**Separate** from merge-relevant score claims.  
**Method:** Small blind sample (n≤5 tasks or n≤3 human raters) on “feel/quality” vs planted score.  
**Output:** Advisory note only → `evidence/BH5_luna_feel.md`.  
**Hard rule:** Results **must not** enter merge CI; may inform routing defaults only after Chris review.

---

## Evidence layout (acceptance)

```
/workspace/handoffs/codex-reddit-eval-2026-09-24/evidence/
  BH1_scoreboard_verify.json
  BH2_efficiency_ratios.md
  BH3_microbench/
  BH4_codex_ab/          # optional
  BH5_luna_feel.md       # advisory
```

Mirror durable copies into agent-harness `docs/evals/bughunt-confirm-2026-09-24/` via local-agent PR (draft).

## Decision rule (charter)

| Outcome | Action |
| --- | --- |
| C1–C4 SUPPORTED | Keep Codex/OpenAI Pro in play for cost-efficient arms; no charter flip |
| C2 + BH3/BH4 show Sol-6 weak on estate | Prefer Astra / Opus for quality-critical coding; Sol-6 for cheap drafts only |
| C5 holds | **Keep Claude Opus 5.5 coding lane** |
| C7 feel diverges | Document; do not gate |

**Never:** Flip Muse/GSQ/local lanes from Reddit alone · launch cloud agents for this · spend on full Bug Hunt re-run.
