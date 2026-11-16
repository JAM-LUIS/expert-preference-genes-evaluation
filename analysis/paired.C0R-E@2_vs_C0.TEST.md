# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C0R-E@2 vs C0 | industryor | 50 | 34.0 | 28.0 | +6.0 | [−6.0, +18.0] | 7/39/4 | 0.5488 |
| qwen3:8b | C0R-E@2 vs C0 | mamo_complex_lp | 75 | 33.3 | 46.7 | −13.3 | [−28.0, +1.3] | 12/41/22 | 0.1214 |
| qwen3:8b | C0R-E@2 vs C0 | pooled | 125 | 33.6 | 39.2 | −5.6 | [−16.0, +4.8] | 19/80/26 | 0.3713 |
