# v5 dev results (regression fixture of the R1 analysis scripts)

Dev data only: the 85 dev cases (MAMO ComplexLP 60, IndustryOR 25), qwen3:8b, the v5 runs of 2026-09-05 to 09-07.
No test run, no test case and no problem text is in this directory.

## What is here

| path | content |
|---|---|
| `runs/<run>/results.<C>.jsonl`, `runs/<run>/metrics.<C>.json` | per-case results and metrics of the 24 v5 dev run directories (12 labels x 2 benchmarks), copied byte for byte |
| `registry.json` | run registry (`analysis/r1/registry.py` format) with the labels of the stage-0 report T8 (C0, C1, C2, C3_r0..C3_r2, C3L_r0..C3L_r2, C3E, C0_np4000, C2_np4000) |
| `t8_expected.json` | the cells of T8 tables 2.1, 2.2 and 3.4 and the pooled execution line after table 2.2, copied verbatim from the report (with the report's sha256) |
| `t8_dev_per_case_matrix.csv`, `t8_mde_shared_round0.csv` | two of T8's output tables (per-case correct / exec per label; shared-round-0 MDE), copied byte for byte |
| `SHA256SUMS` | sha256 of every file above |

## Provenance and neutral writing

- Source: the read-only copy of the v5 evidence snapshot `paper/evidence/dev-snapshot-20260907/runs/` made for the
  stage-0 status check (T8). The sha256 of every copied `results` and `metrics` file equals its line in that
  snapshot's SHA256SUMS (48 of 48, checked when the fixture was made).
- Left out on purpose: the runs' `run_config.json` (they record absolute paths of the machine the runs were made on),
  the report and log files, and the three smoke-run directories. Nothing was edited; the copied files carry no
  absolute path and no identity term.
- The run directory names keep the v5 naming (`<date>-<model>-<benchmark>-dev-<condition>[-np6000][-r<k>]`); they
  sit under `reference/`, not under `experiments/`.

## Use

`analysis/r1/t8_repro.py` runs the registry, the analysis set `dev_all85` and the paired comparisons on these files
and compares every cell with `t8_expected.json` (test: `runtime/tests/test_e20a_t8_repro.py`). Accuracies,
execution rates, counts, discordance, Wilson intervals, differences, McNemar p-values, mean tokens and calls, and the
shared-round-0 MDE all match the report.
