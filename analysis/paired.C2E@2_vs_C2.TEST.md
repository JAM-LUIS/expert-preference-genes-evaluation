# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C2E@2 vs C2 | industryor | 50 | 38.0 | 38.0 | +0.0 | [+0.0, +0.0] | 0/50/0 | 1.0000 |
| qwen3:8b | C2E@2 vs C2 | mamo_complex_lp | 75 | 37.3 | 36.0 | +1.3 | [+0.0, +4.0] | 1/74/0 | 1.0000 |
| qwen3:8b | C2E@2 vs C2 | pooled | 125 | 37.6 | 36.8 | +0.8 | [+0.0, +2.4] | 1/124/0 | 1.0000 |
