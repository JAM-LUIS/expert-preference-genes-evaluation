"""E22: engineering-source case set -- template rendering, MIPLIB-NL conversion, eng_holdout split, isolation check,
execution timeouts (60 s and 600 s from the same outputs) and the working-tree case file.

Fixtures are self-made toy instances (a 2-unit, 3-hour unit commitment; a two-file MIPLIB-NL-style directory; toy
programs). The working-tree tests read data/cases/eng.jsonl only to hash and count; no problem text is printed.
"""
import hashlib
import importlib.util
import itertools
import json
import math
import os
import subprocess
import sys
import threading

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)
sys.path.insert(0, os.path.join(ROOT, "data"))

import pulp  # noqa: E402  (Homebrew interpreter: PuLP + CBC, as for generated programs)

from orgene import cli as CLI  # noqa: E402
from orgene import configs as CF  # noqa: E402
from orgene import conditions as C  # noqa: E402
from orgene import data as D  # noqa: E402
from orgene import env as E  # noqa: E402
from orgene import genes as G  # noqa: E402
from orgene import pipeline as P  # noqa: E402
from orgene import reexec as RX  # noqa: E402
from orgene import split as S  # noqa: E402
from orgene.conditions import read_jsonl, write_jsonl  # noqa: E402
from orgene.execute import run_program  # noqa: E402
from orgene.paths import find_absolute_paths  # noqa: E402

from eng import miplib_nl_convert as MC  # noqa: E402
from eng import pglib_uc_render as UR  # noqa: E402
from eng.reference import cbc as CBC  # noqa: E402
from eng.reference import pglib_uc as UCM  # noqa: E402
from eng.reference import pglib_uc_check as UCK  # noqa: E402

_spec = importlib.util.spec_from_file_location("check_test_isolation", os.path.join(ROOT, "analysis", "check_test_isolation.py"))
CTI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CTI)
_spec2 = importlib.util.spec_from_file_location("ingest_eng", os.path.join(ROOT, "data", "ingest_eng.py"))
ING = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(ING)

STORE = os.path.join(ROOT, "genes", "genes.r1.jsonl")
REGISTRY = os.path.join(ROOT, "configs", "r1_configs.json")
PY = E.orgene_python()
# Recorded with the template (data/eng/pglib_uc_render.py). Editing the wording means a new TEMPLATE_VERSION, a new
# hash here, re-rendered cases and a new freeze entry.
TEMPLATE_SHA256 = {"pglib_uc.v1": "f08081a21bcc3bbece9d761b715e3f6ef5fe970a8a30ef215bd934f9e36c600a"}


# ------------------------------------------------------------------ a toy unit-commitment instance (self-made)


def toy_uc():
    gen = lambda **kw: dict({"must_run": 0, "unit_on_t0": 0, "time_up_t0": 0, "time_down_t0": 3,  # noqa: E731
                             "power_output_t0": 0.0, "ramp_up_limit": 40.0, "ramp_down_limit": 40.0,
                             "ramp_startup_limit": 30.0, "ramp_shutdown_limit": 30.0,
                             "time_up_minimum": 2, "time_down_minimum": 2}, **kw)
    return {
        "time_periods": 3, "demand": [50.0, 80.0, 60.5], "reserves": [5.0, 10.0, 0.0],
        "thermal_generators": {
            "base": gen(unit_on_t0=1, time_up_t0=4, time_down_t0=0, power_output_t0=40.0,
                        power_output_minimum=20.0, power_output_maximum=60.0,
                        piecewise_production=[{"mw": 20.0, "cost": 300.0}, {"mw": 40.0, "cost": 500.0}, {"mw": 60.0, "cost": 800.0}],
                        startup=[{"lag": 1, "cost": 100.0}, {"lag": 3, "cost": 250.0}]),
            "peak": gen(power_output_minimum=10.0, power_output_maximum=50.0, time_down_t0=1,
                        piecewise_production=[{"mw": 10.0, "cost": 400.0}, {"mw": 50.0, "cost": 1400.0}],
                        startup=[{"lag": 1, "cost": 50.0}, {"lag": 2, "cost": 90.0}, {"lag": 4, "cost": 200.0}]),
        },
        "renewable_generators": {
            "w1": {"power_output_minimum": [0.0, 0.0, 0.1], "power_output_maximum": [10.0, 5.5, 0.1]},
            "w2": {"power_output_minimum": [0.0, 0.0, 0.2], "power_output_maximum": [0.0, 12.25, 0.2]},
        },
    }


def test_render_is_deterministic_to_the_byte(tmp_path):
    inst = toy_uc()
    t1, i1 = UR.render(inst)
    t2, _ = UR.render(json.loads(json.dumps(inst)))
    p = tmp_path / "inst.json"
    p.write_text(json.dumps(inst, indent=3))
    t3, _ = UR.render_file(str(p))
    assert t1.encode("utf-8") == t2.encode("utf-8") == t3.encode("utf-8")
    assert i1["text_sha256"] == hashlib.sha256(t1.encode("utf-8")).hexdigest()


def test_template_hash_is_pinned_to_its_version():
    assert hashlib.sha256(UR.TEMPLATE.encode("utf-8")).hexdigest() == TEMPLATE_SHA256[UR.TEMPLATE_VERSION]


def test_render_carries_every_number_and_exact_decimal_totals():
    inst = toy_uc()
    text, info = UR.render(inst)
    assert info["n_thermal"] == 2 and info["n_cost_points"] == 5 and info["n_startup_categories"] == 5
    # renewable totals are decimal sums of the file's numbers (binary 0.1 + 0.2 would print 0.30000000000000004)
    assert "\n3,60.5,0.0,0.3,0.3\n" in text and "\n2,80.0,10.0,0.0,17.75\n" in text
    assert "\n1,0,1,4,0,40.0,20.0,60.0,40.0,40.0,30.0,30.0,2,2\n" in text  # unit 1, columns in UNIT_KEYS order
    assert "\n2,3,4,200.0\n" in text and "\n1,3,60.0,800.0\n" in text
    assert "base" not in text and "peak" not in text  # units are numbered, names are not shown
    inst["renewable_generators"] = {}
    text2, _ = UR.render(inst)
    assert "no renewable units" in text2 and "renewable_min" not in text2


@pytest.mark.parametrize("breakit, what", [
    (lambda i: i["thermal_generators"]["base"]["piecewise_production"].__setitem__(1, {"mw": 40.0, "cost": 700.0}), "convex"),
    (lambda i: i["thermal_generators"]["peak"].__setitem__("time_up_minimum", 0), "minimum up/down"),
    (lambda i: i["thermal_generators"]["peak"]["startup"].__setitem__(1, {"lag": 1, "cost": 90.0}), "lags"),
    (lambda i: i["thermal_generators"]["peak"]["startup"].__setitem__(2, {"lag": 4, "cost": 60.0}), "cheaper"),
    (lambda i: i["thermal_generators"]["base"].__setitem__("power_output_minimum", 25.0), "Pmin to Pmax"),
    (lambda i: i["thermal_generators"]["peak"].__setitem__("power_output_t0", 5.0), "off before"),
    (lambda i: i.__setitem__("demand", [1.0, 2.0]), "time_periods"),
])
def test_render_refuses_an_instance_the_wording_would_misstate(breakit, what):
    inst = toy_uc()
    breakit(inst)
    with pytest.raises(UR.RenderError, match=what):
        UR.render(inst)


def _lp_given_commitment(inst, u):
    """Cheapest dispatch for a fixed commitment (continuous LP), start-up cost from the checker's category rule.
    Independent of the reference MILP; None when infeasible."""
    T, th, rn = inst["time_periods"], inst["thermal_generators"], inst["renewable_generators"]
    lp = pulp.LpProblem("fixed_u", pulp.LpMinimize)
    p = {(g, t): pulp.LpVariable(f"p_{k}_{t}", 0) for k, g in enumerate(th) for t in range(T)}
    r = {(g, t): pulp.LpVariable(f"r_{k}_{t}", 0) for k, g in enumerate(th) for t in range(T)}
    c = {(g, t): pulp.LpVariable(f"c_{k}_{t}") for k, g in enumerate(th) for t in range(T)}
    pw = {(w, t): pulp.LpVariable(f"pw_{k}_{t}", rn[w]["power_output_minimum"][t], rn[w]["power_output_maximum"][t])
          for k, w in enumerate(rn) for t in range(T)}
    lp += pulp.lpSum(c.values())
    for t in range(T):
        lp += pulp.lpSum(p[g, t] + th[g]["power_output_minimum"] * u[g][t] for g in th) + pulp.lpSum(pw[w, t] for w in rn) == inst["demand"][t]
        lp += pulp.lpSum(r[g, t] for g in th) >= inst["reserves"][t]
    for g, gen in th.items():
        prev = [gen["unit_on_t0"]] + u[g][:-1]
        v = [max(a - b, 0) for a, b in zip(u[g], prev)]
        w = [max(b - a, 0) for a, b in zip(u[g], prev)]
        span = gen["power_output_maximum"] - gen["power_output_minimum"]
        su = max(gen["power_output_maximum"] - gen["ramp_startup_limit"], 0)
        sd = max(gen["power_output_maximum"] - gen["ramp_shutdown_limit"], 0)
        p0 = gen["unit_on_t0"] * (gen["power_output_t0"] - gen["power_output_minimum"])
        pts = [(q["mw"] - gen["piecewise_production"][0]["mw"], q["cost"] - gen["piecewise_production"][0]["cost"])
               for q in gen["piecewise_production"]]
        for t in range(T):
            lp += p[g, t] + r[g, t] <= span * u[g][t] - su * v[t]
            if t + 1 < T:
                lp += p[g, t] + r[g, t] <= span * u[g][t] - sd * w[t + 1]
            prev_p = p[g, t - 1] if t else p0
            lp += p[g, t] + r[g, t] - prev_p <= gen["ramp_up_limit"]
            lp += prev_p - p[g, t] <= gen["ramp_down_limit"]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):  # convex curve: cost above every segment line
                lp += c[g, t] >= y1 * u[g][t] + (y2 - y1) / (x2 - x1) * (p[g, t] - x1 * u[g][t])
            lp += c[g, t] >= 0
    lp.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[lp.status] != "Optimal":
        return None
    sched = {"u": u, "p": {g: [p[g, t].varValue for t in range(T)] for g in th},
             "r": {g: [r[g, t].varValue for t in range(T)] for g in th},
             "pw": {w: [pw[w, t].varValue for t in range(T)] for w in rn}}
    bad, cost = UCK.check(inst, sched, tol=1e-6)
    return None if bad else cost


def test_reference_model_equals_brute_force_over_commitments_and_the_checker():
    """The reference MILP (MODEL.tex) and an independent reading of the wording (checker + LP per commitment
    schedule, all 2^(units x hours) schedules) give the same optimum on the toy instance."""
    inst = toy_uc()
    prob, index = UCM.build(inst)
    rec, values = CBC.solve(prob, 60)
    assert rec["status"] == "optimal" and rec["cbc_version"]
    sched = UCM.schedule_from(index, values)
    bad, cost = UCK.check(inst, sched)
    assert bad == [] and math.isclose(cost, rec["objective"], rel_tol=1e-9)
    names = list(inst["thermal_generators"])
    best = None
    for bits in itertools.product((0, 1), repeat=len(names) * inst["time_periods"]):
        u = {g: list(bits[k * 3:(k + 1) * 3]) for k, g in enumerate(names)}
        cst = _lp_given_commitment(inst, u)
        if cst is not None and (best is None or cst < best):
            best = cst
    assert best is not None and math.isclose(best, rec["objective"], rel_tol=1e-7)


def test_checker_catches_a_broken_schedule():
    inst = toy_uc()
    prob, index = UCM.build(inst)
    _, values = CBC.solve(prob, 60)
    sched = UCM.schedule_from(index, values)
    sched["u"]["peak"] = [1, 0, 1]  # starts, stops after one hour (minimum up time 2)
    bad, _ = UCK.check(inst, sched)
    assert any("minimum up time" in b or "demand" in b for b in bad)


# ------------------------------------------------------------------ MIPLIB-NL conversion (self-made directory)


def toy_mnl(tmp_path, csv_text="a,b\n1,2\n3,4\n", extra_files=None):
    d = tmp_path / "toy-instance"
    (d / "data").mkdir(parents=True)
    inst = {"abstract_problem": "  A toy planning problem.\nChoose x to minimise cost.  ",
            "parameters": {"n": 2, "cap": "7"},
            "files": {"table": {"path": "./data/t.csv", "description": "Columns a, b.\n| a | b |"}},
            "optimal_value": 987654321}
    inst["files"].update(extra_files or {})
    (d / "instance.json").write_text(json.dumps(inst))
    (d / "data" / "t.csv").write_text(csv_text)
    return str(d)


def test_miplib_nl_text_keeps_the_wording_and_inlines_the_data(tmp_path):
    d = toy_mnl(tmp_path)
    text, info = MC.convert(d)
    assert text.startswith("A toy planning problem.\nChoose x to minimise cost.\n")
    assert '"cap": "7"' in text and "File `table` (./data/t.csv):\nColumns a, b.\n| a | b |\nContents:\n```csv\na,b\n1,2\n3,4\n```\n" in text
    assert "987654321" not in text  # the published optimal value never enters the text
    assert MC.convert(d)[0] == text and info["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert MC.official_value(d) == 987654321.0


@pytest.mark.parametrize("mutate, what", [
    (lambda d: os.remove(os.path.join(d, "data", "t.csv")), "missing"),
    (lambda d: open(os.path.join(d, "data", "t.csv"), "w").write("﻿a,b\n"), "byte-order"),
    (lambda d: open(os.path.join(d, "data", "t.csv"), "w").write("a\n```\n"), "code fence"),
])
def test_miplib_nl_conversion_refuses_what_it_cannot_carry_verbatim(tmp_path, mutate, what):
    d = toy_mnl(tmp_path)
    mutate(d)
    with pytest.raises(MC.ConvertError, match=what):
        MC.convert(d)


def test_miplib_nl_file_outside_the_instance_is_refused(tmp_path):
    d = toy_mnl(tmp_path, extra_files={"x": {"path": "../outside.csv", "description": ""}})
    (tmp_path / "outside.csv").write_text("a\n")
    with pytest.raises(MC.ConvertError, match="outside"):
        MC.convert(d)


# ------------------------------------------------------------------ eng_holdout split and the isolation check


def _toy_repo(root):
    """Scratch repository: 6 toy 'industryor' cases frozen 2 dev / 4 test, two engineering cases in their own
    eng_holdout split, a gene library, a condition and a dev run."""
    raw = root / "data" / "raw" / "toy.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps([{"en_question": f"maximise {i}x", "en_answer": str(i)} for i in range(1, 7)]))
    cases = root / "data" / "cases" / "industryor.jsonl"
    D.build_cases("industryor", str(raw), str(cases))
    sd = root / "data" / "splits" / "industryor"
    S.make_split(str(cases), str(sd), n_dev=2, seed=3)
    lock = json.loads((sd / "SPLIT_LOCK.json").read_text())
    lock["cases_path"] = "data/cases/industryor.jsonl"
    (sd / "SPLIT_LOCK.json").write_text(json.dumps(lock, indent=2))
    dev = json.loads((sd / "dev_ids.json").read_text())
    eng = root / "data" / "cases" / "eng.jsonl"
    eng.write_text("".join(json.dumps(r) + "\n" for r in [
        {"_header": True, "source": "eng"},
        {"case_id": "pglib_uc-0001", "source": "pglib_uc", "text": "toy", "reference": {"objective": 1.0, "status": None}},
        {"case_id": "miplib_nl-0001", "source": "miplib_nl", "text": "toy", "reference": {"objective": 2.0, "status": None}}]))
    S.freeze_eng_holdout(str(eng), str(root / "data" / "splits" / "eng"), existing_split_dirs=[str(sd)])
    lk = json.loads((root / "data" / "splits" / "eng" / "SPLIT_LOCK.json").read_text())
    lk["cases_path"] = "data/cases/eng.jsonl"
    (root / "data" / "splits" / "eng" / "SPLIT_LOCK.json").write_text(json.dumps(lk, indent=2))
    (root / "genes").mkdir()
    (root / "genes" / "genes.r1.jsonl").write_text(json.dumps({"geneId": "orgene.toy.rule", "audit": {"devCaseIds": dev[:1]},
                                                              "activation": {"rule": "always", "devEvidence": dev[:1]}}) + "\n")
    (root / "conditions").mkdir()
    (root / "conditions" / "C0.md").write_text("Write a PuLP program.\n")
    run = root / "experiments" / "20261001-toy-industryor-dev-C0"
    run.mkdir(parents=True)
    (run / "requests.C0.jsonl").write_text("".join(json.dumps({"case_id": c, "condition": "C0"}) + "\n" for c in dev))
    return dev


def _iso(root, capsys):
    code = CTI.main(["--root", str(root)])
    return code, capsys.readouterr().out


def test_freeze_eng_holdout_writes_an_all_holdout_split(tmp_path):
    _toy_repo(tmp_path)
    d = tmp_path / "data" / "splits" / "eng"
    lock, dev, test = S.read_lock_dir(str(d))
    assert dev == [] and test == [] and lock["kind"] == "eng_holdout" and lock["n_eng_holdout"] == 2
    assert S.load_split_ids(str(d), "eng_holdout") == {"pglib_uc-0001", "miplib_nl-0001"}
    assert lock["eng_holdout_sha256"] == S.ids_sha256(["miplib_nl-0001", "pglib_uc-0001"])
    assert S.verify_eng_holdout(str(d), str(tmp_path / "data" / "cases" / "eng.jsonl")) == []
    # same inputs again: no change; an id that belongs to another frozen split is refused
    S.freeze_eng_holdout(str(tmp_path / "data" / "cases" / "eng.jsonl"), str(tmp_path / "x"))
    clash = tmp_path / "clash.jsonl"
    test_id = json.loads((tmp_path / "data" / "splits" / "industryor" / "test_ids.json").read_text())[0]
    clash.write_text(json.dumps({"_header": True}) + "\n" + json.dumps({"case_id": test_id, "text": "t", "reference": {}}) + "\n")
    with pytest.raises(ValueError, match="already belong"):
        S.freeze_eng_holdout(str(clash), str(tmp_path / "y"), existing_split_dirs=[str(tmp_path / "data" / "splits" / "industryor")])


@pytest.mark.parametrize("tamper, what", [
    ("drop_id", "does not match the lock"),
    ("swap_id_same_count", "does not match the lock"),  # E22 verification: the count alone does not catch this
    ("cases_changed", "cases file changed"),            # E22 verification: a case file edited after the freeze
])
def test_verify_eng_holdout_catches_tampering(tmp_path, tamper, what):
    _toy_repo(tmp_path)
    d = tmp_path / "data" / "splits" / "eng"
    cases = tmp_path / "data" / "cases" / "eng.jsonl"
    if tamper == "drop_id":
        (d / "eng_holdout_ids.json").write_text(json.dumps(["pglib_uc-0001"], indent=0))
    elif tamper == "swap_id_same_count":
        (d / "eng_holdout_ids.json").write_text(json.dumps(["miplib_nl-0002", "pglib_uc-0001"], indent=0))
    else:
        cases.write_text(cases.read_text().replace('"objective": 2.0', '"objective": 2.5'))
    assert any(what in p for p in S.verify_eng_holdout(str(d), str(cases)))


def test_isolation_check_passes_on_the_clean_toy_repo(tmp_path, capsys):
    _toy_repo(tmp_path)
    code, out = _iso(tmp_path, capsys)
    assert code == 0 and "RESULT: PASS" in out and "eng_holdout eng=2" in out and "eng_holdout_sha256" in out
    assert not find_absolute_paths(out)


@pytest.mark.parametrize("where", ["dev_request", "gene_devCaseIds", "gene_devEvidence", "conditions_text", "gene_text"])
def test_eng_holdout_id_reaching_dev_material_fails(tmp_path, capsys, where):
    dev = _toy_repo(tmp_path)
    if where == "dev_request":
        req = tmp_path / "experiments" / "20261001-toy-industryor-dev-C0" / "requests.C0.jsonl"
        with open(req, "a") as f:
            f.write(json.dumps({"case_id": "pglib_uc-0001", "condition": "C0", "request_id": "pglib_uc-0001.C0.rep0"}) + "\n")
    elif where == "conditions_text":
        (tmp_path / "conditions" / "C0.md").write_text("as in miplib_nl-0001, read the table\n")
    elif where == "gene_text":  # an id in the free text of a gene file (not in an id field)
        (tmp_path / "genes" / "notes.md").write_text("checked against pglib_uc-0001 before release\n")
    else:
        field = "audit" if where == "gene_devCaseIds" else "activation"
        g = {"geneId": "orgene.toy.rule", "audit": {"devCaseIds": dev[:1]}, "activation": {"rule": "always", "devEvidence": dev[:1]}}
        g[field]["devCaseIds" if field == "audit" else "devEvidence"] = dev[:1] + ["pglib_uc-0001"]
        (tmp_path / "genes" / "genes.r1.jsonl").write_text(json.dumps(g) + "\n")
    code, out = _iso(tmp_path, capsys)
    assert code == 1 and ("pglib_uc-0001" in out or "miplib_nl-0001" in out)
    assert "RESULT: FAIL" in out


def test_dev_evidence_must_be_a_dev_id_even_when_it_is_not_held_out(tmp_path, capsys):
    """Fails on the pre-E22 check (it read audit.devCaseIds only): an id that is neither dev nor held out."""
    dev = _toy_repo(tmp_path)
    g = {"geneId": "orgene.toy.rule", "audit": {"devCaseIds": dev[:1]}, "activation": {"rule": "always", "devEvidence": ["smoke-0001"]}}
    (tmp_path / "genes" / "genes.r1.jsonl").write_text(json.dumps(g) + "\n")
    code, out = _iso(tmp_path, capsys)
    assert code == 1 and "activation.devEvidence: smoke-0001 (not a frozen dev id)" in out


def test_eng_holdout_runs_are_skipped_like_test_runs(tmp_path, capsys):
    """Fails on the pre-E22 check, which opened this run and reported the engineering ids as leaks."""
    _toy_repo(tmp_path)
    run = tmp_path / "experiments" / "20261001-toy-eng-eng_holdout-C0"
    run.mkdir()
    (run / "requests.C0.jsonl").write_text(json.dumps({"case_id": "pglib_uc-0001"}) + "\n")
    code, out = _iso(tmp_path, capsys)
    assert code == 0 and "1 eng_holdout run(s) skipped by design" in out


def test_tampered_eng_holdout_id_file_fails_the_isolation_check(tmp_path, capsys):
    _toy_repo(tmp_path)
    (tmp_path / "data" / "splits" / "eng" / "eng_holdout_ids.json").write_text(json.dumps(["miplib_nl-0001"], indent=0))
    code, out = _iso(tmp_path, capsys)
    assert code == 1 and "eng_holdout_sha256" in out and "!= lock" in out


# ------------------------------------------------------------------ execution timeouts


PROG = """import time
import pulp
time.sleep({sleep})
{error}prob = pulp.LpProblem("t", pulp.LpMaximize)
a = pulp.LpVariable("a", 0, 10)
prob += a
prob += a <= 7
prob.solve(pulp.PULP_CBC_CMD(msg=0))
print("STATUS:", pulp.LpStatus[prob.status])
print("FINAL_OBJECTIVE:", pulp.value(prob.objective))
"""


def prog(sleep=0.0, error=False):
    return PROG.format(sleep=sleep, error="raise ValueError('boom')\n" if error else "")


def test_registry_holds_the_two_timeouts():
    t = RX.execution_timeouts()
    assert t == {"timeout_s": 60, "timeout_s_engineering_cases": 600}


def test_same_program_at_60_and_600_seconds():
    """One program that needs 61 s: timed out at the main timeout, finished at the engineering-case timeout.
    Both executions run at the same time, so the test takes about a minute."""
    t = RX.execution_timeouts()
    code = prog(sleep=61)
    res = {}
    threads = [threading.Thread(target=lambda k=k: res.__setitem__(k, run_program(code, timeout=t[k], python=PY)))
               for k in ("timeout_s", "timeout_s_engineering_cases")]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    short, long_ = res["timeout_s"], res["timeout_s_engineering_cases"]
    assert short["timed_out"] and not short["exec_ok"] and short["objective"] is None
    assert 59 < short["seconds"] < 90
    assert not long_["timed_out"] and long_["exec_ok"] and long_["objective"] == 7.0 and long_["status"] == "Optimal"


def test_validate_takes_its_default_timeout_from_the_registry(tmp_path, monkeypatch):
    cases = tmp_path / "toy.jsonl"
    cases.write_text(json.dumps({"_header": True, "source": "toy"}) + "\n" +
                     json.dumps({"case_id": "toy-0001", "source": "toy", "text": "t", "reference": {"objective": 7.0, "status": None}}) + "\n")
    seen = {}
    monkeypatch.setattr(P, "validate_round", lambda *a, **k: seen.update(k) or {"n_validated": 0})
    monkeypatch.setattr(E, "require_env", lambda *a, **k: {"ok": True})
    run = tmp_path / "run"
    run.mkdir()
    CLI.main(["validate", "--run", str(run), "--cases", str(cases), "--cond", "C0"])
    assert seen["timeout"] == 60
    CLI.main(["validate", "--run", str(run), "--cases", str(cases), "--cond", "C0", "--timeout", "600"])
    assert seen["timeout"] == 600


# ------------------------------------------------------------------ re-execution of the same outputs


def _outputs(gen_dir, reqs, answer):
    os.makedirs(os.path.join(gen_dir, "outputs"), exist_ok=True)
    for r in reqs:
        content = "```python\n" + answer[r["case_id"]] + "```\n"
        rec = {"request_id": r["request_id"], "case_id": r["case_id"], "condition": r["condition"], "meta": r["meta"],
               "repeat": 0, "ok": True, "done_reason": "stop", "content": content, "eval_count": 10, "prompt_eval_count": 10}
        with open(os.path.join(gen_dir, "outputs", f"{r['request_id']}.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f)


def test_reexecution_replays_the_same_outputs_at_a_longer_timeout(tmp_path):
    """Short timeout 1 s, long 20 s (the rule is the same at 60 s / 600 s):
    slow  -- round 0 needs 3 s: timed out at 1 s and repaired; at 20 s accepted in round 0, round 1 unused;
    error -- round 0 fails the same way at both timeouts: the rebuilt repair request is identical, its output reused;
    slowerr -- round 0 sleeps 3 s then fails: the repair message differs (timeout vs error), so the unit diverges."""
    reg = CF.load_registry(REGISTRY)
    cfg = CF.get_config(reg, "C3E")
    kw = {"gene_scope": cfg["gene_scope"], "repair": cfg["repair"], "closing": cfg["closing"]}
    cases = [{"case_id": f"toy-{n}", "source": "toy", "text": "Maximise a with 0 <= a <= 7.",
              "reference": {"objective": 7.0, "raw": "7", "status": None}} for n in ("slow", "error", "slowerr")]
    by_id = {c["case_id"]: c for c in cases}
    run = str(tmp_path / "run-eng_holdout-C3E")
    os.makedirs(run)
    reqs = C.build_requests(cases, cfg, G.load_store(STORE), "toy")
    write_jsonl(os.path.join(run, "requests.C3E.jsonl"), reqs)
    _outputs(os.path.join(run, "gen.C3E.r0"), reqs,
             {"toy-slow": prog(sleep=3), "toy-error": prog(error=True), "toy-slowerr": prog(sleep=3, error=True)})
    P.validate_round(run, "C3E", 0, os.path.join(run, "gen.C3E.r0"), by_id, STORE, timeout=1, act=True, max_rounds=2, python=PY, **kw)
    rep1 = read_jsonl(os.path.join(run, "requests.C3E.repair1.jsonl"))
    assert sorted(r["case_id"] for r in rep1) == ["toy-error", "toy-slow", "toy-slowerr"]
    _outputs(os.path.join(run, "gen.C3E.repair1"), rep1, {c["case_id"]: prog() for c in cases})
    P.validate_round(run, "C3E", 1, os.path.join(run, "gen.C3E.repair1"), by_id, STORE, timeout=1, act=True, max_rounds=2, python=PY, **kw)
    short = {v["case_id"]: v for v in read_jsonl(os.path.join(run, "final.C3E.jsonl"))}
    assert all(len(v["rounds"]) == 2 and v["exec"]["objective"] == 7.0 for v in short.values())
    assert short["toy-slow"]["exec_timeout_s"] == 1

    out = str(tmp_path / "run-eng_holdout-C3E.t20")
    s = RX.reexecute(run, out, "C3E", by_id, STORE, 20, act=True, max_rounds=2, python=PY, validate_kw=kw)
    long_ = {v["case_id"]: v for v in read_jsonl(os.path.join(out, "final.C3E.jsonl"))}
    assert len(long_["toy-slow"]["rounds"]) == 1 and not long_["toy-slow"]["exec"]["timed_out"]
    assert long_["toy-slow"]["exec"]["objective"] == 7.0 and long_["toy-slow"]["exec_timeout_s"] == 20
    assert len(long_["toy-error"]["rounds"]) == 2 and long_["toy-error"]["exec"]["objective"] == 7.0
    assert long_["toy-slowerr"]["provisional"] and len(long_["toy-slowerr"]["rounds"]) == 1
    assert s["n_diverged"] == 1 and s["diverged"][0]["case_id"] == "toy-slowerr" and s["diverged"][0]["reason"] == "repair request differs"
    assert json.load(open(os.path.join(out, "run_config.json")))["reexec"]["timeout_s"] == 20
    # the original run is untouched (its round 0 still timed out), and the new directory is never overwritten
    r0 = {v["case_id"]: v for v in read_jsonl(os.path.join(run, "validated.C3E.round0.jsonl"))}
    assert r0["toy-slow"]["exec"]["timed_out"] is True and r0["toy-slow"]["exec_timeout_s"] == 1
    with pytest.raises(FileExistsError):
        RX.reexecute(run, out, "C3E", by_id, STORE, 20, python=PY, validate_kw=kw)
    rows = RX.compare_timeouts(run, out, "C3E")
    assert {r["case_id"]: r["rounds"] for r in rows} == {"toy-error": [2, 2], "toy-slow": [2, 1], "toy-slowerr": [2, 1]}


def test_reexec_tool_runs_on_a_dev_style_run(tmp_path):
    cases = tmp_path / "toy.jsonl"
    rows = [{"case_id": "toy-0001", "source": "toy", "text": "Maximise a with 0 <= a <= 7.", "reference": {"objective": 7.0, "raw": "7", "status": None}}]
    cases.write_text(json.dumps({"_header": True, "source": "toy"}) + "\n" + "".join(json.dumps(r) + "\n" for r in rows))
    reg = CF.load_registry(REGISTRY)
    cfg = CF.get_config(reg, "C0")
    run = tmp_path / "20261001-toy-toy-dev-C0"
    run.mkdir()
    reqs = C.build_requests(rows, cfg, G.load_store(STORE), "toy")
    write_jsonl(str(run / "requests.C0.jsonl"), reqs)
    _outputs(str(run / "gen.C0.r0"), reqs, {"toy-0001": prog(sleep=2)})
    P.validate_round(str(run), "C0", 0, str(run / "gen.C0.r0"), {r["case_id"]: r for r in rows}, STORE, timeout=1, act=False, python=PY)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "reexec_timeout.py"), "--run", str(run), "--cases", str(cases),
                        "--cond", "C0", "--timeout", "15"], capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["n_units"] == 1 and out["n_timed_out_final"] == 0 and out["timeout_s"] == 15
    assert os.path.exists(str(run) + ".t15/final.C0.jsonl")


# ------------------------------------------------------------------ the working tree's case set


CASES_PATH = os.path.join(ROOT, "data", "cases", "eng.jsonl")
needs_cases = pytest.mark.skipif(not os.path.exists(CASES_PATH), reason="no data/cases/eng.jsonl in this checkout")


@needs_cases
def test_eng_cases_file_format_and_hashes():
    data = open(CASES_PATH, "rb").read()
    lines = data.decode("utf-8").splitlines()
    header, rows = json.loads(lines[0]), [json.loads(x) for x in lines[1:]]
    assert header["_header"] and header["source"] == "eng" and header["n"] == len(rows) == 8
    hashes = json.load(open(os.path.join(ROOT, "data", "eng", "eng_hashes.json")))
    assert hashes["cases_sha256"] == hashlib.sha256(data).hexdigest()
    assert header["reference_values_sha256"] == hashlib.sha256(open(os.path.join(ROOT, "data", "eng", "reference_values.json"), "rb").read()).hexdigest()
    ids = [r["case_id"] for r in rows]
    assert ids == sorted(ids) and len(set(ids)) == 8
    assert sum(1 for r in rows if r["source"] == "pglib_uc") == 2 and sum(1 for r in rows if r["source"] == "miplib_nl") == 6
    held = json.load(open(os.path.join(ROOT, "data", "splits", "eng", "eng_holdout_ids.json")))
    assert held == ids and hashes["ids"] == ids
    for r in rows:
        assert set(r) == {"case_id", "source", "source_id", "text", "reference", "extra", "license"}
        ref = r["reference"]["objective"]
        assert isinstance(ref, float) and math.isfinite(ref) and r["reference"]["status"] is None
        assert r["extra"]["reference_kind"] in ("cbc_optimal", "cbc_attains_published_optimum", "cbc_time_limited")
        assert r["extra"]["reference_solver"]["cbc_version"] and r["license"]
        # the reference carries its kind; a time-limited one carries [bound, best value], which holds the best value
        kind, iv = r["reference"]["kind"], r["reference"]["interval"]
        assert kind == r["extra"]["reference_kind"] and iv == r["extra"]["reference_interval"]
        assert (iv is not None) == (kind == "cbc_time_limited")
        if iv is not None:
            rs = r["extra"]["reference_solver"]
            assert iv == sorted([rs["bound"], ref]) and iv[0] <= ref <= iv[1] and rs["status"] == "time_limit_feasible"
        h = hashes["cases"][r["case_id"]]
        assert h["text_sha256"] == hashlib.sha256(r["text"].encode("utf-8")).hexdigest()
        assert h["reference_objective"] == ref
        assert not find_absolute_paths(json.dumps(r, ensure_ascii=False))
        assert isinstance(r["extra"]["source_text_issues"], list)
    # defects of the benchmark's own wording found by the E22 verification; the texts stay verbatim
    assert [r["case_id"] for r in rows if r["extra"]["source_text_issues"]] == ["miplib_nl-0005", "miplib_nl-0006"]
    assert S.verify_eng_holdout(os.path.join(ROOT, "data", "splits", "eng"), CASES_PATH) == []


def test_selection_record_matches_the_seeded_rule():
    sel = json.load(open(os.path.join(ROOT, "data", "eng", "selection.json")))
    assert ING.check_selection(sel) == []


def test_selection_check_catches_a_hand_picked_instance():
    sel = json.load(open(os.path.join(ROOT, "data", "eng", "selection.json")))
    first = next(c for c in sel["cases"] if c["source"] == "miplib_nl")
    first["source_id"] = "air03"  # not the first eligible instance of its stratum
    assert any("chosen" in p for p in ING.check_selection(sel))


@pytest.mark.parametrize("tamper", ["objective_off_published", "no_fit", "t_stratum_time_limited", "flag_only"])
def test_selection_check_rederives_eligibility_from_the_evidence(tamper):
    """Fails on the E22 check before verification, which trusted each screening entry's `eligible` flag."""
    sel = json.load(open(os.path.join(ROOT, "data", "eng", "selection.json")))
    scr = sel["miplib_nl_screening"]
    first_t = sel["miplib_nl_rule"]["picks"]["T"][0]
    e = scr[first_t]
    if tamper == "objective_off_published":  # CBC's incumbent no longer equals the published optimum
        e["cbc"]["objective"] = e["official_value"] + 1.0 + abs(e["official_value"])
    elif tamper == "no_fit":  # round-0 prompt too long for num_ctx
        e["tokens"]["max_prompt"] = ING.NUM_CTX
    elif tamper == "t_stratum_time_limited":  # a stratum-T instance whose interval holds the published value, not reached
        lower = e["cbc"]["bound"] < e["official_value"]  # a minimisation: the incumbent lies above the published value
        e["cbc"]["objective"] = e["official_value"] + (0.5 if lower else -0.5)
    else:  # an ineligible instance flagged eligible: the flag alone must not decide
        name = next(n for n, v in scr.items() if not v["eligible"] and v.get("cbc"))
        scr[name]["eligible"] = True
    probs = ING.check_selection(sel)
    assert any("evidence gives" in p for p in probs), probs


def test_screening_eligibility_of_the_recorded_outcomes():
    sel = json.load(open(os.path.join(ROOT, "data", "eng", "selection.json")))
    got = {n: ING.screening_eligible(v["stratum"], v)[0] for n, v in sel["miplib_nl_screening"].items()}
    assert got == {n: v["eligible"] for n, v in sel["miplib_nl_screening"].items()}
    picks = sel["miplib_nl_rule"]["picks"]
    assert all(got[n] for st in picks.values() for n in st)


# ------------------------------------------------------------------ scoring a time-limited reference (E22, option c)


from orgene import refs as R  # noqa: E402
from orgene.score import in_reference_interval, is_correct, correct_by_tol  # noqa: E402

IV = [1000.0, 1010.0]  # [CBC bound, CBC best value] of a minimisation stopped at its time limit


@pytest.mark.parametrize("obj, ok, reason", [
    (1010.0, True, "interval_match"),      # the time-limited best value itself
    (1003.7, True, "interval_match"),      # better than CBC's best value, not below the bound: a correct model can get it
    (1000.0, True, "interval_match"),      # the bound (the optimum may lie there)
    (1010.1, True, "interval_match"),      # above the best value within max(1e-4, 1e-4 * 1010) = 0.101
    (999.95, True, "interval_match"),      # below the bound within 0.1
    (1010.2, False, "outside_interval"),
    (999.8, False, "outside_interval"),
    (None, False, "no_objective"),
    (float("nan"), False, "no_objective"),
])
def test_interval_reference_judgement(obj, ok, reason):
    assert is_correct(obj, 1010.0, None, reference_interval=IV) == (ok, reason)
    # the order of the ends does not matter (a maximisation stores [best value, bound] sorted the same way)
    assert is_correct(obj, 1010.0, None, reference_interval=IV[::-1]) == (ok, reason)


def test_interval_reference_differs_from_a_point_reference_only_inside_the_interval():
    """A better-than-best objective is wrong against the point value (the rule before E22 verification) and right
    against the interval; outside the widened interval both say wrong."""
    assert is_correct(1003.7, 1010.0) == (False, "objective_mismatch")
    assert is_correct(1003.7, 1010.0, reference_interval=IV)[0]
    assert not is_correct(1020.0, 1010.0)[0] and not is_correct(1020.0, 1010.0, reference_interval=IV)[0]
    tiers = correct_by_tol(1010.5, 1010.0, reference_interval=IV)
    assert tiers == {"1e-06": False, "0.0001": False, "0.01": True}
    assert in_reference_interval(1000.0 - 2e-3, IV, 1e-6, 1e-6) is False and in_reference_interval(1000.0, IV, 1e-6, 1e-6)


def _interval_run(tmp_path, overrides=None):
    """Two toy cases scored end to end: toy-0001 time-limited (interval), toy-0002 a point reference."""
    cases = tmp_path / "toy.jsonl"
    rows = [{"_header": True, "source": "toy"},
            {"case_id": "toy-0001", "source": "toy", "text": "t", "reference": {"objective": 1010.0, "raw": "1010.0",
             "status": None, "kind": "cbc_time_limited", "interval": IV}},
            {"case_id": "toy-0002", "source": "toy", "text": "t", "reference": {"objective": 50.0, "raw": "50.0",
             "status": None, "kind": "cbc_optimal", "interval": None}}]
    cases.write_text("".join(json.dumps(r) + "\n" for r in rows))
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    final = [{"case_id": c, "repeat": 0, "exec": {"exec_ok": True, "protocol_ok": True, "status": "Optimal", "objective": o},
              "rounds": [{"round": 0, "hard_failed_genes": []}]} for c, o in (("toy-0001", 1003.7), ("toy-0002", 50.0))]
    write_jsonl(str(run / "final.C0.jsonl"), final)
    by_id = {c["case_id"]: c for c in (D.load_cases(str(cases)) if overrides is None else
                                         D.load_cases(str(cases), overrides=overrides))}
    m = P.score_condition(str(run), "C0", by_id)
    return {r["case_id"]: r for r in read_jsonl(str(run / "results.C0.jsonl"))}, m


def test_score_condition_judges_a_time_limited_reference_by_its_interval(tmp_path):
    res, m = _interval_run(tmp_path)
    r1, r2 = res["toy-0001"], res["toy-0002"]
    assert r1["correct"] and r1["reason"] == "interval_match" and r1["correct_original_ref"]
    assert r1["reference_kind"] == "cbc_time_limited" and r1["reference_interval"] == IV
    assert r1["correct_tol"] == {"1e-06": True, "0.0001": True, "0.01": True}
    assert r2["correct"] and r2["reason"] == "match" and r2["reference_interval"] is None
    assert m["n_correct"] == 2 and m["reference"]["n_interval_reference"] == 1


def test_an_override_value_replaces_the_interval_by_a_point(tmp_path):
    """E13 overrides stay authoritative: a replacing verdict scores against its value; the original-reference
    columns keep the interval."""
    res, _ = _interval_run(tmp_path)  # writes the cases file
    ov = {"path": "toy-overrides", "sha256": "0" * 64, "source": "toy", "cases_sha256": R.sha256_file(str(tmp_path / "toy.jsonl")),
          "mode": "loaded", "entries": {"toy-0001": {"case_id": "toy-0001", "original_value": 1010.0, "new_value": 1020.0,
                                                    "verdict": "INCORRECT", "checkers": ["A", "B"], "date": "2026-09-29",
                                                    "evidence_sha256": "0" * 64}}}
    res, m = _interval_run(tmp_path, overrides=ov)
    r1 = res["toy-0001"]
    assert not r1["correct"] and r1["reason"] == "objective_mismatch" and r1["reference_interval"] is None
    assert r1["correct_original_ref"] and r1["correct_tol_original_ref"]["0.0001"]
    assert m["reference"]["n_interval_reference"] == 0


# ------------------------------------------------------------------ longer solve and upgrade of a time-limited reference


def _before(kind="cbc_time_limited"):
    return {"reference_kind": kind, "reference_objective": 1010.0, "solve_record_sha256": "0" * 64,
            "cbc": {"bound": 1000.0, "objective": 1010.0, "gap": 0.0099, "status": "time_limit_feasible",
                    "wall_seconds": 1800.0, "options": {"time_limit_s": 1800}}}


def _long(status="optimal", obj=1004.0, nviol=0, rel=1e-12):
    return {"status": status, "objective": obj, "bound": None, "check": {"n_violations": nviol, "rel_diff": rel},
            "options": {"time_limit_s": 14400, "threads": 1}}


@pytest.mark.parametrize("before, long, ok, why", [
    (_before(), _long(), True, "optimality proved"),
    (_before(), _long(status="time_limit_feasible"), False, "no optimality proof"),
    (_before(), _long(nviol=2), False, "independent check"),
    (_before(), _long(rel=1e-6), False, "independent check"),
    (_before(), _long(obj=990.0), False, "outside the earlier interval"),
    (_before(), _long(obj=1011.0), False, "outside the earlier interval"),
    (_before("cbc_optimal"), _long(), False, "not cbc_time_limited"),
])
def test_upgrade_decision(before, long, ok, why):
    got, reason = ING.upgrade_decision(before, long)
    assert got is ok and why in reason


def _fake_root(tmp_path, long_status):
    root = tmp_path / "repo"
    logs = root / ING.SOLVE_LOGS
    logs.mkdir(parents=True)
    (root / "data" / "eng").mkdir(parents=True, exist_ok=True)
    (root / ING.REFERENCE_PATH).write_text(json.dumps({"cases": {"pglib_uc-0001": _before()}}))
    rec = dict(_long(status=long_status), result="Optimal solution found" if long_status == "optimal" else "Stopped on time limit")
    (logs / "pglib_uc-0001.long.json").write_text(json.dumps(rec))
    return root


def test_upgrade_records_an_unsuccessful_attempt_and_changes_nothing_else(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, "time_limit_feasible")
    monkeypatch.setattr(ING, "ROOT", str(root))
    called = []
    for fn in ("cmd_collect", "cmd_build", "cmd_split"):
        monkeypatch.setattr(ING, fn, lambda a, fn=fn: called.append(fn))
    assert ING.main(["upgrade"]) == 0
    up = json.loads((root / ING.UPGRADES_PATH).read_text())
    e = up["cases"]["pglib_uc-0001"]
    assert e["upgraded"] is False and e["after"] is None and e["before"]["reference_kind"] == "cbc_time_limited"
    assert e["long_solve"]["record_sha256"] == hashlib.sha256((root / ING.SOLVE_LOGS / "pglib_uc-0001.long.json").read_bytes()).hexdigest()
    assert up["rule"] == ING.UPGRADE_RULE and called == []


def test_upgrade_of_a_proved_optimum_rebuilds_and_is_refused_after_the_freeze(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, "optimal")
    monkeypatch.setattr(ING, "ROOT", str(root))
    called = []
    for fn in ("cmd_collect", "cmd_build", "cmd_split"):
        monkeypatch.setattr(ING, fn, lambda a, fn=fn: called.append(fn))
    assert ING.main(["upgrade"]) == 0
    e = json.loads((root / ING.UPGRADES_PATH).read_text())["cases"]["pglib_uc-0001"]
    assert e["upgraded"] is True and e["after"] == {"reference_kind": "cbc_optimal", "reference_objective": 1004.0}
    assert called == ["cmd_collect", "cmd_build", "cmd_split"]
    (root / ING.FREEZE_MANIFEST).write_text("{}")
    for cmd in (["upgrade"], ["long-solve", "--case", "pglib_uc-0001"]):
        with pytest.raises(SystemExit, match="frozen"):
            ING.main(cmd)


def test_collect_uses_the_long_record_of_an_upgraded_case(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, "optimal")
    monkeypatch.setattr(ING, "ROOT", str(root))
    logs = root / ING.SOLVE_LOGS
    (logs / "pglib_uc-0001.json").write_text(json.dumps(dict(_before()["cbc"], check={"n_violations": 0, "rel_diff": 0.0})))
    sel = {"cases": [{"case_id": "pglib_uc-0001", "source": "pglib_uc", "source_id": "rts_gmlc/x", "source_files": {}}]}
    long_sha = hashlib.sha256((logs / "pglib_uc-0001.long.json").read_bytes()).hexdigest()
    ups = {"cases": {"pglib_uc-0001": {"upgraded": True, "before": {"reference_kind": "cbc_time_limited"},
                                       "long_solve": {"record_sha256": long_sha}}}}
    doc, bad = ING.collect_doc(sel, ups)
    c = doc["cases"]["pglib_uc-0001"]
    assert bad == [] and c["reference_kind"] == "cbc_optimal" and c["reference_objective"] == 1004.0
    assert c["upgraded_from"] == {"reference_kind": "cbc_time_limited"} and c["solve_record_sha256"] == long_sha
    doc, _ = ING.collect_doc(sel, {"cases": {}})  # not upgraded: the 30-minute record
    assert doc["cases"]["pglib_uc-0001"]["reference_kind"] == "cbc_time_limited"
    ups["cases"]["pglib_uc-0001"]["long_solve"]["record_sha256"] = "1" * 64  # the long record changed afterwards
    with pytest.raises(SystemExit, match="changed since the upgrade"):
        ING.collect_doc(sel, ups)


@needs_cases
@pytest.mark.skipif(not os.path.isdir(os.path.join(ROOT, "data", "raw", "eng")), reason="raw engineering sources not fetched here")
def test_ingest_check_rebuilds_the_case_file_byte_for_byte():
    p = subprocess.run([sys.executable, os.path.join(ROOT, "data", "ingest_eng.py"), "check"], capture_output=True, text=True, timeout=600)
    assert p.returncode == 0 and "RESULT: PASS" in p.stdout, p.stdout[-2000:]
