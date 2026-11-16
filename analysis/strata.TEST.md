# [TEST] Stratified comparison C3L@2 vs C3E@2 (correct)

TEST: test cases, read after the freeze gate passed.


## by benchmark

| model | stratum | n | acc A % | acc B % | A−B (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|
| qwen3:8b | industryor | 50 | 36.0 | 32.0 | +4.0 | 2/48/0 | 0.5000 |
| qwen3:8b | mamo_complex_lp | 75 | 54.7 | 50.7 | +4.0 | 3/72/0 | 0.2500 |

## by scale

| model | stratum | n | acc A % | acc B % | A−B (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|
| qwen3:8b | T1 | 36 | 69.4 | 61.1 | +8.3 | 3/33/0 | 0.2500 |
| qwen3:8b | T2 | 23 | 52.2 | 52.2 | +0.0 | 0/23/0 | 1.0000 |
| qwen3:8b | T3 | 66 | 33.3 | 30.3 | +3.0 | 2/64/0 | 0.5000 |

## by difficulty

| model | stratum | n | acc A % | acc B % | A−B (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|
| qwen3:8b | Easy | 18 | 61.1 | 55.6 | +5.6 | 1/17/0 | 1.0000 |
| qwen3:8b | Hard | 13 | 23.1 | 23.1 | +0.0 | 0/13/0 | 1.0000 |
| qwen3:8b | Medium | 19 | 21.1 | 15.8 | +5.3 | 1/18/0 | 1.0000 |
| qwen3:8b | n/a | 75 | 54.7 | 50.7 | +4.0 | 3/72/0 | 0.2500 |

## by type

| model | stratum | n | acc A % | acc B % | A−B (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|
| qwen3:8b | IP | 28 | 46.4 | 39.3 | +7.1 | 2/26/0 | 0.5000 |
| qwen3:8b | LP | 11 | 36.4 | 36.4 | +0.0 | 0/11/0 | 1.0000 |
| qwen3:8b | MILP | 10 | 10.0 | 10.0 | +0.0 | 0/10/0 | 1.0000 |
| qwen3:8b | n/a | 75 | 54.7 | 50.7 | +4.0 | 3/72/0 | 0.2500 |
