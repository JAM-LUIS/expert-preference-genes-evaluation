<!-- status: draft (E11, 2026-09-29). Candidate generic entries for extending conditions/C1_generic_expert_pool.md in 1C. -->
<!-- No prompt reads this file. 1C picks entries and appends them, in order, after the bullets of the pool (the proposed R1 pool is C1_pool_r1.draft.md), and adds a one-to-one paraphrase of each to every rewrite in conditions/variants/. -->
<!-- Generic expert guidance only: runtime/tests/test_c1match.py checks that no entry hits the keyword table drawn from the gene library (runtime/orgene/c1match.py). The entries avoid the topics the genes enforce. E11 verification (2026-09-29): one entry dropped (after solving, check that the main decisions make sense), now bullet 12 of C1_pool_r1.draft.md; the clause saying the instances are small dropped from another (it described the benchmark, not modeling practice). -->
# C1 pool: candidate generic entries (draft)

Why: in qwen3 tokens the whole v5 pool reaches only about 0.90 of the C3 system prompt (working library, dev), below
the 0.95 edge of the matching band, so the pool must grow before C1 can be token-matched (E11 record). About 24 tokens
per entry; the list leaves room for a longer final contract and for the API tokenizer.

- Before formulating, describe to yourself in one sentence what a good plan would look like in practical terms.
- List the things the problem talks about (products, sites, periods, people, machines) before writing any expression.
- When the text describes a process step by step, follow the same order in the model so that each step can be matched to the text.
- Keep each piece of data in one place in the program and refer to it by name everywhere else.
- Choose names that a colleague could understand without having the statement at hand.
- When the text gives a total and also its parts, check that the parts add up to the total before relying on either.
- Read every number together with its qualifier ("per week", "each", "in total") and carry the qualifier into the name you give it.
- When two readings of a sentence lead to different models, prefer the reading a practitioner in that field would assume.
- Keep the model as small as the problem allows; quantities that nothing depends on only make the program harder to check.
- If the statement mentions a figure that plays no part in the decision, it may be left out, but say so in a comment.
- Before solving, think about roughly what the best plan should look like, and afterwards compare the solver's plan with that expectation.
- If a result looks surprising, first look for a misread figure or a mixed-up unit before changing the structure of the model.
- When the problem uses words such as fleet, shift, batch, or lot, decide what one unit of that word means before counting with it.
- Where the problem has one-off costs and costs that grow with the amount produced or moved, keep the two kinds apart in the model.
- Separate the program into a data part, a model part, and a reporting part, so that each part can be read on its own.
- If time is involved, fix the length of one period first and express every rate per that period.
- When the problem gives a range for a value, use the end of the range that the sentence actually refers to.
- Check the model mentally on a tiny version of the problem, such as one product and one period, and see whether it behaves sensibly.
- Use the problem's own terms for products, places, and activities in the program, so that the correspondence is easy to audit.
- Prefer a model that is clear and quick to solve over an elaborate one.
- Keep full precision in intermediate calculations and round nothing before the final report.
- When the problem supplies a table, check that its numbers of rows and columns match the lists of items it refers to.
- If the text lists exceptions (except, other than, apart from), write them down explicitly so that none is lost.
- When a goal is described in words, turn the words into one formula and reuse that formula instead of rewriting it in several places.
- Consider who makes the decision in the story and what they control; quantities outside their control are data, not choices.
- If the problem compares alternatives, check that each alternative is represented and can actually be chosen by the model.
- When a statement uses relative words such as "twice as many" or "half of", write down the relation explicitly before modeling it.
- Keep assumptions few and explicit; each one should be something the problem leaves open, not something it already settles.
- Write the program so that changing one number in the data section changes the model consistently everywhere.
- Before finishing, reread the question sentence of the problem and confirm that the value you print answers it.
