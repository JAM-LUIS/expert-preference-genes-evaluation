# Licences

## Code

The code in `frozen_tree/` (except `frozen_tree/data/cases/`), `quickstart/`, `figures/`, `post_unsealing_tools/` and `reference_check/` is released under the MIT License (file `LICENSE`). The example problem and programs in `quickstart/example/` were written for this repository and are in the public domain (CC0).

## Benchmark-derived data and outputs

- **MAMO ComplexLP** (FreedomIntelligence/Mamo, commit `2c91069`): CC BY-SA 4.0. Applies to `frozen_tree/data/cases/mamo_complex_lp.jsonl` and to run outputs whose stage name contains `mamo`, which quote its problem statements. Redistribution must keep the attribution and the same licence.
- **IndustryOR** (CardinalOperations/IndustryOR, revision `b008119`): CC BY-NC 4.0. Applies to `frozen_tree/data/cases/industryor.jsonl` and to run outputs whose stage name contains `industry`. Non-commercial use only, with attribution.
- **Engineering-source instances** (`frozen_tree/data/eng/`, `frozen_tree/data/cases/eng.jsonl`, stage `eng-holdout`): derived from MIPLIB 2017 and PGLib-UC; see `frozen_tree/data/eng/` for sources and their terms.

The two benchmarks are kept in separate files and archives; do not merge them into one package.

The files in `rederivations/` are named by problem id; a model there may repeat numbers and wording of its problem statement, and each file keeps the licence of the benchmark its problem id names. `references/checked_references.csv` holds ids, values and verdicts only.

`measurement_check/export/booklet.html` quotes problem statements of both benchmarks next to the sampled programs. Each problem there keeps the licence of its source; `measurement_check/export/key.json` gives the benchmark of every problem.

## Everything else

Registration texts, analysis outputs, the rule library and the documentation are released under CC BY 4.0.

## Logo

`assets/jam-studio-logo.png` is the mark of JAM Studio. It is shown here to say who built the software; it is not covered by the licences above.
