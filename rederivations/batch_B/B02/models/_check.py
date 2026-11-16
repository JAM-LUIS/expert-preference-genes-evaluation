import json, os, re, glob
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")
rows = [json.loads(l) for l in open("results.jsonl", encoding="utf-8")]
ids = sorted(os.path.basename(f)[:-4] for f in glob.glob("*.txt"))
assert sorted(r["case_id"] for r in rows) == ids and len(set(r["case_id"] for r in rows)) == len(rows)
for r in rows:
    for k in ("model_file","output_file"): assert os.path.exists(r[k]), r[k]
    v = re.search(r"FINAL_OBJECTIVE: (\S+)", open(r["output_file"]).read()).group(1)
    assert float(v) == r["objective"], r["case_id"]
    for rd in r["readings"]:
        out = rd["model_file"][:-3] + ".out.txt"
        assert float(re.search(r"FINAL_OBJECTIVE: (\S+)", open(out).read()).group(1)) == rd["objective"]
    if r["case_id"].startswith("industryor"):
        assert r["problem_type"] and r["type_rationale"] and r["type_confidence"]
print("OK", len(rows), "rows;", [ (r["case_id"], r["issue"], r["confidence"]) for r in rows if r["issue"]!="NONE" or r["confidence"]=="LOW"])
