# Lexicographic goal programming. x[k,s,c]: people of type k assigned to specialty s in city c.
# Main reading: demand of each (city, specialty) filled exactly (p1 deviations), people of each type <= 1500.
# Reported value: minimum underachievement d3- of goal p3 (8000 people in preferred city).
import sys
import pulp
OVERFILL = len(sys.argv) > 1 and sys.argv[1] == "overfill"
cities = ["D","N"]
dem = {("D",1):1000,("D",2):2000,("D",3):1500,("N",1):2000,("N",2):1000,("N",3):1000}
types = {1:(1500,[1,2],1,"D"),2:(1500,[2,3],2,"D"),3:(1500,[1,3],1,"N"),
         4:(1500,[1,3],3,"N"),5:(1500,[2,3],3,"D"),6:(1500,[3],3,"N")}
keys = [(k,s,c) for k,(n,suit,ps,pc) in types.items() for s in suit for c in cities]
def build():
    m = pulp.LpProblem("ior0029", pulp.LpMinimize)
    x = pulp.LpVariable.dicts("x", keys, lowBound=0, cat="Integer")
    d1m = pulp.LpVariable.dicts("d1m", dem.keys(), lowBound=0)
    d1p = pulp.LpVariable.dicts("d1p", dem.keys(), lowBound=0)
    d2m = pulp.LpVariable("d2m", lowBound=0); d2p = pulp.LpVariable("d2p", lowBound=0)
    d3m = pulp.LpVariable("d3m", lowBound=0); d3p = pulp.LpVariable("d3p", lowBound=0)
    for k,(n,suit,ps,pc) in types.items():
        m += pulp.lpSum(x[k,s,c] for s in suit for c in cities) <= n
    for (c,s),q in dem.items():
        e = pulp.lpSum(x[k,s2,c2] for (k,s2,c2) in keys if s2==s and c2==c)
        m += e + d1m[c,s] - d1p[c,s] == q
        if not OVERFILL:
            m += d1p[c,s] == 0
    m += pulp.lpSum(x[k,s,c] for (k,s,c) in keys if s==types[k][2]) + d2m - d2p == 8000
    m += pulp.lpSum(x[k,s,c] for (k,s,c) in keys if c==types[k][3]) + d3m - d3p == 8000
    return m, x, d1m, d2m, d3m
P1 = lambda d1m: pulp.lpSum(d1m.values())
res = []
m, x, d1m, d2m, d3m = build()
m.setObjective(P1(d1m)); m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s1 = pulp.LpStatus[m.status]; v1 = pulp.value(m.objective)
m += P1(d1m) <= v1 + 1e-6
m.setObjective(d2m); m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s2 = pulp.LpStatus[m.status]; v2 = pulp.value(m.objective)
m += d2m <= v2 + 1e-6
m.setObjective(d3m); m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]; sol_status = pulp.LpSolution[m.sol_status]
print("stage1", s1, v1, "stage2", s2, v2)
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    tot = sum(x[k].varValue for k in keys)
    pc = sum(x[k].varValue for k in keys if k[2]==types[k[0]][3])
    print("total assigned:", tot, "in preferred city:", pc, "assigned not in preferred city:", tot-pc)
    for k in keys:
        if x[k].varValue > 0: print(" ", k, x[k].varValue)
else:
    print("FINAL_OBJECTIVE: None")
