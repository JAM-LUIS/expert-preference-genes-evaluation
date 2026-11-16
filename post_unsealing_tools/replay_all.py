"""All-rules replay (preregistration Section 3, C3L-ALL): apply the rules that were inactive on a problem to the stored
first program of gene repair and count the problems whose trigger would change. Outside the frozen tree; counts only."""
import json, sys, glob, collections
sys.path.insert(0, "runtime")
from orgene import analysis_sets as A
from orgene import genes as G
E = "experiments/test-main-20261006"; ids = set(A.analysis_set("main")["ids"])
idk = "case_id"
cases = {}
for b in ("mamo_complex_lp", "industryor"):
    for c in map(json.loads, open(f"data/cases/{b}.jsonl")):
        if c.get(idk) in ids: cases[c[idk]] = c
store = G.load_store("genes/genes.it1.jsonl", lexicon="genes/activation_lexicon.v2.json")
print("store type:", type(store).__name__, (list(store.keys())[:6] if isinstance(store, dict) else len(store)))
genes = store["genes"] if isinstance(store, dict) and "genes" in store else store
changed = 0; inactive_n = 0; which = collections.Counter(); already = 0
for st in ("mamo-test", "industryor-test"):
    for p in glob.glob(f"{E}/{st}/by-model/qwen3-8b.main/units/*.C3L.r0.json"):
        u = json.load(open(p)); k = u["case_id"]
        if k not in ids: continue
        allact, _, _ = G.activate_case(genes, cases[k], lexicon="genes/activation_lexicon.v2.json", condition="C3L", mode="all")
        have = {g["geneId"] for g in u["activation"]["active_genes"]}
        extra = [g for g in allact if g["geneId"] not in have]
        if not extra: continue
        inactive_n += 1
        v0 = u["rounds"][0]["validated"]; ctx = {"case": cases[k], "spec": v0.get("spec"), "code": v0.get("code"), "exec": v0.get("exec")}
        iss = G.validate(extra, {**ctx, "exec": None}, "pre_exec") + (G.validate(extra, ctx, "post_exec") if v0.get("exec") else [])
        hard = G.hard_failures(iss)
        which.update(i["geneId"].split("orgene.")[-1] for i in hard)
        if hard and not v0["hard_failed_genes"]: changed += 1
        elif hard: already += 1
out = {"problems": len(ids), "problems_with_an_inactive_rule": inactive_n, "inactive_rule_would_fail_hard": dict(which),
       "problems_newly_sent_to_repair": changed, "problems_already_in_repair_with_one_more_finding": already}
print(out)
d = json.load(open(f"{E}/analysis_20261010/descriptives.TEST.json")); d["replay_all"] = out
json.dump(d, open(f"{E}/analysis_20261010/descriptives.TEST.json", "w"), indent=1)
