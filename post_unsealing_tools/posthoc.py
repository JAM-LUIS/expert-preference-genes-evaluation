import json, sys
sys.path.insert(0, "runtime")
from orgene import analysis_sets as A
E = "experiments/test-main-20261006"
def rows(stage, cond):
    return {r["case_id"]: r for r in map(json.loads, open(f"{E}/{stage}/by-model/qwen3-8b.main/results.{cond}.jsonl"))}
L = {**rows("mamo-test", "C3L"), **rows("industryor-test", "C3L")}
Ee = {**rows("mamo-test", "C3E"), **rows("industryor-test", "C3E")}
C0 = {**rows("mamo-test", "C0"), **rows("industryor-test", "C0")}
print("result row keys:", [k for k in list(L.values())[0].keys()][:40])
main = set(A.analysis_set("main")["ids"])
unchecked = {"industryor-0003", "industryor-0039", "mamo_complex_lp-0012", "mamo_complex_lp-0014", "mamo_complex_lp-0017",
             "mamo_complex_lp-0039", "mamo_complex_lp-0053", "mamo_complex_lp-0207"}
def wtl(ids, a, b, f="correct"):
    w = sorted(c for c in ids if a[c][f] and not b[c][f]); l = sorted(c for c in ids if b[c][f] and not a[c][f])
    return len(ids), sum(bool(a[c][f]) for c in ids), sum(bool(b[c][f]) for c in ids), w, l
n, ca, cb, w, l = wtl(main, L, Ee); print("main C3L vs C3E:", n, ca, cb, "wins", w, "losses", l)
n, ca, cb, w, l = wtl(main - unchecked, L, Ee); print("main minus 8 unchecked:", n, ca, cb, "wins", len(w), "losses", len(l))
print("unchecked in wins:", sorted(set(wtl(main, L, Ee)[3]) & unchecked))
ex = json.load(open("data/exclusions_r1.json"))
q3 = set(ex["q3_removed"]["ids"]) | set(ex["nl_not_linearizable"]["ids"])
rem = sorted(c for c in q3 if c in L)            # removed problems that were run on test
f = "correct_original_ref" if "correct_original_ref" in list(L.values())[0] else "correct"
n, ca, cb, w, l = wtl(rem, L, Ee, f); print(f"removed by adjudication, run on test ({f}):", n, ca, cb, "wins", w, "losses", l)
n, ca, cb, w, l = wtl(main, L, C0); print("main C3L vs C0:", n, ca, cb, "wins", len(w), "losses", len(l))
