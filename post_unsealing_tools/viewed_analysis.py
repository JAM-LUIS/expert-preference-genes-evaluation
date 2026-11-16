"""Post hoc joins outside the frozen tree (2026-10-10): (1) the main comparison with the nine viewed problems added
back (rows of the formal run joined with the supplementary run); (2) the temperature-0.7 subset restricted to the
main-analysis set; (3) the main set without the eight problems whose human check was not completed.
Uses analysis/r1/paired.compare_cases (registered exact test and stratified bootstrap). Counts and ids only."""
import json, sys, collections
sys.path.insert(0, "runtime"); sys.path.insert(0, "analysis/r1"); sys.path.insert(0, ".")
from orgene import analysis_sets as A
import paired as P
E, V = "experiments/test-main-20261006", "experiments/test-viewed0905-20261010"
def load(path):
    try: return [json.loads(l) for l in open(path)]
    except FileNotFoundError: return []
def per_case(cond, entry="qwen3-8b.main", field="correct", viewed=True):
    vals = collections.defaultdict(list)
    dirs = [f"{E}/mamo-test", f"{E}/industryor-test"] + ([f"{V}/mamo-viewed0905", f"{V}/industryor-viewed0905"] if viewed else [])
    for d in dirs:
        for r in load(f"{d}/by-model/{entry}/results.{cond}.jsonl"):
            vals[r["case_id"]].append(1.0 if r[field] else 0.0)
    return {c: sum(v) / len(v) for c, v in vals.items()}, {c: len(v) for c, v in vals.items()}
def show(tag, ids, pa, pb, bench):
    r = P.compare_cases(pa, pb, ids, bench)
    print(f"{tag:46s} n={r['n']:3d} A={100*r['acc_a']:.1f} B={100*r['acc_b']:.1f} diff={100*r['diff']:+.1f} ci=[{100*r['ci'][0]:.1f}, {100*r['ci'][1]:.1f}] "
          f"W/T/L={r['wins']}/{r['ties']}/{r['losses']} p={r['mcnemar_exact_p']:.4f}")
    return r
out = {}
L, _ = per_case("C3L"); Ee, _ = per_case("C3E"); C0, _ = per_case("C0")
for name in ("main", "sens_incl0905", "sens_full211", "sens_full211_incl0905"):
    s = A.analysis_set(name); bench = {c: c.rsplit("-", 1)[0] for c in s["ids"]}
    miss = [c for c in s["ids"] if c not in L or c not in Ee]
    if miss: print(name, "missing", len(miss), miss[:4]); continue
    out[name] = show(f"C3L vs C3E  {name}", s["ids"], L, Ee, bench)
    out[name + ".L_vs_C0"] = show(f"C3L vs C0   {name}", s["ids"], L, C0, bench)
viewed = sorted(set(A.analysis_set("sens_full211_incl0905")["ids"]) - set(A.analysis_set("sens_full211")["ids"]))
print("viewed problems:", [(c, int(C0.get(c, -1)), int(Ee.get(c, -1)), int(L.get(c, -1))) for c in viewed], "(C0, C3E, C3L correct)")
main = A.analysis_set("main"); bench = {c: c.rsplit("-", 1)[0] for c in main["ids"]}
unchecked = {"industryor-0003", "industryor-0039", "mamo_complex_lp-0012", "mamo_complex_lp-0014", "mamo_complex_lp-0017", "mamo_complex_lp-0039", "mamo_complex_lp-0053", "mamo_complex_lp-0207"}
out["main_minus_unchecked8"] = show("C3L vs C3E  main minus 8 unchecked", sorted(set(main["ids"]) - unchecked), L, Ee, bench)
# temperature 0.7 subset (three repeats), restricted to the main-analysis set
Lv, nl = per_case("C3L", "qwen3-8b.var07", viewed=False); Ev, ne = per_case("C3E", "qwen3-8b.var07", viewed=False); Cv, nc = per_case("C0", "qwen3-8b.var07", viewed=False)
sub = sorted(set(Lv) & set(main["ids"]))
print("var07 subset: cases", len(Lv), "in main", len(sub), "repeats", collections.Counter(nl.values()))
out["var07.L_vs_E"] = show("C3L vs C3E  temperature 0.7 subset in main", sub, Lv, Ev, bench)
out["var07.L_vs_C0"] = show("C3L vs C0   temperature 0.7 subset in main", sub, Lv, Cv, bench)
out["var07.t0.L_vs_E"] = show("C3L vs C3E  same problems at temperature 0", sub, L, Ee, bench)
for o in out.values(): o.pop("_exact", None)
json.dump(out, open("experiments/test-main-20261006/analysis_20261010/posthoc_joins.TEST.json", "w"), indent=1)
