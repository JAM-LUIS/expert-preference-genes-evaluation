#!/usr/bin/env python3
# industryor-0031: products I,II,III on stage A and B machines; integer pieces.
import pulp
t = {('I','A1'):5, ('I','A2'):7, ('I','B1'):6, ('I','B2'):4, ('I','B3'):7,
     ('II','A1'):10, ('II','A2'):9, ('II','B1'):8,
     ('III','A2'):12, ('III','B2'):11}
cap = {'A1':6000, 'A2':10000, 'B1':4000, 'B2':7000, 'B3':4000}
rate = {'A1':0.05, 'A2':0.03, 'B1':0.06, 'B2':0.11, 'B3':0.05}
raw = {'I':0.25, 'II':0.35, 'III':0.5}
price = {'I':1.25, 'II':2, 'III':2.8}
P = ['I', 'II', 'III']
m = pulp.LpProblem("io0031", pulp.LpMaximize)
x = {k: pulp.LpVariable(f"x_{k[0]}_{k[1]}", lowBound=0, cat="Integer") for k in t}
nprod = {pp: pulp.LpVariable(f"n_{pp}", lowBound=0, cat="Integer") for pp in P}
for pp in P:
    m += pulp.lpSum(x[k] for k in t if k[0]==pp and k[1].startswith('A')) == nprod[pp], f"A_{pp}"
    m += pulp.lpSum(x[k] for k in t if k[0]==pp and k[1].startswith('B')) == nprod[pp], f"B_{pp}"
for e in cap:
    m += pulp.lpSum(t[k]*x[k] for k in t if k[1]==e) <= cap[e], f"cap_{e}"
m += pulp.lpSum((price[pp]-raw[pp])*nprod[pp] for pp in P) - pulp.lpSum(rate[k[1]]*t[k]*x[k] for k in t)
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")
to_relax = [v for v in m.variables()
            if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
for v in to_relax:
    v.cat = pulp.LpContinuous
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
      f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
for v in to_relax:
    v.cat = pulp.LpInteger
