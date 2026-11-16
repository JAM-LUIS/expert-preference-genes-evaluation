import pulp, math
# node: (x, y, demand, a, b, service)
N = {0:(40,50,0,0,1236,0),
 1:(45,68,10,912,967,90), 2:(45,70,30,825,870,90), 3:(42,66,10,65,146,90), 4:(42,68,10,727,782,90),
 5:(42,65,10,15,67,90), 6:(40,69,20,621,702,90), 7:(40,66,20,170,225,90), 8:(38,68,20,255,324,90),
 9:(38,70,10,534,605,90), 10:(35,66,10,357,410,90), 11:(35,69,10,448,505,90), 12:(25,85,20,652,721,90),
 13:(22,75,30,30,92,90), 14:(22,85,10,567,620,90), 15:(20,80,40,384,429,90), 16:(20,85,40,475,528,90),
 17:(18,75,20,99,148,90), 18:(15,75,20,179,254,90), 19:(15,80,10,278,345,90), 20:(30,50,10,10,73,90)}
Q = 200; KMAX = 5
V = list(N); C = [i for i in V if i != 0]
d = {(i,j): math.hypot(N[i][0]-N[j][0], N[i][1]-N[j][1]) for i in V for j in V if i != j}
# assumption: travel time (minutes) = Euclidean distance
A = [(i,j) for (i,j) in d if j == 0 or N[i][3] + N[i][5] + d[i,j] <= N[j][4] + 1e-9]
m = pulp.LpProblem("io0036", pulp.LpMinimize)
x = {a: pulp.LpVariable(f"x_{a[0]}_{a[1]}", cat="Binary") for a in A}
t = {i: pulp.LpVariable(f"t_{i}", lowBound=N[i][3], upBound=N[i][4]) for i in V}
u = {i: pulp.LpVariable(f"u_{i}", lowBound=N[i][2], upBound=Q) for i in C}
m += pulp.lpSum(d[a]*x[a] for a in A)
for i in C:
    m += pulp.lpSum(x[a] for a in A if a[0] == i) == 1
    m += pulp.lpSum(x[a] for a in A if a[1] == i) == 1
m += pulp.lpSum(x[a] for a in A if a[0] == 0) <= KMAX
m += pulp.lpSum(x[a] for a in A if a[0] == 0) == pulp.lpSum(x[a] for a in A if a[1] == 0)
BIGT = 1236 + 90 + 200
for (i,j) in A:
    if j != 0:
        m += t[j] >= t[i] + N[i][5] + d[i,j] - BIGT*(1 - x[i,j])
    else:
        m += t[i] + N[i][5] + d[i,0] <= 1236 + BIGT*(1 - x[i,0])
    if i != 0 and j != 0:
        m += u[j] >= u[i] + N[j][2] - Q*(1 - x[i,j])

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
if status == "Optimal":
    succ = {i:j for (i,j) in A if x[i,j].varValue > 0.5}
    starts = [j for (i,j) in A if i == 0 and x[i,j].varValue > 0.5]
    for s0 in starts:
        r = [0, s0]
        while r[-1] != 0: r.append(succ[r[-1]])
        print("ROUTE", r, "load", sum(N[k][2] for k in r))
