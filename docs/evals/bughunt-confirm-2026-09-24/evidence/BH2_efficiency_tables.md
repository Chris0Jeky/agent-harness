# BH2 — Cost / $ efficiency tables (bonus evidence for #327)

Generated: 2026-09-24T13:09:10.350320+01:00
Source: KEY_RUNS.json featured preferred; list-price peers only.
Status: **bonus** — BH1 is the gate for this phase.

## Pairwise (featured means)

| Pair | Arm A fixed/$ | Arm B fixed/$ | pts/$ A | pts/$ B | $/pt A | $/pt B | Winner (pts/$) |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Astra-6 max vs Sol-5.6 max | 45.0/33.03 | 43.5/95.35 | 1.3624 | 0.4562 | 0.734 | 2.192 | Astra-6 max |
| Sol-6 max vs Sol-5.6 med | 29.3/9.33 | 29.0/15.77 | 3.1404 | 1.8389 | 0.3184 | 0.5438 | Sol-6 max |
| Luna-6 max vs Luna-5.6 max | 18.3/0.52 | 31.3/3.15 | 35.1923 | 9.9365 | 0.0284 | 0.1006 | Luna-6 max |

## C4 efficiency story check

- Astra vs Sol-5.6 max: Astra pts/$ = 1.3624 vs 0.4562 (Astra should win on $/efficiency; score near-parity).
- Sol-6 max vs Sol-5.6 med: Sol-6 pts/$ = 3.1404 vs 1.8389.
- Luna-6 vs Luna-5.6: Luna-6 pts/$ = 35.1923 vs 9.9365 (Luna-6 may win $/pt despite worse absolute score).

## Effort ladder (KEY_RUNS list peers)

| model | effort | featured | n | fixed | cost_usd | pts_per_dollar | dollars_per_pt |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| GPT-5.6 Luna | high | False | 1 | 13 | 0.57 | 22.807 | 0.0438 |
| GPT-5.6 Luna | low | False | 1 | 4 | 0.1 | 40.0 | 0.025 |
| GPT-5.6 Luna | max | True | 3 | 31.3 | 3.15 | 9.9365 | 0.1006 |
| GPT-5.6 Luna | medium | False | 1 | 9 | 0.33 | 27.2727 | 0.0367 |
| GPT-5.6 Luna | xhigh | False | 1 | 23 | 2.5 | 9.2 | 0.1087 |
| GPT-5.6 Sol | high | False | 1 | 34 | 33.92 | 1.0024 | 0.9976 |
| GPT-5.6 Sol | max | True | 2 | 43.5 | 95.35 | 0.4562 | 2.192 |
| GPT-5.6 Sol | medium | False | 1 | 29 | 15.77 | 1.8389 | 0.5438 |
| GPT-5.6 Sol | xhigh | False | 1 | 39 | 52.75 | 0.7393 | 1.3526 |
| GPT-6 Astra | high | False | 1 | 35 | 20.6 | 1.699 | 0.5886 |
| GPT-6 Astra | low | False | 1 | 27 | 11.69 | 2.3097 | 0.433 |
| GPT-6 Astra | max | True | 3 | 45 | 33.03 | 1.3624 | 0.734 |
| GPT-6 Astra | medium | False | 1 | 34 | 15.78 | 2.1546 | 0.4641 |
| GPT-6 Astra | xhigh | True | 1 | 43 | 24.22 | 1.7754 | 0.5633 |
| GPT-6 Luna | high | False | 1 | 9 | 0.13 | 69.2308 | 0.0144 |
| GPT-6 Luna | low | False | 1 | 4 | 0.2 | 20.0 | 0.05 |
| GPT-6 Luna | max | True | 3 | 18.3 | 0.52 | 35.1923 | 0.0284 |
| GPT-6 Luna | medium | False | 1 | 4 | 0.06 | 66.6667 | 0.015 |
| GPT-6 Luna | xhigh | False | 1 | 14 | 0.39 | 35.8974 | 0.0279 |
| GPT-6 Sol | high | True | 1 | 20 | 4.16 | 4.8077 | 0.208 |
| GPT-6 Sol | low | False | 1 | 6 | 1.08 | 5.5556 | 0.18 |
| GPT-6 Sol | max | True | 3 | 29.3 | 9.33 | 3.1404 | 0.3184 |
| GPT-6 Sol | medium | False | 1 | 14 | 2.39 | 5.8577 | 0.1707 |
| GPT-6 Sol | xhigh | True | 1 | 25 | 7.67 | 3.2595 | 0.3068 |
