import json, os, glob
rows = [json.loads(l) for l in open("results.jsonl", encoding="utf-8")]
ids = sorted(os.path.basename(p)[:-4] for p in glob.glob("*.txt"))
assert sorted(r["case_id"] for r in rows) == ids, "id mismatch"
for r in rows:
    assert os.path.exists(r["model_file"]) and os.path.exists(r["output_file"])
    fo = [l for l in open(r["output_file"]) if l.startswith("FINAL_OBJECTIVE:")][0].split(":")[1].strip()
    assert abs(float(fo) - r["objective"]) < 1e-6, (r["case_id"], fo)
    if r["case_id"].startswith("industryor"):
        assert r["problem_type"] and r["type_rationale"] and r["type_confidence"]
print("OK", len(rows), "rows")
