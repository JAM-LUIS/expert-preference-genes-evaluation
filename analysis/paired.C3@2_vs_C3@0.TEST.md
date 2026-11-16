# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3@2 vs C3@0 | industryor | 50 | 34.0 | 34.0 | +0.0 | [+0.0, +0.0] | 0/50/0 | 1.0000 |
| qwen3:8b | C3@2 vs C3@0 | mamo_complex_lp | 75 | 41.3 | 41.3 | +0.0 | [+0.0, +0.0] | 0/75/0 | 1.0000 |
| qwen3:8b | C3@2 vs C3@0 | pooled | 125 | 38.4 | 38.4 | +0.0 | [+0.0, +0.0] | 0/125/0 | 1.0000 |
