import json
R = []
def add(**k):
    base = dict(status="Optimal", solver="PULP_CBC_CMD", integrality_ambiguous=False, integer_relaxed_objective=None,
                asked_value=None, issue="NONE", issue_note="", readings=[], problem_type=None,
                type_after_linearization=None, type_rationale="", type_confidence=None, notes="")
    base.update(k)
    cid = base["case_id"]
    base.setdefault("model_file", f"models/{cid}.py"); base.setdefault("output_file", f"models/{cid}.out.txt")
    order = ["case_id","status","objective","sense","model_file","output_file","solver","model_summary",
             "integrality_ambiguous","integer_relaxed_objective","asked_value","issue","issue_note","readings",
             "confidence","problem_type","type_after_linearization","type_rationale","type_confidence","notes"]
    R.append({o: base[o] for o in order})
def rd(reading, obj, f, status="Optimal"):
    return {"reading": reading, "objective": obj, "status": status, "model_file": f}

add(case_id="industryor-0002", objective=175.0, sense="max",
    model_summary="Integer numbers of jets assigned to training in years 1 and 2; maximize pilots trained (5 per training jet per year); training jets limited by jets available.",
    issue="AMBIGUOUS",
    issue_note="The problem gives no explicit objective/constraint structure: unclear whether jets accumulate across years and can be reused for training, whether training jets in year j come only from that year's production a_j, and whether trained pilots must be matched to combat jets (the original combat-vs-training trade-off is not specified).",
    readings=[rd("Fleet accumulates (10, then 25 jets); any jet may train in each year; maximize pilots trained", 175.0, "models/industryor-0002.py"),
              rd("Training jets each year come only from that year's production a_j", 125.0, "models/industryor-0002__r2.py"),
              rd("Fleet accumulates, but year-1 pilots must each fly a combat jet in year 2, reducing training jets in year 2", 125.0, "models/industryor-0002__r3.py")],
    confidence="LOW", problem_type="IP",
    type_rationale="Decision variables are integer counts of training jets per year; objective and constraints are linear.",
    type_confidence="MEDIUM", notes="Problem appears to be a truncated version of a larger multi-year model; values depend strongly on interpretation.")

add(case_id="industryor-0007", objective=468510.0, sense="min",
    model_summary="Integer containers x_ij and integer trucks y_ij per warehouse-port lane; minimize 30*distance*trucks; supply limits, port demands, x_ij <= 2*y_ij.",
    issue="AMBIGUOUS",
    issue_note="'The cost to transport each container is proportional to the distance traveled by the trucks, with a rate of 30 euros per kilometer. Each truck can carry up to 2 containers.' Can be read as cost per truck-km (trucks carry 2 containers) or as 30 EUR/km per container.",
    readings=[rd("30 EUR per truck-km, trucks carry up to 2 containers (integer trucks per lane)", 468510.0, "models/industryor-0007.py"),
              rd("30 EUR per km per container", 904590.0, "models/industryor-0007__r2.py")],
    confidence="MEDIUM", problem_type="IP",
    type_rationale="Containers and trucks per lane are integer counts; costs and constraints are linear (truck count via 2*y >= x, a ceiling-type linear formulation).",
    type_confidence="MEDIUM", notes="Total supply 124 exceeds demand 114; demand as >= and supply as <=. Request to use COPTPY ignored (CBC used as instructed).")

add(case_id="industryor-0012", objective=43200.0, sense="min",
    model_summary="Integer production x_i, binary setup y_i, and integer allocation s_ij of type i to demand j (i>=j); minimize variable cost plus 1200 per activated equipment; demands met, allocations within production, x_i <= M*y_i.",
    confidence="HIGH", problem_type="IP",
    integrality_ambiguous=True, integer_relaxed_objective=43200.0,
    type_rationale="Production/allocation quantities are integer container counts with 0-1 setup variables; fixed-charge logic via binaries, all linear.",
    type_confidence="MEDIUM", notes="Integer vs continuous quantities give the same optimum; if quantities were continuous the type would be MILP.")

add(case_id="industryor-0017", objective=0.5765928623157908, sense="max", solver="enumeration",
    model_summary="Integer numbers of heavy and light bombs sent to each of 4 parts; maximize probability that at least 2 parts are destroyed; bomb stock (28 heavy, 12 light) and total fuel (<=10000 L) limits, fuel per trip = loaded leg + empty return + 100 L.",
    confidence="MEDIUM", problem_type="NL_LINEARIZABLE", type_after_linearization="IP",
    type_rationale="Decision variables are bounded integer bomb counts; the success probability (products of powers of survival probabilities, at-least-2-of-4 combination) is nonlinear but a function of bounded integers, so it can be linearized exactly by value enumeration with 0-1 variables and products of binaries.",
    type_confidence="LOW",
    notes="Global optimum by complete enumeration of all integer allocations (heavy sum<=28, light sum<=12) satisfying fuel. Fuel interpretation: d/2 or d/3 L outbound loaded, d/4 L return empty, 100 L per trip for takeoff+landing. Parts and bombs assumed independent. Optimal plan: 11 heavy on part 2, light 3/6/3 on parts 1/3/4.")

add(case_id="industryor-0024", objective=1000.0, sense="min",
    model_summary="Integer trips per vehicle type plus binaries for van/EV use; minimize total pollution; at most one of van/EV, pollution <= 2000, >= 10 truck trips, capacity >= 1800 units.",
    confidence="HIGH", problem_type="IP",
    type_rationale="Trip counts are integers and the either-or van/EV condition uses 0-1 variables with linear big-M constraints; objective linear.",
    type_confidence="HIGH", notes="Optimal uses 10 truck trips plus EV trips (zero pollution); number of EV trips is non-unique.")

add(case_id="industryor-0029", objective=2500.0, sense="min",
    model_summary="Integer people x[type,specialty,city] (only suitable specialties); lexicographic goal programming: P1 demand of each city-specialty filled, P2 >= 8000 in preferred specialty, P3 >= 8000 in preferred city; minimize deviations in priority order, type supply <= 1500.",
    integrality_ambiguous=True, integer_relaxed_objective=2500.0,
    issue="AMBIGUOUS",
    issue_note="'At least how many people can't meet P3' can mean the underachievement of goal P3 (8000 minus people in preferred city) or the number of recruited people not placed in their preferred city; also unclear whether over-recruitment beyond demand is allowed in P1.",
    readings=[rd("Demand met exactly; value = minimum shortfall d3- of the 8000 preferred-city goal", 2500.0, "models/industryor-0029.py"),
              rd("Same model; value = assigned people not in their preferred city", 3000.0, "models/industryor-0029__r2.py"),
              rd("Over-recruitment above demand allowed (positive deviations in P1); value = d3-", 2000.0, "models/industryor-0029__r3.py")],
    confidence="LOW", problem_type="MILP",
    type_rationale="Assignment counts are integer people while goal deviation variables are continuous; all goal constraints and the lexicographic objectives are linear.",
    type_confidence="LOW",
    notes="P1 fully achievable; P2 shortfall 1000 at lexicographic optimum. LP relaxation gives same values (models/industryor-0029__relaxed.py). If people treated as continuous, type would be LP.")

add(case_id="industryor-0037", objective=11250.0, sense="max",
    model_summary="Integer weekly units of A and B; maximize profit 300A+450B with goals as constraints: profit >= 10000, A >= 10, B >= 15, Process I time = 150, Process II time >= 70 (overtime allowed).",
    confidence="MEDIUM", problem_type="IP",
    type_rationale="Production quantities are integer units; all goal conditions and the profit objective are linear.",
    type_confidence="MEDIUM",
    notes="All goals are simultaneously attainable; a lexicographic goal program with deviation variables followed by profit maximization (models/industryor-0037__r2.py) gives the same 11250. Continuous quantities give the same value. Optimal plan not unique.")

add(case_id="industryor-0039", objective=600.0, sense="min",
    model_summary="Integer trips per method and binaries for method use; minimize pollution; at most 2 methods used, motorcycle trips <= 8, capacity >= 300 units, total trips <= 20.",
    issue="AMBIGUOUS",
    issue_note="'The company can only choose two out of these three transportation methods' may mean at most two methods, or exactly two methods each actually used.",
    readings=[rd("At most two methods used", 600.0, "models/industryor-0039.py"),
              rd("Exactly two methods, each with at least one trip", 640.0, "models/industryor-0039__r2.py")],
    confidence="MEDIUM", problem_type="IP",
    type_rationale="Trip counts are integers and method selection uses 0-1 variables with linear linking constraints; objective linear.",
    type_confidence="HIGH")

add(case_id="industryor-0040", objective=36288566.34, sense="max",
    model_summary="Continuous production x_i of steel, engines, electronics, plastic and net exports e_i = x_i - interindustry use >= 0; maximize GDP = world value of exports minus other imported goods; engine <= 650000, plastic <= 60000, labor <= 830000 person-months.",
    confidence="MEDIUM", problem_type="LP",
    type_rationale="Production and export quantities are continuous; input-output balances, capacity, labor constraints and the GDP objective are linear.",
    type_confidence="HIGH",
    notes="GDP taken as export revenue minus 'other imported goods'; commodities themselves not importable (e_i >= 0). Person-years converted to 12 person-months. AMPL request ignored (CBC used). Only engines are exported at the optimum; labor binding.")

add(case_id="industryor-0073", objective=1600.0, sense="min",
    model_summary="Binary take/not-take per child; minimize total cost; at most 3 and at least 2 children, Bob taken, logical incompatibility and implication constraints.",
    confidence="HIGH", problem_type="IP",
    type_rationale="All decision variables are 0-1 selections; if-then and incompatibility conditions are linear constraints on binaries; objective linear.",
    type_confidence="HIGH", notes="Optimal: Bob and Ella.")

add(case_id="industryor-0087", objective=4170.0, sense="min",
    model_summary="Integer numbers of Type A and Type B trucks; minimize rental cost per km 30A+40B; refrigerated capacity 20A+30B >= 3000, non-refrigerated 40A+30B >= 4000.",
    confidence="HIGH", problem_type="IP",
    type_rationale="Truck counts are integer; capacity constraints and cost per km objective are linear.",
    type_confidence="HIGH",
    notes="Objective is cost per kilometre (distance not given, common positive factor). LP relaxation 4166.67. Optimal 51 Type A, 66 Type B.")

add(case_id="industryor-0088", objective=1.25, sense="max",
    model_summary="Continuous lots of liquid and solid produced; maximize total ending inventory (initial + production - demand); machine time limits 2400 and 2100 minutes, demand must be met.",
    confidence="HIGH", problem_type="LP",
    type_rationale="Production lots are continuous (fractional lots allowed); machine and demand constraints and inventory objective are linear.",
    type_confidence="HIGH", notes="Objective includes the constant (initial inventory minus demand = -50); production 45 liquid, 6.25 solid.")

add(case_id="mamo_complex_lp-0025", objective=15.8617234, sense="min",
    model_summary="Continuous quantities of six foods; minimize cost; protein >= 70 g, carbohydrates >= 187 g, calories >= 2181.",
    integrality_ambiguous=True, integer_relaxed_objective=15.8617234,
    confidence="MEDIUM",
    notes="Main model treats food quantities as continuous (divisible). With integer servings the optimum is 16.0 (models/mamo_complex_lp-0025__r2.py).")

add(case_id="mamo_complex_lp-0101", objective=96.0, sense="max",
    model_summary="Continuous arc flows bounded by capacities; maximize net flow out of station 0 with flow conservation at stations 1-7.",
    confidence="HIGH", notes="Equals total source outgoing capacity.")

add(case_id="mamo_complex_lp-0138", objective=43.0, sense="max",
    model_summary="Continuous arc flows bounded by channel capacities; maximize net flow from center 0 to center 8 with conservation at centers 1-7.",
    confidence="HIGH",
    notes="Row for center 0 lists 8 values for centers 1-8 and row for center 1 lists 8 values for centers 0,2-8; rows 2-8 list 9 values including a zero self-loop. Equals total source outgoing capacity.")

add(case_id="mamo_complex_lp-0154", objective=469200.0, sense="min",
    model_summary="Binary open decisions for 4 centers and continuous shipments; minimize opening plus transport cost; store demands met, shipments within capacity of opened centers.",
    confidence="HIGH", notes="Shipments treated as continuous; solution is integral anyway.")

with open("results.jsonl", "w", encoding="utf-8") as fh:
    for r in R:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print(len(R))
