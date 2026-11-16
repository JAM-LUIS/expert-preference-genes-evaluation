# [TEST] Paired comparison (correct_tol:1e-06, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@2 vs C3E@2 | industryor | 50 | 34.0 | 30.0 | +4.0 | [+0.0, +10.0] | 2/48/0 | 0.5000 |
| qwen3:8b | C3L@2 vs C3E@2 | mamo_complex_lp | 75 | 53.3 | 49.3 | +4.0 | [+0.0, +9.3] | 3/72/0 | 0.2500 |
| qwen3:8b | C3L@2 vs C3E@2 | pooled | 125 | 45.6 | 41.6 | +4.0 | [+0.8, +8.0] | 5/120/0 | 0.0625 |
