# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@2 vs C2 | industryor | 50 | 36.0 | 38.0 | −2.0 | [−16.0, +10.0] | 5/39/6 | 1.0000 |
| qwen3:8b | C3L@2 vs C2 | mamo_complex_lp | 75 | 54.7 | 36.0 | +18.7 | [+5.3, +32.0] | 22/45/8 | 0.0161 |
| qwen3:8b | C3L@2 vs C2 | pooled | 125 | 47.2 | 36.8 | +10.4 | [+0.8, +20.0] | 27/84/14 | 0.0596 |
