# [TEST] Paired comparison (correct, set well_specified)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@2 vs C3E@2 | industryor | 48 | 37.5 | 33.3 | +4.2 | [+0.0, +10.4] | 2/46/0 | 0.5000 |
| qwen3:8b | C3L@2 vs C3E@2 | mamo_complex_lp | 71 | 54.9 | 50.7 | +4.2 | [+0.0, +9.9] | 3/68/0 | 0.2500 |
| qwen3:8b | C3L@2 vs C3E@2 | pooled | 119 | 47.9 | 43.7 | +4.2 | [+0.8, +8.4] | 5/114/0 | 0.0625 |
