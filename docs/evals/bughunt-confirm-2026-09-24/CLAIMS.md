# CLAIMS — FACT vs inference vs community anecdote

Snapshot basis: `/workspace/handoffs/codex-reddit-eval-2026-09-24/benchmark.json` (meta.updated **2026-09-23**), distilled in `CLAIM_CHECKS.json` + `KEY_RUNS.json`.  
Prefer **featured** rows; treat earlier singles as historical when a mean supersedes them.

Legend: **FACT** = published board number · **INFERENCE** = estate implication · **ANECDOTE** = Reddit/X feel · Status from ledger: SUPPORTED / CHECK

---

## C1 — GPT-6 Astra max leads planted-bug score

- **Kind:** FACT  
- **Claim:** Astra max ≈ **45/105 @ ~$33** leads featured board (earlier single **48 @ $31.21** also exists, not featured).  
- **Evidence:** `CLAIM_CHECKS.json` · KEY_RUNS Astra max mean-of-3 vs 5.6 Sol max 43.5.  
- **Status:** **SUPPORTED**  
- **Confirm protocol:** BH1 — recompute top-N featured by `fixed` desc from frozen `benchmark.json`; assert Astra max mean ≥ next featured OpenAI/Claude arm.  
- **Refute if:** Live board (same planted set) publishes a featured arm > Astra max mean with comparable harness notes.

## C2 — GPT-6 Sol max is a large absolute drop vs 5.6 Sol max

- **Kind:** FACT  
- **Claim:** Sol-6 max ≈ **29.3–32 /105 @ ~$9–10** vs 5.6 Sol max **43.5 @ ~$95** (Δ ≈ −14 on preferred means).  
- **Evidence:** Featured Sol-6 max mean-of-3 = 29.3; earlier single 32 @$10.03.  
- **Status:** **SUPPORTED**  
- **Confirm protocol:** BH1 — Δ(fixed Sol-6 max preferred − Sol-5.6 max preferred) ≤ −10.  
- **Refute if:** Preferred Sol-6 max ≥ 5.6 Sol max − 5 on same board revision.

## C3 — GPT-6 Sol max ≈ GPT-5.6 Sol medium

- **Kind:** FACT  
- **Claim:** Sol-6 max **29.3** ≈ 5.6 Sol medium **29**.  
- **Status:** **SUPPORTED**  
- **Confirm protocol:** BH1 — |Sol-6 max − 5.6 Sol medium| ≤ 2 on preferred rows.  
- **Refute if:** Gap > 5 points on same snapshot.

## C4 — Astra/Sol-6 match or beat prior-gen mid/high tiers at much lower $

- **Kind:** FACT (score) + INFERENCE (efficiency story)  
- **Claim:** Astra max ≈ 5.6 Sol max score at ~1/3 cost; Sol-6 max ≈ medium prior score at lower list $.  
- **Evidence:** Astra 45/$33.03 vs Sol56 43.5/$95.35; Sol-6 29.3/$9.33 vs medium 29/$15.77.  
- **Status:** **SUPPORTED** (numbers) · efficiency framing **CHECK** via BH2 ratios.  
- **Confirm protocol:** BH2 — compute `fixed / cost_usd` and `$ per fixed point` for Astra/Sol/Luna × effort; rank vs 5.6 peers.  
- **Refute if:** Preferred efficiency ranking flips when using only `cost_kind=list` peers or when superseded rows are excluded.

## C5 — Opus 5.5 max near frontier ceiling (keep Claude coding lane)

- **Kind:** FACT + INFERENCE  
- **Claim:** Opus 5.5 max ≈ **41.7–43 @ ~$58–60** near Astra; supports keeping Claude Opus 5.5 coding lane.  
- **Status:** FACT **SUPPORTED** · estate keep-Claude **INFERENCE / CHECK** (needs BH3/BH4 estate relevance).  
- **Confirm protocol:** BH1 score proximity (|Opus−Astra| ≤ 5) + BH3 planted-bug microbench parity (not full Bug Hunt).  
- **Refute if:** Estate microbench shows Opus systematically worse than Codex Astra/Sol on Chris fixtures under deterministic oracles.

## C6 — Absolute Sol-6 quality is the controversy (not the cost story)

- **Kind:** INFERENCE / community narrative  
- **Claim:** Cost wins are real; absolute Sol-6 quality drop is why Reddit/X “needs more attention.”  
- **Status:** Narrative **CHECK** — numbers SUPPORTED; product implication needs BH3/BH4.  
- **Confirm protocol:** BH3 oracle fail rates on planted bugs; optional BH4 n≤5 Codex CLI A/B.  
- **Refute if:** Estate fixtures show Sol-6 max ≈ Astra/Opus under same oracle (board does not transfer).

## C7 — Luna-6 Max feels/worse than Luna-5.6 xHigh / Max (community feel)

- **Kind:** FACT (absolute score) + ANECDOTE (feel)  
- **Claim:** Luna-6 max **18.3 @ ~$0.52** vs 5.6 Luna max **31.3 @ ~$3.15** — absolute worse; community “feel” may diverge from $/pt.  
- **Status:** Score **SUPPORTED** · feel **CHECK** (BH5 advisory only).  
- **Confirm protocol:** BH5 — small advisory sample; never merge-gate.  
- **Refute if:** Blind human/estate sample prefers Luna-6 Max on quality despite lower planted score, or board revises Luna-6 upward.

## Non-claims (explicit)

- Reddit alone does **not** flip coding-lane charter.  
- Full Bug Hunt re-run is **out of scope** ($100+/arm).  
- LLM judgment must **not** become a merge CI gate.
