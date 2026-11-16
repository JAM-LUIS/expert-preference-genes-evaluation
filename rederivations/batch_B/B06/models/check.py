import json, os, re, glob
d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
rows = [json.loads(l) for l in open(os.path.join(d, "results.jsonl"), encoding="utf-8")]
ids = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(d, "*.txt")))
print("rows", len(rows), "cases", len(ids), "match", sorted(r["case_id"] for r in rows) == ids)
for r in rows:
    files = [(r["model_file"], r["output_file"], r["objective"])] + [(x["model_file"], x["model_file"][:-3] + ".out.txt", x["objective"]) for x in r["readings"]]
    for mf, of, obj in files:
        assert os.path.exists(os.path.join(d, mf)) and os.path.exists(os.path.join(d, of)), mf
        txt = open(os.path.join(d, of)).read()
        fo = re.search(r"^FINAL_OBJECTIVE: (\S+)", txt, re.M).group(1)
        ok = (fo == "None" and obj is None) or (obj is not None and abs(float(fo) - obj) < 1e-6)
        if not ok: print("MISMATCH", r["case_id"], of, fo, obj)
    if r["case_id"].startswith("industryor"):
        assert r["problem_type"] and r["type_rationale"] and r["type_confidence"], r["case_id"]
print("check done")
