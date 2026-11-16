# Registration record 1: rule library before reference re-derivation results are read

Prepared 2026-10-03T23:26:33+00:00. To be time-stamped publicly (OSF) by the author **before** the comparison of the blind re-derivations with the reference answers is run. It contains hashes only: no problem text, no reference answers, no results.

## Statement

The rule library (iteration it1), its activation lexicon and its check code are final for the held-out evaluation. No rule text, check or activation rule will be changed after this record, whatever the reference re-derivation, adjudication or rehearsal show. The rule records, the lexicon, `predicates_it0.py` and `features.py` stay byte-identical. `genes.py` also holds repair-message code for the comparison conditions; if a defect there has to be fixed after rehearsal, its check functions and their messages stay unchanged and the diff is disclosed with the full preregistration. Templates and the configuration registry are listed for the record and are frozen with the full preregistration.

## Rule library (repository branch r1/it1-dev-20261003)

- commit `a56f82f485446b0395288d716580a43c310ad698`, tree `e9a854425fa51788711b3c670bc23210c0dc829a`

| File | SHA-256 |
|---|---|
| `genes/genes.it1.jsonl` | `731ae37eb6aca75d453252f951e1993d7267371b8e10976a7e7cd0ef6c420cfc` |
| `genes/activation_lexicon.v2.json` | `2df6c5badce9b0e700eea7a2e82d02c6b0ce797109af0c427352138c9e419636` |
| `runtime/orgene/genes.py` | `fb33cae9f92f66e1689eecb06fe1f94da8f03a93d7326295738784e0783ab7da` |
| `runtime/orgene/predicates_it0.py` | `36efdd5297d3a503e600f54c85bdd1b3510816e7874eeacc088fdcc311a8c7de` |
| `runtime/orgene/features.py` | `8c24520da13303bd52afef47bee82eba8ae2b8dd2cc961a44451cab2cb26d095` |
| `conditions/review_checklist.md` | `a595f8c3607f98e81eefe93e9b200f5763c4ba8e1a3ca1d16cc1b4b6656078a9` |
| `conditions/C0R_rules_in_prompt.md` | `ace94e8249a800557338adbe64dc764255f9ffb9c5b8654cf3c8c2c439773c13` |
| `conditions/C0_direct.md` | `f293f4478674f62bff6702810e86bfe0753bf535e21fe9eed1e16255960ca4ae` |
| `conditions/base_system.md` | `cffa26552afe7198b8c7de8b88fd33495075920645beabcd0777b21cda57dfc5` |
| `configs/gene_function_classes.json` | `bb748abd63a9fd7155dd35bc921d1a0c66f4d00c5cfe99865297e01b6949cd5d` |
| `configs/r1_configs.json` | `08fc34a4f7e40cba6292c2683ccb6a77aa66ffcaa446c28959372176be09d7de` |

## Rule-text review and blind re-derivation package (local files)

| File | SHA-256 |
|---|---|
| `stage1/gene_dev/packet_it1/AUTHOR_DECISIONS_it1.json` | `cf349118215e26cf848aa823340a164adb1cceedaee7687797ddc4e991b1838d` |
| `stage1/gene_dev/packet_it1/RUBRIC_it1_clause_review.md` | `85844595c26021679b36cf934bc6a9481100cd983ced7298b7c9f1ea59d76b46` |
| `stage1/gene_dev/packet_it1/review/it1_review_outputs.json` | `ad3dca4cd258d736ccd6fef25e798258fcf5b6c4f1051bc03cf566f2f0d0e9ec` |
| `stage1/gene_dev/packet_it1/REGISTRY.md` | `d92affc5fdf357092893fe27e359a250d97264e21d90d811b03c6b87893f578d` |
| `stage1/annotation_agent/MANIFEST.sha256` | `24d10af3165e7ef665da65587743443f91b6ad639026857cb15ff2b674fe10b5` |
| `stage1/annotation_agent/REDERIVATION_INSTRUCTIONS.md` | `0a0b0b93393b62c2d3499222293613c353da65148461b1cc599ead843f259990` |
| `stage1/annotation_agent/groups.json` | `e34672ab2802e4a6b5367bd2c83e9e52521f46e28bbe4f5d865391bff997b10b` |
| `stage1/annotation_agent/scripts/compare.py` | `59d4bb0b27a2414d3fe85ef5993b4672680179740709d4f96010cec97604e506` |
| `stage1/annotation_agent/scripts/_common.py` | `77fa64bc0911fff0f2f2f84335c2494bbab4e802a1837c5f23adbe9c0e0182c1` |

## Order of events

1. it1 rule texts decided by the author (2026-10-03T18:33Z), before any development replay.
2. Blind re-derivation agents dispatched 2026-10-03 (batch A: Fable 5.1; batch B: Opus 5.5). Their outputs are not read by anyone on the rule-writing side.
3. This record is time-stamped publicly.
4. Only then: comparison with the reference answers, adjudication by the co-author who takes no part in rule drafting or review.

The full preregistration (analysis plan, conditions, templates, scripts) is registered separately before the held-out run.
