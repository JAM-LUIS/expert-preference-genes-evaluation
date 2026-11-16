# [TEST] Equivalence (TOST), margin ±5.0 points, alpha 0.05

TEST: test cases, read after the freeze gate passed.

| model | a vs b | scope | n | estimate (pp) | score 90% CI (pp) | TOST p | bootstrap 90% CI (pp) | equivalent | methods agree |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:8b | C3L@1 vs C3T@1 | pooled | 125 | +4.0 | [+1.8, +8.0] | 0.3040 | [+1.6, +7.2] | False | True |
