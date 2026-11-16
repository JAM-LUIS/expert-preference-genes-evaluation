# Measurement check of the solver-based accuracy measure (pre-registered plan)

This section is part of the pre-registered analysis plan. It is fixed before any test-set run, together with the SHA-256 digests of the reviewer guide (English and Chinese versions) and the judgment workbook template, which are listed in the freeze manifest. Condition names follow the main plan: C0 (direct program generation), C3E (C0 plus generic execution-feedback repair) and C3L (C0 plus rule-based checking and repair). Both repair conditions use at most two repair rounds and share C0's program as round 0.

## 1. Purpose and status

The primary outcome is execution accuracy judged by the solver. An output counts as correct if its program runs within the time limit, reports an optimal status, and prints an objective value within the primary tolerance of the benchmark's reference value, using the reference values that result from the pre-registered reference-check rules. This measure compares objective values only.

The measurement check asks two independent human reviewers whether the programs formulate the stated problems correctly. It estimates how often the solver-based measure disagrees with them:

- **false positive (FP)**: counted correct, but the formulation is wrong;
- **false negative (FN)**: counted incorrect, but the program runs and its formulation is right, for example because the reference value is wrong or the statement admits more than one reasonable reading.

The rates are reported overall and for C0, C3E and C3L. The main effect is bounded from the judgments on the problems where C3L and C3E produced different programs (Section 9). Because the sample includes outputs counted as correct, the check is also the model-level verification of such outputs. The check tests the measure; it is not an outcome. No confirmatory claim depends on it, and nothing in the main analysis is changed because of it.

## 2. Reviewers

- Two reviewers. Neither is an author. Neither is a member of the company associated with the first author, or has a financial relationship with it (apart from any payment for this check, which would be disclosed). Neither has ever collaborated with either author, is a student of either author, or works or studies at either author's institution. Neither is an author of a method compared in the paper.
- Each reviewer signs a one-page independence declaration before receiving any material.
- Recruitment follows the reply of the first author's university human research office to an inquiry about whether the check constitutes human subjects research.
- The reviewers take no part in writing or reviewing the rule library, in the reference-answer check, or in the analysis. The authors do not judge any program and do not take part in the reviewers' discussion.

## 3. Sampling

### 3.1 Frame and the set D

- **Frame U.** The primary analysis set of the main comparison for the primary model (qwen3:8b): the test problems of both benchmarks that enter the main analysis. The frame therefore excludes the nine test problems whose statements were seen on 5 September 2026, the IndustryOR problems labelled non-linear and not linearizable, and the problems removed from the main analysis by the reference-check rules. Before the last two exclusions the frame has 151 problems. N denotes its final size.
- **Program identity.** Two programs are the same if their Python token sequences are identical once comments, docstrings and layout (blank lines, indentation width, spacing) are ignored. The comparison is automatic and is made on every problem of the frame.
- **The set D.** D contains the problems of U whose final C3L program and final C3E program are not the same. N_D = |D|. On every problem outside D the two conditions submitted the same program, so they receive the same solver verdict and the same human judgment.

### 3.2 Two parts of the sample

**Part 1: problems in D (for the main effect and for the misclassification rates).**

- If N_D ≤ 24, every problem in D is judged (census).
- If N_D > 24, 24 problems are drawn from D, stratified by benchmark (MAMO ComplexLP, IndustryOR) × type of disagreement between the two conditions' solver verdicts. There are three types:
  - C3L counted correct and C3E incorrect;
  - C3L counted incorrect and C3E correct;
  - the same verdict for both, with different programs.

**Part 2: problems outside D (for the misclassification rates only).**

- 10 problems are drawn from U \ D, stratified by benchmark × the solver verdict of C3L (correct or incorrect).

The sample therefore has at most 34 problems. Solver verdicts use the tolerance and reference values of the main analysis.

### 3.3 Allocation and selection

- **Allocation** (the same rule in each part; target 24 in part 1 when N_D > 24, target 10 in part 2):
  - Every non-empty stratum first receives one problem.
  - The remaining units are allocated in proportion to N_h − 1 by the largest-remainder method, never exceeding N_h.
  - Ties are broken in the fixed stratum order: benchmark (MAMO, then IndustryOR), then type (the order listed in 3.2).
- **Selection.** Within each stratum, problems are sorted by the hexadecimal SHA-256 digest of the string `"<SEED>:<problem_id>"` (ascending), and the first n_h are taken, with SEED = 20261008. This is equivalent to a random draw and can be reproduced by anyone from the problem IDs, the program identities, the solver verdicts and the seed.
- **Timing.** The sample is drawn once, after all primary-model test runs have been scored and registered. The selected problem IDs, N_D, the stratum sizes and their digest are added to the run registry before any material is sent.
- **Weights.** Each sampled problem carries the design weight w_i = N_h / n_h of its stratum. In a census of D, the weight is 1 for every problem of D.

### 3.4 Why this design

The main-effect correction (Section 9) can come only from problems in D. A uniform sample of 50 of the roughly 150 problems, the design first considered, would judge only about a third of D and spend most of its problems outside D, where they cannot change the main effect. The present design:

- judges all of D when D is small (up to 24 problems), which removes sampling error from the main-effect correction;
- otherwise judges 24 problems of D. For D of up to about 70 problems, that is as many as or more than a uniform sample of 50 would judge, and a much larger share when D is moderate (for example, 24 of 30 instead of 10);
- keeps 10 problems outside D, so that the misclassification rates of every condition can still be estimated with design weights.

The sizes were chosen to keep each reviewer's total time at about 6 hours: at about 4 minutes per program, the 34 problems give about 60 to 90 programs and about 5 hours of judging (range 4 to 6). A version with 30 problems from D and 12 from outside D was also considered. It would take about 6 hours of judging (range 5 to 7.5) and gives somewhat narrower bounds when D is large (Section 9.4).

This design has two costs:

- When D is very large (more than about 72 of 150 problems), the uniform sample of 50 would judge more problems of D.
- The problems outside D carry large weights (about 8.4 when N_D = 66), so the misclassification rates there are less precise.

## 4. What is judged

- For each sampled problem, the final programs of C0, C3E and C3L: the programs that were executed and scored in the main analysis.
- Because C3E and C3L start from C0's program, the three programs are identical when no repair was triggered. Each distinct program (in the sense of 3.1) is judged once, and the judgment counts for every condition that produced it. A problem in D shows two or three programs; a problem outside D usually shows one.
- Outputs of other conditions, of the other models and of the repeated runs are not judged.

## 5. Blinding and presentation

- **Normalization for display (automatic).** Comments and docstrings are removed. String literals that contain condition names, rule identifiers or run metadata are masked. Blank lines and trailing whitespace are normalized. Nothing else is changed. An automatic check confirms that each displayed program has the same abstract syntax tree as the original, apart from the removed docstrings and masked strings. Programs that do not parse have only their comments removed, and are flagged in the key. If two programs of the same problem become identical on display, they are shown once and judged once.
- **What reviewers see.** The problem statement exactly as the model received it, and the displayed programs.
- **What reviewers do not see.** Condition labels, round numbers, repair messages, the model's natural-language output, execution output, solver verdicts, reference values, the benchmark name, the original problem ID, and whether a problem belongs to D.
- **Codes.** All sampled problems, from both parts, are presented together in ascending order of SHA-256(`"<SEED>:order:<problem_id>"`) and coded P01, P02 and so on. Within a problem, distinct programs are ordered by SHA-256(`"<SEED>:program:<problem_id>:<identity digest of the program>"`) and lettered A, B, C. The key linking codes to problems, conditions, verdicts, strata and weights is kept by the authors. Both reviewers receive the same booklet and workbook layout.
- **Instructions.** Reviewers follow the frozen reviewer guide. They are asked not to look up the problems or their answers, not to use AI tools, and not to discuss any item before the disagreement step. Running the programs is allowed but not required.

## 6. Judgments

For each distinct program, each reviewer records:

- four aspects, each correct, incorrect or cannot judge: variables, objective, constraints, data use;
- an overall judgment: correct, incorrect or cannot judge;
- for incorrect programs, the category of the most serious error: missing constraint, objective sense, integrality, Big-M, data misread, other;
- optional notes, which are required for cannot judge. Notes start with `AMBIG:` when the statement admits more than one reasonable reading.

"Correct" means a correct formulation of the problem as stated, under a reasonable reading. A formulation error counts as an error even if it might not change the optimal value for the given data. Full definitions and a worked example are in the guide.

## 7. Agreement and resolution of disagreements

- **Agreement.** Cohen's κ on the reviewers' independent overall judgments, over all distinct programs judged (unweighted: κ describes the judging procedure), with three categories. The 95% confidence interval comes from a problem-level bootstrap (10,000 resamples within the sampling strata of both parts, seed 1, percentile method). Also reported: percent agreement; κ for each aspect; and κ for correct versus incorrect after excluding programs that either reviewer marked cannot judge.
- **Reference value.** 0.60. Landis and Koch (1977) describe values above 0.60 as substantial agreement. The value is reported as observed, and a value below 0.60 is discussed as a limitation. No reviewer is replaced and no item is re-judged because of κ.
- **Resolution.** A script lists the programs whose overall judgments differ, and the programs that both reviewers judged incorrect but placed in different categories, with both judgments and notes. The two reviewers discuss these programs without the authors and record a final judgment and category, or "unresolved".
- **Final labels.** Where the independent judgments agree, that label is final; otherwise the label from the discussion is final. Programs that are unresolved, or that both reviewers finally mark cannot judge, have no final label (NA).

## 8. Definitions and misclassification rates

For problem i and condition c ∈ {C0, C3E, C3L}:

```
S_ic ∈ {0,1}      solver verdict of the main analysis (observed for every problem)
X_ic ∈ {0,1}      the program ran within the time limit and printed both protocol lines (from the run logs)
H_ic ∈ {0,1,NA}   final human label of the program
T_ic = X_ic · H_ic
```

T is the correctness of the output. A program that does not run cannot be a correct output, and whether it runs is observed directly, so the human judgment decides only whether an executed program is formulated correctly. S_ic = 1 implies X_ic = 1.

**Rates.** They are estimated with the design weights w_i of Section 3.3 (Horvitz–Thompson totals, combined as ratios). The sums run over sampled problems whose label is not NA.

```
FP_c = Σ_i w_i · 1[S_ic = 1, T_ic = 0]  /  Σ_i w_i · 1[S_ic = 1]
FN_c = Σ_i w_i · 1[S_ic = 0, T_ic = 1]  /  Σ_i w_i · 1[S_ic = 0]
```

- **Overall rates.** The same ratios over distinct programs, each counted once with the weight of its problem. If identical programs received different solver verdicts in different runs, this is reported, and the program is counted once under each verdict.
- **Intervals.** 95% Clopper–Pearson intervals evaluated at the Kish effective sample size of the denominator, n_eff = (Σw)² / Σw², with effective count p̂ · n_eff (Korn and Graubard, 1998). Beta quantiles are used for non-integer values. Without weights this is the ordinary Clopper–Pearson interval. The overall rates pool programs of the same problem, which are not independent, so their intervals are indicative.
- **Also reported:**
  - the same rates unweighted and separately for the two parts of the sample;
  - FN among executed outputs;
  - the number of programs judged correct that did not run (a correct formulation with a code-level failure; these are not false negatives of the measure);
  - rates by benchmark (descriptive).
- **Corrected accuracy per condition** (descriptive point estimate): acc*_c = acc_c + (1/N) Σ_i w_i (T_ic − S_ic), where acc_c is the accuracy on the full frame.
- **Reasons for false negatives** (descriptive, after unblinding). The authors classify each false negative as "reference value apparently wrong", "statement ambiguous", "tolerance" or "other", from the reviewers' notes and the reference-check records.

## 9. Bounds for the main effect

The main effect is the observed difference on the frame, as in the main analysis:

```
Δ  = (1/N) Σ_{i∈U} (S_{i,C3L} − S_{i,C3E})
```

The corrected effect uses T instead of S:

```
Δ* = (1/N) Σ_{i∈U} (T_{i,C3L} − T_{i,C3E}) = Δ + (1/N) Σ_{i∈D} d_i

d_i = (T_{i,C3L} − S_{i,C3L}) − (T_{i,C3E} − S_{i,C3E})      d_i ∈ {−2, −1, 0, 1, 2}
```

- d_i < 0 means that measurement error inflates C3L's advantage on problem i, through a C3L false positive or a C3E false negative. d_i > 0 means the reverse.
- Outside D the two conditions submitted the same program, so d_i = 0 there. The correction therefore needs judgments on D only; part 2 of the sample does not enter this section.

### 9.1 Census of D (N_D ≤ 24)

Δ* is known exactly, except for programs with label NA.

- For a problem with an NA program, d_min and d_max are the smallest and largest values of d_i consistent with the possible labels. An NA program that ran can have T = 0 or 1; one that did not run has T = 0.
- The formulas:

```
Δ̂* = Δ + (1/N) Σ_{resolved i∈D} d_i
L   = Δ + (1/N) [ Σ_{resolved i∈D} d_i + Σ_{NA i∈D} d_min ]
U   = Δ + (1/N) [ Σ_{resolved i∈D} d_i + Σ_{NA i∈D} d_max ]
```

Without NA programs, L = U = Δ̂* = Δ*.

### 9.2 Sample of D (N_D > 24)

With m⁻ and m⁺ the numbers of adverse and favourable discrepancy units observed in the n_D judged problems of D (NA problems left out):

```
m⁻ = Σ_{i ∈ judged ∩ D} max(−d_i, 0)        m⁺ = Σ_{i ∈ judged ∩ D} max(d_i, 0)

Δ̂* = Δ + (1/N) Σ_{i ∈ judged ∩ D} w_i · d_i        (Horvitz–Thompson)

L = Δ − K⁻ / N          U = Δ + K⁺ / N
```

- **K⁻ and K⁺.** K⁻ is the one-sided 97.5% exact upper confidence limit for the number of adverse discrepancy units in D. It is the largest K ∈ {m⁻, …, N_D − n_D + m⁻} with P(Y ≤ m⁻) ≥ 0.025, where Y follows a hypergeometric distribution with population N_D, K marked units and sample n_D. K⁺ is computed in the same way from m⁺.
- **Coverage.** Each limit holds with at least 97.5% confidence, so [L, U] contains Δ* with at least 95% confidence.
- **Approximations.**
  - Allocation in part 1 is close to proportional, so the judged problems of D are treated as a simple random sample of D.
  - A problem with d_i = −2 (a C3L false positive and a C3E false negative on the same problem) counts as two units. The hypergeometric model is exact when no problem contributes two units. Any such problem is reported.
- **NA.** In a sensitivity computation, NA problems are kept with worst-case values: T_{C3L} = 0 and T_{C3E} = 1 for L, and the reverse for U.

### 9.3 Reading and reporting

- [L, U] describes measurement error only. The problem-sampling uncertainty of Δ is given by the main analysis (bootstrap confidence interval) and is reported next to it.
- For the secondary comparisons C3L − C0 and C3E − C0, only the Horvitz–Thompson point estimate of the corrected difference is reported: the sample is not designed to bound them.

### 9.4 Examples with fictitious numbers (illustration only; not results)

**Shared setting.**

- N = 150. C3L is counted correct on 93 problems and C3E on 81, so Δ = 8.0 percentage points.
- The C3L and C3E programs differ on N_D = 66 problems; the other 84 problems are outside D.

**(a) Uniform sample of 50 problems (considered first).**

- About 22 of the 50 problems fall in D.
- In them, the reviewers find:
  - one problem where C3L's program is counted correct but judged wrong (d = −1);
  - one problem where the reference value is wrong, C3L's program is judged right and C3E's is judged wrong (d = +1);
  - one problem where C3E's program is counted correct but judged wrong while C3L's is right (d = +1).
- So m⁻ = 1 and m⁺ = 2.
- Point estimate: Δ̂* = 8.0 + (66/150) · (2 − 1)/22 · 100 = 10.0 points.
- K⁻ = 13, since P(Y ≤ 1 | 66, 13, 22) = 0.0252 and the value for K = 14 is 0.0162. K⁺ = 17, since P(Y ≤ 2 | 66, 17, 22) = 0.0250 and the value for K = 18 is 0.0164.
- **[L, U] = [−0.7, 19.3].** Had the reviewers found no adverse discrepancy (m⁻ = 0), L would be 2.7.

**(b) 30 problems from D and 12 from outside D (considered next).**

- Allocation is taken as proportional in this example, so every judged problem of D has weight 66/30 = 2.2.
- In the 30 problems of D, the reviewers find one adverse discrepancy and three favourable ones, so m⁻ = 1 and m⁺ = 3.
- Point estimate: Δ̂* = 8.0 + 2.2 · (3 − 1)/150 · 100 = 10.9 points.
- K⁻ = 9, since P(Y ≤ 1 | 66, 9, 30) = 0.0271 and the value for K = 10 is 0.0146. K⁺ = 14, since P(Y ≤ 3 | 66, 14, 30) = 0.0395 and the value for K = 15 is 0.0231.
- **[L, U] = [2.0, 17.3].** With m⁻ = 0, L would be 4.7.

**(c) Present design: 24 problems from D and 10 from outside D.**

- Every judged problem of D has weight 66/24 = 2.75.
- In the 24 problems of D, the reviewers find one adverse discrepancy and two favourable ones, so m⁻ = 1 and m⁺ = 2.
- Point estimate: Δ̂* = 8.0 + 2.75 · (2 − 1)/150 · 100 = 9.8 points.
- K⁻ = 11, since P(Y ≤ 1 | 66, 11, 24) = 0.0369 and the value for K = 12 is 0.0231. K⁺ = 15, since P(Y ≤ 2 | 66, 15, 24) = 0.0313 and the value for K = 16 is 0.0200.
- **[L, U] = [0.7, 18.0].** With m⁻ = 0, K⁻ would be 7 and L would be 3.3.

**(d) Present design when D is small (census).**

- Suppose instead that N_D = 22, so all 22 problems of D are judged.
- The reviewers find discrepancies of +1, +1 and −1. On one further problem, C3L's program is unresolved (NA): it was counted correct, and the C3E program was counted incorrect and judged wrong, so d ∈ {−1, 0}.
- Δ̂* = 8.0 + 1/150 · 100 = 8.7, and [L, U] = [8.0, 8.7].

**How far below Δ the lower bound can fall, in points (N = 150).**

Each cell shows two cases: no adverse discrepancy found / one found. "Exact" means D is judged in full, so only NA programs widen the bound.

| N_D | uniform 50 | 30 from D + 12 | present: 24 from D + 10 |
|---|---|---|---|
| 20 | 4.0 / 6.7 | exact | exact |
| 30 | 4.7 / 7.3 | exact | 1.3 / 2.0 |
| 40 | 5.3 / 8.0 | 1.3 / 2.7 | 2.0 / 4.0 |
| 66 | 5.3 / 8.7 | 3.3 / 6.0 | 4.7 / 7.3 |
| 90 | 5.3 / 8.7 | 5.3 / 8.7 | 7.3 / 10.7 |

Approximate totals and judging times:

| Design | Problems | Programs | Judging time |
|---|---|---|---|
| Uniform 50 | 50 | about 90 to 97 | about 6 to 6.5 hours |
| 30 from D + 12 | at most 42 | about 70 to 115 | about 6 hours (5 to 7.5) |
| Present: 24 from D + 10 | at most 34 | about 60 to 90 | about 5 hours (4 to 6) |

**Weighted false-positive rate (present design, example (c)).**

- C3L's program is counted correct on 13 of the 24 judged problems in D (weight 2.75), with one false positive.
- C3L's program is counted correct on 6 of the 10 problems outside D (weight 84/10 = 8.4), with none.
- FP_C3L = (2.75 · 1) / (2.75 · 13 + 8.4 · 6) = 2.75 / 86.15 = 3.2%.
- n_eff = 86.15² / (13 · 2.75² + 6 · 8.4²) = 14.2, and the 95% interval is [0.0, 28.0]%.
- The unweighted ratio, 1/19 = 5.3%, would over-represent D, where repairs make errors more likely to be caught or introduced.

## 10. Why decision variables are not compared

- The benchmarks publish only a reference optimal objective value for each problem. They provide no reference model and no reference solution.
- Even with a reference solution, optimal solutions are often not unique, so a correct program can return a different optimal solution.
- Correct formulations define different variables (aggregated or disaggregated, auxiliary variables, different indexing), so there is no common variable space for an automatic comparison.
- The objective value is therefore the only quantity that can be compared automatically. The measurement check covers the remaining gap by having people judge the formulation directly.
- A separate formulation-equivalence diagnostic is described in the main plan and is not part of this check.

## 11. Error categories and the rule-based classification

For programs whose final label is incorrect, the final error categories are tabulated by condition, with and without weights. They are cross-tabulated with the offline run of all rule predicates on the same programs (which predicates failed, if any). This comparison is descriptive.

## 12. Rule read-through (descriptive)

After the disagreement step is closed and its sheet is registered, the two reviewers read through the frozen rule library (release 1.0) and the rule provenance table once. They point out obvious errors only, with no scores. The order preserves blinding, because the reviewers see the rules only after all judgments are final. The issues raised are listed in full in an appendix. The rule library used for the test runs is not changed, and no analysis is rerun because of them.

## 13. What is reported

- Sample composition: N_D; whether D was judged in full; N_h, n_h and the weights of every stratum in both parts; the number of distinct programs; and programs per problem.
- Agreement statistics (Section 7), the number of disagreements, how they were resolved, and the number of NA.
- FP and FN rates overall and per condition, weighted with intervals, with the extra quantities of Section 8 and the reasons for false negatives.
- The main effect:
  - Δ and its bootstrap interval from the main analysis;
  - Δ̂* and [L, U], with N_D, n_D, m⁻ and m⁺ (or the NA ranges in a census);
  - the worst-case NA version;
  - the point estimates for the secondary comparisons.
- Error categories by condition and their cross-tabulation with the rule predicates.
- The rule read-through issues (appendix).

## 14. Timing, deviations and contingencies

- **Timing.** The check starts after all primary-model test runs have been scored and registered. Materials go to both reviewers at the same time.
- **One reviewer withdraws.** If a reviewer withdraws before finishing the independent judgments, the check is completed by the other reviewer. κ is then not available, and this is reported.
- **Check not completed in time.** If the independent reviewers cannot complete the check before the revision deadline, it is carried out, blinded in the same way, by a co-author who did not write or review the rules. That co-author has seen the reference values of the problems adjudicated in the reference check. The paper then states that the check was not independent.
- **Deviations.** Any deviation from this plan is reported as such.
