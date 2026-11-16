# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@2 vs C1 | industryor | 50 | 36.0 | 26.0 | +10.0 | [−2.0, +22.0] | 7/41/2 | 0.1797 |
| qwen3:8b | C3L@2 vs C1 | mamo_complex_lp | 75 | 54.7 | 29.3 | +25.3 | [+13.3, +37.3] | 23/48/4 | 0.0003 |
| qwen3:8b | C3L@2 vs C1 | pooled | 125 | 47.2 | 28.0 | +19.2 | [+10.4, +28.0] | 30/89/6 | <0.0001 |
