# Registration record 7: supplementary run of the nine test problems viewed on 5 September 2026 (after unsealing)

Prepared 2026-10-10T17:40Z for public time-stamping on OSF, before the supplementary run starts. It supersedes the manifest of record 6 (https://osf.io/y9x3u/, content `e7325fb92c2fa6cc26c3824b5a03066d8238478521ecbf1f8827863170a53b59`) for the freeze gate. Hashes, counts and case identifiers only.

## Status: post hoc

The scores of the formal run were unsealed on 2026-10-10 from about 16:55Z, after record 6 became public. This record and the run it registers come after that and are post hoc. Nothing of the formal run is rerun, rescored or changed.

## Why

The preregistration (Section 2) promises a sensitivity analysis that adds back the test problems whose statements were viewed on 2026-09-05. The formal run's unit matrices were built from the split locks that exclude those problems, so the nine problems (MAMO ComplexLP 0022, 0070, 0149, 0151, 0184; IndustryOR 0014, 0041, 0061, 0066) were never run and the analysis could not be computed. This supplementary run executes them with the three conditions of the main comparison (C0, C3E, C3L) on qwen3:8b, registry entry `qwen3-8b.main`: 27 units, same library, lexicon, templates, model, decoding settings and scheduler as the formal run; campaign seed 20261010.

## What changed since manifest 4

Eight files (commit `1d7adec`; manifest 5 in `8d884df`):

- `tools/run_campaign.py`: one more id selector (`minus_split_dir`: the ids of one split lock's side without those of another lock's same side), seven lines. No other code changed; scoring and analysis code are identical to manifest 4.
- `configs/campaigns/test_viewed0905_20261010.json` (campaign spec), `configs/run_matrix/mamo-viewed0905.json` (15 units), `configs/run_matrix/industryor-viewed0905.json` (12 units), and the two scheduler plans with their hash receipts.

Manifest 5: 294 files, `complete: true`, content SHA-256 `da8f807102defd97050bd593706062f5de17f27359374310ee81f0e4028ecea5`. The 11 files of record 1 remain byte-identical.

## How the run is made

The driver's preflight scans the working tree for held-out case identifiers outside sealed run directories and refuses to start when it finds any; after a completed test run it finds them in that run's directory. For the duration of the supplementary run the formal run's directory (`experiments/test-main-20261006/`) is moved out of the repository and moved back afterwards. Before the move a copy was made and both copies were checked against `OUTPUT_SHA256.txt` (SHA-256 `bb47c5e2358bc9e2edb55b29ef5c465665957dbf5426ec3eaa9283b7ee3e7f7e`): 4,158 of 4,163 files match; the five that differ are the `freeze_gate.jsonl` logs of the five Qwen3-8B model entries, to which the scoring of 2026-10-10 appended its gate records.

## Analysis

The paired comparison C3L vs C3E (two rounds) is computed on the main-analysis set plus the five viewed problems that belong to the main sets (MAMO 0022; IndustryOR 0014, 0041, 0061, 0066), with the registered test and bootstrap, and on the full set plus all nine. The run registry holds one run directory per label and benchmark, so the rows of the two run directories are joined by a script outside the frozen tree; the result is labelled post hoc.

## Notes recorded after unsealing (for the record; none changes a frozen file)

- gpt-oss:20b refusals: `industryor-0011`, condition C0, was refused on two attempts of the formal run and answered on the third, so the refusal is not fully deterministic, as Section 3 of the preregistration had assumed. The frozen `tools/server_refused.py` stops on the blocking events that those earlier attempts left in the event log; it was called through a wrapper outside the tree (`server_refused_resolved_blocks.py`, SHA-256 `b1666db2037b28816383b212c778711520f11946bf94a7f9588c13c1c5ddb5fe`) that ignores a blocking event when both the blocked unit and its source unit are complete. Result: 15 refused units, 10 dependency-blocked units, as counted before unsealing.
- The problem-family cluster bootstrap (Section 4) was not computed: family labels were not produced before unsealing.
- `registry.py matrix` (the all-labels matrix export) refuses on one gpt-oss:20b unit record whose stored content hash does not match its stored answer (`mamo_complex_lp-0015`, C1); the paired analyses do not use that export. Cause not yet established.
- The temperature-0.7 subset is not a named analysis set; its comparison is computed on the subset's problems that lie in the main-analysis set, by a script outside the frozen tree.

| Uploaded file | SHA-256 |
|---|---|
| `FREEZE_MANIFEST.json` | `5feb0f717bcc321417127ac03912aa26a4950a960e9f93d480ac7316e9803e96` |
| `test_viewed0905_20261010.json` | `c95aebaeb088ea79a67b73ee99f1d71cc5818cea2551442fe7e10aa011da312b` |
