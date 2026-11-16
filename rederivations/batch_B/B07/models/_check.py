import json, os, glob, re
rows = [json.loads(l) for l in open("results.jsonl", encoding="utf-8")]
ids = sorted(os.path.basename(p)[:-4] for p in glob.glob("*.txt"))
assert sorted(r["case_id"] for r in rows) == ids, "id mismatch"
for r in rows:
    for k in ("model_file","output_file"): assert os.path.exists(r[k]), r[k]
    out = open(r["output_file"]).read()
    fo = float(re.search(r"FINAL_OBJECTIVE: (\S+)", out).group(1))
    assert abs(fo - r["objective"]) <= 1e-6*max(1,abs(fo)), (r["case_id"], fo, r["objective"])
    for rd in r["readings"]:
        o = float(re.search(r"FINAL_OBJECTIVE: (\S+)", open(rd["model_file"][:-3]+".out.txt").read()).group(1))
        assert abs(o - rd["objective"]) <= 1e-6*max(1,abs(o)), (rd, o)
    if r["case_id"].startswith("industryor"):
        assert r["problem_type"] and r["type_rationale"] and r["type_confidence"], r["case_id"]
print("OK", len(rows), "rows")
