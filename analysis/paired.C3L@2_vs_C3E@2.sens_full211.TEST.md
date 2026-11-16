# [TEST] Paired comparison (correct, set sens_full211)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@2 vs C3E@2 | industryor | 69 | 29.0 | 26.1 | +2.9 | [+0.0, +7.2] | 2/67/0 | 0.5000 |
| qwen3:8b | C3L@2 vs C3E@2 | mamo_complex_lp | 146 | 44.5 | 39.7 | +4.8 | [+1.4, +8.2] | 7/139/0 | 0.0156 |
| qwen3:8b | C3L@2 vs C3E@2 | pooled | 215 | 39.5 | 35.4 | +4.2 | [+1.9, +7.0] | 9/206/0 | 0.0039 |
