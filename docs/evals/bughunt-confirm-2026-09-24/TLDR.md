# Bug Hunt Bench confirm evals — TLDR

**Seeded:** 2026-09-24 (Europe/London / BST) · bench snapshot 2026-09-23  
**Trigger:** https://www.reddit.com/r/codex/comments/1woxxj2/this_needs_more_attention/  
**Bench:** https://bughunt.productcompass.pm/ · data in this pack (`benchmark.json`)  
**Home:** agent-harness · parent [#299](https://github.com/Chris0Jeky/agent-harness/issues/299) · sister UX [#281](https://github.com/Chris0Jeky/agent-harness/issues/281) (do not merge)

## Why

Confirm GPT-6 Astra cost-win + GPT-6 Sol absolute drop vs 5.6 Sol **without** re-running full Bug Hunt ($100+/arm).

## Headline FACTS (featured / non-superseded preferred)

| Arm | /105 | $ (list) |
| --- | ---: | ---: |
| GPT-6 Astra max (mean×3) | **45** | **~33** |
| GPT-5.6 Sol max (mean×2) | **43.5** | **~95** |
| Opus 5.5 max (mean×3) | **41.7** | **~59** |
| GPT-6 Sol max (mean×3) | **29.3** | **~9** |
| GPT-5.6 Sol medium | **29** | ~16 |
| GPT-6 Luna max (mean×3) | **18.3** | **~0.52** |

Earlier singles exist (Astra 48@$31; Sol-6 32@$10; Opus 43@$60) — prefer featured means. Sol-6 max ≈ 5.6 Sol medium; Luna-6 max << 5.6 Luna max (31.3).

## Hard rules

Deterministic oracles may gate merges · **no LLM merge CI** · extend agent-harness only · cloud agents exception-only · no charter flip from Reddit. Stack: keep Opus 5.5 coding lane; Grok Heavy skipped; Codex/OpenAI Pro in play; Muse/local GSQ.

## Confirm path

**(A)** scoreboard re-verify · **(B)** cost/$ ratios · **(C)** estate planted-bug microbench + deterministic oracle · **(D)** optional Codex CLI A/B n≤5 budget-capped · **(E)** Luna feel advisory only.

## Start

`CLAIMS.md` · `EVAL_PROTOCOL.md` · `CLAIM_CHECKS.json` · `KEY_RUNS.json` · `LOCAL_AGENT_HANDOFF.md`
