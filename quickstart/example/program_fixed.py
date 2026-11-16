import pulp

kitchens = ["K1", "K2"]
shops = ["S1", "S2", "S3"]
supply = {"K1": 40, "K2": 50}
need = {"S1": 30, "S2": 25, "S3": 20}
cost = {"K1": {"S1": 4, "S2": 6, "S3": 9},
        "K2": {"S1": 5, "S2": 3, "S3": 7}}

prob = pulp.LpProblem("jam_shipping", pulp.LpMinimize)
x = pulp.LpVariable.dicts("ship", [(k, s) for k in kitchens for s in shops], lowBound=0, cat="Integer")

prob += pulp.lpSum(cost[k][s] * x[(k, s)] for k in kitchens for s in shops)
for k in kitchens:
    prob += pulp.lpSum(x[(k, s)] for s in shops) <= supply[k]
for s in shops:
    prob += pulp.lpSum(x[(k, s)] for k in kitchens) >= need[s]

prob.solve(pulp.PULP_CBC_CMD(msg=0))
print(f"STATUS: {pulp.LpStatus[prob.status]}")
print(f"FINAL_OBJECTIVE: {pulp.value(prob.objective)}")
