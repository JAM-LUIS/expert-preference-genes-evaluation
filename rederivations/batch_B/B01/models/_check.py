import json, os, re, glob
rows = [json.loads(l) for l in open("results.jsonl", encoding="utf-8")]
ids = sorted(os.path.basename(p)[:-4] for p in glob.glob("*.txt"))
assert sorted(r["case_id"] for r in rows) == ids, "id mismatch"
assert len(rows) == len(set(r["case_id"] for r in rows))
for r in rows:
    for k in ["model_file","output_file"]:
        assert os.path.exists(r[k]), r[k]
    out = open(r["output_file"]).read()
    v = re.search(r"^FINAL_OBJECTIVE: (\S+)", out, re.M).group(1)
    assert abs(float(v) - r["objective"]) <= 1e-6*max(1,abs(r["objective"])), (r["case_id"], v, r["objective"])
    for rd in r["readings"]:
        o = open(rd["model_file"].replace(".py",".out.txt")).read()
        v = re.search(r"^FINAL_OBJECTIVE: (\S+)", o, re.M).group(1)
        assert abs(float(v) - rd["objective"]) <= 1e-6*max(1,abs(rd["objective"])), (r["case_id"], rd)
    if r["case_id"].startswith("industryor"):
        assert r["problem_type"] and r["type_rationale"] and r["type_confidence"]
print("OK", len(rows), "rows,", len(ids), "problems")
