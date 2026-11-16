# Registration record 2: blind re-derivations, comparison output and adjudication package before adjudication

Prepared 2026-10-04T16:20Z. To be time-stamped publicly (OSF) before the adjudicator returns any verdict. It contains hashes only: no problem text, no reference answers, no re-derived values, no verdicts.

## Statement

The two blind re-derivation batches, the comparison output and the round-1 adjudication package listed below are final as handed to the adjudicator (code C). No re-derivation result, comparison output or adjudication row will be changed after this record. The adjudicator's verdicts are recorded in the returned sheet; any second audit round is built by `make_adjudication.py --round2` under the rule fixed on 2026-09-29 and is registered or disclosed separately.

Preceding record: Registration record 1 (rule library), https://osf.io/x5tqc/ , registered 2026-10-04T16:10:41Z.

## Blind re-derivations (returned 2026-10-03; batch A: claude-fable-5-1, batch B: claude-opus-5-5)

| File | SHA-256 |
|---|---|
| `stage1/annotation_agent/batch_A/A01/results.jsonl` | `47f1e4a27b3bbe2c2e7a17770ecc5a93281d8c9b4b494420f2df9c9bec832dfa` |
| `stage1/annotation_agent/batch_A/A02/results.jsonl` | `b8354e8e07c4040ab8394a5ea0861cbada0acd95a38e369203751687203fdb63` |
| `stage1/annotation_agent/batch_A/A03/results.jsonl` | `25116cc6eebb37b768a9b0d911bb74c57512a5f243d3b213235074bc2413ca5f` |
| `stage1/annotation_agent/batch_A/A04/results.jsonl` | `a74cf1cdeb370b63e1386df1ab70cd880ef09682ca4708b1938b0b6d2b429f9b` |
| `stage1/annotation_agent/batch_A/A05/results.jsonl` | `d3eb08b6ad9763b3910e53699e72d05b5e632d515b7e6efc2764bba2ae11250d` |
| `stage1/annotation_agent/batch_A/A06/results.jsonl` | `e62bb1f7d3ee7cb839e5135b736bf9d7fff6b02e64a909e58ea4531126240fd5` |
| `stage1/annotation_agent/batch_A/A07/results.jsonl` | `706819de5494f2fefd61ca63c26b5d608dbdd072d057ca8ab7d607521260d3af` |
| `stage1/annotation_agent/batch_A/A08/results.jsonl` | `3b8ed7c377f91fc1cdd117028a65cc3131165f9698bd2da6739077c679f01a7a` |
| `stage1/annotation_agent/batch_B/B01/results.jsonl` | `9aa90771c85ba8dd626267c0cc8476493918f7fabcd58224e1978e6b5684076c` |
| `stage1/annotation_agent/batch_B/B02/results.jsonl` | `30ec87e600948a06a0f0733442b85cad926130a63f9da000791c19a536b1cc33` |
| `stage1/annotation_agent/batch_B/B03/results.jsonl` | `3644eed3ebf19a4e663f1848bee4cb6c96ccb60ea2cccdca10e46420ac4499b2` |
| `stage1/annotation_agent/batch_B/B04/results.jsonl` | `ef7e3a2225fcb16b68020eb73c414b4872582d4d122bc00bd97311619a1c1803` |
| `stage1/annotation_agent/batch_B/B05/results.jsonl` | `cceb66eb53cbd1364cda427e0810bfb89f3f940309ce8a57842e5f1bcaf3b5c1` |
| `stage1/annotation_agent/batch_B/B06/results.jsonl` | `a5652bf097e0d47d2a19fe17f84d4e98851f0b5b947b8f0196acbf88e8f14286` |
| `stage1/annotation_agent/batch_B/B07/results.jsonl` | `52929de81a82fe1921f3536cc5c8f69b1ec3001458c8d8a78c386bd1246fb994` |
| `stage1/annotation_agent/batch_B/B08/results.jsonl` | `f0cb66da301591319f941d45336a04eba4014838695ff1947720c7b4f3ed5a28` |

Model scripts and outputs written by the agents, as one digest per batch. Digest = SHA-256 of the `shasum -a 256` listing of every file under `batch_X/*/models/` (`.DS_Store` excluded), sorted by path with `LC_ALL=C`:

| Batch | Files | Digest |
|---|---|---|
| A | 373 | `a15948d44bfa73795629e76b89b9782d7b971cbdd1634e6a7dc9b335a34662eb` |
| B | 362 | `e68c3bd3db1aaffddabd017b1b4f95d0356844b90bdbaccaf4d136230420f49b` |

Tool-call audit of the re-derivation agents:

| File | SHA-256 |
|---|---|
| `stage1/annotation_agent_scratch_20261003/audit_recompute.py` | `78184958cfffd700f52ceae577a24ec0f5ed64b693844c100c745c12550821c1` |
| `stage1/annotation_agent_scratch_20261003/recompute_audit.json` | `f799cf986301c1ebc17b21db6c53eb9b23a16bf65db76589cca0a4cf863d9d58` |

## Reference answers and comparison (run 2026-10-04 after record 1 was public)

Command: `compare.py --model A=claude-fable-5-1 --model B=claude-opus-5-5` (no `--rerun`), with `compare.py` and `_common.py` as hashed in record 1.

| File | SHA-256 |
|---|---|
| `stage1/annotation_agent_hidden/references.json` | `9825bfe8cc148fc06b7e372115090bbf1663d5d84f5699fa54693f575ec0f3a3` |
| `stage1/annotation_agent_hidden/MANIFEST.sha256` | `476aef0ede6b258130b7d2f6b1d8d58751015b4e16d655f8da069080c9347c55` |
| `stage1/annotation_agent_hidden/comparison/comparison.json` | `7ae2f939b8b092742e931c9a7288d32ac81c90dc0e2eeec8512320c916bd998d` |
| `stage1/annotation_agent_hidden/comparison/summary.json` | `2fbd81f4975ec494bf13e58cf27cb2930dedf42fa1ebb9411c77d42e82c8b40f` |
| `stage1/annotation_agent_hidden/comparison/routing.csv` | `40c9b08cb2b28811c09671a2b3a1e3ca3f84915302b4eb892e3638797609dab2` |
| `stage1/annotation_agent_hidden/comparison/MANIFEST.sha256` | `a1c15b0245fa8ee35e676ef80dbbc3eb842c4772522a8e7e07b0a3b75217e295` |

Counts (no values): 125 cases per batch. Reference check, sampled 66: 29 adjudicate, 10 random audit, 27 automatically correct. Full screening, unsampled 59: 9 flagged, 50 kept. Type label, 100: 73 automatic, 10 random audit, 14 adjudicate, 3 linear-unresolved.

## Round-1 adjudication package (handed to adjudicator C)

| File | SHA-256 |
|---|---|
| `stage1/annotation_agent_hidden/adjudication/MANIFEST.sha256` (417 entries) | `aa24ad6a6b8663245616832b6646ed7f89acff6978250b2b15ea61b11439baa8` |
| `stage1/annotation_agent_hidden/adjudication_C_round1_20261004.zip` | `d5d5a0bfc5d147e17fe3e453645ac907407ab95de7e7aed39347b8f23ec283ee` |

64 rows: 39 sampled reference checks, 9 full-screening findings, 16 type-only rows.

## Scripts used after this record

| File | SHA-256 |
|---|---|
| `stage1/annotation_agent/scripts/make_adjudication.py` | `7b4adaa7ff1f2ec5cc39ff25ff3c208e79c4dd3e090528b3c6ffbba3d667fb45` |
| `stage1/annotation_agent/scripts/export_for_ingest.py` | `cdcaa93ac5c3373bed36c1efa1325cced07b80a1fb9ccac6e0b9eb17d9da2f29` |
| `stage1/annotation_agent/scripts/selfcheck.py` | `df3f4681e3d8d10f93e6bd2652c60e9037b50ea1f39fb7c5c17164b1750af940` |
| `stage1/annotation_agent/README_ISOLATION.md` | `0c7c5de4ad9515f4d3b7e48c95a4c8489f3077950e3e849b102e130709dd7477` |
| `stage1/annotation_agent/case_set.json` | `b4114517396f116d5f61e465d25c6754aff7e27932d74cfc2970ea01dad0f40b` |

## Order of events

1. Rule library frozen and registered publicly (record 1, 2026-10-04T16:10:41Z; public after approval about 16:14Z).
2. Comparison run and round-1 adjudication package built (2026-10-04, about 16:14–16:16Z).
3. This record is time-stamped publicly, before the package's verdicts are returned.
4. Adjudication by C; the filled sheet is then ingested with `export_for_ingest.py`.
