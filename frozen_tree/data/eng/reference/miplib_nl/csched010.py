"""csched010: translation of the instance's solve.py (time-indexed cumulative scheduling, total delay).

Translated as written, including its resource-balance loop (the release term `tau + duration == t` never falls in
the loop's range, so started demand is never released). Whether the script reproduces the published optimal value
is exactly what the E22 eligibility rule checks."""
import os

import pulp

from . import read_rows


def build(instance_dir):
    d = os.path.join(instance_dir, "data")
    tasks = []
    info = {}
    for r in read_rows(os.path.join(d, "tasks.csv")):
        j = int(r["task_id"])
        tasks.append(j)
        info[j] = {k: int(float(r[k])) for k in ("duration", "resource_demand", "release_time", "latest_start", "target_start")}
    params = {r["parameter"]: r["value"] for r in read_rows(os.path.join(d, "parameters.csv"))}
    capacity = int(float(params["resource_capacity"]))
    horizon = int(float(params["max_time"]))
    max_deadline = max(v["latest_start"] + v["duration"] - 1 for v in info.values())
    ext = max(horizon, max_deadline + 50)
    times = list(range(0, ext + 1))
    prob = pulp.LpProblem("csched010", pulp.LpMinimize)
    x = {}
    for j in tasks:
        ls = min(info[j]["latest_start"], len(times) - info[j]["duration"] - 1)
        for t in range(info[j]["release_time"], ls + 1):
            x[j, t] = pulp.LpVariable(f"x_{j}_{t}", cat=pulp.LpBinary)
    s = {j: pulp.LpVariable(f"s_{j}", lowBound=info[j]["release_time"], upBound=info[j]["latest_start"], cat=pulp.LpInteger) for j in tasks}
    delay = {j: pulp.LpVariable(f"delay_{j}", lowBound=0) for j in tasks}
    z = {t: pulp.LpVariable(f"z_{t}", lowBound=0, upBound=capacity) for t in times}
    prob += pulp.lpSum(delay.values())
    for j in tasks:
        prob += pulp.lpSum(x[j, t] for t in times if (j, t) in x) == 1, f"task_must_start_{j}"
        prob += s[j] == pulp.lpSum(t * x[j, t] for t in times if (j, t) in x), f"start_time_def_{j}"
        prob += delay[j] >= s[j] - info[j]["target_start"], f"delay_def_{j}"
    prob += z[0] == 0, "initial_resource"
    for t in range(1, len(times)):
        change = []
        for j in tasks:
            dur, res = info[j]["duration"], info[j]["resource_demand"]
            for tau in range(max(0, t - dur + 1), t + 1):
                if (j, tau) in x:
                    if tau == t:
                        change.append(res * x[j, tau])
                    if tau + dur == t:
                        change.append(-res * x[j, tau])
        prob += z[times[t]] - z[times[t - 1]] == pulp.lpSum(change), f"resource_balance_{t}"
    for t in times:
        prob += z[t] <= capacity, f"capacity_limit_{t}"
    return prob
