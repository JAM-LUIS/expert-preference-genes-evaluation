The problem below is an optimization problem written in natural language. Model it as a linear or mixed-integer program and solve that program.

Requirements for the program:
- Produce a single, complete Python 3 program that relies on nothing beyond the standard library and the `pulp` package.
- Create the model with `pulp.LpProblem`, add its objective and its constraints, and solve it with `prob.solve(pulp.PULP_CBC_CMD(msg=0))`.
- The program may not read any file, access the network, or wait for input.
- As its last output the program must print the following two lines exactly, in this order, with nothing printed after them:
STATUS: <pulp.LpStatus[prob.status]>
FINAL_OBJECTIVE: <pulp.value(prob.objective) as a plain number>
- Place the whole program in one ```python fenced block.
