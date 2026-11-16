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
# industryor-0001: 8-week workforce/training/overtime/backlog plan.
# Reading: REQUIRE_CLEAR_BY_WEEK8 = False (True: all booked food delivered by end of week 8)
REQUIRE_CLEAR_BY_WEEK8 = False
W = range(1, 9)
dI = {1:10000,2:10000,3:12000,4:12000,5:16000,6:16000,7:20000,8:20000}
dII = {1:6000,2:7200,3:8400,4:10800,5:10800,6:12000,7:12000,8:12000}
SKILLED = 50
m = pulp.LpProblem("io0001", pulp.LpMinimize)
tch = pulp.LpVariable.dicts("teachers_start", W, lowBound=0, cat="Integer")   # skilled workers starting a 2-week training stint in week t
trn = pulp.LpVariable.dicts("trainees_start", W, lowBound=0, cat="Integer")   # new workers starting training in week t
nor = pulp.LpVariable.dicts("skilled_40h", W, lowBound=0, cat="Integer")
ot  = pulp.LpVariable.dicts("skilled_60h", W, lowBound=0, cat="Integer")
hI  = pulp.LpVariable.dicts("hours_I", W, lowBound=0)
hII = pulp.LpVariable.dicts("hours_II", W, lowBound=0)
invI = pulp.LpVariable.dicts("inv_I", W, lowBound=0); bkI = pulp.LpVariable.dicts("backlog_I", W, lowBound=0)
invII = pulp.LpVariable.dicts("inv_II", W, lowBound=0); bkII = pulp.LpVariable.dicts("backlog_II", W, lowBound=0)
# training must finish by end of week 8 -> start no later than week 7
m += tch[8] == 0
m += trn[8] == 0
m += pulp.lpSum(trn[t] for t in W) == 50
cost = []
for t in W:
    teaching = tch[t] + (tch[t-1] if t > 1 else 0)
    training = trn[t] + (trn[t-1] if t > 1 else 0)
    trained = pulp.lpSum(trn[s] for s in W if s <= t-2)        # finished training, now productive
    m += trn[t] <= 3*tch[t]                                    # each skilled worker trains up to 3 in two weeks
    m += nor[t] + ot[t] + teaching <= SKILLED
    m += hI[t] + hII[t] <= 40*nor[t] + 60*ot[t] + 40*trained
    prevI = (invI[t-1] - bkI[t-1]) if t > 1 else 0
    prevII = (invII[t-1] - bkII[t-1]) if t > 1 else 0
    m += invI[t] - bkI[t] == prevI + 10*hI[t] - dI[t]
    m += invII[t] - bkII[t] == prevII + 6*hII[t] - dII[t]
    # wages: all skilled paid 360 (540 if on 60h), trainee 120 during training, 240 after
    cost.append(360*SKILLED + 180*ot[t] + 120*training + 240*trained + 0.5*bkI[t] + 0.6*bkII[t])
if REQUIRE_CLEAR_BY_WEEK8:
    m += bkI[8] == 0
    m += bkII[8] == 0
m += pulp.lpSum(cost)
report(m, relax=True)
