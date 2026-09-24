# bughunt-micro — BH3 planted-bug fixture

Tiny stdlib+pytest app with **N=10** independent planted bugs and a **deterministic** oracle (no LLM judge).

## Layout

```
fixtures/bughunt-micro/
  src/app.py           # buggy implementation
  tests/test_oracle.py # one test per bug
  oracle/score.sh      # JSON {passed,total,per_bug}
  oracle/check.sh      # exit 0 iff passed==total
  bugs/MANIFEST.json   # ids, fingerprints, tests
  fixes/golden.patch   # makes oracle fully green
```

## Baseline (bugs present)

```bash
cd fixtures/bughunt-micro
../../.venv/bin/python -m pytest -q   # or: oracle/score.sh
# expect passed < 10
```

## Golden green (prove oracle)

```bash
cd fixtures/bughunt-micro
cp src/app.py src/app.py.bak
patch -p1 < fixes/golden.patch
oracle/check.sh   # expect exit 0, 10/10
mv src/app.py.bak src/app.py   # restore buggy baseline for agents
```

## Constraints

- Deterministic oracles may gate merges · **no LLM merge CI**
- Non-blocking docs/eval wiring only
- Parent: agent-harness #328 · epic #325 · track #299
