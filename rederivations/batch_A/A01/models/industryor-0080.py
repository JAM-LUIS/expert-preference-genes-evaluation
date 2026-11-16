import pulp
m = pulp.LpProblem("workers", pulp.LpMinimize)
I = lambda n: pulp.LpVariable(n, lowBound=0, cat="Integer")
B = lambda n: pulp.LpVariable(n, cat="Binary")
s1a, g1b = I("t1A_skilled"), I("t1B_groups")      # group = 1 skilled + 2 laborers
s2a, l2b = I("t2A_skilled"), I("t2B_laborers")
g3a, g3b = I("t3A_groups5"), I("t3B_groups")      # 5 laborers ; 1 skilled + 3 laborers
z1a, z1b, z2a, z2b, z3a, z3b = [B(n) for n in ["z1a","z1b","z2a","z2b","z3a","z3b"]]
S, L = I("hired_skilled"), I("hired_laborers")
HS, HL = 42, 36
m += 100*S + 80*L + 500*z1b
m += z1a + z1b == 1; m += z2a + z2b == 1; m += z3a + z3b == 1
m += HS*s1a >= 8400*z1a
m += (HS + 2*HL)*g1b >= 8400*z1b
m += HS*s2a >= 10800*z2a
m += HL*l2b >= 10800*z2b
m += 5*HL*g3a >= 18000*z3a
m += (HS + 3*HL)*g3b >= 18000*z3b
# a method not chosen gets no workers
m += s1a <= 400*z1a; m += g1b <= 400*z1b; m += s2a <= 400*z2a
m += l2b <= 800*z2b; m += g3a <= 160*z3a; m += g3b <= 266*z3b
m += S >= s1a + g1b + s2a + g3b
m += L >= 2*g1b + l2b + 5*g3a + 3*g3b
m += S <= 400; m += L <= 800
m += z1b + z3a <= 1           # exclusion
m += g3b >= 20*z3b            # min 20 skilled on task 3 method B
m += S <= 0.6*L               # hiring policy

m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue and abs(v.varValue) > 1e-9:
            print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

