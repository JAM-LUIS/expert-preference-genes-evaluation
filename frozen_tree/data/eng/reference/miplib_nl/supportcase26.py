"""supportcase26: translation of the instance's solve.py (start times of jobs in groups; big-M separation between
jobs of different groups; minimise the sum of start times)."""
import pulp

from . import data_path, load_instance, read_rows


def build(instance_dir):
    inst = load_instance(instance_dir)
    p = inst["parameters"]["p"]
    S = inst["parameters"]["S"]
    jobs = [{"id": int(r["id"]), "group": int(r["group"]), "arrival_time": float(r["arrival_time"])}
            for r in read_rows(data_path(instance_dir, inst, "jobs"))]
    groups = {}
    for jb in jobs:
        groups.setdefault(jb["group"], []).append(jb)
    for g in groups:
        groups[g].sort(key=lambda x: x["id"])
    M = 100000.0
    prob = pulp.LpProblem("supportcase26", pulp.LpMinimize)
    t = {jb["id"]: pulp.LpVariable(f"t_{jb['id']}", lowBound=0) for jb in jobs}
    for jb in jobs:
        prob += t[jb["id"]] >= jb["arrival_time"], f"Arrival_{jb['id']}"
    for g, gj in groups.items():
        for k in range(1, len(gj)):
            prob += t[gj[k]["id"]] >= t[gj[k - 1]["id"]] + p, f"SameGroup_{gj[k - 1]['id']}_{gj[k]['id']}"
    gids = list(groups)
    for a in range(len(gids)):
        for b in range(a + 1, len(gids)):
            for j1 in groups[gids[a]]:
                for j2 in groups[gids[b]]:
                    i, j = j1["id"], j2["id"]
                    y = pulp.LpVariable(f"y_{i}_{j}", cat=pulp.LpBinary)
                    prob += t[j] >= t[i] + S - M * (1 - y), f"DiffGroup_1_{i}_{j}"
                    prob += t[i] >= t[j] + S - M * y, f"DiffGroup_2_{i}_{j}"
    prob += pulp.lpSum(t.values())
    return prob
