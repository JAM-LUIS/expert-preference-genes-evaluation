# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@2 vs C3L@1 | industryor | 50 | 36.0 | 36.0 | +0.0 | [+0.0, +0.0] | 0/50/0 | 1.0000 |
| qwen3:8b | C3L@2 vs C3L@1 | mamo_complex_lp | 75 | 54.7 | 54.7 | +0.0 | [+0.0, +0.0] | 0/75/0 | 1.0000 |
| qwen3:8b | C3L@2 vs C3L@1 | pooled | 125 | 47.2 | 47.2 | +0.0 | [+0.0, +0.0] | 0/125/0 | 1.0000 |
