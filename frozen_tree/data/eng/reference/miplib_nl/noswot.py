"""noswot: translation of the instance's solve.py (integer quantities per machine and stage with set-up binaries)."""
import pulp

from . import data_path, load_instance, read_rows


def build(instance_dir):
    inst = load_instance(instance_dir)
    params = inst.get("parameters", {})
    n, m = params.get("n", 5), params.get("m", 5)
    global_limit = params.get("global_limit", float("inf"))
    C = {int(r["machine"]): float(r["limit"]) for r in read_rows(data_path(instance_dir, inst, "machine_capacities"))}
    smin, smax = {}, {}
    for r in read_rows(data_path(instance_dir, inst, "stage_limits")):
        smin[int(r["stage"])] = float(r["min_limit"])
        smax[int(r["stage"])] = float(r["max_limit"])
    task = {(int(r["machine"]), int(r["stage"])): {k: float(r[k]) for k in ("fixed_cost", "unit_cost", "max_qty")}
            for r in read_rows(data_path(instance_dir, inst, "task_parameters"))}
    prob = pulp.LpProblem("noswot", pulp.LpMaximize)
    machines, stages = range(1, n + 1), range(1, m + 1)
    x = {(i, j): pulp.LpVariable(f"x_{i}_{j}", lowBound=0, cat=pulp.LpInteger) for i in machines for j in stages}
    z = {(i, j): pulp.LpVariable(f"z_{i}_{j}", cat=pulp.LpBinary) for i in machines for j in stages}
    prob += pulp.lpSum(x.values())
    for i in machines:
        terms = [(z[i, j], task[i, j]["fixed_cost"]) for j in stages if (i, j) in task] + \
                [(x[i, j], task[i, j]["unit_cost"]) for j in stages if (i, j) in task]
        if i in C:
            prob += pulp.LpAffineExpression(terms) <= C[i], f"Cap_{i}"
    for i in machines:
        for j in stages:
            if (i, j) in task:
                prob += x[i, j] <= int(task[i, j]["max_qty"]) * z[i, j], f"Link_{i}_{j}"
            else:
                prob += x[i, j] == 0, f"NoTaskX_{i}_{j}"
                prob += z[i, j] == 0, f"NoTaskZ_{i}_{j}"
    for j in stages:
        tot = pulp.lpSum(x[i, j] for i in machines)
        if j in smin:
            prob += tot >= smin[j], f"StageMin_{j}"
        if j in smax:
            prob += tot <= smax[j], f"StageMax_{j}"
    if global_limit != float("inf"):
        prob += pulp.lpSum(x.values()) <= global_limit, "GlobalLimit"
    return prob
