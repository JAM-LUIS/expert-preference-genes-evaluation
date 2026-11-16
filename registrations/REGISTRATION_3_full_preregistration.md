# Registration record 3: full preregistration of the held-out evaluation

OSF registration https://osf.io/8rkf7/ (project bjz9f), submitted 2026-10-06T16:07:27Z, immediate public release; approved and public at 2026-10-06T17:31Z. **Superseded for the freeze gate by record 4 (https://osf.io/9qux6/), which adds the committed scheduler plans; everything else in this record stands.** Preceded by record 1 (https://osf.io/x5tqc/, 2026-10-04T16:10:41Z, rule library) and record 2 (https://osf.io/kafzj/, 2026-10-04T16:22:13Z, blind re-derivations and adjudication package).

## What was registered

Repository branch `r1/it1-integ-20261004`, commit `e9320b3` (manifest) on top of the registered rule-library commit `a56f82f`; the 11 files of record 1 are byte-identical in it. Freeze manifest: 273 files, 44 items (37 ok; 7 optional items not present: ORA prompts, AlphaOPT patch/library/taxonomy, and the adjudication-derived exclusions, type labels and reference overrides, which are appended before unsealing), computed items gene_anchors and git_trees ok, neutral-writing scan 274 files 0 hits, `complete: true`, content SHA-256 `6d0004b317140d39c4519713cc8ee9ae7bb189cd9df725ce833f90327893f459`.

| Uploaded file | SHA-256 |
|---|---|
| `FREEZE_MANIFEST.json` | `e8de3c30d09312fd33ca3e8cda8c5eb0e90a559f55cd496c13157bb47d6490aa` |
| `PREREG_R1.md` | `353bbc2e33faa428d468814cf14cc59a9c2ea2d49381a005c522f423802d934a` |
| `MEASUREMENT_CHECK_PLAN.md` | `c29ae48eac841a3287677eeaeca609086b98dc9fa3bf8c01f3796028f64ad010` |
| `test_main_20261006.json` | `c6864b05bc8719945306c3d0555596851f4c3523f6662fa1274e2a7ef44c30a5` |
| `mamo-test.json` | `60512e90006e289fea1241c0f51fdbdcd3e26d3232237cb7e2a3e4c985015530` |
| `industryor-test.json` | `d3cb4c9c3422650a0fed858975aea78065f8775a0329c66fb139ef7fb7557b99` |
| `eng-holdout.json` | `3317081b50a558d1aa37a972caef87aeaf17e318e2ae8334fa9baa6df97f16d5` |

## Scope fixed by this record

- Conditions on test (qwen3:8b): C0, C1, C2, C3, C3E, C3L, C2E, C3T, C3A, C0R-E on the MAMO sensitivity test set (146; the main subset of 80 is contained in it) and the IndustryOR test set (71); variance flow (temperature 0.7, repeats 0-2) on the 100-problem subset; gpt-oss:20b C0, C1, C2, C3, C3E, C3L on the main sets (80 + 71); engineering-source held-out set (8) with C0, C3E, C3L. 4,000 units; the committed matrices are what the driver must reproduce.
- Not run: ORA, AlphaOPT, prompt rewrites, reverse-order rerun. Measured anchors ORLM and LLMOPT: superseding manifest after their own dev rehearsal.
- gpt-oss server refusals: rule `server_refused` (counted as not executed; complete-case report alongside).
- Scores sealed until the adjudication (record 2) is appended.

## Verification done before submission

- Full test suite 1,849 passed, 33 skipped; selftest, isolation, split, subset and census checks pass.
- Dev rehearsal of the whole pipeline through the scheduler (605 units, 2026-10-05): 600 complete; round-0 outputs identical to the fixed-order run 60/60; design checks (shared round 0, C3T trigger and request identity, checklist content, C3A forced review, C2E source, variance repeats, C1 prompt identity) all pass.
- Independent re-simulation of the power table (exact McNemar, 20,000 draws): n=151, effect 3.6 points, harm 1%: 0.33 (table 0.33); effect 7.0: 0.81 / 0.70 at 1% / 2% harm (table 0.81 / 0.70). After plausible exclusions (n about 140) the power at 3.6 points is 0.30 / 0.23.
- Set relations: variance subset within the main test sets; main MAMO set within the sensitivity set; no test id in any dev set.
