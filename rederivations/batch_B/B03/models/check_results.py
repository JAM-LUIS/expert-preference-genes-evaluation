#!/usr/bin/env python3
import json, os, re, glob
rows = [json.loads(l) for l in open("results.jsonl", encoding="utf-8")]
ids = sorted(os.path.basename(p)[:-4] for p in glob.glob("*.txt"))
print("rows", len(rows), "cases", len(ids), "match", sorted(r["case_id"] for r in rows) == ids)
for r in rows:
    files = [r["model_file"], r["output_file"]] + [x["model_file"] for x in r["readings"]]
    for f in files:
        if not os.path.exists(f): print("MISSING", f)
    out = open(r["output_file"]).read()
    v = re.search(r"FINAL_OBJECTIVE: (\S+)", out).group(1)
    if abs(float(v) - r["objective"]) > 1e-6 * max(1, abs(r["objective"])): print("MISMATCH", r["case_id"], v, r["objective"])
    for x in r["readings"]:
        o = open(x["model_file"][:-3] + ".out.txt").read()
        vv = float(re.search(r"FINAL_OBJECTIVE: (\S+)", o).group(1))
        if abs(vv - x["objective"]) > 1e-6 * max(1, abs(vv)): print("RMISMATCH", r["case_id"], vv, x["objective"])
    if r["case_id"].startswith("industryor") and not (r["problem_type"] and r["type_rationale"] and r["type_confidence"]):
        print("TYPE MISSING", r["case_id"])
print("done")
