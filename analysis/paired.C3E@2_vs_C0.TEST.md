# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3E@2 vs C0 | industryor | 50 | 32.0 | 28.0 | +4.0 | [+0.0, +10.0] | 2/48/0 | 0.5000 |
| qwen3:8b | C3E@2 vs C0 | mamo_complex_lp | 75 | 50.7 | 46.7 | +4.0 | [+0.0, +9.3] | 3/72/0 | 0.2500 |
| qwen3:8b | C3E@2 vs C0 | pooled | 125 | 43.2 | 39.2 | +4.0 | [+0.8, +8.0] | 5/120/0 | 0.0625 |
