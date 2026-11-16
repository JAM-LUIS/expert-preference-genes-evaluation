"""E20a end-to-end regression: the stage-0 report T8, tables 2.1 and 2.2 (and 3.4), reproduced cell by cell from the v5
dev results in reference/v5_dev_results through the registry, the analysis sets and paired.py. Dev data only."""
import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))
sys.path.insert(0, os.path.join(ROOT, "analysis", "r1"))

import registry as RG  # noqa: E402
import t8_repro as T8  # noqa: E402
from orgene import paths as PAT  # noqa: E402

FIX = os.path.join(ROOT, "reference", "v5_dev_results")


def test_t8_tables_are_reproduced_cell_by_cell():
    doc = T8.reproduce(ROOT)
    bad = [c for c in doc["checks"] if not c["ok"]]
    assert not bad, bad[:5]
    assert doc["all_match"] and doc["data"] == "DEV"
    s = doc["summary"]
    # 12 labels x 6 cells; 22 pairs x 6 cells; 5 execution-rate pairs; 5 x 3 MDE cells (+ the unrounded CSV)
    assert (s["2.1"]["n"], s["2.2"]["n"], s["exec_line"]["n"], s["3.4"]["n"], s["3.4_csv"]["n"]) == (72, 132, 5, 15, 15)
    assert s["metrics"]["n"] == 48 and s["per_case"]["n"] == 2
    assert doc["analysis_set"]["name"] == "dev_all85" and doc["analysis_set"]["n"] == 85 and doc["n_rows"] == 1020


def test_cli_exit_code_and_labelled_output(tmp_path):
    out = str(tmp_path / "t8.json")
    p = subprocess.run([sys.executable, "-B", "analysis/r1/t8_repro.py", "--skip-mde", "--out", out],
                       capture_output=True, text=True, timeout=300, cwd=ROOT)
    assert p.returncode == 0, p.stdout[-800:] + p.stderr[-800:]
    assert "All cells match: **True**" in p.stdout and p.stdout.startswith("# [DEV] ")
    doc = json.load(open(str(tmp_path / "t8.DEV.json"), encoding="utf-8"))
    assert doc["all_match"] and not PAT.find_absolute_paths(json.dumps(doc))


def test_fixture_hashes_and_content_rules():
    sums = {}
    for line in open(os.path.join(FIX, "SHA256SUMS"), encoding="utf-8"):
        h, p = line.split(None, 1)
        sums[p.strip()] = h
    files = sorted(os.path.relpath(os.path.join(d, f), FIX).replace(os.sep, "/")
                   for d, _, fs in os.walk(FIX) for f in fs if f not in ("SHA256SUMS",) and not f.startswith("."))
    assert sorted(sums) == files
    for p, h in sums.items():
        assert hashlib.sha256(open(os.path.join(FIX, p), "rb").read()).hexdigest() == h, p
    # dev cases only, no absolute path anywhere, registry paths relative
    dev = set()
    for b in ("mamo_complex_lp", "industryor"):
        dev |= set(json.load(open(os.path.join(ROOT, "data", "splits", b, "dev_ids.json"), encoding="utf-8")))
    for p in files:
        text = open(os.path.join(FIX, p), encoding="utf-8").read()
        assert not PAT.find_absolute_paths(text), p
        if p.endswith(".jsonl"):
            assert {json.loads(l)["case_id"] for l in text.splitlines() if l.strip()} <= dev, p
    reg = RG.load_registry(os.path.join(FIX, "registry.json"), root=ROOT)
    assert len(reg.runs) == 24 and all(e["split"] == "dev" and e["path"].startswith("reference/") for e in reg.runs)


def _mini_root(tmp_path):
    """A copy of what the reproduction reads: the fixture, the frozen splits and the analysis-set files."""
    root = str(tmp_path / "repo")
    shutil.copytree(FIX, os.path.join(root, "reference", "v5_dev_results"))
    for d in ("data/splits", "data/analysis_sets"):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(root, d))
    for f in ("configs/analysis_set_defs.r1.json", "data/mamo_underspecified_ids.json"):
        os.makedirs(os.path.dirname(os.path.join(root, f)), exist_ok=True)
        shutil.copy(os.path.join(ROOT, f), os.path.join(root, f))
    return root


def _flip_first_correct(root, label):
    reg_p = os.path.join(root, "reference/v5_dev_results/registry.json")
    reg = json.load(open(reg_p, encoding="utf-8"))
    e = next(x for x in reg["runs"] if x["label"] == label and x["benchmark"] == "mamo_complex_lp")
    p = os.path.join(root, e["path"], e["results"])
    rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    rows[0]["correct"] = not rows[0]["correct"]
    os.chmod(p, 0o644)
    with open(p, "w", encoding="utf-8") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))
    return reg_p, reg, e, p


def test_a_changed_result_is_caught(tmp_path):
    root = _mini_root(tmp_path)
    assert T8.reproduce(root, skip_mde=True)["all_match"]      # the copy reproduces as the tree does
    reg_p, reg, e, p = _flip_first_correct(root, "C3E")
    with pytest.raises(RG.RegistryError, match="changed after registration"):
        T8.reproduce(root, skip_mde=True)
    # re-registering the changed file passes the registry, and the tables no longer match
    e["results_sha256"] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    with open(reg_p, "w", encoding="utf-8") as f:
        json.dump(reg, f)
    doc = T8.reproduce(root, skip_mde=True)
    assert not doc["all_match"]
    bad = {(c["table"], c["row"]) for c in doc["checks"] if not c["ok"]}
    assert ("2.1", "C3E") in bad and any(t == "2.2" and "C3E" in r for t, r in bad)
