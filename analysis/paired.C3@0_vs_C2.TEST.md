# [TEST] Paired comparison (correct, set main)

TEST: test cases, read after the freeze gate passed.

| model | comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3@0 vs C2 | industryor | 50 | 34.0 | 38.0 | −4.0 | [−14.0, +6.0] | 2/44/4 | 0.6875 |
| qwen3:8b | C3@0 vs C2 | mamo_complex_lp | 75 | 41.3 | 36.0 | +5.3 | [−5.3, +16.0] | 10/59/6 | 0.4545 |
| qwen3:8b | C3@0 vs C2 | pooled | 125 | 38.4 | 36.8 | +1.6 | [−5.6, +8.8] | 12/103/10 | 0.8318 |
