"""Deterministic problem text for a PGLib-UC instance (E22): fixed wording plus data tables, nothing else.

Isolation: this file holds the problem wording of engineering hold-out cases. Gene-writing sessions do not open it
(data/cases/README_ISOLATION.md). The text is produced only from TEMPLATE and the instance's structured data; no
person or model writes or edits any part of it (decision of 2026-09-28).

What the wording states is the model of MODEL.tex / uc_model.py in power-grid-lib/pglib-uc (reference/pglib_uc.py
is the same model in PuLP). Presentation choices, each exact for the optimal value:
- units are numbered 1..G in the order of the instance file; their names are not shown;
- renewable units have no cost and appear only in the load balance with independent hourly bounds, so the table
  gives, for every hour, the sum of their minima and the sum of their maxima (computed in decimal from the values
  in the file); a per-unit table would not fit the 32768-token context;
- numbers are printed as in the instance file (shortest round-trip form of each value).
render() refuses an instance for which one of these statements would not be exact (non-convex cost curve,
minimum up or down time below 1, start-up lags not increasing, first cost point not at the minimum output ...).
"""
import hashlib
import json
from decimal import Decimal

TEMPLATE_VERSION = "pglib_uc.v1"

TEMPLATE = """\
A power system operator plans the operation of its generating units for the next {T} hours (hours t = 1, ..., {T}). \
The system has {G} thermal units, numbered 1 to {G}, and {renewable_sentence} \
For every thermal unit and every hour the operator decides whether the unit is on (committed) or off, how much power \
it produces and how much spinning reserve it holds{renewable_decision}. \
The goal is to minimise the total operating cost of the thermal units over the {T} hours, that is, their production \
costs plus their start-up costs, subject to the rules below. Powers are in MW, costs in dollars, times in hours.

Notation for thermal unit g and hour t:
- u(g,t) = 1 if unit g is on in hour t and 0 if it is off.
- An on unit produces its minimum output Pmin(g) plus an amount p(g,t) >= 0 above the minimum; an off unit produces nothing.
- r(g,t) >= 0 is the spinning reserve unit g holds in hour t.
- Unit g starts up in hour t if it is on in hour t and was off in hour t-1, and it shuts down in hour t if it is off in \
hour t and was on in hour t-1. For t = 1, the state in hour t-1 is the state before the horizon, given by unit_on_t0 \
(1 = on, 0 = off).

Rules:
1. Load balance: in every hour t, the total thermal output (the sum over all units of Pmin(g) * u(g,t) + p(g,t)){renewable_balance} \
equals the load of hour t exactly.
2. {renewable_rule}
3. Reserve: in every hour t, the sum of r(g,t) over all thermal units is at least the reserve requirement of hour t.
4. Must-run: a unit with must_run = 1 is on in every hour.
5. Minimum up and down times: let UT(g) = min(time_up_minimum, {T}) and DT(g) = min(time_down_minimum, {T}). For every \
hour t >= UT(g), the number of start-ups of unit g in hours t-UT(g)+1, ..., t is at most u(g,t). For every hour \
t >= DT(g), the number of shut-downs of unit g in hours t-DT(g)+1, ..., t is at most 1 - u(g,t).
6. State before the horizon: a unit with unit_on_t0 = 1 has been on for time_up_t0 hours before hour 1; it must stay on \
in hours 1, ..., min(time_up_minimum - time_up_t0, {T}) (no requirement if this number is below 1). A unit with \
unit_on_t0 = 0 has been off for time_down_t0 hours before hour 1; it must stay off in hours 1, ..., \
min(time_down_minimum - time_down_t0, {T}) (no requirement if this number is below 1).
7. Output limits: let SU(g) = max(Pmax(g) - ramp_startup_limit, 0) and SD(g) = max(Pmax(g) - ramp_shutdown_limit, 0). \
In every hour t, p(g,t) + r(g,t) <= (Pmax(g) - Pmin(g)) * u(g,t) - SU(g) * [1 if unit g starts up in hour t, else 0]. \
In every hour t < {T}, p(g,t) + r(g,t) <= (Pmax(g) - Pmin(g)) * u(g,t) - SD(g) * [1 if unit g shuts down in hour t+1, \
else 0]. A unit with unit_on_t0 = 1 may shut down in hour 1 only if power_output_t0 - Pmin(g) <= Pmax(g) - Pmin(g) - SD(g).
8. Ramping: let p(g,0) = power_output_t0 - Pmin(g) for a unit with unit_on_t0 = 1 and p(g,0) = 0 for a unit with \
unit_on_t0 = 0 (p(g,t) is 0 in every hour in which the unit is off). In every hour t = 1, ..., {T}: \
p(g,t) + r(g,t) - p(g,t-1) <= ramp_up_limit and p(g,t-1) - p(g,t) <= ramp_down_limit.
9. Production cost: in every hour in which unit g is on, it pays the production cost given by its cost curve. The \
curve of a unit is a list of points (mw, cost), with mw increasing from Pmin(g) at point 1 to Pmax(g) at the last \
point; the cost at output Pmin(g) + p(g,t) is the linear interpolation between consecutive points (every curve is \
convex; a unit with a single point has Pmin(g) = Pmax(g)). An off unit pays no production cost.
10. Start-up cost: every start-up of unit g pays the cost of exactly one of its start-up categories s = 1, ..., S(g), \
listed from the hottest (category 1, lowest cost) to the coldest (category S(g)), each with a lag in hours, where \
lag(1) < lag(2) < ... < lag(S(g)). The coldest category can always be used. A category s < S(g) can be used for a \
start-up in hour t only if either (a) t >= lag(s+1) and unit g shut down in one of the hours t-lag(s+1)+1, ..., \
t-lag(s); or (b) t < lag(s+1) and t <= lag(s+1) - time_down_t0 (time_down_t0 is 0 for a unit that was on before the \
horizon).
11. Objective: minimise the sum, over all thermal units and hours, of the production costs and the start-up costs.

Data (comma-separated tables).

Table 1: hours ({T} rows). Columns: hour, load, reserve_requirement{renewable_columns}.
```csv
{table_hours}
```

Table 2: thermal units ({G} rows). Columns: unit, must_run, unit_on_t0, time_up_t0, time_down_t0, power_output_t0, \
Pmin, Pmax, ramp_up_limit, ramp_down_limit, ramp_startup_limit, ramp_shutdown_limit, time_up_minimum, time_down_minimum.
```csv
{table_units}
```

Table 3: production cost curves ({n_points} rows). Columns: unit, point, mw, cost (cost in dollars per hour at output mw).
```csv
{table_points}
```

Table 4: start-up categories ({n_categories} rows). Columns: unit, category, lag, cost (cost in dollars per start-up).
```csv
{table_categories}
```
"""

UNIT_KEYS = ("must_run", "unit_on_t0", "time_up_t0", "time_down_t0", "power_output_t0", "power_output_minimum",
             "power_output_maximum", "ramp_up_limit", "ramp_down_limit", "ramp_startup_limit", "ramp_shutdown_limit",
             "time_up_minimum", "time_down_minimum")


class RenderError(ValueError):
    """The instance does not satisfy a statement the fixed wording makes."""


def num(x):
    """A number as the instance file gives it: ints as ints, floats in shortest round-trip form."""
    if isinstance(x, bool):
        raise RenderError("boolean where a number is expected")
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        return repr(x)
    raise RenderError(f"not a number: {type(x).__name__}")


def dsum(values):
    """Exact decimal sum of the file's numbers, printed without a trailing '.0' change of meaning."""
    s = sum((Decimal(num(v)) for v in values), Decimal(0))
    t = format(s, "f")
    return t


def _check(inst):
    T = inst["time_periods"]
    if not isinstance(T, int) or T < 1:
        raise RenderError("time_periods must be a positive integer")
    for k in ("demand", "reserves"):
        if len(inst[k]) != T:
            raise RenderError(f"{k} does not have time_periods entries")
    for n, (name, g) in enumerate(inst["thermal_generators"].items(), 1):
        where = f"thermal unit {n}"
        if g["unit_on_t0"] not in (0, 1) or g["must_run"] not in (0, 1):
            raise RenderError(f"{where}: unit_on_t0 and must_run must be 0 or 1")
        if g["time_up_minimum"] < 1 or g["time_down_minimum"] < 1:
            raise RenderError(f"{where}: minimum up/down time below 1 (start-up/shut-down wording would not be exact)")
        pts = g["piecewise_production"]
        if not pts:
            raise RenderError(f"{where}: empty cost curve")
        if pts[0]["mw"] != g["power_output_minimum"] or pts[-1]["mw"] != g["power_output_maximum"]:
            raise RenderError(f"{where}: cost curve does not run from Pmin to Pmax")
        if len(pts) == 1 and g["power_output_minimum"] != g["power_output_maximum"]:
            raise RenderError(f"{where}: single cost point but Pmin != Pmax")
        for a, b in zip(pts, pts[1:]):
            if not b["mw"] > a["mw"]:
                raise RenderError(f"{where}: cost points not strictly increasing in mw")
        for a, b, c in zip(pts, pts[1:], pts[2:]):
            s1 = (b["cost"] - a["cost"]) / (b["mw"] - a["mw"])
            s2 = (c["cost"] - b["cost"]) / (c["mw"] - b["mw"])
            if s2 < s1 - 1e-9 * max(1.0, abs(s1)):
                raise RenderError(f"{where}: cost curve is not convex")
        st = g["startup"]
        if not st:
            raise RenderError(f"{where}: no start-up category")
        for a, b in zip(st, st[1:]):
            if not b["lag"] > a["lag"]:
                raise RenderError(f"{where}: start-up lags not increasing")
            if b["cost"] < a["cost"]:
                raise RenderError(f"{where}: a colder start-up category is cheaper (wording says hottest = lowest cost)")
        if g["unit_on_t0"] == 1 and g["time_down_t0"] != 0:
            raise RenderError(f"{where}: on before the horizon but time_down_t0 != 0")
        if g["unit_on_t0"] == 0 and g["power_output_t0"] != 0:
            raise RenderError(f"{where}: off before the horizon but power_output_t0 != 0")
    for w, r in inst["renewable_generators"].items():
        for k in ("power_output_minimum", "power_output_maximum"):
            if len(r[k]) != T:
                raise RenderError(f"renewable unit: {k} does not have time_periods entries")


def render(inst):
    """(text, info). info: counts and the sha256 of the text; the same instance always gives the same bytes."""
    _check(inst)
    T = inst["time_periods"]
    th = inst["thermal_generators"]
    rn = inst["renewable_generators"]
    G = len(th)
    has_rn = len(rn) > 0
    hours = ["hour,load,reserve_requirement" + (",renewable_min,renewable_max" if has_rn else "")]
    for t in range(T):
        row = [str(t + 1), num(inst["demand"][t]), num(inst["reserves"][t])]
        if has_rn:
            row += [dsum(r["power_output_minimum"][t] for r in rn.values()),
                    dsum(r["power_output_maximum"][t] for r in rn.values())]
        hours.append(",".join(row))
    units = ["unit," + ",".join(k.replace("power_output_minimum", "Pmin").replace("power_output_maximum", "Pmax")
                                for k in UNIT_KEYS)]
    points = ["unit,point,mw,cost"]
    cats = ["unit,category,lag,cost"]
    for n, g in enumerate(th.values(), 1):
        units.append(",".join([str(n)] + [num(g[k]) for k in UNIT_KEYS]))
        for l, pt in enumerate(g["piecewise_production"], 1):
            points.append(f"{n},{l},{num(pt['mw'])},{num(pt['cost'])}")
        for s, c in enumerate(g["startup"], 1):
            cats.append(f"{n},{s},{num(c['lag'])},{num(c['cost'])}")
    if has_rn:
        fields = dict(
            renewable_sentence=f"{len(rn)} renewable units whose power has no cost.",
            renewable_decision=", and how much renewable power is used in every hour",
            renewable_balance=" plus the renewable power used in hour t",
            renewable_rule=("Renewable power: in every hour t, the total renewable power used can be any amount "
                            "between renewable_min and renewable_max of that hour (Table 1 gives these totals over all "
                            "renewable units); it has no cost."),
            renewable_columns=", renewable_min, renewable_max")
    else:
        fields = dict(renewable_sentence="no renewable units.", renewable_decision="", renewable_balance="",
                      renewable_rule="Renewable power: there are no renewable units.", renewable_columns="")
    text = TEMPLATE.format(T=T, G=G, table_hours="\n".join(hours), table_units="\n".join(units),
                           table_points="\n".join(points), table_categories="\n".join(cats),
                           n_points=len(points) - 1, n_categories=len(cats) - 1, **fields)
    info = {"template_version": TEMPLATE_VERSION, "template_sha256": hashlib.sha256(TEMPLATE.encode("utf-8")).hexdigest(),
            "time_periods": T, "n_thermal": G, "n_renewable": len(rn), "n_cost_points": len(points) - 1,
            "n_startup_categories": len(cats) - 1, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "text_chars": len(text), "text_bytes": len(text.encode("utf-8"))}
    return text, info


def render_file(path):
    with open(path, encoding="utf-8") as f:
        return render(json.load(f))
