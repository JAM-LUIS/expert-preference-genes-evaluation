# Prompt rewrites (conditions/variants/)

status: draft (E11, 2026-09-29). Frozen in 1D on the final contract; until then nothing here is used by a registered
configuration.

Default 8 of the engineering plan (6.3) asks for two rewrites each of the C0 base prompt (which C0, C3L and C3E share),
of C1 and of C3, run only on the pre-registered 100-case variance subset, with both models (todo A1-30: prompt
sensitivity in the sense of Sclar et al. 2024).

## How a rewrite is chosen

A rewrite is a directory `conditions/variants/<name>/` that holds only the templates it rewrites; every other template
comes from `conditions/`. A registry configuration selects it with its `variant` field (runtime/orgene/configs.py,
conditions.load_templates). A file that is not a template name is refused, so a misspelt file cannot silently fall
back to the original.

Each rewrite here is one paraphrase family: `rw1` and `rw2` each reword the base rules, the C0 line, the C1 pool and
the C3 template together with the framing lines of the compiled contract (`C3_contract_frame.json`). A configuration
with variant `rwN` therefore reads all of its templates from `rwN`: C0-rwN (and C3L/C3E reusing it) get the rewritten
base; C1-rwN and C3-rwN get the rewritten base as well, so C1 and C3 are compared under the same wording of the shared
rules. If 1D prefers to rewrite only the condition-specific part of C1 or C3, a directory holding only that template
does it without code changes.

## Rewriting principles

1. Same meaning; only the wording and the order change. Nothing is added or left out.
2. Protocol literals stay verbatim, because the extractor, the executor and the scorer depend on them: the fenced
   block markers (```python, ```json), `pulp`, `pulp.LpProblem`, `prob.solve(pulp.PULP_CBC_CMD(msg=0))`, and the two
   lines the program prints last, `STATUS: <pulp.LpStatus[prob.status]>` and `FINAL_OBJECTIVE:
   <pulp.value(prob.objective) as a plain number>`, each on its own line and in this order. The placeholders
   `{SPEC_SCHEMA_SUMMARY}` and `{CONTRACT}` stay; the spec schema summary (field names) is not rewritten.
3. Gene texts are not rewritten: the compiled contract lines are the gene library. The C3 rewrite covers the C3
   template and the four framing lines of the contract (heading, the "required", "forbidden" and "checks" labels).
4. The C1 pool is paraphrased one to one: the same number of bullets in the same order, so that the matched prefix
   covers the same guidance. No bullet and no header line may carry gene wording (keyword table from the gene
   library; runtime/orgene/c1match.py, checked in tests and in every matching report), as for the working pool.
   When 1C replaces or adds entries of the pool, each rewrite gets a paraphrase of every new entry, in the same
   position (the proposed R1 pool and its rw1, rw2 paraphrases: conditions/drafts/C1_pool_r1*.draft.md).
   Modal strength stays: an imperative stays an instruction, a preference ("prefer") stays a preference.
5. Order: rw1 keeps the original order everywhere and changes the wording lightly; rw2 changes the wording more and
   reorders where the order carries no meaning (the list of program rules, where the rule on the two output lines
   moves to the end; clauses within a sentence; the contract before the specification instruction in C3).
6. No configuration, request or case identifier appears in any text (conditions.check_messages refuses it).
7. Length is not preserved. C1-rwN is matched in tokens to C3-rwN on the dev cases (`orgene_cli.py c1-match`, which
   covers every directory here and records it in c1_matching_report.json).
