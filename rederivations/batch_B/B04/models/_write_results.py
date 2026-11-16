#!/usr/bin/env python3
import json, re, os
def fo(path):
    t = open(path).read()
    v = re.search(r"FINAL_OBJECTIVE: (\S+)", t).group(1)
    return None if v == "None" else float(v)
def rd(case, suffix, reading):
    f = f"models/{case}{suffix}.py"
    o = fo(f"models/{case}{suffix}.out.txt")
    return {"reading": reading, "objective": o, "status": "Optimal" if o is not None else "Infeasible", "model_file": f}
R = []
def add(case, sense, summary, ptype, rationale, tconf, conf, solver="PULP_CBC_CMD", ia=False, iro=None, issue="NONE",
        note="", readings=None, tal=None, notes="", asked=None):
    o = fo(f"models/{case}.out.txt")
    R.append({"case_id": case, "status": "Optimal" if o is not None else "NotSolved", "objective": o, "sense": sense,
              "model_file": f"models/{case}.py", "output_file": f"models/{case}.out.txt", "solver": solver,
              "model_summary": summary, "integrality_ambiguous": ia, "integer_relaxed_objective": iro,
              "asked_value": asked, "issue": issue, "issue_note": note, "readings": readings or [],
              "confidence": conf, "problem_type": ptype, "type_after_linearization": tal, "type_rationale": rationale,
              "type_confidence": tconf, "notes": notes})
add("industryor-0008","min","Binary x[w,t] assigning 5 workers to 4 tasks; each task exactly one worker, each worker at most one; minimize total hours.",
    "IP","All variables are 0-1 assignment variables; objective and constraints linear.","HIGH","HIGH")
add("industryor-0019","min","Integer order counts from A, B, C (15/10/10 chairs per order); 100<=chairs<=500; binaries link 'A used -> >=10 chairs from B' and 'B used -> C used'; minimize chair cost.",
    "IP","Order counts are integer (stated) and the if-then conditions use 0-1 variables; everything linear.","HIGH","HIGH",
    notes="Cost interpreted as per-chair price times chairs per order. Optimum orders only from C; the logical conditions are inactive.")
add("industryor-0033","min","Binary x per item (dogs as one indivisible 6000 lot, three diamonds separate) assigning to son 1 or 2; minimize |V1-V2| via epigraph variable d>=+-(V1-V2).",
    "NL_LINEARIZABLE","Binary item-allocation variables; objective is an absolute value of a linear expression, minimized, so exactly linearized with a continuous epigraph variable.","MEDIUM","HIGH",tal="MILP",
    notes="Total estate value is odd in thousands so a zero difference is impossible. COPTPY mention ignored; CBC used as required.")
add("industryor-0044","min","Continuous flows supply->station and station->demand, binary station-open z_k; supply <= a_i, demand met exactly, station throughput <= q_k z_k, flow conservation at stations; minimize transport + fixed costs.",
    "MILP","Continuous shipment quantities plus 0-1 fixed-charge station variables; linear.","HIGH","HIGH",
    notes="Demand modeled as equality; >= would give the same optimum since costs are positive.")
add("industryor-0048","min","Preemptive goal programming: integer regular/overtime production of A and B, deviation variables for profit>=10000, contract minimums, Process I =150 h, Process II regular 70 h fully used, overtime <=30 h; priorities solved lexicographically.",
    "MILP","Production units integer, deviation variables continuous; all goal constraints and objectives linear.","MEDIUM","LOW",
    issue="AMBIGUOUS",
    note="The problem only asks to 'formulate the model' for goals p1-p4 without stating a single numeric objective. Reading 1: preemptive goal programming (objective = total unmet deviation, all goals attainable -> 0). Reading 2: maximize weekly profit with all goals as hard constraints.",
    readings=[rd("industryor-0048","","Lexicographic goal programming P1>P2>P3>P4, objective = sum of remaining deviations"),
              rd("industryor-0048","__r2","Maximize profit with goals p1-p4 imposed as hard constraints (regular Process II exactly 70 h, overtime <=30 h)")],
    notes="Overtime units modeled separately with reduced unit profit (280 and 425). In reading 1 the final lexicographic solution is not unique. Reading 2 is the same with integer or continuous production.")
add("industryor-0049","min","Integer area (100 m2 units) for contracts (start month s, length k); monthly coverage equals demand exactly; binaries for contract used/length used; >=2 lengths, not both 1- and 4-month, <=3 distinct contract types; minimize rental fee.",
    "IP","Integer contract quantities and 0-1 logic variables; constraints and objective linear.","MEDIUM","LOW",
    issue="AMBIGUOUS",
    note="(a) 'Each contract must cover consecutive months starting from the beginning of the period': read literally (all contracts start in month 1), exact coverage of 1500/1000/2000/1200 is infeasible. (b) Rule 4 'number of distinct warehouse contracts <= 3': as distinct (start,length) contracts it is infeasible with exact coverage; as distinct contract lengths it is redundant and the model is feasible. Main reading: contracts may start in any month, rule 4 counts distinct lengths.",
    readings=[rd("industryor-0049","","Contracts start any month; rule 4 = at most 3 distinct contract lengths"),
              rd("industryor-0049","__r2","Contracts start any month; rule 4 = at most 3 distinct (start,length) contracts"),
              rd("industryor-0049","__r3","All contracts start in month 1 (literal)")],
    notes="Integer and continuous areas give the same optimum in the main reading.")
add("industryor-0059","max","Continuous kg x[raw,brand]; raw-material monthly limits; ratio constraints on raw A and C content per brand, linearized by multiplying through by brand total; maximize sales minus processing and raw-material cost.",
    "LP","Continuous kg quantities; percentage constraints linear after multiplying by total; linear objective.","HIGH","HIGH",
    notes="Optimum produces no brand C. Reported value contains tiny float noise (6160).",
    asked=None)
add("industryor-0061","min","Integer units on each device x_k <= cap_k*y_k with binary setup y_k; total 2000 units; minimize setup + unit production costs.",
    "IP","Product units are integer and device-enable variables are 0-1; fixed-charge linear model (MILP if units are treated as continuous).","MEDIUM","HIGH",
    notes="Continuous units give the same optimum.")
add("industryor-0074","min","Continuous start times with precedence constraints; T >= all finish times; minimize 1000*T + 5000*(finish B - start A).",
    "LP","Continuous start times and makespan; linear precedence constraints and linear cost.","HIGH","MEDIUM",
    issue="AMBIGUOUS",
    note="'The cost of work per day is 1000 Euros': read as per day of project duration (main) or per activity-day of work (constant over all schedules).",
    readings=[rd("industryor-0074","","Work cost 1000 per day of project duration"),
              rd("industryor-0074","__r2","Work cost 1000 per activity-day (sum of durations, constant)")],
    notes="Durations fixed (no crashing); project starts at time 0.")
add("industryor-0076","max","Continuous x[i,j] bought in quarter i and sold in quarter j>=i (10^4 m3); sales <= max sales; warehouse capacity 20 on all stock held in each quarter; storage cost 70+100u yuan/m3 for u>=1 quarters; maximize profit (10^4 yuan).",
    "LP","Continuous purchase/sale/storage quantities; linear constraints and objective.","HIGH","LOW",
    issue="AMBIGUOUS",
    note="Two unclear points: (1) whether the 200,000 m3 capacity limits all timber in the warehouse in a quarter (including timber bought and sold in the same quarter) or only inventory carried to later quarters; (2) whether storage cost a+b*u applies with u=0 to timber sold in the purchase quarter. Also the table header says 10,000 m2, read as 10,000 m3.",
    readings=[rd("industryor-0076","","Capacity on all stock held each quarter; storage cost only for u>=1"),
              rd("industryor-0076","__r2","Capacity only on inventory carried to later quarters; storage cost only for u>=1"),
              rd("industryor-0076","__r3","Capacity on all stock; storage cost a+b*u also charged for u=0")],
    notes="Objective in units of 10^4 yuan. With the stated storage cost (>=170 yuan/m3 per quarter stored) carrying inventory is never profitable, so the result depends only on the readings above.")
add("industryor-0077","min","Binary x[part,machine] and setup y[machine]; each part on exactly one machine; x1A + x2A = 1; parts 3,4,5 fixed to A,B,C; at most 3 parts on C; minimize processing + setup costs.",
    "IP","All variables 0-1; the if-then condition between parts 1 and 2 becomes the linear equation x1A + x2A = 1.","HIGH","HIGH")
add("industryor-0091","max","Integer units of A and B; 12A+25B <= 1800 minutes; 5B >= 2A; maximize 3A+5B.",
    "IP","Product units integer; linear constraints and objective (LP if units treated as continuous).","MEDIUM","MEDIUM",
    ia=True, iro=fo("models/industryor-0091.out.txt") and float(re.search(r"INTEGERS_RELAXED: Optimal (\S+)", open("models/industryor-0091.out.txt").read()).group(1)),
    notes="Problem says only 'formulate'; objective assumed to be maximize total profit. Integrality uncertain (textbook may intend LP).")
add("industryor-0094","max","Continuous tons of crude A/B in gasoline I/II; crude A purchase split into three price tiers (10000/8000/6000) with ordering binaries because the cost is concave; A available = 500 + purchase, B = 1000; min A share 50%/60%; maximize revenue minus purchase cost.",
    "NL_LINEARIZABLE","Continuous quantities; purchase cost is a concave piecewise-linear function of the purchase amount, linearized exactly with tier variables plus 0-1 ordering variables.","HIGH","MEDIUM",tal="MILP",
    notes="Existing inventories treated as sunk (no cost); no processing costs given.")
add("industryor-0100","max","Binary arc selection forming a simple directed path A->E through C (flow conservation + MTZ); continuous z <= bandwidth of each selected arc (big-M = max bandwidth); maximize z. Cross-checked by enumerating all simple paths.",
    "NL_LINEARIZABLE","Path arcs are 0-1; the objective max of min bandwidth over selected arcs is linearized exactly with an epigraph variable and big-M; result MILP.","MEDIUM","MEDIUM",tal="MILP",
    notes="Table asymmetric; arcs read as directed row->column. Treating links as undirected with the larger of the two directional values gives the same maximum.")
for case, iv in [("mamo_complex_lp-0024", None), ("mamo_complex_lp-0033", None)]:
    t = open(f"models/{case}.out.txt").read()
    intv = float(re.search(r"INTEGER_VERSION: Optimal Optimal Solution Found (\S+)", t).group(1))
    o = fo(f"models/{case}.out.txt")
    R.append({"case_id": case, "status": "Optimal", "objective": o, "sense": "min", "model_file": f"models/{case}.py",
              "output_file": f"models/{case}.out.txt", "solver": "PULP_CBC_CMD",
              "model_summary": "Continuous quantities of each food; protein, carbohydrate and calorie minimums; minimize cost.",
              "integrality_ambiguous": True, "integer_relaxed_objective": o, "asked_value": None, "issue": "NONE",
              "issue_note": "", "readings": [], "confidence": "MEDIUM", "problem_type": "LP", "type_after_linearization": None,
              "type_rationale": "", "type_confidence": None,
              "notes": f"Main model continuous (servings divisible); if food quantities must be integer the optimum is {intv} (printed as INTEGER_VERSION in the output). integer_relaxed_objective equals the main value because the main model is already continuous."})
with open("results.jsonl","w") as fh:
    for r in R: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
# checks
cases = sorted(f[:-4] for f in os.listdir(".") if f.endswith(".txt"))
ids = [r["case_id"] for r in R]
assert sorted(ids) == cases and len(set(ids)) == len(ids), (ids, cases)
for r in R:
    assert os.path.exists(r["model_file"]) and os.path.exists(r["output_file"])
    assert (r["objective"] is None and fo(r["output_file"]) is None) or abs(r["objective"] - fo(r["output_file"])) < 1e-9
    if r["case_id"].startswith("industryor"): assert r["problem_type"] and r["type_rationale"] and r["type_confidence"]
    for rr in r["readings"]: assert os.path.exists(rr["model_file"])
print("OK", len(R))
