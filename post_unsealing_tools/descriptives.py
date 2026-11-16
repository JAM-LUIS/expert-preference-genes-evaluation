"""Registered descriptive analyses (preregistration Section 5.2 and Section 9 lists) computed from the unit records
of the formal run, main-analysis set. Outside the frozen tree, written 2026-10-10 after unsealing. Counts only."""
import json, sys, glob, collections, statistics as st, math
sys.path.insert(0, "runtime"); sys.path.insert(0, "analysis/r1"); sys.path.insert(0, ".")
from orgene import analysis_sets as A
from orgene import genes as G
import strata as ST
E = "experiments/test-main-20261006"
main = A.analysis_set("main"); ids = set(main["ids"])
STAGES = (("mamo-test", "mamo_complex_lp"), ("industryor-test", "industryor"))
def units(entry):
    out = collections.defaultdict(dict)
    for stage, _ in STAGES:
        for p in glob.glob(f"{E}/{stage}/by-model/{entry}/units/*.json"):
            if p.endswith("setup.json"): continue
            u = json.load(open(p))
            if u.get("case_id") in ids and int(u.get("repeat", 0)) == 0: out[u["config_id"]][u["case_id"]] = u
    return out
def results(entry, cond):
    out = {}
    for stage, _ in STAGES:
        try:
            for r in map(json.loads, open(f"{E}/{stage}/by-model/{entry}/results.{cond}.jsonl")):
                if r["case_id"] in ids: out[r["case_id"]] = r
        except FileNotFoundError: pass
    return out
ORDER = ["C0", "C1", "C2", "C3", "C3E", "C3L", "C2E", "C3T", "C3A", "C0R-E"]
out = {}
for entry, res_entry in (("qwen3-8b.main", "qwen3-8b.main"), ("gptoss-20b.main", "gptoss-20b.main.server_refused")):
    U = units(entry); print(f"\n===== {entry}")
    for c in [x for x in ORDER if x in U]:
        us = U[c]; R = results(res_entry, c)
        vals = [[r["validated"] for r in u.get("rounds", []) if r.get("validated")] for u in us.values() if u.get("status") == "complete"]
        trunc = sum(any(v.get("done_reason") == "length" for v in vs) for vs in vals)
        ctx = sum(bool(u.get("context_exceeded")) for u in us.values())
        stop = collections.Counter(u.get("stop_reason") for u in us.values())
        gen = [sum((v.get("gen_seconds") or 0) for v in vs) for vs in vals]
        ncor = sum(bool(r["correct"]) for r in R.values())
        tout = sum(bool(((vs[-1].get("exec") or {}).get("timed_out"))) for vs in vals if vs)
        mis = sum(bool((r.get("misreport") or {}).get("any_misreport")) for r in R.values())
        mis_rec = sum(bool((r.get("misreport") or {}).get("recorded")) for r in R.values())
        cat = collections.Counter(r.get("status_category") for r in R.values()); rea = collections.Counter(r.get("reason") for r in R.values())
        row = {"n_units": len(us), "n_complete": len(vals), "truncated_units": trunc, "context_exceeded": ctx, "stop_reasons": dict(stop),
               "gen_seconds_mean": round(st.mean(gen), 1) if gen else None, "gen_seconds_per_correct": round(sum(gen) / ncor, 1) if ncor else None,
               "n_correct": ncor, "exec_timeouts_final": tout, "misreports": mis, "misreport_recorded": mis_rec,
               "status_category": dict(cat), "reason": dict(rea)}
        out[f"{entry}|{c}"] = row
        print(f"{c:6s} units {len(us):3d} trunc {trunc:2d} ctx {ctx} timeouts {tout:2d} misreport {mis:2d}/{mis_rec:3d} gen_s/problem {row['gen_seconds_mean']} gen_s/correct {row['gen_seconds_per_correct']} stop {dict(stop)}")
        print(f"        status {dict(cat)}  reason {dict(rea)}")
# run time and time-outs by scale tertile (qwen, C0 / C3E / C3L)
Uq = units("qwen3-8b.main")
sc, _ = ST.scale_strata(sorted(ids), "n_numeric_literals")
print("\n===== scale tertiles (qwen): mean generation seconds per problem, final exec seconds, exec time-outs")
for c in ("C0", "C3E", "C3L"):
    for t in ("T1", "T2", "T3"):
        cs = [k for k in ids if sc[k] == t and k in Uq[c]]
        g = [sum((r["validated"].get("gen_seconds") or 0) for r in Uq[c][k]["rounds"] if r.get("validated")) for k in cs]
        ex = [((Uq[c][k]["rounds"][-1]["validated"].get("exec") or {}).get("seconds") or 0) for k in cs]
        to = sum(bool((Uq[c][k]["rounds"][-1]["validated"].get("exec") or {}).get("timed_out")) for k in cs)
        out[f"scale|{c}|{t}"] = {"n": len(cs), "gen_seconds_mean": round(st.mean(g), 1), "exec_seconds_mean": round(st.mean(ex), 2), "timeouts": to}
        print(f"{c:4s} {t} n={len(cs):3d} gen {st.mean(g):6.1f}s exec {st.mean(ex):5.2f}s timeouts {to}")
# conflicts and non-convergence (gene repair): a hard failure that appears after a repair round and was not failing before it
print("\n===== repair conflicts and non-convergence (qwen, C3L)")
pairs = collections.Counter(); nconf = 0; noncv = 0; left = collections.Counter()
for k, u in Uq["C3L"].items():
    vs = [r["validated"] for r in u["rounds"] if r.get("validated")]
    conf = False
    for a, b in zip(vs, vs[1:]):
        new = set(b["hard_failed_genes"]) - set(a["hard_failed_genes"])
        for n in new:
            conf = True
            for g in (a.get("repair_applied_genes") or ["(none)"]): pairs[(g.split("orgene.")[-1], n.split("orgene.")[-1])] += 1
    nconf += conf
    if vs and vs[-1]["hard_failed_genes"] and len(vs) > 1:
        noncv += 1; left.update(g.split("orgene.")[-1] for g in vs[-1]["hard_failed_genes"])
trig = sum(len([r for r in u["rounds"] if r.get("validated")]) > 1 for u in Uq["C3L"].values())
out["conflicts"] = {"repaired_problems": trig, "problems_with_new_hard_failure_after_repair": nconf, "pairs": {f"{a} -> {b}": n for (a, b), n in pairs.most_common(8)},
                    "not_converged_after_repair": noncv, "rules_still_failing": dict(left.most_common(8))}
print(json.dumps(out["conflicts"], indent=1))
# activation rates and the all-rules replay
print("\n===== activation (qwen, C3L): share of problems on which each rule was active; all-rules replay")
act = collections.Counter()
for u in Uq["C3L"].values(): act.update(g["geneId"].split("orgene.")[-1] for g in u["activation"]["active_genes"])
out["activation"] = {g: round(n / len(Uq["C3L"]), 3) for g, n in sorted(act.items())}
print({g: v for g, v in out["activation"].items() if v < 1.0}, "| always active:", sum(v == 1.0 for v in out["activation"].values()), "rules")
try:
    cases = {}
    for _, b in STAGES:
        for c in map(json.loads, open(f"data/cases/{b}.jsonl")):
            if c["case_id"] in ids: cases[c["case_id"]] = c
    store = G.load_store("genes/genes.it1.jsonl", lexicon="genes/activation_lexicon.v2.json")
    genes = store["genes"] if isinstance(store, dict) and "genes" in store else store
    changed = 0; inactive_n = 0; which = collections.Counter()
    for k, u in Uq["C3L"].items():
        allact, _, _ = G.activate_case(genes, cases[k], lexicon="genes/activation_lexicon.v2.json", condition="C3L", mode="all")
        have = {g["geneId"] for g in u["activation"]["active_genes"]}
        extra = [g for g in allact if g["geneId"] not in have]
        if not extra: continue
        inactive_n += 1
        v0 = u["rounds"][0]["validated"]; ctx = {"case": cases[k], "spec": v0.get("spec"), "code": v0.get("code"), "exec": v0.get("exec")}
        iss = G.validate(extra, {**ctx, "exec": None}, "pre_exec") + (G.validate(extra, ctx, "post_exec") if v0.get("exec") else [])
        hard = G.hard_failures(iss)
        if hard and not v0["hard_failed_genes"]: changed += 1
        which.update(i["geneId"].split("orgene.")[-1] for i in hard)
    out["replay_all"] = {"problems_with_an_inactive_rule": inactive_n, "inactive_rule_fails_hard": dict(which), "problems_whose_trigger_would_change": changed}
    print(out["replay_all"])
except Exception as e:
    print("replay failed:", repr(e)[:300])
# order effect: correctness on run position (qwen, all ten conditions, main set), cluster-robust by problem
try:
    import numpy as np, statsmodels.api as sm
    rows = []
    for c in ORDER:
        R = results("qwen3-8b.main", c)
        for k, u in Uq[c].items():
            rows.append((k, c, u["schedule"]["planned_index"], k.rsplit("-", 1)[0], 1.0 if R[k]["correct"] else 0.0))
    pos = {}
    for b in ("mamo_complex_lp", "industryor"):
        idx = [r[2] for r in rows if r[3] == b]; lo, hi = min(idx), max(idx)
        pos[b] = (lo, hi)
    X = []; y = []; groups = []; gid = {}
    for k, c, i, b, cor in rows:
        lo, hi = pos[b]
        X.append([1.0, (i - lo) / (hi - lo), 1.0 if b == "industryor" else 0.0] + [1.0 if c == o else 0.0 for o in ORDER[1:]])
        y.append(cor); groups.append(gid.setdefault(k, len(gid)))
    m = sm.GLM(np.array(y), np.array(X), family=sm.families.Binomial()).fit(cov_type="cluster", cov_kwds={"groups": np.array(groups)})
    ci = m.conf_int()[1]
    out["order_effect"] = {"n_units": len(y), "coef_position_logit": round(float(m.params[1]), 3), "ci95": [round(float(ci[0]), 3), round(float(ci[1]), 3)], "p": round(float(m.pvalues[1]), 3),
                           "model": "logit(correct) ~ run position (0 = first, 1 = last unit of the stage) + benchmark + condition; SE clustered by problem"}
    print("\n===== order effect:", out["order_effect"])
except Exception as e:
    print("order effect failed:", repr(e)[:300])
json.dump(out, open(f"{E}/analysis_20261010/descriptives.TEST.json", "w"), indent=1)
