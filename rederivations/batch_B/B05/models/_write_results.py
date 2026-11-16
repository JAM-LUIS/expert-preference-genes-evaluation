import json, re
def obj(f):
    t = open(f).read()
    v = re.search(r"FINAL_OBJECTIVE: (\S+)", t).group(1)
    return None if v == "None" else round(float(v), 6)
def relaxed(f):
    m = re.search(r"INTEGERS_RELAXED: \S+ (\S+)", open(f).read())
    return round(float(m.group(1)), 6) if m else None
def rec(cid, sense, summary, ptype, rationale, tconf, conf, amb=False, issue="NONE", note="", readings=None, asked=None, notes="", tal=None):
    mf = f"models/{cid}.py"; of = f"models/{cid}.out.txt"
    r = {"case_id": cid, "status": "Optimal", "objective": obj(of), "sense": sense, "model_file": mf, "output_file": of,
         "solver": "PULP_CBC_CMD", "model_summary": summary, "integrality_ambiguous": amb,
         "integer_relaxed_objective": relaxed(of) if amb else None, "asked_value": asked, "issue": issue,
         "issue_note": note, "readings": [], "confidence": conf, "problem_type": ptype,
         "type_after_linearization": tal, "type_rationale": rationale, "type_confidence": tconf, "notes": notes}
    if readings:
        r["readings"] = [{"reading": rd, "objective": obj(f"models/{f}.out.txt"), "status": "Optimal", "model_file": f"models/{f}.py"} for rd, f in readings]
    return r
R = []
R.append(rec("industryor-0003", "max", "Monthly workforce, hires, fires, in-house production, overtime hours, outsourcing, sales, end inventory and backorders; maximize sales revenue minus material, outsourcing, holding, backorder, regular wage (paid on all 160 h per worker), overtime, hiring and firing costs; labor-hour, overtime-cap (20 h/worker), inventory/backorder balance and terminal conditions.",
  "MILP", "Workers, units and hires/fires are integer counts while overtime hours are continuous; all constraints and the objective are linear.", "MEDIUM", "MEDIUM", amb=True,
  notes="Units (tables, inventory, outsourcing) treated as integer as well as workers; all-continuous version gives integer_relaxed_objective (then type would be LP). Workforce in month t is after that month's hiring/firing. Revenue counts all units delivered (total equals total demand since backorders must be cleared)."))
R.append(rec("industryor-0005", "max", "Grams of each of 7 foods (continuous) plus selection binaries; maximize fiber; total 600 g, cost <= $15, exactly one protein selected, at least two vegetables selected, amount <= 600*selection.",
  "MILP", "Continuous gram amounts with 0-1 selection variables linked by big-M; linear objective and constraints.", "HIGH", "MEDIUM",
  notes="Proteins have no fiber, so the optimum selects a protein with 0 g (and two extra vegetables selected at 0 g); no minimum purchase amount is given, so selection is only an upper-bound link. Requiring a strictly positive protein amount would make the supremum unattained but equal to the same value."))
R.append(rec("industryor-0023", "max", "Integer weekly output of shirts, short-sleeves, casual clothes plus binary equipment-use variables; maximize (price - variable cost)*quantity minus fixed equipment cost of used lines; labor <= 1500, material <= 1600.",
  "IP", "Integer product quantities and 0-1 fixed-charge variables with linear constraints (MILP if quantities taken as continuous).", "MEDIUM", "HIGH", amb=True))
R.append(rec("industryor-0026", "min", "Integer number of salespeople starting at each of 6 shift times; minimize total; each 4-hour period covered by the two overlapping shifts meets its requirement (cyclic).",
  "IP", "Integer headcounts, linear covering constraints and objective.", "HIGH", "HIGH"))
R.append(rec("industryor-0032", "max", "Hours of each workshop assigned to each component plus number of complete products z; maximize z; workshop hour capacities and each component's total output >= z.",
  "LP", "Continuous hours and product count z (max-min objective via epigraph is already linear); problem asks for an LP formulation.", "HIGH", "HIGH",
  notes="Number of complete products is fractional at the LP optimum; problem explicitly asks for an LP so it is kept continuous."))
R.append(rec("industryor-0050", "max", "Monthly purchase, sales and end inventory Jul-Dec; maximize sales revenue minus purchase cost; stock after start-of-month purchase <= 500, inventory balance from 200 initial units.",
  "LP", "Continuous purchase/sale quantities, linear balance and capacity constraints and linear objective.", "HIGH", "MEDIUM", issue="AMBIGUOUS",
  note="Timing of sales vs purchases ('purchases are made at the beginning of each month'): whether goods bought at the start of a month can be sold in the same month (main) or sales in a month are limited to stock carried in from the previous month.",
  readings=[("Purchased goods can be sold in the same month; stock after purchase <= 500.", "industryor-0050"), ("Sales in month t limited to stock carried into month t (before purchase); stock after purchase <= 500.", "industryor-0050__r2")],
  notes="Integer requirement immaterial (LP optimum integral). Ending inventory has no salvage value."))
R.append(rec("industryor-0051", "min", "Integer regular and contract nurses starting at each of 6 shift times; minimize total pay (8 h * 10 or 15 yuan); cyclic coverage of each period's requirement.",
  "IP", "Integer nurse counts; linear coverage constraints and linear cost.", "HIGH", "MEDIUM", asked=0,
  notes="The question asks whether/how many contract nurses to hire: the optimum hires 0 contract nurses (asked_value), objective is the minimum total pay. No limit on regular nurses is given; the question appears to be a sub-part of a longer exercise."))
R.append(rec("industryor-0053", "min", "Binary take/not-take for 6 children; minimize cost; 3 to 4 children, Ginny taken, Harry excludes Fred and George, George requires Fred and Hermione.",
  "IP", "All 0-1 variables with linear logical constraints.", "HIGH", "HIGH"))
R.append(rec("industryor-0062", "max", "Binary purchase of 4 restaurants; maximize annual revenue; total cost <= 6 million; D excludes A.",
  "IP", "All 0-1 variables, linear budget and conflict constraints.", "HIGH", "HIGH"))
R.append(rec("industryor-0066", "max", "Integer production of high/mid/low-end toys; maximize profit; labor <= 1000 h, inspection <= 500 h, demand caps 50/80/150.",
  "IP", "Integer unit counts with linear constraints and objective.", "HIGH", "HIGH", notes="LP relaxation gives the same value."))
R.append(rec("industryor-0068", "min", "Tons shipped from yards A,B to 3 areas; minimize ton-km; demands met exactly; A ships at least 80 t and B at least 100 t (all received coal distributed).",
  "LP", "Continuous shipment quantities, linear transportation constraints and objective.", "HIGH", "MEDIUM", issue="AMBIGUOUS",
  note="'each receiving no less than 80 tons and 100 tons': main reading = each yard must distribute at least that much (total exactly matches demand 180 t, so supplies are 80/100); alternative = these are only lower bounds on availability with no upper limit, so supply is effectively uncapacitated.",
  readings=[("Yards ship >= 80 / >= 100 t (balanced, so exactly 80/100).", "industryor-0068"), ("80/100 are lower bounds on availability only; no supply limit.", "industryor-0068__r2")],
  notes="Treating 80/100 as upper capacities gives the same value as the main reading since total equals demand."))
R.append(rec("industryor-0078", "min", "Goal programming: total full-time hours x1 and part-time hours x2 with deviation variables; lexicographic P1 min sales shortfall below 5500 pairs (5x1+2x2), P2 min under-employment below 800 / 320 h, P3 min overtime hours above 800 / 320 h.",
  "LP", "Continuous hours and deviation variables; each priority level is a linear program (preemptive goal programming).", "MEDIUM", "LOW", issue="AMBIGUOUS",
  note="The task only asks to 'establish a model'; no single numeric objective is defined. Reported value is the P3 level (overtime hours) after P1 and P2 are fully met; P3 could also be weighted by overtime pay (1.5 vs 0.7). Wages and the 0.3 profit per pair are not used by the goals as stated.",
  readings=[("P3 = unweighted total overtime hours.", "industryor-0078"), ("P3 weighted by overtime pay 1.5 (full-time) / 0.7 (part-time).", "industryor-0078__r2")],
  notes="P1 and P2 deviations both reach 0; overtime is all full-time (172 h) in both readings."))
R.append(rec("industryor-0086", "max", "Packs of Meaties and Yummies; maximize price minus grain, meat and mixing costs; grains <= 400,000 lb, meat <= 300,000 lb, Meaties <= 90,000 packs.",
  "LP", "Continuous pack quantities, linear constraints and linear profit.", "HIGH", "HIGH",
  notes="Unit profits 0.65 and 0.45 per pack; LP optimum is integral."))
R.append(rec("industryor-0090", "max", "Integer numbers of packages A and B; maximize revenue 30A+50B; shirts A+3B <= 200, pants 2A+B <= 100, A >= 20, B >= 10.",
  "IP", "Integer package counts with linear constraints and objective.", "HIGH", "HIGH", notes="LP relaxation gives the same value."))
R.append(rec("industryor-0096", "min", "All feasible cutting patterns enumerated (<=5 pieces, leftover <=100 mm); integer pipes per pattern in 4 rank slots with binary slot assignment; minimize raw pipes plus rank-based extra cost (k/10 pipe value per pipe for the k-th most used pattern); demands met; at most 4 patterns.",
  "NL_LINEARIZABLE", "The direct model has integer pieces-per-pattern times integer pipe counts and frequency-rank costs; with bounded integers it is exactly linearized by pattern enumeration and binary slot assignment (rearrangement makes free slot assignment equal to rank ordering), giving a pure IP.", "MEDIUM", "MEDIUM", tal="IP",
  issue="AMBIGUOUS",
  note="'the most frequently used cutting pattern incurs an extra cost equal to 1/10 of the value of one raw pipe...': main reading = extra cost per raw pipe cut with that pattern; alternative = one-time cost per pattern used.",
  readings=[("Extra k/10 pipe value per pipe cut with the k-th most used pattern.", "industryor-0096"), ("Extra k/10 pipe value charged once per pattern used.", "industryor-0096__r2")],
  notes="Costs expressed in units of one raw pipe's value (value not given numerically). Overproduction allowed (demand >= order)."))
r = rec("mamo_complex_lp-0063", "min", "Binary arc variables for an asymmetric-form 4-city tour with MTZ subtour elimination; minimize travel cost; each city entered and left once.",
  None, "", None, "HIGH")
r["type_rationale"] = ""
R.append(r)
with open("results.jsonl", "w", encoding="utf-8") as f:
    for x in R:
        f.write(json.dumps(x, ensure_ascii=False) + "\n")
# checks
import os
cases = sorted(fn[:-4] for fn in os.listdir(".") if fn.endswith(".txt") and fn != "MANIFEST.sha256")
ids = [x["case_id"] for x in R]
assert sorted(ids) == cases and len(set(ids)) == len(ids), (ids, cases)
for x in R:
    assert os.path.exists(x["model_file"]) and os.path.exists(x["output_file"])
    assert x["objective"] == obj(x["output_file"])
    if x["case_id"].startswith("industryor"):
        assert x["problem_type"] and x["type_rationale"] and x["type_confidence"]
print("OK", len(R))
