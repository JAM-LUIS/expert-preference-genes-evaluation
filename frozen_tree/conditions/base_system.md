You are given an optimization problem stated in natural language. Formulate it as a linear or mixed-integer program and solve it.

Rules for the program:
- Write one complete Python 3 program that uses only the standard library and the `pulp` package.
- Build the model with `pulp.LpProblem`, add the objective and constraints, and solve with `prob.solve(pulp.PULP_CBC_CMD(msg=0))`.
- The program must not read files, use the network, or ask for input.
- At the very end the program must print exactly these two lines, in this order, and nothing after them:
STATUS: <pulp.LpStatus[prob.status]>
FINAL_OBJECTIVE: <pulp.value(prob.objective) as a plain number>
- Put the program in a single ```python fenced block.
