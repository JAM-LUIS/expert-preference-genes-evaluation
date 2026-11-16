Formulate the optimization problem below, which is stated in plain language, as a linear or mixed-integer program, and solve it.

How the program must be written:
- Enclose the program in exactly one ```python fenced block.
- It is one complete Python 3 program; apart from the standard library, the only package it uses is `pulp`.
- It must not ask for input, read files, or use the network.
- It builds the model as a `pulp.LpProblem` with the objective and the constraints, and it solves the model by calling `prob.solve(pulp.PULP_CBC_CMD(msg=0))`.
- Its final output is exactly the two lines below, in this order; nothing may be printed after them:
STATUS: <pulp.LpStatus[prob.status]>
FINAL_OBJECTIVE: <pulp.value(prob.objective) as a plain number>
