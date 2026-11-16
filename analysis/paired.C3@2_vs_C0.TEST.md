# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3@2 vs C0 | industryor | 50 | 34.0 | 28.0 | +6.0 | [−4.0, +16.0] | 5/43/2 | 0.4531 |
| qwen3:8b | C3@2 vs C0 | mamo_complex_lp | 75 | 41.3 | 46.7 | −5.3 | [−21.3, +9.3] | 15/41/19 | 0.6076 |
| qwen3:8b | C3@2 vs C0 | pooled | 125 | 38.4 | 39.2 | −0.8 | [−10.4, +8.8] | 20/84/21 | 1.0000 |
