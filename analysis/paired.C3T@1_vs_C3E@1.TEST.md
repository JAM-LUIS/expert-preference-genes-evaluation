# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3T@1 vs C3E@1 | industryor | 50 | 32.0 | 32.0 | +0.0 | [+0.0, +0.0] | 0/50/0 | 1.0000 |
| qwen3:8b | C3T@1 vs C3E@1 | mamo_complex_lp | 75 | 50.7 | 50.7 | +0.0 | [+0.0, +0.0] | 0/75/0 | 1.0000 |
| qwen3:8b | C3T@1 vs C3E@1 | pooled | 125 | 43.2 | 43.2 | +0.0 | [+0.0, +0.0] | 0/125/0 | 1.0000 |
