# [TEST] Paired comparison (correct, set sens_orig_ref)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@2 vs C3E@2 | industryor | 50 | 36.0 | 32.0 | +4.0 | [+0.0, +10.0] | 2/48/0 | 0.5000 |
| qwen3:8b | C3L@2 vs C3E@2 | mamo_complex_lp | 75 | 56.0 | 50.7 | +5.3 | [+1.3, +10.7] | 4/71/0 | 0.1250 |
| qwen3:8b | C3L@2 vs C3E@2 | pooled | 125 | 48.0 | 43.2 | +4.8 | [+1.6, +8.8] | 6/119/0 | 0.0312 |
