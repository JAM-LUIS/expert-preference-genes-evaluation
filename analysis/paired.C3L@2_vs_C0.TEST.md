# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@2 vs C0 | industryor | 50 | 36.0 | 28.0 | +8.0 | [+2.0, +16.0] | 4/46/0 | 0.1250 |
| qwen3:8b | C3L@2 vs C0 | mamo_complex_lp | 75 | 54.7 | 46.7 | +8.0 | [+2.7, +14.7] | 6/69/0 | 0.0312 |
| qwen3:8b | C3L@2 vs C0 | pooled | 125 | 47.2 | 39.2 | +8.0 | [+3.2, +12.8] | 10/115/0 | 0.0020 |
