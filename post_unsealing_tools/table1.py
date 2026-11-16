import json, sys, collections, statistics as st
sys.path.insert(0, "runtime")
from orgene import analysis_sets as A
E = "experiments/test-main-20261006"
main = A.analysis_set("main"); ids = set(main["ids"]); bench = {c: b for b, cs in main["by_benchmark"].items() for c in cs}
def rows(entry, cond):
    out = {}
    for stage in ("mamo-test", "industryor-test"):
        for r in map(json.loads, open(f"{E}/{stage}/by-model/{entry}/results.{cond}.jsonl")):
            if r["case_id"] in ids: out[r["case_id"]] = r
    assert len(out) == len(ids), (entry, cond, len(out))
    return out
def line(entry, cond, name):
    R = rows(entry, cond); v = list(R.values())
    cm = sum(bool(r["correct"]) for c, r in R.items() if bench[c] == "mamo_complex_lp"); ci = sum(bool(r["correct"]) for c, r in R.items() if bench[c] == "industryor")
    trig = sum((r.get("repair_rounds_used") or 0) > 0 for r in v)
    print(f"{name:34s} mamo {cm:2d} ior {ci:2d} correct {cm+ci:3d} acc {100*(cm+ci)/len(v):5.1f} exec {100*sum(bool(r['exec_ok']) for r in v)/len(v):5.1f} "
          f"verified {sum(bool(r.get('verified_correct')) for r in v):3d} in {st.mean(r['in_tokens'] or 0 for r in v):7.0f} out {st.mean(r['out_tokens'] or 0 for r in v):6.0f} "
          f"calls {st.mean(r['n_calls'] or 0 for r in v):.2f} trig {trig:3d} misrep {sum(bool(r.get('misreport')) for r in v):2d} "
          f"reasons {dict(collections.Counter(r.get('reason') for r in v if not r['correct']).most_common(4))}")
    return R
Q = {}
for cond, name in (("C0", "Direct"), ("C1", "Advice prompt"), ("C2", "Specification first"), ("C3", "Specification with contract"), ("C3E", "Generic repair"), ("C3L", "Gene repair"),
                   ("C2E", "Spec first + generic repair"), ("C3T", "Gene trigger, generic text"), ("C3A", "Forced review"), ("C0R-E", "Rules in prompt")):
    Q[cond] = line("qwen3-8b.main", cond, name)
print("-- gpt-oss (refused units wrong)")
for cond, name in (("C0", "Direct"), ("C1", "Advice prompt"), ("C2", "Specification first"), ("C3", "Specification with contract"), ("C3E", "Generic repair"), ("C3L", "Gene repair")):
    G = line("gptoss-20b.main.server_refused", cond, name)
    print("     refused/blocked rows in main:", sum(r.get("reason") == "server_refused" for r in G.values()))
# cost per triggered problem: extra tokens over the shared first program
for c in ("C3E", "C3L", "C3T", "C3A"):
    t = [k for k, r in Q[c].items() if (r.get("repair_rounds_used") or 0) > 0]
    ex = [(Q[c][k]["in_tokens"] + Q[c][k]["out_tokens"]) - (Q["C0"][k]["in_tokens"] + Q["C0"][k]["out_tokens"]) for k in t]
    rounds = collections.Counter(Q[c][k].get("repair_rounds_used") for k in Q[c])
    print(f"{c}: triggered {len(t)} ({100*len(t)/125:.1f}%), extra tokens per triggered {st.mean(ex) if ex else 0:.0f}, rounds used {dict(rounds)}, total tok/problem {st.mean(r['in_tokens']+r['out_tokens'] for r in Q[c].values()):.0f}")
print("C0 total tok/problem", round(st.mean(r['in_tokens']+r['out_tokens'] for r in Q['C0'].values())), "C0R-E", round(st.mean(r['in_tokens']+r['out_tokens'] for r in Q['C0R-E'].values())))
keys = [k for k in list(Q["C3L"].values())[0].keys()]; print("extra row keys:", [k for k in keys if k not in ("case_id",)][20:])
# engineering set
print("-- eng")
for d, tag in ((f"{E}/eng-holdout/by-model/qwen3-8b.main", "60s"), (f"{E}/eng-holdout/by-model/qwen3-8b.main.final_t600", "600s")):
    for c in ("C0", "C3E", "C3L"):
        rs = list(map(json.loads, open(f"{d}/results.{c}.jsonl")))
        print(tag, c, [(r["case_id"][-12:], int(bool(r["exec_ok"])), int(bool(r["correct"])), (r.get("reason") or "")[:28]) for r in rs])
