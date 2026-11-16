import pulp

def report(m, relax=False):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]
    sol_status = pulp.LpSolution[m.sol_status]
    print("STATUS:", status)
    print("SOLUTION_STATUS:", sol_status)
    if status == "Optimal" and sol_status == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue is not None and abs(v.varValue) > 1e-9:
                print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
    if relax:
        to_relax = [v for v in m.variables()
                    if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
        for v in to_relax:
            v.cat = pulp.LpContinuous
        m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
        print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
              f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
        for v in to_relax:
            v.cat = pulp.LpInteger
# industryor-0027 reading 2: "operating cost at full capacity" treated as a fixed cost paid for every machine regardless of usage
hours = dict(A1=6000, A2=10000, B1=4000, B2=7000, B3=4000)
full = dict(A1=300, A2=321, B1=250, B2=783, B3=200)
t = {("I","A1"):5, ("I","A2"):7, ("I","B1"):6, ("I","B2"):4, ("I","B3"):7,
     ("II","A1"):10, ("II","A2"):9, ("II","B1"):8,
     ("III","A2"):12, ("III","B2"):11}
raw = dict(I=0.25, II=0.35, III=0.50)
price = dict(I=1.25, II=2.00, III=2.80)
A = ["A1","A2"]; B = ["B1","B2","B3"]
m = pulp.LpProblem("io0027", pulp.LpMaximize)
x = {k: pulp.LpVariable(f"x_{k[0]}_{k[1]}", lowBound=0, cat="Integer") for k in t}
prods = ["I","II","III"]
# units of product = units through A stage = units through B stage
qty = {p: pulp.lpSum(x[k] for k in t if k[0]==p and k[1] in A) for p in prods}
for p in prods:
    m += qty[p] == pulp.lpSum(x[k] for k in t if k[0]==p and k[1] in B)
use = {mc: pulp.lpSum(t[k]*x[k] for k in t if k[1]==mc) for mc in hours}
for mc in hours:
    m += use[mc] <= hours[mc]
m += pulp.lpSum((price[p]-raw[p])*qty[p] for p in prods) - sum(full.values())
report(m, relax=True)
