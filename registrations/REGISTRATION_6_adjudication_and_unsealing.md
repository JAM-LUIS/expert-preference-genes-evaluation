# Registration record 6: reference adjudication, type labels, and the tools used at unsealing

Prepared 2026-10-10T16:45Z for public time-stamping on OSF. Appended before any test score was unsealed (preregistration Section 6.5, step 4). Supersedes the manifest of record 5 (https://osf.io/wcdn6/, content `33cde4dbe644e7af8cba587f615df74d3507240af56edb2dc768c19f3cef984c`) for the freeze gate. This record holds hashes, counts and case identifiers only: no problem text, no reference value, no model output.

## State at the time of this record

The test run ended 2026-10-08T06:08Z (4,163 output files, hashes in `OUTPUT_SHA256.txt`, SHA-256 `bb47c5e2358bc9e2edb55b29ef5c465665957dbf5426ec3eaa9283b7ee3e7f7e`). No test output has been scored, opened or summarised. The coordinating session read counts, case identifiers, hashes and error messages only.

## Adjudication as returned

Adjudicator C returned the round-1 sheet and a log on 2026-10-10.

| File | SHA-256 |
|---|---|
| Round-1 sheet as sent (record 2) | `37c657b64dbe7c230c9eceae3bc1476afffc5cef472e378b4f7e33ce90f96a0e` |
| Round-1 sheet as returned | `af3f582b07c6aa9611b55e0f2593dbd1746429df3fe51fa59a74928e32c1ec1a` |
| Adjudicator's log as returned | `8b0e3396f5eb158578706de10825382859c4feeca77db110a9d50b848b3e7991` |

Integrity: sheet names, headers, row order and every cell outside the six decision columns are identical to the sheet as sent.

The log is a per-session record (date, time span, files, row ranges) that C wrote after the sessions, not while working; C stated this when returning it. It is not an access log. The sheet was last saved at 2026-10-10T03:04Z; the last logged session ends 2026-10-10T02:30Z.

Counts (125 re-derived problems): sampled reference check, 66 problems: 27 automatic, 10 random audit (9 confirmed, 1 overturned), 29 adjudication rows (28 with a verdict). Full screening, 59 problems: 9 flagged, all 9 with a verdict. Type labels, 100 problems: 73 automatic, 10 random audit (none overturned), 14 adjudicated, 3 linear-unresolved.

## Deviations from the registered procedure (decided 2026-10-10, all scores sealed)

The returned sheet left four gaps. C was not asked again, for lack of time before the revision deadline. Nobody entered a decision on C's behalf and nobody else read a problem statement. Each gap is closed by a fixed rule that uses only material registered in record 2, written in `adjudication_deviations_20261010.json` and applied by `export_for_ingest.py --deviations`.

| # | Gap | Rule applied | Effect |
|---|---|---|---|
| D1 | The reference audit overturned 1 of 10 cases (`mamo_complex_lp-0036`), so the registered rule calls for a second audit round of the 10 fixed candidates. It was not performed. | The 10 candidates keep their automatic settlement (both batches match the reference within tolerance, both optimal, no flag). | 7 test and 3 dev problems stay CORRECT without a human audit. |
| D2 | `industryor-0039` (test): adjudication row returned with no verdict, value or reason. Both batches matched the reference; both had flagged the statement as ambiguous, which is why it was sent to C. | The reference is kept (method: agreement of the two batches; no adjudicator). | Stays in the main analysis set without a human verdict. |
| D3 | `industryor-0045` (test): C labelled it NL_LINEARIZABLE without the class after linearisation. | The class both batches gave independently (IP). | None on the main set: C judged the reference AMBIGUOUS. |
| D4 | `industryor-0096` (test): C labelled it NL_NOT_LINEARIZABLE and also entered a class after linearisation. | The label cell stands; the dependent cell is dropped. | None on the main set: C judged the reference AMBIGUOUS. |

Post hoc sensitivity analysis added because of D1 and D2: the primary comparisons are repeated without the 8 test problems whose registered human check was not completed (`industryor-0003`, `industryor-0039`, `mamo_complex_lp-0012`, `-0014`, `-0017`, `-0039`, `-0053`, `-0064`, `-0140`, `-0207` restricted to the test side of the main set). It is labelled post hoc in the paper.

Also noted: `industryor-0026` (audit row, verdict only) came back with a type entered although none was asked; it equals the automatic label and is not read.

## Resulting inputs

| File | SHA-256 |
|---|---|
| `adjudication_deviations_20261010.json` | `e358a4270d3635c1de7fda606820209fd06e176335df637502c3987600143352` |
| `export_for_ingest.py` (as used; differs from record 2 by the LINEAR_UNRESOLVED pass-through of 2026-10-08 and the deviation rules of 2026-10-10) | `106ffc12174440309ed978501f45413cc0b890ad5db7526ede58ac4077ff32d1` |
| `ref_check.csv` | `c1851d51646d471b701b3c5ac7983448a366296530ac176b97315aac1bd52d52` |
| `reference_check_scope.json` | `e4aa44f9a2e3426c0eff452b8dfe71a9c575c5dff26f2243d327c057f62a52ff` |
| `type_final_labels.csv` | `35b236554cbf4a3f5af919026404f48f9e4ad466efaf1be736adb5aee187a612` |
| `adjudication_summary.json` | `db8d47fef736b5efbb6c90263a75b1f9f688d7309463d463c6f8b257d893a7eb` |

Verdicts over the 75 checked problems: CORRECT 37, INCORRECT 4, AMBIGUOUS 34, CORRECT_ROUNDED 0, UNDERSPECIFIED 0. Type labels: LP 24, MILP 15, IP 46, NL_LINEARIZABLE 10, NL_NOT_LINEARIZABLE 2, linear-unresolved 3.

Main analysis set after the registered removals: **n = 125 test problems** (151 before adjudication; 26 removed as AMBIGUOUS, of which 2 are also NL_NOT_LINEARIZABLE).

## Code added after the test run and before unsealing

The new files did not exist in manifest 3 and the changed ones differ from it; all are committed (`55734f0`, ingest `29a6e43`, manifest `4e51d69`) and covered by manifest 4 before the gate opens. The digest of the scoring rules (`refs.rules_sha256`, `8c14104e…`) is unchanged. They implement rules that were registered without code, or the deviations above. None was written with knowledge of any test output.

| File | Purpose |
|---|---|
| `runtime/orgene/annotations.py`, `analysis/r1/strata.py`, `data/ingest_annotations.py` and two tests | The registered LINEAR_UNRESOLVED rule (preregistration Section 2): counted as linear, left out of type strata only. |
| `tools/server_refused.py` | The registered server-refusal rule for gpt-oss:20b: refused and dependency-blocked units are scored as incorrect; complete-case variant. Actual counts: 15 refused units on 15 problems, 10 dependent units blocked. |
| `tools/reexec_final.py` | The registered 600-second re-execution of the engineering set's final programs. |
| `analysis/r1/measurement_check.py` and its test | Sampling, material export and analysis of the registered measurement-check plan. |
| Checker guide (English `145d156e8e5a825aaee8e85c0f4da772da01dfe60e6580e6c7c4a183c7df5f79`, Chinese `b5eea821b4d70a3b4763f9b85dc4b78e110c77b306503832d49f04abbfdd6a19`) and workbook template (`42b6629951b1c1d26a4c27a98d64fc5a9eb014dbe3187fd797b8c3360fee3f7e`) | Not code and not in the manifest: unchanged since 2026-09-29, when these hashes were written in project notes; the measurement-check plan said they would be in the freeze manifest, and they were not. Recorded here instead. |

Manifest 4: 287 files, `complete: true`, content SHA-256 `e7325fb92c2fa6cc26c3824b5a03066d8238478521ecbf1f8827863170a53b59`. The 11 files of record 1 remain byte-identical.

| Uploaded file | SHA-256 |
|---|---|
| `FREEZE_MANIFEST.json` | `57a355a5ed852d70d489f9f67a90a9784bb6c98904fd9e0cd83302bd5903f7b1` |
| `adjudication_deviations_20261010.json` | `e358a4270d3635c1de7fda606820209fd06e176335df637502c3987600143352` |
| `adjudication_summary.json` | `db8d47fef736b5efbb6c90263a75b1f9f688d7309463d463c6f8b257d893a7eb` |
