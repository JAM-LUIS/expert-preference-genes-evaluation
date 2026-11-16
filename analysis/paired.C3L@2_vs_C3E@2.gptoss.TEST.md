# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| gpt-oss:20b | C3L@2 vs C3E@2 | industryor | 50 | 58.0 | 58.0 | +0.0 | [+0.0, +0.0] | 0/50/0 | 1.0000 |
| gpt-oss:20b | C3L@2 vs C3E@2 | mamo_complex_lp | 75 | 69.3 | 69.3 | +0.0 | [+0.0, +0.0] | 0/75/0 | 1.0000 |
| gpt-oss:20b | C3L@2 vs C3E@2 | pooled | 125 | 64.8 | 64.8 | +0.0 | [+0.0, +0.0] | 0/125/0 | 1.0000 |
