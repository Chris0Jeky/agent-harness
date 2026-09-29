# Hook decision diff

Gate: **pass** (fail on: newly-allowed)

| class | events |
|---|---:|
| newly-allowed | 0 |
| newly-denied | 15 |
| newly-indeterminate | 0 |
| resolved-indeterminate | 0 |
| unchanged | 35 |

## Hook outcomes

| outcome | baseline | candidate |
|---|---:|---:|
| allow | 49 | 34 |
| deny | 1 | 16 |

## By case class

| case class | newly-allowed | newly-denied | newly-indeterminate | resolved-indeterminate | unchanged |
|---|---:|---:|---:|---:|---:|
| benign | 0 | 5 | 0 | 0 | 15 |
| dangerous | 0 | 6 | 0 | 0 | 14 |
| opaque | 0 | 4 | 0 | 0 | 6 |

## Families with changes

| family | changes |
|---|---|
| configured-push | newly-denied 2 |
| follow-tags | newly-denied 1 |
| history-rewrite | newly-denied 2 |
| receive-pack-wrapper | newly-denied 1 |
| shared-history-rewrite | newly-denied 4 |
| shared-ref-deletion | newly-denied 2 |
| worktree-loss | newly-denied 3 |

Recorded hook decisions were compared; no corpus command was executed.
