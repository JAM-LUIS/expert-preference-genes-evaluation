# Registration record 5: superseding freeze manifest 3 (scheduler receipt-guard fix)

OSF registration https://osf.io/wcdn6/ (project pnwf2), submitted 2026-10-06T17:58:29Z, immediate public release, approval pending at the time of writing. Supersedes the manifests of record 3 (https://osf.io/8rkf7/) and record 4 (https://osf.io/9qux6/, content `5fec94019e340db4c1e7ec30c172e05caaf87ff0e2631285c20aa9e29bd2705a`).

## Why

The second launch of the formal run (after record 4 became public, 2026-10-06T17:44Z) was refused by the scheduler on every stage: on a sealed stage the freeze gate appends its own record (`freeze_gate.jsonl`) to the model context before the scheduler's input receipt exists, and the receipt guard counted that record as an unattributed artifact. The dev rehearsal could not show this (no gate record on dev). No unit was executed; the refused attempt's files were moved out of the repository.

Fix: `runtime/orgene/schedule.py` excludes the lock and the gate record by name in `_context_has_artifacts`; regression test in `runtime/tests/test_schedule_receipts.py`. Commit `260a943`; full suite 1,843 passed, 40 skipped. Manifest 3: 279 files, `complete: true`, content SHA-256 `33cde4dbe644e7af8cba587f615df74d3507240af56edb2dc768c19f3cef984c` (commit `743aa5a`, then the registration id). Everything else is unchanged from records 3 and 4; the 11 files of record 1 remain byte-identical.

| Uploaded file | SHA-256 |
|---|---|
| `FREEZE_MANIFEST.json` | `acedbcfc0dad83020b539868af6edc390018cfe2a03585ab56e81a741e57e3e7` |
