# Expert check of the solver-based measure: materials

Materials of the expert check described in Sections 4.6 and 6.5 and Supplementary Material S4 of the manuscript.
Added to the review project after the cut-off of 18 October 2026, 12:00 ET, at which the reviewers of each set were
fixed. Reviewers are identified by number only; 2 returned workbook(s) are included.

| Path | Content |
|---|---|
| `export/` | The blinded booklet the reviewers judged, the item list, the key that maps programs to conditions and solver verdicts (never sent to a reviewer), and the export manifest. |
| `workbooks/` | The returned judgment workbooks. Cell contents are as received; see Redactions for file metadata. |
| `rules/` | The three assignment rules in the order written: the pair rule (10 Oct), its change to blocks (12 Oct) and to sets (13 Oct), each fixed before any judgment was returned; `sets.json` lists the 12 sets. The rules are working notes in Chinese. |
| `reviewer_guide_EN.md` | The reviewer guide as sent. |
| `analysis/measurement_final.json` | Output of `tools/final_measurement.py`: set assignment, agreement, error rates, corrected accuracies and bounds. |
| `tools/` | `final_measurement.py` (applies the set rule and calls the frozen `analysis/r1/measurement_check.py` of the frozen tree), `sets.py` and `blocks.py` (set and block plans, workbook reading). |

To recompute: place `tools/` next to each other as `audit/20261016_final_analysis/`, `audit/20261013_sets/` and
`audit/20261012_blocks/` of a working copy that contains the frozen tree, then run
`final_measurement.py --export export --rater R3=workbooks/judgments_R3.xlsx@2026-10-16T16:13:05Z --rater R4=...`
with the return times given in `analysis/measurement_final.json`.

## Redactions

The names of invited and participating reviewers, the authors' names and the authors' e-mail address are replaced
in the three rules and in the two plan scripts (for example, a reviewer's name by the reviewer number); nothing
else is changed. The SHA-256 of each original file, before redaction, is listed below so that the originals,
which the authors keep, can be verified later.

Workbook metadata written by the reviewer's spreadsheet program (the name of the saving user and the folder the
file was saved from): `workbooks/judgments_R4.xlsx`: saved-from path and document author fields cleared. Every cell is unchanged.

The analysis output is unchanged except that the local paths of
the two workbooks are replaced by their paths in this archive.

| Path in this archive | Original file | SHA-256 of the original |
|---|---|---|
| `analysis/measurement_final.json` | `measurement_final_20261018.json` | `21b4e6027b25d5d9d5ce81c1b7e9edad7a6052d39f2de65d55e93660bbc34ba5` |
| `export/booklet.html` | `booklet.html` | `952e6d74118a020bc99fed150371dc40b59aaf5f8afc0fe59464c8b3ed8b6a45` |
| `export/export_manifest.json` | `export_manifest.json` | `de4d5e72b7a0fb6833a69870ca8397a5b7790389c4929efde6c07c005c80acf8` |
| `export/items.json` | `items.json` | `9a183df49f1d258ee2a267d76cdb36d4db3b65d3185e6b106251d4471d7ff376` |
| `export/key.json` | `key.json` | `6f1759ad6c36123f872acf192ce9107f143b0af8e7e3e76861a2e6168b9a059f` |
| `reviewer_guide_EN.md` | `04_reviewer_guide_EN.md` | `145d156e8e5a825aaee8e85c0f4da772da01dfe60e6580e6c7c4a183c7df5f79` |
| `rules/1_PAIR_RULE_20261010_redacted.md` | `PAIR_RULE_20261010.md` | `9cbbc4ecf066a0af0c9c630621a4ce855131268e8289dca29b8d5f2dc1c97d19` |
| `rules/2_BLOCK_RULE_20261012_redacted.md` | `BLOCK_RULE_20261012.md` | `ff8a73999af6d9156c1812a458bfca5272ea65ad45699167bcdd13a9055a2d84` |
| `rules/3_SET_RULE_20261013_redacted.md` | `SET_RULE_20261013.md` | `559b166b541943ccbdbd2d68ba4aab2fe1e09aa7d091c86bf2c29a8d4540d4d9` |
| `rules/sets.json` | `sets.json` | `029fe5953b762c74c8e588d86e344299f67b956e640382bb6df28d382e3e472c` |
| `tools/blocks.py` | `blocks.py` | `447b11f9d018ac302fbc8b206dbe743582cc3f7c6bc66490ade163e8fff3bca7` |
| `tools/final_measurement.py` | `final_measurement.py` | `2f187ece2a98eed02aa1e80f1e9d9f895a397a6cef35df616185960c589e75d5` |
| `tools/sets.py` | `sets.py` | `7ed409637dc5e30b1b47fb690b4775cc4ef2b7bb27182b3166a141cddf2c2366` |
| `workbooks/judgments_R3.xlsx` | `judgments_R3_returned_20261016.xlsx` | `5b881a5f91f07c94c1da513a54ed7a4a3584cc942ff3ce87e49512b09fff787d` |
| `workbooks/judgments_R4.xlsx` | `judgments_R4_returned_20261018.xlsx` | `e7faea12535d0330ec7b66a1eadd98bcc2f75adcab4b5ae1f13ffc1f0b546e72` |
