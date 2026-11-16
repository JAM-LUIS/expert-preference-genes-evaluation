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
READING = 2  # 1: Node-8 line = arcs 8->i (irrelevant to 0->8 flow); 2: Node-8 line = capacities i->8 overriding earlier values
cap = {
 0: {1:13,2:19,3:17,4:7,5:7,6:11,7:7,8:7},
 1: {0:9,2:19,3:20,4:10,5:19,6:20,7:19,8:3},
 2: {0:0,1:16,3:0,4:10,5:2,6:14,7:9,8:9},
 3: {0:6,1:0,2:5,4:7,5:18,6:15,7:20,8:7},
 4: {0:18,1:19,2:12,3:0,5:16,6:20,7:10,8:4},
 5: {0:3,1:4,2:8,3:9,4:20,6:7,7:8,8:1},
 6: {0:3,1:14,2:14,3:16,4:1,5:12,7:10,8:10},
 7: {0:9,1:20,2:19,3:4,4:9,5:16,6:1,8:6},
}
node8 = {0:7,1:15,2:14,3:18,4:18,5:11,6:18}
arcs = {(i,j):c for i in cap for j,c in cap[i].items()}
if READING == 1:
    for i,c in node8.items(): arcs[(8,i)] = c
else:
    for i,c in node8.items(): arcs[(i,8)] = c
m = pulp.LpProblem("mamo0128", pulp.LpMaximize)
f = {a: pulp.LpVariable(f"f_{a[0]}_{a[1]}", lowBound=0, upBound=c) for a,c in arcs.items()}
F = pulp.LpVariable("F", lowBound=0)
for n in range(9):
    out_ = pulp.lpSum(f[a] for a in arcs if a[0]==n); in_ = pulp.lpSum(f[a] for a in arcs if a[1]==n)
    m += out_ - in_ == (F if n==0 else (-F if n==8 else 0))
m += F
report(m)
