# [TEST] Output length and accuracy: correct ~ configuration + log(output tokens)

TEST: test cases, read after the freeze gate passed.


## qwen3:8b: C3L@2, C3E@2, C0 (reference C3L@2)

| model | term | coef | 95% CI | OR | p |
|---|---|---|---|---|---|
| primary | – | no finite estimate: separation (linear-program check): a combination of the covariates never lowers and somewhere raises the conditional likelihood, e.g. one configuration never loses among the informative cases | | | |
| sensitivity | intercept | 0.829 | [-0.738, 2.395] | 2.290 | 0.2999 |
| sensitivity | label[C3E@2] | -0.175 | [-0.313, -0.036] | 0.840 | 0.0136 |
| sensitivity | label[C0] | -0.374 | [-0.541, -0.206] | 0.688 | 0.0000 |
| sensitivity | log_out_tokens | -0.141 | [-0.380, 0.098] | 0.868 | 0.2476 |

Quartile cut points (output tokens): 422, 602, 914

| label | quartile | n | accuracy |
|---|---|---|---|
| C3L@2 | Q1 | 28 | 0.75 |
| C3L@2 | Q2 | 27 | 0.6667 |
| C3L@2 | Q3 | 29 | 0.5517 |
| C3L@2 | Q4 | 41 | 0.0976 |
| C3E@2 | Q1 | 31 | 0.6774 |
| C3E@2 | Q2 | 29 | 0.6207 |
| C3E@2 | Q3 | 30 | 0.4667 |
| C3E@2 | Q4 | 35 | 0.0286 |
| C0 | Q1 | 37 | 0.5676 |
| C0 | Q2 | 36 | 0.5 |
| C0 | Q3 | 35 | 0.2857 |
| C0 | Q4 | 17 | 0.0 |
