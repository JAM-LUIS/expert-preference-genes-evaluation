# Things the paper did not say

> *The records do not make a rule right; they make it visible, repeatable and revisable, which is the condition for deciding whether it is right.*
>
> A sentence cut from the last draft of the article. It was cut for style. We still mean it.

A journal article says what it can defend against four reviewers. A repository can say a little more, as long as it says how sure it is. Every item on this page carries a label:

| Label | Meaning |
|---|---|
| **measured** | Read straight from the released test outputs. `python quickstart/beyond_the_paper.py` prints every such number. |
| **post hoc** | A comparison nobody registered before the test, with no correction for looking at many things. A description of one run. |
| **hunch** | What we think is going on. No test behind it. |
| **not done** | Something we wanted and did not do. |
| **from the notebook** | Decisions recorded while the rules were being written, on development problems only. |

Nothing here changes what the article claims. Where this page and the article disagree, the article is the one that was reviewed.

## 1. "Optimal" is not "correct"

**measured.** The small model wrote 76 wrong programs on the first try. 51 of them ran without an error. 39 printed `STATUS: Optimal`.

So half of the wrong models came with the solver's best compliment attached. The solver is not lying. It optimized exactly what it was given, and what it was given was not the problem.

## 2. As a detector, the rules had no false alarm

**measured.** The rules flagged 49 first programs. All 49 were wrong. Of the 49 programs that were right, they flagged none.

Thirty of the flagged programs were caught by a rule about the model or the code, and 14 of those had run cleanly and printed a number. All 14 were wrong. These are the cases the project exists for: nothing crashed, nothing warned, and the answer was wrong.

Now the other half. 27 wrong programs passed every rule. And of the 14 silent ones the rules caught, repair fixed one. The rules can point at the fault. An 8-billion-parameter model mostly cannot act on the pointing.

## 3. Say the rules beforehand and things get worse; check afterwards and they get better

**measured, comparisons post hoc.** Same model, same 125 problems:

| What the model was given | Solved |
|---|---|
| The problem, nothing else | 39.2% |
| An expert role and a page of good modeling advice, before writing | 28.0% |
| The rules themselves, in the prompt, then generic repair | 33.6% |
| Nothing beforehand, then generic repair | 43.2% |
| Nothing beforehand, then the findings of the rules | 47.2% |

The advice prompt lost 24 problems that plain generation solved and gained 10 (p = 0.024). The larger model moved the same way (19 lost, 8 gained, p = 0.052). Delivering the rules as checks instead of as prompt text gained 29 problems and lost 12 (p = 0.012).

The article says that writing the rules into the prompt "did not help". That is the careful version. The plain version is that good advice, given in advance to a small model, cost it eleven points.

## 4. The second repair round fixed nothing

**measured.** Gene repair fixed ten programs. All ten were fixed in the first round. Every program that went to a second round stayed wrong. If you pay per token, stop after one.

## 5. A bigger model beats the rules

**measured, comparison post hoc.** The 20-billion-parameter model, writing once with no rules and no repair, solved 64.0%. The 8-billion-parameter model with gene repair solved 47.2% (38 problems against 17, p = 0.006). On the larger model the two repairs added one problem each.

If you can run the larger model, run the larger model. Rules are for when you cannot, or when you need to show someone why a program was sent back.

## 6. What it costs

**measured.** Per problem, input plus output tokens: direct generation 1,418; generic repair 3,021; gene repair 3,473. Gene repair is 2.4 times the tokens of writing once, for eight points.

## 7. Two rules never fired, and two can only warn

**measured.** Of the 16 rules gene repair uses, two did not fail a single program on the test: `artifact.code_present` (every answer did contain a program) and `code.pulp_api_exists` (written after development programs called functions PuLP does not have; the test programs did not). Two more, `data.no_invented_numbers` and `numeric.bigm_bounded`, are warnings by design. They spoke up 4 and 7 times and never sent a program to repair.

They all stayed in the library because the library was frozen before the test. That is what freezing means: you do not get to delete the rules that turned out to be idle.

The per-rule table is in the output of `quickstart/beyond_the_paper.py`.

## 8. The wall

**measured.** Fourteen problems were solved by nothing: two models, sixteen model-and-condition combinations, zero correct programs.

```text
industryor-0003  industryor-0006  industryor-0017  industryor-0021  industryor-0028
industryor-0031  industryor-0036  industryor-0038  industryor-0059  industryor-0074
industryor-0089  industryor-0100  mamo_complex_lp-0083  mamo_complex_lp-0100
```

Five of them have a checked reference (`references/checked_references.csv`); the other nine keep the answer the benchmark ships. So some of these may be walls because the answer key is wrong, which would also be worth knowing. If your method gets through one, open an issue and show the program.

## 9. The graveyard: rules that did not make it

**from the notebook.** The frozen tree keeps a file of rejected rules (`frozen_tree/genes/CANDIDATES.md`, in Chinese). In English:

- **"Every requirement sentence needs a constraint."** A missing constraint was the largest class of failure on the development problems: 17 of 48 wrong programs. So we wrote the obvious rule, and its check still sits in `frozen_tree/runtime/orgene/genes.py`. It never entered the library. Its precision was 0.60, wrong two times in five, and it reached even that only after the threshold was moved until enough cases fired. A threshold tuned on development problems is a number that was tried until it worked. We dropped the rule and kept the principle.
- **"Things you count must be integers."** Killed by the benchmark. The one development problem that triggered it has a reference answer that equals neither the continuous optimum nor the integer optimum. A rule about integrality cannot be trained against an answer key that is undecided about integrality.
- **Subtour elimination.** Two development problems failed for the lack of it. Refused: it belongs to one family of problems, and the library holds general modeling rules only.
- **A table of smaller ideas**, each dropped with a reason. Balance equations that must sum to zero (the cases were built in loops; no static check could read them). Duplicate constraints (three hits on wrong programs, one on a correct one, and only a tuned threshold would separate them). Numbers in the statement that the program never uses (the distributions of right and wrong programs overlap). A missing lower bound (zero cases). Seven kinds of fault that appeared once each and needed someone to understand the problem.

The pattern in the graveyard: the faults that matter most are the ones a program cannot check without understanding the problem. That is the wall the rules stop at.

## 10. Hunches

**hunch.** None of these is tested.

- **Detection is the product; repair is the bottleneck.** Items 2 and 4 say the same thing from two sides. These rules may be worth more as a linter that a person reads than as a message a small model is asked to obey.
- **A stronger model may want the rules as a contract.** The larger model solved 70.4% when it wrote a specification under the contract of the active rules, against 64.0% writing directly (19 gained, 11 lost, p = 0.20, so this is noise until someone shows otherwise). The small model got nothing from the same condition. Rules up front may need a model strong enough to hold them in mind.
- **About half of IndustryOR may not be gradable by one number.** In the sample of 41 IndustryOR problems drawn for the reference check, 20 were judged ambiguous: more than one reasonable reading, more than one optimum. One adjudicator made these calls, so treat the share as a first estimate. But a field that ranks methods on a benchmark should want to know.

## 11. What we wanted and did not do

**not done.**

- **Both models under all three treatments, as one design.** Small and large model, each writing once, with generic repair and with gene repair, planned as a crossing with enough problems to see an interaction. We have the cells; we did not have the design or the sample.
- **Problems chosen by someone else, after the freeze.** The cleanest answer to "did the authors pick problems their rules like" is a third party picking them once the library is locked.
- **Rules from more than one head.** A structured elicitation from several experts was not run. Every rule here passed through the same two authors.
- **An agent with the same call budget.** The natural rival of a rule layer is a model that reviews its own program freely for the same number of calls. Not run on the same model.
- **The missing-constraint rule, done properly.** The notebook says how: map each constraint back to the sentence it implements and look for sentences nobody implemented. That needs reading, not counting.

If you do one of these, tell us. We would rather be corrected by data than be left alone.
