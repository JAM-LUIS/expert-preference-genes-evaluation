# Blind recomputations of 125 benchmark references

Before the test, the reference answers of 125 problems (25 of MAMO ComplexLP, 100 of IndustryOR) were recomputed twice. Two batches of isolated agents each read only the problem statement, wrote an optimization model and solved it with CBC. Neither batch saw the reference answer or the other batch. The instructions they followed are in `reference_check/REDERIVATION_INSTRUCTIONS.md`.

| Path | Content |
|---|---|
| `batch_A/A01` … `A08` | First batch (model claude-fable-5-1), eight groups of problems |
| `batch_B/B01` … `B08` | Second batch (model claude-opus-5-5), a different grouping of the same problems |
| `<group>/results.jsonl` | One line per problem: solver status, objective value, model summary, whether the statement is ambiguous and under which readings, problem type, confidence |
| `<group>/models/<problem id>.py`, `.out.txt` | The model the agent wrote and what it printed. Files with `__r2` or `__check` in the name are the agent's own second readings and checks |
| `comparison/` | The two batches set against each other and against the benchmark reference: `comparison.json` (per problem), `routing.csv` (which problems went to the adjudicator and why), `summary.json` |

The verdicts that came out of this comparison and of the adjudication are in `frozen_tree/data/reference_overrides/` and, as a table, in `references/checked_references.csv`.

## Things to know before you use these files

- The models were written by language-model agents and were not corrected afterwards. Where the two batches disagree, at least one of them is wrong; that is what the comparison is for.
- The summaries and notes inside `results.jsonl` are in Chinese.
- The 16 `results.jsonl` files and the three comparison files are byte-identical to the ones fixed in registration record 2 (<https://osf.io/kafzj/>, text in `registrations/REGISTRATION_2_comparison_and_adjudication.md`, where they appear under their original paths `stage1/annotation_agent/` and `stage1/annotation_agent_hidden/`). `shasum -a 256` on a file gives the digest listed there.
- The adjudicator's sheet is not included.
- A model file may repeat numbers and wording of its problem statement. Each file keeps the licence of the benchmark its problem id names (`LICENSES.md`).
