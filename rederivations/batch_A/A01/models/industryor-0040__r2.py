import pulp
# x: gross production of steel, engines, electronics, plastic (continuous units)
G = ["steel","engine","elec","plastic"]
price = {"steel":500,"engine":1500,"elec":300,"plastic":1200}
# use[g][h] = units of h consumed per unit of g produced
use = {"steel":{"engine":0.02,"plastic":0.01},
       "engine":{"steel":0.8,"elec":0.15,"plastic":0.11},
       "elec":{"steel":0.01,"engine":0.01,"plastic":0.05},
       "plastic":{"engine":0.03,"steel":0.2,"elec":0.05}}
imp = {"steel":250,"engine":300,"elec":50,"plastic":300}
labor = {"steel":6,"engine":12,"elec":6,"plastic":24}   # person-months
m = pulp.LpProblem("carelland", pulp.LpMaximize)
x = pulp.LpVariable.dicts("x", G, lowBound=0)
net = {h: x[h] - pulp.lpSum(use[g].get(h,0)*x[g] for g in G) for h in G}
m += pulp.lpSum(price[h]*net[h] for h in G) - pulp.lpSum(imp[g]*x[g] for g in G)
m += x["engine"] <= 650000
m += x["plastic"] <= 60000
m += pulp.lpSum(labor[g]*x[g] for g in G) <= 830000
# reading 2: commodities may also be bought on the world market (net output may be negative)

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

