# Bug Hunt source-verification follow-up (draft)

**Acceptance status: blocked on missing frozen inputs. Do not merge yet.**

This restores the historical BH1/BH2 material split from PR #331, preserving
its original claim and receipt bytes from commit
`259fa5f66f35593bcdd9667a8c171691cf58c1be`. The old documents' `FACT`,
`SUPPORTED`, and `PASS` labels describe what that imported pack reported;
they are not a fresh verification by this repository or the current review.
The receipt's `overall_pass: true` is retained as historical evidence, not
promoted into source-verified acceptance. The original README is available in
that commit. This qualification takes precedence when reading the mirror.

BH3's independently tested fixture remains in `fixtures/bughunt-micro/`.
A passing fixture test does not validate these external benchmark numbers,
model rankings, costs, claims, or their transfer to the estate.

## Missing evidence

The receipt names these source bytes, which are not in the PR or supplied
repository archive:

| Input | Required SHA-256 |
| --- | --- |
| `benchmark.json` | `d58f9add7926f471b694cb4809cb12559ab9d2a1af88cb5efe096b0e875766fb` |
| `KEY_RUNS.json` | `9f1375733e52c93b0f11a235df117dc5e19a833e57ab3b55b3f86ccc18b61418` |

The generating verifier is also absent. Its former machine-local path,
`/workspace/handoffs/codex-reddit-eval-2026-09-24/`, is not a portable source
artifact. A newer live scoreboard must not silently replace these frozen
inputs. A hash in a receipt proves neither possession nor verification of
the corresponding file.

## Bounded completion plan

1. Recover the exact frozen inputs and generator, verify their hashes, and
   record a durable permitted source location. Keep any redistributability or
   private-data restriction explicit instead of publishing unapproved data.
2. Implement or recover a deterministic offline verifier. Select rows by
   stable identity; make featured/superseding rules explicit; reject duplicate,
   absent, non-finite, negative or zero-denominator data. Label any deliberate
   non-featured comparison rather than calling every row a featured mean.
3. Recompute claims and cost ratios from the recovered inputs. Keep list
   estimates separate from billed amounts, distinguish arithmetic checks
   from model-quality inference, and test missing/corrupt input failure paths.
4. Emit a new provenance-bound result without overwriting the imported
   receipt. Review every FACT/SUPPORTED label against that result and remove
   or qualify conclusions that the supplied evidence cannot establish.
5. Review this draft and its final-head checks before merging. Only then
   consider completing #326/#327. A successful docs-only CI run is not source
   verification and does not satisfy these steps.

No model calls, paid benchmark rerun, charter change, native-agent
qualification, new LLM judge, or merge authority is introduced here.

Tracks #326 and #327 under #325/#299. BH4/BH5 remain separate owner-budgeted
or advisory work in #329/#330. The sister UX track #281 is unchanged.
