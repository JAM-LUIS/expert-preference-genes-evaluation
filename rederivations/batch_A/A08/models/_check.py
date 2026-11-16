import json, os, re, glob
rows = [json.loads(l) for l in open("results.jsonl", encoding="utf-8")]
ids = sorted(os.path.basename(p)[:-4] for p in glob.glob("industryor-*.txt"))
assert sorted(r["case_id"] for r in rows) == ids and len(rows) == 15, "id mismatch"
for r in rows:
    files = [r["model_file"], r["output_file"]] + [x["model_file"] for x in r["readings"]]
    for p in files:
        assert os.path.exists(p), p
    def fo(p):
        mm = re.search(r"FINAL_OBJECTIVE: (\S+)", open(p).read()); return None if mm.group(1) == "None" else float(mm.group(1))
    v = fo(r["output_file"])
    assert (v is None and r["objective"] is None) or abs(v - r["objective"]) < 1e-6, (r["case_id"], v)
    for x in r["readings"]:
        op = x["model_file"][:-3] + ".out.txt"
        vv = fo(op)
        if not ((vv is None and x["objective"] is None) or (vv is not None and x["objective"] is not None and abs(vv - x["objective"]) < 1e-6)):
            print("reading differs from default output (check notes):", r["case_id"], x["model_file"], vv, x["objective"])
    assert r["problem_type"] and r["type_rationale"] and r["type_confidence"]
    if r["integrality_ambiguous"]: assert r["integer_relaxed_objective"] is not None
print("OK", len(rows))
