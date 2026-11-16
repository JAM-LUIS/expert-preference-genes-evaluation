# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3@2 vs C3E@2 | industryor | 50 | 34.0 | 32.0 | +2.0 | [−8.0, +12.0] | 4/43/3 | 1.0000 |
| qwen3:8b | C3@2 vs C3E@2 | mamo_complex_lp | 75 | 41.3 | 50.7 | −9.3 | [−25.3, +5.3] | 14/40/21 | 0.3105 |
| qwen3:8b | C3@2 vs C3E@2 | pooled | 125 | 38.4 | 43.2 | −4.8 | [−15.2, +4.8] | 18/83/24 | 0.4408 |
