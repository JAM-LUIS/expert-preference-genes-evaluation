# [TEST] Mechanism analysis (strata, decomposition, detection and repair)

TEST: test cases, read after the freeze gate passed.


## qwen3:8b: l=C3L@1, e=C3E@1, t=C3T@1, a=C3A@1, round0=C0

Round-0 strata (from the gene-repair run's round-0 checks): N 76, P 19, X 18, M 12

| comparison | scope | n | acc A % | acc B % | A−B (pp) | bootstrap CI (pp) | W/T/L | McNemar p |
|---|---|---|---|---|---|---|---|---|
| L_vs_E | pooled | 125 | 47.2 | 43.2 | +4.0 | [+0.8, +8.0] | 5/120/0 | 0.0625 |
| L_vs_E | N | 76 | 64.5 | 64.5 | +0.0 | [+0.0, +0.0] | 0/76/0 | 1.0000 |
| L_vs_E | P | 19 | 21.1 | 21.1 | +0.0 | [+0.0, +0.0] | 0/19/0 | 1.0000 |
| L_vs_E | X | 18 | 33.3 | 5.6 | +27.8 | [+11.1, +50.0] | 5/13/0 | 0.0625 |
| L_vs_E | M | 12 | 0.0 | 0.0 | +0.0 | [+0.0, +0.0] | 0/12/0 | 1.0000 |
| T_vs_E | pooled | 125 | 43.2 | 43.2 | +0.0 | [+0.0, +0.0] | 0/125/0 | 1.0000 |
| T_vs_E | N | 76 | 64.5 | 64.5 | +0.0 | [+0.0, +0.0] | 0/76/0 | 1.0000 |
| T_vs_E | P | 19 | 21.1 | 21.1 | +0.0 | [+0.0, +0.0] | 0/19/0 | 1.0000 |
| T_vs_E | X | 18 | 5.6 | 5.6 | +0.0 | [+0.0, +0.0] | 0/18/0 | 1.0000 |
| T_vs_E | M | 12 | 0.0 | 0.0 | +0.0 | [+0.0, +0.0] | 0/12/0 | 1.0000 |
| L_vs_T | pooled | 125 | 47.2 | 43.2 | +4.0 | [+0.8, +8.0] | 5/120/0 | 0.0625 |
| L_vs_T | N | 76 | 64.5 | 64.5 | +0.0 | [+0.0, +0.0] | 0/76/0 | 1.0000 |
| L_vs_T | P | 19 | 21.1 | 21.1 | +0.0 | [+0.0, +0.0] | 0/19/0 | 1.0000 |
| L_vs_T | X | 18 | 33.3 | 5.6 | +27.8 | [+11.1, +50.0] | 5/13/0 | 0.0625 |
| L_vs_T | M | 12 | 0.0 | 0.0 | +0.0 | [+0.0, +0.0] | 0/12/0 | 1.0000 |
| A_vs_T | pooled | 125 | 43.2 | 43.2 | +0.0 | [+0.0, +0.0] | 0/125/0 | 1.0000 |
| A_vs_T | N | 76 | 64.5 | 64.5 | +0.0 | [+0.0, +0.0] | 0/76/0 | 1.0000 |
| A_vs_T | P | 19 | 21.1 | 21.1 | +0.0 | [+0.0, +0.0] | 0/19/0 | 1.0000 |
| A_vs_T | X | 18 | 5.6 | 5.6 | +0.0 | [+0.0, +0.0] | 0/18/0 | 1.0000 |
| A_vs_T | M | 12 | 0.0 | 0.0 | +0.0 | [+0.0, +0.0] | 0/12/0 | 1.0000 |

Nested decomposition (pp): total +4.0 = detection with generic content +0.0 + gene diagnosis and prescription +4.0; additive case by case: True.

| label | wrong at r0 | detected | repaired ok | correct at r0 | false alarms | broken | final correct |
|---|---|---|---|---|---|---|---|
| C3L@1 | 76 | 49 | 10 | 49 | 0 | 0 | 59 |
| C3E@1 | 76 | 37 | 5 | 49 | 0 | 0 | 54 |
| C3T@1 | 76 | 49 | 5 | 49 | 0 | 0 | 54 |
| C3A@1 | 76 | 76 | 5 | 49 | 49 | 0 | 54 |

| function class of applied genes | wins | losses | single-class wins | single-class losses |
|---|---|---|---|---|
| protocol_execution | 4 | 0 | 0 | 0 |
| coding_hygiene | 4 | 0 | 0 | 0 |
| or_modelling | 5 | 0 | 1 | 0 |
| answer_distribution_heuristic | 0 | 0 | 0 | 0 |

Conservative bound: 2 case(s) flagged at round 0 only by the answer-distribution heuristic (0 outcome(s) changed); L−E becomes +4.0 pp, CI [+0.8, +8.0], McNemar p 0.0625.

| gene | class | fires on wrong | fires on correct | precision | false alarm |
|---|---|---|---|---|---|
| orgene.boundary.solve_before_report | protocol_execution | 5 | 0 | 1.0 | 0.0 |
| orgene.boundary.status_reported | protocol_execution | 5 | 0 | 1.0 | 0.0 |
| orgene.code.sparse_index_guard | coding_hygiene | 7 | 0 | 1.0 | 0.0 |
| orgene.code.tuple_key_indexing | coding_hygiene | 7 | 0 | 1.0 | 0.0 |
| orgene.constraints.rows_sign_feasible | or_modelling | 1 | 0 | 1.0 | 0.0 |
| orgene.data.no_invented_numbers | or_modelling | 1 | 3 | 0.25 | 0.0612 |
| orgene.execution.runs | protocol_execution | 26 | 0 | 1.0 | 0.0 |
| orgene.model.binary_cardinality_linked | or_modelling | 4 | 0 | 1.0 | 0.0 |
| orgene.model.linear_expressions_only | or_modelling | 1 | 0 | 1.0 | 0.0 |
| orgene.model.logic_via_indicators | or_modelling | 4 | 0 | 1.0 | 0.0 |
| orgene.numeric.bigm_bounded | or_modelling | 5 | 2 | 0.7143 | 0.0408 |
| orgene.objective.aggregates_declared_variables | or_modelling | 8 | 0 | 1.0 | 0.0 |
| orgene.solution.nontrivial_optimum | answer_distribution_heuristic | 2 | 0 | 1.0 | 0.0 |
| orgene.solution.status_optimal_or_justified | or_modelling | 37 | 0 | 1.0 | 0.0 |

Problem families: pending.
