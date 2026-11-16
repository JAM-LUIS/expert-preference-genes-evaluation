# Reviewer Guide: Checking AI-Generated Optimization Models

Guide version 1.0. The dates, the file names and the e-mail address for questions are in the invitation e-mail.

## 1. What this check is for

The paper evaluates methods that help a large language model turn a text description of an optimization problem into a linear or mixed-integer model, written as a Python program that uses the PuLP package. The main measure is automatic: a program counts as correct if it runs and the optimal objective value it prints matches the reference value published with the benchmark.

This measure can be wrong in two ways:

- **false positive**: the value matches, but the model is wrong (for example, a missing constraint that happens not to matter for these particular numbers);
- **false negative**: the value does not match, but the model is right (for example, the reference value itself is wrong, or the statement allows two reasonable readings).

Your judgments tell us how often each of these happens. They are about the programs, not about you, and nobody's performance is assessed.

The check has three steps:

| Step | What you do | Time |
|---|---|---|
| 1 | Judge every program in the booklet, on your own | about 5 hours (4 to 6) |
| 2 | Discuss the programs on which the two reviewers disagree and agree on a final judgment where you can | up to 30 minutes |
| 3 | Read through the modeling rules used by one of the methods and point out obvious errors | 30 to 45 minutes |

You can work in as many sessions as you like.

## 2. What you receive

- this guide;
- a **booklet** (an HTML file that opens in any web browser): up to 34 problems, each with the problem statement exactly as the AI system received it, followed by one to three programs written for that statement (about 60 to 90 programs in all);
- an **Excel workbook** for step 1; its sheet `judgments` has one row per program, already labelled with the problem ID (for example `P07`) and the program ID (for example `P07-B`);
- after step 1, a separate file for step 2 with the list of disagreements (sheet `consensus`);
- after step 2, the rule list and a separate file for step 3 (sheet `gene_review`).

## 3. Keep it blind and independent

You will not be told which method wrote a program, whether a program ran, whether its value matched the reference, what the reference value is, or which benchmark a problem comes from. Comments and any labels or identifiers that could reveal the method have been removed from the programs; nothing else was changed.

Please:

- judge on your own and do not discuss the materials with the other reviewer until step 2;
- do not look up the problems, their sources or their answers online;
- do not use AI tools (chatbots, coding assistants) to help you judge, and do not paste any of the materials into them;
- keep the materials confidential and delete them when the check is finished.

You do not need to run the programs. If you want to run one, you may.

## 4. What to judge

The AI system was asked to write one complete Python program that builds the model with PuLP, solves it with the CBC solver, and ends by printing two lines, `STATUS: ...` and `FINAL_OBJECTIVE: ...` (the optimal objective value). Judge each program against the problem statement above it, not against the other programs of the same problem.

**The question is whether the program formulates the stated problem correctly.** Judge the formulation, not whether a number might come out right. Code style, naming, efficiency and solver settings do not matter.

### 4.1 Four aspects

For each aspect choose **correct**, **incorrect** or **cannot judge**.

| Aspect | Correct means |
|---|---|
| **Variables** | The decision variables represent the decisions the problem asks for, over the right index sets, with the right type (continuous, integer or binary) and simple bounds (for example, non-negativity). |
| **Objective** | The direction is right (minimize or maximize) and the expression is right: all the relevant cost or profit terms, with the right coefficients, and nothing extra. |
| **Constraints** | Every requirement in the statement is enforced correctly (right terms, signs, directions and right-hand sides), including linking or logical constraints, and nothing is added that the statement does not say. |
| **Data use** | Every number in the model comes from the statement, or is correctly derived from it, and is used in the right place and unit. No number is misread, swapped or invented, and no needed data item is ignored. |

One mistake can make two aspects incorrect. For example, a capacity read as 300 instead of 30 makes both **data use** and **constraints** incorrect. Mark each aspect on its own.

### 4.2 Overall judgment

- **correct**: the program is a correct formulation of the problem as stated. The variables, objective, constraints and data together describe exactly the problem's feasible plans and its goal, so solving the model gives an optimal plan for the stated problem, and the printed value is the model's optimal objective value. An equivalent formulation that differs from the one you would write is correct. A constraint implied by the others, an unused variable, or a big-M constant that is valid but larger than necessary is not an error.
- **incorrect**: any requirement is missing or misstated; something is added that the statement does not say; a number is misread or invented; the objective is wrong; or the printed value is not the model's optimal objective value. This holds **even if the error might not change the optimal value for these particular numbers.**
- **cannot judge**: you cannot decide, for example because the statement cannot be understood or lacks data the model needs, or the program is too garbled to read. Please say why in the notes.

If a statement allows more than one reasonable reading, judge the program by the reading it uses. If that reading is reasonable, the program can be correct. Start the note with `AMBIG:` and describe the reading.

If you notice a bug that would stop the program from running, judge the model that the code tries to build and mention the bug in the notes. You do not need to decide whether a program runs.

If an aspect is incorrect, the overall judgment should be incorrect. If all four aspects are correct but the program is still wrong (for example, it prints a number that is not the model's objective value), choose incorrect and explain in the notes.

### 4.3 Error category (only when the overall judgment is incorrect)

Choose the category of the most serious error, meaning the one that changes the model most. Mention any further errors in the notes.

| Category | Use it when |
|---|---|
| **missing constraint** | A requirement of the problem is not enforced, including a missing bound (such as a capacity or non-negativity) or a missing linking constraint. |
| **objective sense** | The model minimizes where it should maximize, or the other way round. |
| **integrality** | A variable that must take whole-number or yes/no values is continuous, or a variable that may be fractional is forced to be integer. |
| **Big-M** | A big-M (or other logical) constraint is present but its constant is too small, so valid plans are cut off, or it links the wrong variables or has the wrong logic. |
| **data misread** | A number from the statement is misread, swapped, used in the wrong unit or replaced by an invented number, or needed data are ignored. |
| **other** | Any other error, for example a wrong constraint form or direction, an extra constraint the statement does not support, wrong indexing or aggregation, wrong or missing objective terms, or a printed value that is not the model's objective. Describe it in the notes. |

If a linking constraint is missing entirely, choose **missing constraint**. If it is present but its constant is too small, choose **Big-M**.

### 4.4 Notes

Notes are optional for correct programs. For incorrect programs, one sentence saying what is wrong is enough. Notes are needed for **cannot judge**. You may write in English or Chinese.

### 4.5 Reading PuLP (quick reference)

```python
prob = pulp.LpProblem("name", pulp.LpMaximize)      # or pulp.LpMinimize
x = pulp.LpVariable("x", lowBound=0, cat="Integer")  # cat: "Continuous" (default), "Integer", "Binary"
y = pulp.LpVariable.dicts("y", index_list, lowBound=0)  # one variable per index
prob += 3 * x + pulp.lpSum(c[i] * y[i] for i in I)     # the first expression added is the objective
prob += 2 * x + y["a"] <= 10                           # expressions with <=, >= or == are constraints
prob.solve(pulp.PULP_CBC_CMD(msg=0))
```

## 5. Identical programs are shown once

Different methods sometimes produce exactly the same program for a problem (after comments are removed). Such a program appears only once, and your judgment counts for every method that produced it. So a problem may show one, two or three programs. The letters A, B and C are assigned at random and say nothing about the method.

Programs of the same problem are often similar. You may compare them to find the differences quickly, but judge each one against the statement.

## 6. Filling in the workbook

- Sheet `judgments`: one row per program. The grey columns (`problem_id`, `program_id`) are filled in already; do not change them.
- For each program choose from the drop-down lists in `variables`, `objective`, `constraints`, `data_use` and `overall`, and, if the overall judgment is incorrect, in `error_category`. Write any note in `notes`.
- The column `auto_check` shows a warning if a row is incomplete or inconsistent (for example, an incorrect aspect with a correct overall judgment, or an incorrect program without a category). A tick means the row is complete. It is only a reminder and is not used in the analysis.
- You may sort or filter the sheet; the IDs stay with their rows. Please do not add, delete or merge rows or columns.
- Save the file under the same name and return it by e-mail by the date in the invitation. After you return it, please do not change it; steps 2 and 3 use separate files.

The sheet `example` shows the completed rows for the worked example in Section 9.

## 7. Time

Plan on about 4 minutes per program on average, including the time to read the statement. A problem with one program takes about 4 to 5 minutes. A problem with three programs takes about 12 minutes, because the programs of a problem are usually similar. With about 60 to 90 programs in all, step 1 takes about 5 hours (4 to 6 hours). If a problem takes much longer (say, more than 20 minutes), give your best judgment, or choose cannot judge and say why, and move on.

## 8. Step 2: resolving disagreements

After both workbooks are returned, a script lists the programs on which your overall judgments differ, and the programs that you both judged incorrect but placed in different error categories. Both of you receive the same list (sheet `consensus`), with both reviewers' original judgments and notes.

- Discuss these programs with each other by e-mail or in a short call. The authors do not take part and will not comment on any program.
- For each listed program, fill in `final_overall` and, if it is incorrect, `final_error_category`, and add a short `resolution_notes`. If you cannot agree, choose **unresolved**.
- Return one completed `consensus` file together. Your step 1 workbooks stay as they were: agreement between reviewers is computed from them.

## 9. Worked example (made up for this guide; not from any benchmark)

**Problem statement.** A workshop makes chairs and tables. Each chair needs 2 hours of labor and 1 m² of wood; each table needs 3 hours of labor and 4 m² of wood. This week 120 hours of labor and 100 m² of wood are available. Each chair earns a profit of $30 and each table $70. Tables can be made only if the table line is set up this week, which costs $200; when the line is set up, at most 30 tables can be made. Only whole chairs and tables can be made. How many chairs and tables should be made to maximize the week's profit after the setup cost?

**Program EX1-A**

```python
import pulp

products = ["chair", "table"]
labor = {"chair": 2, "table": 3}
wood = {"chair": 1, "table": 4}
profit = {"chair": 30, "table": 70}

prob = pulp.LpProblem("workshop", pulp.LpMaximize)
make = {p: pulp.LpVariable(f"make_{p}", lowBound=0, cat="Integer") for p in products}
setup = pulp.LpVariable("setup_table_line", lowBound=0, upBound=1, cat="Integer")

prob += pulp.lpSum(profit[p] * make[p] for p in products) - 200 * setup
prob += pulp.lpSum(labor[p] * make[p] for p in products) <= 120
prob += pulp.lpSum(wood[p] * make[p] for p in products) <= 100
prob += make["table"] <= 30 * setup
prob += make["chair"] <= 60

prob.solve(pulp.PULP_CBC_CMD(msg=0))
print("STATUS:", pulp.LpStatus[prob.status])
print("FINAL_OBJECTIVE:", pulp.value(prob.objective))
```

**Program EX1-B**

```python
import pulp

prob = pulp.LpProblem("workshop", pulp.LpMaximize)
x = pulp.LpVariable("chairs", lowBound=0, cat="Integer")
y = pulp.LpVariable("tables", lowBound=0, cat="Integer")
z = pulp.LpVariable("setup", cat="Binary")

prob += 30 * x + 70 * y - 200 * z
prob += 2 * x + 3 * y <= 120
prob += x + 4 * y <= 100
prob += y <= 30

prob.solve(pulp.PULP_CBC_CMD(msg=0))
print("STATUS:", pulp.LpStatus[prob.status])
print("FINAL_OBJECTIVE:", pulp.value(prob.objective))
```

**Program EX1-C**: the same as EX1-B, except that the last constraint is

```python
prob += y <= 20 * z
```

**Completed rows** (also in the sheet `example`):

| program_id | variables | objective | constraints | data_use | overall | error_category | notes |
|---|---|---|---|---|---|---|---|
| EX1-A | correct | correct | correct | correct | correct | | `chair <= 60` is implied by the labor limit; setup as an integer in [0, 1] is the same as binary. |
| EX1-B | correct | correct | incorrect | correct | incorrect | missing constraint | Tables are not linked to the setup (`tables <= 30*setup` is missing), so the setup cost can be avoided. |
| EX1-C | correct | correct | incorrect | incorrect | incorrect | Big-M | Uses 20 as the table limit; the statement says 30, so plans with 21 to 30 tables are cut off. |

Why:

- **EX1-A** is written differently from the other two but is a correct formulation. The extra constraint is redundant, not wrong.
- **EX1-B** has the capacity of 30 tables but no link to the setup decision. The solver would set `z = 0`, make tables and never pay the setup cost.
- **EX1-C** links tables to the setup, but with 20 instead of 30. For these particular numbers the best plan makes 16 tables, so EX1-C prints the same optimal value as EX1-A. It is still incorrect, because it forbids plans the statement allows. This is the kind of case the automatic measure cannot catch, and the reason we ask you to judge the formulation rather than guess at the value.

If the statement had not said that only whole tables can be made, both integer and continuous numbers of tables would be reasonable readings. A program using either reading could then be correct, with a note beginning `AMBIG:`.

## 10. Step 3: reading through the modeling rules

After step 2 you will receive the list of modeling rules that one of the evaluated methods uses. Each rule has:

- an ID;
- a statement of good modeling practice;
- its rationale and source;
- what its automatic check looks for (the check's code may be shown);
- whether a failed check triggers a repair or only a warning;
- the repair instruction given to the AI system when the check fails;
- when the rule applies.

A table of where each rule came from is attached.

Please read through the list once and point out **obvious errors only**:

- a statement that is wrong as modeling advice;
- a check that would flag correct models in ordinary cases, or that clearly does not test what the statement says;
- a repair instruction that could lead the AI system to introduce an error;
- a condition for when the rule applies that is clearly wrong.

There is nothing to score, and you do not need to judge the library as a whole or suggest new rules. Each of you does this on your own. Write one row per issue in the sheet `gene_review` of the step 3 file: `gene_id`, `issue_type` from the drop-down list, a short `description` and an optional `suggestion`. If you find nothing, write one row with `issue_type` = none. Finding nothing is a valid result.

Your notes will be listed in the paper's appendix as they are, without your names. The rules used in the experiments will not be changed, and no experiment will be rerun because of them.

## 11. Questions

Reply to the invitation e-mail. To keep the two judgments independent, questions about the procedure are answered with the same message to both reviewers, and questions about how to judge a particular program are answered by pointing to this guide.
