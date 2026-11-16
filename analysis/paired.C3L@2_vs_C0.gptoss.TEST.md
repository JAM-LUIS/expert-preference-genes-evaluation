# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| gpt-oss:20b | C3L@2 vs C0 | industryor | 50 | 58.0 | 58.0 | +0.0 | [+0.0, +0.0] | 0/50/0 | 1.0000 |
| gpt-oss:20b | C3L@2 vs C0 | mamo_complex_lp | 75 | 69.3 | 68.0 | +1.3 | [+0.0, +4.0] | 1/74/0 | 1.0000 |
| gpt-oss:20b | C3L@2 vs C0 | pooled | 125 | 64.8 | 64.0 | +0.8 | [+0.0, +2.4] | 1/124/0 | 1.0000 |
