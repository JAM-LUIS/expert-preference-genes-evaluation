# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@2 vs C0R-E@2 | industryor | 50 | 36.0 | 34.0 | +2.0 | [−10.0, +14.0] | 5/41/4 | 1.0000 |
| qwen3:8b | C3L@2 vs C0R-E@2 | mamo_complex_lp | 75 | 54.7 | 33.3 | +21.3 | [+8.0, +36.0] | 24/43/8 | 0.0070 |
| qwen3:8b | C3L@2 vs C0R-E@2 | pooled | 125 | 47.2 | 33.6 | +13.6 | [+4.0, +23.2] | 29/84/12 | 0.0115 |
