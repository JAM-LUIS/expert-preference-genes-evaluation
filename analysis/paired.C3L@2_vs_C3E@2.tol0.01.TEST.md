# [TEST] Paired comparison (correct_tol:0.01, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@2 vs C3E@2 | industryor | 50 | 38.0 | 34.0 | +4.0 | [−4.0, +12.0] | 3/46/1 | 0.6250 |
| qwen3:8b | C3L@2 vs C3E@2 | mamo_complex_lp | 75 | 56.0 | 52.0 | +4.0 | [+0.0, +9.3] | 3/72/0 | 0.2500 |
| qwen3:8b | C3L@2 vs C3E@2 | pooled | 125 | 48.8 | 44.8 | +4.0 | [+0.0, +8.0] | 6/118/1 | 0.1250 |
