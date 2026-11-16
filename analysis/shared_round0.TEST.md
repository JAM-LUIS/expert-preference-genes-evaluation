# [TEST] Shared round 0: identity, paired test, decomposition, MDE

TEST: test cases, read after the freeze gate passed.


## qwen3:8b: C3L@2 vs C3E@2 (round 0 = C0)

Round-0 identity (sha): round-0 content sha256 equal on every unit.

| scope | n | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|
| industryor | 50 | +4.0 | [+0.0, +10.0] | 2/48/0 | 0.5000 |
| mamo_complex_lp | 75 | +4.0 | [+0.0, +9.3] | 3/72/0 | 0.2500 |
| pooled | 125 | +4.0 | [+0.8, +8.0] | 5/120/0 | 0.0625 |

| repair pattern | n | A only right | B only right | outcome triples (r0, A, B) |
|---|---|---|---|---|
| both_repaired | 37 | 5 | 0 | r0=0 a=0 b=0: 27; r0=0 a=1 b=0: 5; r0=0 a=1 b=1: 5 |
| only_a_repaired | 12 | 0 | 0 | r0=0 a=0 b=0: 12 |
| only_b_repaired | 0 | 0 | 0 |  |
| neither_repaired | 76 | 0 | 0 | r0=0 a=0 b=0: 27; r0=1 a=1 b=1: 49 |

## MDE under a shared round 0 (analysis set main (sizes only))

| p01 | scope | n | MDE (pp) | power |
|---|---|---|---|---|
| 0.0 | pooled | 125 | 6.3 | 0.806 |
| 0.0 | industryor | 50 | 15.4 | 0.803 |
| 0.0 | mamo_complex_lp | 75 | 10.4 | 0.805 |
| 0.005 | pooled | 125 | 7.2 | 0.804 |
| 0.005 | industryor | 50 | 16.3 | 0.801 |
| 0.005 | mamo_complex_lp | 75 | 11.3 | 0.803 |
| 0.01 | pooled | 125 | 8.0 | 0.801 |
| 0.01 | industryor | 50 | 17.2 | 0.801 |
| 0.01 | mamo_complex_lp | 75 | 12.2 | 0.803 |
| 0.02 | pooled | 125 | 9.3 | 0.802 |
| 0.02 | industryor | 50 | 19.0 | 0.802 |
| 0.02 | mamo_complex_lp | 75 | 13.8 | 0.803 |
| 0.03 | pooled | 125 | 10.4 | 0.803 |
| 0.03 | industryor | 50 | 20.5 | 0.8 |
| 0.03 | mamo_complex_lp | 75 | 15.1 | 0.804 |
