"""E14: scale features from the statement by script only; tertile cut points from dev only; numbers only in the output.

Self-made toy cases only.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import data as D  # noqa: E402
from orgene import split as S  # noqa: E402

_spec = importlib.util.spec_from_file_location("scale_features", os.path.join(ROOT, "analysis", "r1", "scale_features.py"))
SF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SF)

MARK = "UNIQUE-STATEMENT-MARKER"


def _repo(root, texts, n_dev):
    raw = root / "data" / "raw" / "toy.jsonl"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("".join(json.dumps({"question": t, "answer": "1"}) + "\n" for t in texts), encoding="utf-8")
    cases = root / "data" / "cases" / "toy.jsonl"
    D.build_cases("toy", str(raw), str(cases))
    d = root / "data" / "splits" / "toy"
    S.make_split(str(cases), str(d), n_dev=n_dev, seed=11)
    lock = json.loads((d / "SPLIT_LOCK.json").read_text())
    lock["cases_path"] = "data/cases/toy.jsonl"
    (d / "SPLIT_LOCK.json").write_text(json.dumps(lock, indent=2))
    return json.loads((d / "dev_ids.json").read_text()), json.loads((d / "test_ids.json").read_text())


def test_numeric_literal_count():
    f = SF.text_features("Plant x1 makes 1,200 units at $3.50 each; demand is 40% of 2e3, costs -5.")
    assert f["n_numeric_literals"] == 5            # 1,200 / 3.50 / 40% / 2e3 / -5 ; not the 1 in x1
    assert f["n_tokens"] is None
    assert SF.text_features("a b c", count_tokens=lambda t: 7)["n_tokens"] == 7


def test_features_output_has_numbers_only_and_dev_cut_points(tmp_path, capsys):
    texts = [f"{MARK} " + " ".join(str(k) for k in range(i + 1)) for i in range(12)]
    dev, test = _repo(tmp_path, texts, n_dev=6)
    code = SF.main(["--root", str(tmp_path), "--out", "data/features/f.json"])
    out = capsys.readouterr().out
    assert code == 0 and MARK not in out
    doc_text = (tmp_path / "data" / "features" / "f.json").read_text()
    assert MARK not in doc_text                                   # no statement text leaves the script
    doc = json.loads(doc_text)
    assert set(doc["features"]) == set(dev) | set(test)
    assert all(doc["features"][c]["split"] == "dev" for c in dev)
    cp = doc["cutpoints"]["toy"]["n_numeric_literals"]
    dev_vals = sorted(doc["features"][c]["n_numeric_literals"] for c in dev)
    assert cp[0] >= dev_vals[0] and cp[1] <= dev_vals[-1]
    assert doc["pending"] and doc["cutpoints"]["toy"]["n_tokens"] is None
    assert all(v["strata"]["n_tokens"] is None for v in doc["features"].values())
    # cut points depend on dev only: changing a test statement leaves them unchanged
    texts2 = list(texts)
    idx = int(test[0].split("-")[1]) - 1
    texts2[idx] = f"{MARK} " + " ".join(["9"] * 200)
    tmp2 = tmp_path / "second"
    _repo(tmp2, texts2, n_dev=6)
    SF.main(["--root", str(tmp2), "--out", "data/features/f.json"])
    capsys.readouterr()
    doc2 = json.loads((tmp2 / "data" / "features" / "f.json").read_text())
    assert doc2["cutpoints"] == doc["cutpoints"]
    assert doc2["features"][test[0]]["strata"]["n_numeric_literals"] == 2


def test_token_counter_and_solve_record_hooks(tmp_path, capsys):
    dev, test = _repo(tmp_path, [f"{MARK} {'1 ' * i}" for i in range(1, 9)], n_dev=4)
    mod = tmp_path / "toycount.py"
    mod.write_text("def count(text):\n    return len(text) // 2\n")
    sys.path.insert(0, str(tmp_path))
    rec = tmp_path / "solve.jsonl"
    rec.write_text(json.dumps({"case_id": dev[0], "n_variables": 3, "n_constraints": 2}) + "\n")
    try:
        SF.main(["--root", str(tmp_path), "--out", "data/features/f.json", "--token-counter", "toycount:count",
                 "--solve-records", str(rec)])
    finally:
        sys.path.remove(str(tmp_path))
    capsys.readouterr()
    doc = json.loads((tmp_path / "data" / "features" / "f.json").read_text())
    assert doc["pending"] == [] and doc["tokenizer"] == "toycount:count" and doc["solve_records"] == ["solve.jsonl"]
    assert all(isinstance(v["n_tokens"], int) for v in doc["features"].values())
    assert doc["features"][dev[0]]["n_variables_est"] == 3
    assert doc["features"][test[0]]["n_variables_est"] is None and doc["features"][test[0]]["strata"]["n_variables_est"] is None
