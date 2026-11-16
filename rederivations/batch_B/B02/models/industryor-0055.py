import pulp
courses = ['Calculus','OR','DataStruct','MgmtStat','Simulation','Programming','Forecasting']
cat = {'Calculus':{'M'}, 'OR':{'OR','M'}, 'DataStruct':{'CS','M'}, 'MgmtStat':{'M','OR'},
       'Simulation':{'CS','OR'}, 'Programming':{'CS'}, 'Forecasting':{'OR','M'}}
m = pulp.LpProblem("io0055", pulp.LpMinimize)
x = {c: pulp.LpVariable("x_"+c, cat="Binary") for c in courses}
m += pulp.lpSum(x.values())
for g in ['M','OR','CS']:
    m += pulp.lpSum(x[c] for c in courses if g in cat[c]) >= 2, "req_"+g
m += x['Simulation'] <= x['Programming']
m += x['DataStruct'] <= x['Programming']
m += x['MgmtStat'] <= x['Calculus']
m += x['Forecasting'] <= x['MgmtStat']

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
