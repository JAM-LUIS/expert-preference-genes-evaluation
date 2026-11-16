"""E20a run registry, per-case matrix, analysis sets and the paired CLI path, on a self-made toy repository
(toy ids, toy results; no benchmark text). The real superseded-runs file and the real analysis sets are read for ids
and counts only."""
import argparse
import hashlib
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))
sys.path.insert(0, os.path.join(ROOT, "analysis", "r1"))

import common as CM  # noqa: E402
import paired as PA  # noqa: E402
import prereg as PR  # noqa: E402
import registry as RG  # noqa: E402
from prereg_draft import draft_file  # noqa: E402

DEV = [f"toy-{i:04d}" for i in range(1, 9)]
TEST = [f"toy-{i:04d}" for i in range(9, 13)]
PY = sys.executable


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _results(root, run, cond, outcomes, bench="toy", tokens=100, repaired=None):
    rows = []
    for i, (cid, ok) in enumerate(outcomes.items()):
        rows.append({"case_id": cid, "repeat": 0, "condition": cond, "source": bench, "exec_ok": True,
                     "protocol_ok": True, "status": "Optimal", "objective": 1.0, "correct": ok, "reason": "match",
                     "provisional": False, "out_tokens": tokens + i, "in_tokens": 50, "n_calls": 1 + (repaired or {}).get(cid, 0),
                     "repair_rounds_used": (repaired or {}).get(cid, 0), "hard_issue_count_round0": 0,
                     "hard_failed_genes_final": [], "soft_failed_genes_final": [], "exec_seconds": 0.1,
                     "correct_tol": {"1e-06": ok, "0.0001": ok, "0.01": ok}, "correct_original_ref": ok})
    p = os.path.join(root, run, f"results.{cond}.jsonl")
    _write(p, "".join(json.dumps(r) + "\n" for r in rows))
    return p


def _entry(root, label, cond, run, k=None, split="dev", bench="toy", **extra):
    e = {"label": label, "config": cond, "model": "toy-model", "benchmark": bench, "split": split,
         "max_repair_rounds": k, "path": run, "results": f"results.{cond}.jsonl",
         "results_sha256": _sha(os.path.join(root, run, f"results.{cond}.jsonl"))}
    e.update(extra)
    return e


@pytest.fixture()
def toy(tmp_path):
    root = str(tmp_path)
    _write(os.path.join(root, "data/splits/toy/dev_ids.json"), json.dumps(DEV))
    _write(os.path.join(root, "data/splits/toy/test_ids.json"), json.dumps(TEST))
    a = {c: i % 2 == 0 for i, c in enumerate(DEV)}
    b = {c: i % 4 == 0 for i, c in enumerate(DEV)}
    _results(root, "experiments/run-a", "C3L", a, repaired={DEV[1]: 1})
    _results(root, "experiments/run-b", "C3E", b)
    runs = [_entry(root, "C3L@2", "C3L", "experiments/run-a", 2, round0="reuse:C0"),
            _entry(root, "C3E@2", "C3E", "experiments/run-b", 2, round0="reuse:C0")]
    reg_path = _write(os.path.join(root, "experiments/run_registry.json"),
                      json.dumps({"schema": RG.REGISTRY_SCHEMA, "runs": runs}))
    return {"root": root, "reg": reg_path, "runs": runs, "a": a, "b": b}


def _reg(toy, runs=None):
    if runs is not None:
        _write(toy["reg"], json.dumps({"schema": RG.REGISTRY_SCHEMA, "runs": runs}))
    return RG.load_registry(toy["reg"], root=toy["root"])


def _aset(ids, split="dev", reference="r1", name="toyset"):
    return {"name": name, "split": split, "reference": reference, "n": len(ids), "sha256": "0" * 64,
            "ids": sorted(ids), "by_benchmark": {"toy": sorted(ids)}, "pending": []}


# ------------------------------------------------------------------ superseded runs


def test_real_superseded_runs_are_registered_by_condition_count_and_time_only():
    s = RG.load_superseded(root=ROOT)
    ents = s["entries"]
    assert [(e["config"], e["benchmark"], e["n_cases"]) for e in ents] == [
        ("C0", "mamo_complex_lp", 151), ("C0", "industryor", 75), ("C1", "mamo_complex_lp", 151),
        ("C1", "industryor", 75), ("C2", "mamo_complex_lp", 151), ("C2", "industryor", 75)]
    for e in ents:
        assert e["split"] == "test" and set(e) <= set(RG.SUPERSEDED_REQUIRED) | set(RG.SUPERSEDED_OPTIONAL)
        assert e["started_utc"] < e["finished_utc"]
    # consecutive: every run starts when the previous one finished (one Ollama slot)
    assert all(ents[i + 1]["started_utc"] >= ents[i]["finished_utc"] for i in range(len(ents) - 1))
    doc = json.load(open(os.path.join(ROOT, RG.DEFAULT_SUPERSEDED), encoding="utf-8"))
    assert doc["common"]["contents"] == "not opened"


@pytest.mark.parametrize("key,value", [("path", "experiments/x-test-C0"), ("results", "results.C0.jsonl"),
                                       ("results_sha256", "0" * 64)])
def test_a_superseded_entry_that_names_a_file_is_refused(tmp_path, key, value):
    doc = json.load(open(os.path.join(ROOT, RG.DEFAULT_SUPERSEDED), encoding="utf-8"))
    doc["superseded"][0][key] = value
    p = _write(str(tmp_path / "superseded.json"), json.dumps(doc))
    with pytest.raises(RG.RegistryError, match="never names a directory or a file"):
        RG.load_superseded(p, root=str(tmp_path))


def test_superseded_cli_lists_the_runs():
    p = subprocess.run([PY, "-B", os.path.join(ROOT, "analysis/r1/registry.py"), "superseded"], capture_output=True,
                       text=True, timeout=60, cwd=ROOT)
    assert p.returncode == 0 and p.stdout.count(" test ") == 6 and "contents not opened" in p.stdout


# ------------------------------------------------------------------ registry validation


def test_registry_validation(toy):
    base = toy["runs"]
    bad_abs = [dict(base[0], path=os.path.join(toy["root"], "experiments/run-a"))]
    with pytest.raises(RG.RegistryError, match="relative to the repository root"):
        _reg(toy, bad_abs)
    with pytest.raises(RG.RegistryError, match="registered twice"):
        _reg(toy, [base[0], dict(base[0])])
    with pytest.raises(RG.RegistryError, match="names both"):
        _reg(toy, [base[0], dict(base[1], label="C3L@2", benchmark="other")])
    with pytest.raises(RG.RegistryError, match="unknown keys"):
        _reg(toy, [dict(base[0], contents="x")])
    with pytest.raises(RG.RegistryError, match="leave the repository"):
        _reg(toy, [dict(base[0], path="../elsewhere")])
    _write(toy["reg"], json.dumps({"schema": RG.REGISTRY_SCHEMA, "runs": base, "superseded": []}))
    with pytest.raises(RG.RegistryError, match="superseded runs live in"):
        RG.load_registry(toy["reg"], root=toy["root"])


# ------------------------------------------------------------------ matrix


def test_matrix_rows_fields_and_label(toy):
    m = RG.build_matrix(_reg(toy), toy["root"])
    assert m.label == "DEV" and len(m.rows) == 16
    for r in m.rows:
        assert list(r) == list(RG.MATRIX_FIELDS)
        assert r["round0_source"] == "reuse:C0"
        assert all(r[k] is None for k in RG.RESERVED if k != "round0_source")
    a = {r["case_id"]: r["correct"] for r in m.select("toy-model", "C3L@2")}
    assert a == toy["a"]
    assert m.header["superseded"]["read"] is False and m.header["freeze_gate"] is None
    with pytest.raises(CM.AnalysisError, match="no rows for label"):
        m.select("toy-model", "C0")


def test_changed_results_file_is_refused(toy):
    p = os.path.join(toy["root"], "experiments/run-a/results.C3L.jsonl")
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(RG.RegistryError, match="changed after registration"):
        RG.build_matrix(_reg(toy), toy["root"])


def test_dev_run_with_a_test_case_is_refused(toy):
    _results(toy["root"], "experiments/run-c", "C0", {DEV[0]: True, TEST[0]: False})
    runs = toy["runs"] + [_entry(toy["root"], "C0", "C0", "experiments/run-c")]
    with pytest.raises(RG.RegistryError, match=r"not dev cases of toy \(they belong to \['test'\]\)"):
        RG.build_matrix(_reg(toy, runs), toy["root"])


def test_test_run_is_not_read_before_the_freeze_gate(toy):
    p = _results(toy["root"], "experiments/run-t", "C0", {c: True for c in TEST})
    runs = [_entry(toy["root"], "C0", "C0", "experiments/run-t", split="test")]
    os.chmod(p, 0)       # reading it would raise PermissionError; the gate must refuse first
    try:
        with pytest.raises(RG.RegistryError, match="is a test run: .*freeze"):
            RG.build_matrix(_reg(toy, runs), toy["root"])
    finally:
        os.chmod(p, 0o644)


def test_the_gate_requires_the_analysis_inputs_to_be_frozen(toy, monkeypatch):
    from orgene import freeze as FZ
    seen = {}

    def fake_gate(root, manifest_path=None, split_dir=None, inputs=()):
        seen["inputs"] = [os.path.relpath(p, root) for p in inputs]
        return {"manifest": "FREEZE_MANIFEST.json", "manifest_file_sha256": "0" * 64, "content_sha256": "1" * 64,
                "osf_registration_id": "toy00"}

    _write(os.path.join(toy["root"], "configs/prereg_analysis.json"), "{}")
    _write(os.path.join(toy["root"], "analysis/r1/paired.py"), "# toy\n")
    _results(toy["root"], "experiments/run-t", "C0", {c: True for c in TEST})
    runs = [_entry(toy["root"], "C0", "C0", "experiments/run-t", split="test")]
    monkeypatch.setattr(FZ, "check_gate", fake_gate)
    m = RG.build_matrix(_reg(toy, runs), toy["root"])
    assert m.label == "TEST" and m.header["freeze_gate"][0]["stage"] == "analysis"
    assert {"configs/prereg_analysis.json", "analysis/r1/paired.py", "data/splits/toy/test_ids.json"} <= set(seen["inputs"])
    assert not any(p.startswith("experiments/") for p in seen["inputs"])   # results and registry are not freeze inputs

    def refusing_gate(root, manifest_path=None, split_dir=None, inputs=()):
        raise FZ.GateRefused("1 input file(s) not covered by the freeze manifest: configs/prereg_analysis.json")

    monkeypatch.setattr(FZ, "check_gate", refusing_gate)
    with pytest.raises(RG.RegistryError, match="not covered by the freeze"):
        RG.build_matrix(_reg(toy, runs), toy["root"])


def test_wrong_condition_file_is_refused(toy):
    runs = [dict(toy["runs"][0], config="C3E", label="C3E@2", results="results.C3L.jsonl")]
    with pytest.raises(RG.RegistryError, match="another condition"):
        RG.build_matrix(_reg(toy, runs), toy["root"])


def test_enrichers_may_set_reserved_fields_only(toy):
    def ok(e, rows, root):
        for r in rows:
            r["done_reasons"] = ["stop"]

    m = RG.build_matrix(_reg(toy), toy["root"], enrichers=[ok])
    assert all(r["done_reasons"] == ["stop"] for r in m.rows)

    def touches_core(e, rows, root):
        rows[0]["correct"] = not rows[0]["correct"]

    with pytest.raises(RG.RegistryError, match="changed core fields"):
        RG.build_matrix(_reg(toy), toy["root"], enrichers=[touches_core])

    def adds_field(e, rows, root):
        rows[0]["surprise"] = 1

    with pytest.raises(RG.RegistryError, match="added fields"):
        RG.build_matrix(_reg(toy), toy["root"], enrichers=[adds_field])


def test_round0_sha_from_runner_outputs(toy):
    gen = os.path.join(toy["root"], "experiments/run-a/gen.C3L.r0/outputs")
    for i, c in enumerate(DEV):
        _write(os.path.join(gen, f"{c}.json"), json.dumps({"case_id": c, "repeat": 0, "content": f"answer {i}",
                                                           "meta": {"round": 0}}))
    runs = [dict(toy["runs"][0], round0_gen_dir="experiments/run-a/gen.C3L.r0"), toy["runs"][1]]
    m = RG.build_matrix(_reg(toy, runs), toy["root"])
    a = {r["case_id"]: r["round0_content_sha256"] for r in m.select("toy-model", "C3L@2")}
    assert a[DEV[3]] == hashlib.sha256(b"answer 3").hexdigest()
    assert all(r["round0_content_sha256"] is None for r in m.select("toy-model", "C3E@2"))
    _write(os.path.join(gen, f"{DEV[0]}.json"), json.dumps({"case_id": DEV[0], "content": "x", "meta": {"round": 1}}))
    with pytest.raises(RG.RegistryError, match="not a round-0 answer"):
        RG.build_matrix(_reg(toy, runs), toy["root"])


# ------------------------------------------------------------------ analysis sets


def test_set_names_and_restriction(toy):
    assert RG.set_name_for("DEV") == "dev_signal55"
    assert RG.set_name_for("TEST") == "main"
    assert RG.set_name_for("TEST", incl_0905=True) == "sens_incl0905"
    assert RG.set_name_for("TEST", "sens_full211", incl_0905=True) == "sens_full211_incl0905"
    with pytest.raises(CM.AnalysisError, match="--incl-0905 applies"):
        RG.set_name_for("DEV", incl_0905=True)
    m = RG.build_matrix(_reg(toy), toy["root"])
    sub = RG.restrict(m, _aset(DEV[:6]))
    assert len(sub.rows) == 12 and sub.header["analysis_set"]["n"] == 6
    with pytest.raises(CM.AnalysisError, match="is a test set"):
        RG.restrict(m, _aset(TEST, split="test"))


def test_main_set_excludes_the_0905_cases_and_the_sensitivity_set_adds_them_back():
    from orgene import analysis_sets as AS
    main = RG.resolve_set("main", root=ROOT, allow_pending=True)
    incl = RG.resolve_set("sens_incl0905", root=ROOT, allow_pending=True)
    ids = AS.load_id_sets(root=ROOT)
    seen = set(ids["exclusions"]["seen_20260905_test"]["ids"])
    excl = set(ids["sets"]["mamo_main_clean111_excl0905"]["test"]) | set(ids["sets"]["industryor_main_rev2026_100_excl0905"]["test"])
    assert not set(main["ids"]) & seen and set(main["ids"]) <= excl
    assert set(main["ids"]) <= set(incl["ids"]) and set(incl["ids"]) - set(main["ids"]) <= seen
    assert set(incl["ids"]) - set(main["ids"])          # the sensitivity set really adds cases back
    if main["pending"]:
        with pytest.raises(CM.AnalysisError, match="pending|depends on"):
            RG.resolve_set("main", root=ROOT, allow_pending=False)


# ------------------------------------------------------------------ paired on the toy matrix


def _args(**kw):
    ns = argparse.Namespace(a="C3L@2", b="C3E@2", registry=None, superseded=None, prereg=None, set=None,
                            incl_0905=False, allow_pending=False, outcome="correct", models=None, n_boot=200, seed=1,
                            out=None)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def test_matrix_cli_resolves_pending_sets_for_dev_data_only(toy, monkeypatch, tmp_path):
    """`registry.py matrix --allow-pending` resolves pending set lists as empty for a DEV matrix; a TEST matrix
    always gets the strict (final) set."""
    m = RG.build_matrix(_reg(toy), toy["root"])
    m_test = RG.Matrix([dict(r, split="test") for r in m.rows], dict(m.header, data="TEST"))
    monkeypatch.setattr(RG, "load_registry", lambda *a, **k: None)
    for mat, want in ((m, True), (m_test, False)):
        seen = []

        def fake_resolve(name, root=None, allow_pending=False, mat=mat, seen=seen):
            seen.append(allow_pending)
            return _aset(DEV, split={"DEV": "dev", "TEST": "test"}[mat.label], name=name)

        monkeypatch.setattr(RG, "build_matrix", lambda *a, mat=mat, **k: mat)
        monkeypatch.setattr(RG, "resolve_set", fake_resolve)
        assert RG.main(["matrix", "--allow-pending", "--out", str(tmp_path / "m.jsonl")]) == 0
        assert seen == [want], (mat.label, seen)


def test_paired_run_on_the_toy_matrix(toy, tmp_path):
    m = RG.build_matrix(_reg(toy), toy["root"])
    doc = PA.run(_args(), matrix=m, aset=_aset(DEV), prereg=PR.load())
    assert doc["data"] == "DEV" and doc["prereg"]["pending_used"] == {}
    # with the bootstrap settings still pending (the file before 2026-10-03), a dev analysis records the proposal
    draft = PA.run(_args(), matrix=m, aset=_aset(DEV), prereg=PR.load(draft_file(tmp_path)))
    assert draft["prereg"]["pending_used"]["bootstrap"]["n_boot"] == 10000
    (r,) = doc["results"]          # one benchmark: no pooled row
    wins = sum(1 for c in DEV if toy["a"][c] and not toy["b"][c])
    losses = sum(1 for c in DEV if toy["b"][c] and not toy["a"][c])
    assert (r["scope"], r["n"], r["wins"], r["losses"]) == ("toy", 8, wins, losses)
    assert r["mcnemar_exact_p"] == PA.mcnemar_exact(wins, losses)
    md = PA.render_md(doc)
    assert md.startswith("# [DEV] ") and "not a test result" in md
    # original-reference sets read correct_original_ref; error-type-only sets are refused
    doc2 = PA.run(_args(), matrix=m, aset=_aset(DEV, reference="original"), prereg=PR.load())
    assert doc2["results"][0]["field"] == "correct_original_ref"
    with pytest.raises(CM.AnalysisError, match="not a correctness signal"):
        PA.run(_args(), matrix=m, aset=_aset(DEV, reference="not_a_signal"), prereg=PR.load())
    # a case of the set that a label lacks
    with pytest.raises(CM.AnalysisError, match="lack a value"):
        PA.run(_args(), matrix=RG.restrict(m, _aset(DEV[:4])), aset=_aset(DEV), prereg=PR.load())


def test_test_data_refuses_pending_prereg_items(toy, tmp_path):
    m = RG.build_matrix(_reg(toy), toy["root"])
    m_test = RG.Matrix([dict(r, split="test") for r in m.rows], dict(m.header, data="TEST"))
    with pytest.raises(PR.PendingItem):
        PA.run(_args(), matrix=m_test, aset=_aset(DEV, split="test"), prereg=PR.load(draft_file(tmp_path)))


# ------------------------------------------------------------------ CLI on the reference fixture


def test_cli_add_check_matrix_on_the_fixture(tmp_path):
    reg = str(tmp_path / "reg.json")
    runs = sorted(os.listdir(os.path.join(ROOT, "reference/v5_dev_results/runs")))
    c0 = [r for r in runs if r.endswith("-dev-C0-np6000")]
    for run in c0:
        bench = "industryor" if "-industryor-" in run else "mamo_complex_lp"
        p = subprocess.run([PY, "-B", "analysis/r1/registry.py", "add", "--registry", reg, "--run",
                            f"reference/v5_dev_results/runs/{run}", "--results", "results.C0.jsonl", "--config", "C0",
                            "--model", "qwen3:8b", "--benchmark", bench, "--split", "dev"],
                           capture_output=True, text=True, timeout=60, cwd=ROOT)
        assert p.returncode == 0, p.stderr
    p = subprocess.run([PY, "-B", "analysis/r1/registry.py", "check", "--registry", reg], capture_output=True,
                       text=True, timeout=60, cwd=ROOT)
    assert p.returncode == 0 and "[registry] OK" in p.stdout
    out = str(tmp_path / "m.jsonl")
    p = subprocess.run([PY, "-B", "analysis/r1/registry.py", "matrix", "--registry", reg, "--set", "dev_all85",
                        "--out", out], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert p.returncode == 0, p.stderr
    lines = open(str(tmp_path / "m.DEV.jsonl"), encoding="utf-8").read().splitlines()
    head = json.loads(lines[0])
    assert head["data"] == "DEV" and head["analysis_set"]["name"] == "dev_all85" and len(lines) == 86
    assert not any(os.path.isabs(x["path"]) for x in head["runs"])
    # adding the same run twice is refused
    p = subprocess.run([PY, "-B", "analysis/r1/registry.py", "add", "--registry", reg, "--run",
                        f"reference/v5_dev_results/runs/{c0[0]}", "--results", "results.C0.jsonl", "--config", "C0",
                        "--model", "qwen3:8b", "--benchmark", "industryor", "--split", "dev"],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert p.returncode != 0 and "registered twice" in (p.stdout + p.stderr)


def _unit(root, run, case, config, content, reused_from=None, sha=None):
    sha = sha or hashlib.sha256(content.encode()).hexdigest()
    u = {"schema_version": RG.UNIT_SCHEMA, "case_id": case, "config_id": config, "repeat": 0,
         "round0": {"source": "reuse:C0" if reused_from else "own",
                    "reused_from": {"content_sha256": reused_from} if reused_from else None},
         "rounds": [{"round": 0, "calls": [{"call": {"content": content, "content_sha256": sha}}]}]}
    _write(os.path.join(root, run, "units", f"{case}.{config}.r0.json"), json.dumps(u))
    return sha


def test_round0_sha_from_unit_records_and_ladder_points(toy):
    root = toy["root"]
    shas = {c: _unit(root, "experiments/run-a", c, "C3L", f"answer {i}",
                     reused_from=hashlib.sha256(f"answer {i}".encode()).hexdigest()) for i, c in enumerate(DEV)}
    _unit(root, "experiments/run-a", DEV[0], "C0", "answer 0")          # another configuration in the same run: ignored
    _write(os.path.join(root, "experiments/run-a/units/setup.json"), json.dumps({"schema_version": "x"}))
    m = RG.build_matrix(_reg(toy), root)
    assert {r["case_id"]: r["round0_content_sha256"] for r in m.select("toy-model", "C3L@2")} == shas
    assert all(r["round0_content_sha256"] is None for r in m.select("toy-model", "C3E@2"))   # no records: unchanged
    # a ladder point reads the unit records of its source run
    _results(root, "experiments/run-a-r1", "C3L", toy["a"])
    _write(os.path.join(root, "experiments/run-a-r1/ladder.C3L.json"),
           json.dumps({"schema_version": RG.LADDER_SCHEMA, "condition": "C3L", "source_run": "run-a"}))
    runs = toy["runs"] + [_entry(root, "C3L@1", "C3L", "experiments/run-a-r1", 1, round0="reuse:C0")]
    m = RG.build_matrix(_reg(toy, runs), root)
    assert {r["case_id"]: r["round0_content_sha256"] for r in m.select("toy-model", "C3L@1")} == shas
    # a registered round0_gen_dir still takes precedence
    gen = os.path.join(root, "experiments/run-a/gen.C3L.r0/outputs")
    for c in DEV:
        _write(os.path.join(gen, f"{c}.json"), json.dumps({"case_id": c, "repeat": 0, "content": "batch", "meta": {"round": 0}}))
    runs2 = [dict(toy["runs"][0], round0_gen_dir="experiments/run-a/gen.C3L.r0"), toy["runs"][1]]
    m = RG.build_matrix(_reg(toy, runs2), root)
    assert {r["round0_content_sha256"] for r in m.select("toy-model", "C3L@2")} == {hashlib.sha256(b"batch").hexdigest()}


@pytest.mark.parametrize("kind,match", [("content", "not the hash of the recorded"), ("shared", "another content sha256"),
                                        ("ladder", "sibling source run")])
def test_round0_sha_from_unit_records_refuses_inconsistent_records(toy, kind, match):
    root = toy["root"]
    for i, c in enumerate(DEV):
        _unit(root, "experiments/run-a", c, "C3L", f"answer {i}")
    runs = toy["runs"]
    if kind == "content":
        _unit(root, "experiments/run-a", DEV[0], "C3L", "answer 0", sha="0" * 64)
    elif kind == "shared":
        _unit(root, "experiments/run-a", DEV[0], "C3L", "answer 0", reused_from="1" * 64)
    else:
        _results(root, "experiments/run-a-r1", "C3L", toy["a"])
        _write(os.path.join(root, "experiments/run-a-r1/ladder.C3L.json"),
               json.dumps({"schema_version": RG.LADDER_SCHEMA, "condition": "C3L", "source_run": "../elsewhere"}))
        runs = runs + [_entry(root, "C3L@1", "C3L", "experiments/run-a-r1", 1, round0="reuse:C0")]
    with pytest.raises(RG.RegistryError, match=match):
        RG.build_matrix(_reg(toy, runs), root)
