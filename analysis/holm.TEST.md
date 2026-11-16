# [TEST] Holm correction per pre-registered family

TEST: test cases, read after the freeze gate passed.


## primary (m = 1, alpha = 0.05)

| comparison | a vs b | p | Holm p | reject |
|---|---|---|---|---|
| C3L_vs_C3E | C3L@2 vs C3E@2 | 0.0625 | 0.0625 | False |

## ladder (m = 5, alpha = 0.05)

| comparison | a vs b | p | Holm p | reject |
|---|---|---|---|---|
| C3E_vs_C0 | C3E@2 vs C0 | 0.0625 | 0.3125 | False |
| C3L1_vs_C3E | C3L@1 vs C3E@2 | 0.0625 | 0.3125 | False |
| C3L2_vs_C3L1 | C3L@2 vs C3L@1 | 1.0000 | 1.0000 | False |
| C2E_vs_C2 | C2E@2 vs C2 | 1.0000 | 1.0000 | False |
| C3_2_vs_C3_0 | C3@2 vs C3@0 | 1.0000 | 1.0000 | False |

## controls (m = 4, alpha = 0.05)

| comparison | a vs b | p | Holm p | reject |
|---|---|---|---|---|
| C3L_vs_C0 | C3L@2 vs C0 | 0.0020 | 0.0059 | True |
| C3L_vs_C1 | C3L@2 vs C1 | <0.0001 | 0.0003 | True |
| C3L_vs_C2 | C3L@2 vs C2 | 0.0596 | 0.1192 | False |
| C3L_vs_C3 | C3L@2 vs C3@2 | 0.1173 | 0.1192 | False |

## gated tests (fixed sequence)

| test | gate | gate rejected | a vs b | diff | p | reject | reading |
|---|---|---|---|---|---|---|---|
| H2 | C3L_vs_C3E | False | C3L@1 vs C3T@1 | 0.04 | n/a | False | estimate only (gate not rejected) |
