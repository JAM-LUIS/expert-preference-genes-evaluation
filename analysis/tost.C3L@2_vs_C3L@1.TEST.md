# [TEST] Equivalence (TOST), margin ±5.0 points, alpha 0.05

TEST: test cases, read after the freeze gate passed.

| model | a vs b | scope | n | estimate (pp) | score 90% CI (pp) | TOST p | bootstrap 90% CI (pp) | equivalent | methods agree |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@2 vs C3L@1 | pooled | 125 | +0.0 | [−2.1, +2.1] | 0.0052 | [+0.0, +0.0] | True | True |
