# Registration record 4: superseding freeze manifest (scheduler plans added)

OSF registration https://osf.io/9qux6/ (project 5xs36), submitted 2026-10-06T17:37:26Z, immediate public release, approved and public at 2026-10-06T17:42Z. **Superseded for the freeze gate by record 5 (https://osf.io/wcdn6/).** Supersedes the manifest of record 3 (https://osf.io/8rkf7/, content `6d0004b317140d39c4519713cc8ee9ae7bb189cd9df725ce833f90327893f459`).

## Why

The first launch of the formal run (2026-10-06T17:31Z, right after record 3 became public) was refused by the test gate: the seeded scheduler plan is an input of a sealed stage and must itself be frozen. No unit was executed; the refused attempt's files were moved out of the repository. The plans are deterministic (seeded shuffle of the committed matrices, sorted keys, no timestamps), so they were generated once, committed under `configs/run_plans/`, added to the freeze spec, and the manifest was rebuilt with `--supersede` (chain recorded in the manifest).

Manifest 2: 279 files (the 273 of manifest 1 plus the three plans and their hash receipts), `complete: true`, content SHA-256 `5fec94019e340db4c1e7ec30c172e05caaf87ff0e2631285c20aa9e29bd2705a`. Commits: `a0095a5` (plans, spec, driver), `7c1d394` (manifest 2), then the registration id. The 11 files of record 1 remain byte-identical; the preregistration text, the measurement-check plan and the unit matrices are unchanged from record 3.

| Uploaded file | SHA-256 |
|---|---|
| `FREEZE_MANIFEST.json` | `561dd770d4d6b75d1c249cc11d597f89f6b97d94a3b123a4b4db99ff70c532d5` |
| `test_main_20261006.json` | `19768ab2665f0cbcbd621956af53825cb4e5e00cb759bfd0f2322fae74dd848d` |
| `mamo-test.plan.json` | `2d815a9b2458cc2a372ff5d3ee919a474ebf011a570d06a24c564d4ea271ede8` |
| `industryor-test.plan.json` | `5706da24abb0172e1551a3ef656ab72d3b246a4a78f43e90cd721b14f78eb0ca` |
| `eng-holdout.plan.json` | `34cf49482b650604ae459192da339068c934eb371b45c63febbfc7c821d23e0d` |
| `mamo-test.plan.json.sha256` | `83cd6ae7dc3ed247e7f4a5224248bccc530cac94e18023693a33ae78bbd28aa2` |
| `industryor-test.plan.json.sha256` | `4a6f8fccd9b39b4253dc3c545a2f20b01584cade856f880132bbdd2604ae0279` |
| `eng-holdout.plan.json.sha256` | `df299c7e47c320467225ce36d096669e782d8767a0a3a8e5c6a0ad98b65c37f0` |
