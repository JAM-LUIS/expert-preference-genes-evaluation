"""Reference MILP for a PGLib-UC instance (E22), written in PuLP for CBC.

Isolation: this is the gold model of engineering hold-out cases. Gene-writing sessions do not open data/eng/
(data/cases/README_ISOLATION.md).

The model is the one the benchmark defines: MODEL.tex of power-grid-lib/pglib-uc (Morales-Espana et al. 2013 tight
formulation, piecewise production costs after Sridhar et al. 2013), in the form of the repository's reference
implementation uc_model.py at commit 39a7f38. Equation numbers (1)-(24) follow uc_model.py. Only the solver options
differ from the repository script (which stops at a 1% gap): the reference value is solved to a relative gap of
at most 1e-7 (cbc.solve).
"""
import pulp


def _pos(x):
    return x if x > 0 else 0


def build(inst):
    """PuLP problem for a parsed instance dict. Returns (prob, index) with index giving the variable dicts."""
    T = int(inst["time_periods"])
    times = range(1, T + 1)
    thermal = inst["thermal_generators"]
    renew = inst["renewable_generators"]
    G = list(thermal)
    W = list(renew)
    gi = {g: f"g{k}" for k, g in enumerate(G)}  # neutral variable names; generator names stay out of the LP file
    wi = {w: f"w{k}" for k, w in enumerate(W)}

    prob = pulp.LpProblem("pglib_uc", pulp.LpMinimize)
    cg, pg, rg, ug, vg, wg, dg, lg = {}, {}, {}, {}, {}, {}, {}, {}
    for g in G:
        gen = thermal[g]
        for t in times:
            k = f"{gi[g]}_{t}"
            cg[g, t] = pulp.LpVariable(f"c_{k}")  # free
            pg[g, t] = pulp.LpVariable(f"p_{k}", lowBound=0)
            rg[g, t] = pulp.LpVariable(f"r_{k}", lowBound=0)
            ug[g, t] = pulp.LpVariable(f"u_{k}", cat=pulp.LpBinary)
            vg[g, t] = pulp.LpVariable(f"v_{k}", cat=pulp.LpBinary)
            wg[g, t] = pulp.LpVariable(f"w_{k}", cat=pulp.LpBinary)
            for s in range(len(gen["startup"])):
                dg[g, s, t] = pulp.LpVariable(f"d_{k}_{s}", cat=pulp.LpBinary)
            for l in range(len(gen["piecewise_production"])):
                lg[g, l, t] = pulp.LpVariable(f"l_{k}_{l}", lowBound=0, upBound=1)
    pw = {}
    for w in W:
        for t in times:
            pw[w, t] = pulp.LpVariable(f"pw_{wi[w]}_{t}", lowBound=renew[w]["power_output_minimum"][t - 1],
                                       upBound=renew[w]["power_output_maximum"][t - 1])  # (24)

    # (1) objective
    prob += pulp.lpSum(
        cg[g, t] + thermal[g]["piecewise_production"][0]["cost"] * ug[g, t]
        + pulp.lpSum(st["cost"] * dg[g, s, t] for s, st in enumerate(thermal[g]["startup"]))
        for g in G for t in times)

    for t in times:
        prob += (pulp.lpSum(pg[g, t] + thermal[g]["power_output_minimum"] * ug[g, t] for g in G)
                 + pulp.lpSum(pw[w, t] for w in W) == inst["demand"][t - 1]), f"demand_{t}"  # (2)
        prob += pulp.lpSum(rg[g, t] for g in G) >= inst["reserves"][t - 1], f"reserves_{t}"  # (3)

    for g in G:
        gen = thermal[g]
        n = gi[g]
        on0 = gen["unit_on_t0"]
        if on0 not in (0, 1):
            raise ValueError(f"unit_on_t0 must be 0 or 1 for generator {n}")
        if on0 == 1 and gen["time_up_minimum"] - gen["time_up_t0"] >= 1:  # (4)
            prob += pulp.lpSum(ug[g, t] - 1 for t in range(1, min(gen["time_up_minimum"] - gen["time_up_t0"], T) + 1)) == 0, f"uptimet0_{n}"
        if on0 == 0 and gen["time_down_minimum"] - gen["time_down_t0"] >= 1:  # (5)
            prob += pulp.lpSum(ug[g, t] for t in range(1, min(gen["time_down_minimum"] - gen["time_down_t0"], T) + 1)) == 0, f"downtimet0_{n}"
        prob += ug[g, 1] - on0 == vg[g, 1] - wg[g, 1], f"logicalt0_{n}"  # (6)
        terms = [dg[g, s, t]
                 for s in range(len(gen["startup"]) - 1)
                 for t in range(max(1, gen["startup"][s + 1]["lag"] - gen["time_down_t0"] + 1),
                                min(gen["startup"][s + 1]["lag"] - 1, T) + 1)]
        if terms:
            prob += pulp.lpSum(terms) == 0, f"startupt0_{n}"  # (7)
        above0 = on0 * (gen["power_output_t0"] - gen["power_output_minimum"])
        prob += pg[g, 1] + rg[g, 1] - above0 <= gen["ramp_up_limit"], f"rampupt0_{n}"  # (8)
        prob += above0 - pg[g, 1] <= gen["ramp_down_limit"], f"rampdownt0_{n}"  # (9)
        coef = _pos(gen["power_output_maximum"] - gen["ramp_shutdown_limit"])
        rhs0 = on0 * (gen["power_output_maximum"] - gen["power_output_minimum"])
        if coef != 0:  # (10); a constant inequality when coef is 0 (uc_model.py skips it then)
            prob += coef * wg[g, 1] <= rhs0 - above0, f"shutdownt0_{n}"
        elif above0 > rhs0:
            raise ValueError(f"generator {n}: constant constraint (10) is violated by the initial condition")

        UT = min(gen["time_up_minimum"], T)
        DT = min(gen["time_down_minimum"], T)
        su = _pos(gen["power_output_maximum"] - gen["ramp_startup_limit"])
        sd = _pos(gen["power_output_maximum"] - gen["ramp_shutdown_limit"])
        span = gen["power_output_maximum"] - gen["power_output_minimum"]
        mw1 = gen["piecewise_production"][0]["mw"]
        c1 = gen["piecewise_production"][0]["cost"]
        for t in times:
            k = f"{n}_{t}"
            if gen["must_run"]:
                prob += ug[g, t] >= gen["must_run"], f"mustrun_{k}"  # (11)
            if t > 1:
                prob += ug[g, t] - ug[g, t - 1] == vg[g, t] - wg[g, t], f"logical_{k}"  # (12)
            if t >= UT:
                prob += pulp.lpSum(vg[g, i] for i in range(t - UT + 1, t + 1)) <= ug[g, t], f"uptime_{k}"  # (13)
            if t >= DT:
                prob += pulp.lpSum(wg[g, i] for i in range(t - DT + 1, t + 1)) <= 1 - ug[g, t], f"downtime_{k}"  # (14)
            prob += vg[g, t] == pulp.lpSum(dg[g, s, t] for s in range(len(gen["startup"]))), f"startup_select_{k}"  # (16)
            prob += pg[g, t] + rg[g, t] <= span * ug[g, t] - su * vg[g, t], f"gen_limit1_{k}"  # (17)
            if t < T:
                prob += pg[g, t] + rg[g, t] <= span * ug[g, t] - sd * wg[g, t + 1], f"gen_limit2_{k}"  # (18)
            if t > 1:
                prob += pg[g, t] + rg[g, t] - pg[g, t - 1] <= gen["ramp_up_limit"], f"ramp_up_{k}"  # (19)
                prob += pg[g, t - 1] - pg[g, t] <= gen["ramp_down_limit"], f"ramp_down_{k}"  # (20)
            pieces = gen["piecewise_production"]
            prob += pg[g, t] == pulp.lpSum((pc["mw"] - mw1) * lg[g, l, t] for l, pc in enumerate(pieces)), f"power_select_{k}"  # (21)
            prob += cg[g, t] == pulp.lpSum((pc["cost"] - c1) * lg[g, l, t] for l, pc in enumerate(pieces)), f"cost_select_{k}"  # (22)
            prob += ug[g, t] == pulp.lpSum(lg[g, l, t] for l in range(len(pieces))), f"on_select_{k}"  # (23)
        for s in range(len(gen["startup"]) - 1):  # (15)
            lag_s, lag_next = gen["startup"][s]["lag"], gen["startup"][s + 1]["lag"]
            for t in times:
                if t >= lag_next:
                    prob += dg[g, s, t] <= pulp.lpSum(wg[g, t - i] for i in range(lag_s, lag_next)), f"startup_allowed_{n}_{s}_{t}"
    index = {"G": G, "W": W, "T": T, "gi": gi, "wi": wi, "p": pg, "r": rg, "u": ug, "v": vg, "w": wg, "d": dg, "pw": pw}
    return prob, index


def schedule_from(index, values):
    """Commitment and output of a solved model as plain dicts (by generator name, period 1..T)."""
    G, W, T = index["G"], index["W"], index["T"]
    rnd = lambda x: 0 if x is None else int(round(x))  # noqa: E731
    val = lambda x: 0.0 if x is None else float(x)  # noqa: E731
    return {
        "u": {g: [rnd(values[index["u"][g, t].name]) for t in range(1, T + 1)] for g in G},
        "p": {g: [val(values[index["p"][g, t].name]) for t in range(1, T + 1)] for g in G},
        "r": {g: [val(values[index["r"][g, t].name]) for t in range(1, T + 1)] for g in G},
        "pw": {w: [val(values[index["pw"][w, t].name]) for t in range(1, T + 1)] for w in W},
    }
