"""Independent check of a PGLib-UC schedule (E22): every constraint of MODEL.tex, and the cost recomputed from the
schedule alone.

Isolation: part of the gold material of engineering hold-out cases (data/cases/README_ISOLATION.md).

It does not share code with pglib_uc.py: start-ups and shut-downs are derived from the commitment, the production
cost is the lower convex envelope of the cost points evaluated at the output, and each start-up is charged the
cheapest category the model allows. The reference solve passes when the schedule has no violation and the
recomputed cost equals the solver's objective.
"""


def _lower_envelope(points):
    """Lower convex hull of (x, y) points sorted by x, as a list of vertices."""
    pts = sorted(set(points))
    hull = []
    for p in pts:
        while len(hull) >= 2:
            (x1, y1), (x2, y2) = hull[-2], hull[-1]
            if (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1) <= 0:
                hull.pop()
            else:
                break
        hull.append(p)
    return hull


def _interp(hull, x, tol):
    if x < hull[0][0] - tol or x > hull[-1][0] + tol:
        return None
    x = min(max(x, hull[0][0]), hull[-1][0])
    for (x1, y1), (x2, y2) in zip(hull, hull[1:]):
        if x1 - 1e-12 <= x <= x2 + 1e-12:
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1) if x2 > x1 else min(y1, y2)
    return hull[0][1]


def check(inst, sched, tol=1e-5):
    """(violations, cost). sched = {"u": {g: [0/1]*T}, "p": {g: [...]}, "r": {g: [...]}, "pw": {w: [...]}}; p is the
    output above the minimum. Violations are strings naming the constraint, generator index and period."""
    T = int(inst["time_periods"])
    th, rn = inst["thermal_generators"], inst["renewable_generators"]
    bad = []
    ftol = lambda x: tol * max(1.0, abs(x))  # noqa: E731
    total = 0.0
    for t in range(T):
        supply = sum(sched["p"][g][t] + th[g]["power_output_minimum"] * sched["u"][g][t] for g in th)
        supply += sum(sched["pw"][w][t] for w in rn)
        if abs(supply - inst["demand"][t]) > ftol(inst["demand"][t]):
            bad.append(f"demand t={t + 1}")
        if sum(sched["r"][g][t] for g in th) < inst["reserves"][t] - ftol(inst["reserves"][t]):
            bad.append(f"reserves t={t + 1}")
    for w in rn:
        for t in range(T):
            x = sched["pw"][w][t]
            if x < rn[w]["power_output_minimum"][t] - tol or x > rn[w]["power_output_maximum"][t] + tol:
                bad.append(f"renewable bounds {w} t={t + 1}")
    for k, g in enumerate(th):
        gen = th[g]
        u = [int(x) for x in sched["u"][g]]
        p, r = sched["p"][g], sched["r"][g]
        u0 = gen["unit_on_t0"]
        prev = [u0] + u[:-1]
        v = [max(a - b, 0) for a, b in zip(u, prev)]
        w = [max(b - a, 0) for a, b in zip(u, prev)]
        pmin, pmax = gen["power_output_minimum"], gen["power_output_maximum"]
        span = pmax - pmin
        above0 = u0 * (gen["power_output_t0"] - pmin)
        su = max(pmax - gen["ramp_startup_limit"], 0)
        sd = max(pmax - gen["ramp_shutdown_limit"], 0)
        name = f"g{k}"
        if u0 == 1:
            n = min(gen["time_up_minimum"] - gen["time_up_t0"], T)
            if n >= 1 and any(x != 1 for x in u[:n]):
                bad.append(f"initial up time {name}")
        else:
            n = min(gen["time_down_minimum"] - gen["time_down_t0"], T)
            if n >= 1 and any(x != 0 for x in u[:n]):
                bad.append(f"initial down time {name}")
        if above0 > span * u0 - sd * w[0] + tol:
            bad.append(f"initial shutdown capability {name}")
        if p[0] + r[0] - above0 > gen["ramp_up_limit"] + tol:
            bad.append(f"ramp up t=1 {name}")
        if above0 - p[0] > gen["ramp_down_limit"] + tol:
            bad.append(f"ramp down t=1 {name}")
        UT, DT = min(gen["time_up_minimum"], T), min(gen["time_down_minimum"], T)
        for t in range(T):
            if u[t] < gen["must_run"]:
                bad.append(f"must run {name} t={t + 1}")
            if p[t] < -tol or r[t] < -tol:
                bad.append(f"negative output or reserve {name} t={t + 1}")
            if t + 1 >= UT and sum(v[t - UT + 1:t + 1]) > u[t]:
                bad.append(f"minimum up time {name} t={t + 1}")
            if t + 1 >= DT and sum(w[t - DT + 1:t + 1]) > 1 - u[t]:
                bad.append(f"minimum down time {name} t={t + 1}")
            if p[t] + r[t] > span * u[t] - su * v[t] + tol:
                bad.append(f"startup capability / max output {name} t={t + 1}")
            if t + 1 < T and p[t] + r[t] > span * u[t] - sd * w[t + 1] + tol:
                bad.append(f"shutdown capability {name} t={t + 1}")
            if t > 0 and p[t] + r[t] - p[t - 1] > gen["ramp_up_limit"] + tol:
                bad.append(f"ramp up {name} t={t + 1}")
            if t > 0 and p[t - 1] - p[t] > gen["ramp_down_limit"] + tol:
                bad.append(f"ramp down {name} t={t + 1}")
        pieces = gen["piecewise_production"]
        mw1, c1 = pieces[0]["mw"], pieces[0]["cost"]
        hull = _lower_envelope([(pc["mw"] - mw1, pc["cost"] - c1) for pc in pieces])
        st = gen["startup"]
        for t in range(T):
            if u[t]:
                c = _interp(hull, p[t], tol * max(1.0, span))
                if c is None:
                    bad.append(f"output outside the cost curve {name} t={t + 1}")
                    c = 0.0
                total += c1 + c
            if v[t]:
                allowed = []
                for s in range(len(st)):
                    if s == len(st) - 1:
                        allowed.append(st[s]["cost"])
                        continue
                    lag_s, lag_next = st[s]["lag"], st[s + 1]["lag"]
                    tt = t + 1
                    if tt >= lag_next:
                        ok = any(1 <= tt - i <= T and w[tt - i - 1] for i in range(lag_s, lag_next))
                    else:
                        lo = max(1, lag_next - gen["time_down_t0"] + 1)
                        hi = min(lag_next - 1, T)
                        ok = not (lo <= tt <= hi)
                    if ok:
                        allowed.append(st[s]["cost"])
                total += min(allowed)
    return bad, total
