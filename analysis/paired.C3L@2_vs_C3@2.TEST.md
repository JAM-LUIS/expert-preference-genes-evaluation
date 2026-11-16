# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@2 vs C3@2 | industryor | 50 | 36.0 | 34.0 | +2.0 | [−10.0, +14.0] | 5/41/4 | 1.0000 |
| qwen3:8b | C3L@2 vs C3@2 | mamo_complex_lp | 75 | 54.7 | 41.3 | +13.3 | [−1.3, +28.0] | 21/43/11 | 0.1102 |
| qwen3:8b | C3L@2 vs C3@2 | pooled | 125 | 47.2 | 38.4 | +8.8 | [−0.8, +18.4] | 26/84/15 | 0.1173 |
