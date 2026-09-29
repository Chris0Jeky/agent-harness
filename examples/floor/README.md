# The frozen floor as a replay target

`templates/hooks/dispatch.py` is a PreToolUse hook that reads the repository's
tier from `.agent-harness/tier.json` in the project directory. The two
workspace templates here declare tier 3 and tier 4, so replaying the same hook
over both shows what the stricter tier adds:

```bash
charter-replay hooks \
  --baseline "python templates/hooks/dispatch.py --event pre --runtime claude" \
  --candidate "python templates/hooks/dispatch.py --event pre --runtime claude" \
  --baseline-workspace examples/floor/workspace-t3 \
  --candidate-workspace examples/floor/workspace-t4 \
  --corpus replay_v0/corpora/charter \
  --output reports/floor-t3-t4 \
  --fail-on newly-allowed
```

[`report/summary.md`](report/summary.md) is the result on the charter corpus:
tier 4 newly denies 15 of 50 events and newly allows none. The same command
with two different hook files compares two floor versions.

## Private corpus run

`charter-replay import --sample 10000 --output .local/private-sample` builds a
scrubbed sample from local transcripts; pass that directory as `--corpus`. Only
aggregate numbers from such a run belong in a public place.
