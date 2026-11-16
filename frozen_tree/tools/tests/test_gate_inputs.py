"""Test gate, wave1 follow-up verification: what a gated stage reads must be frozen, and the runner finds sealed cases
in request ids too.

The freeze manifest verifies the repository; a stage could still read a gene library, lexicon, registry, template or
cases file from somewhere else (per-problem activation sets are recorded per request, so they are only as frozen as
those inputs). freeze.unfrozen_inputs / gate_stage(inputs=...) refuse that. Self-made repositories and the smoke case
only; a real sealed id is used as an id, never with its problem text.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT, copy_runtime_repo, write

from orgene import env as E  # noqa: E402
from orgene import freeze as FZ  # noqa: E402
from orgene.paths import OUTSIDE  # noqa: E402


def _frozen(root, terms_file):
    m = FZ.make(root, terms_file=terms_file)
    FZ.register(root, osf_id="q7m2k")
    return m


# ------------------------------------------------------------------ library


def test_unfrozen_inputs_names_what_the_freeze_does_not_cover(mini_repo, terms_file, tmp_path):
    man = _frozen(mini_repo, terms_file)
    outside = write(tmp_path, "elsewhere/genes.jsonl", "{}\n")
    ignored = write(mini_repo, "tools/__pycache__/prov.cpython.pyc", "x")  # inside a frozen tree, but git-ignored
    paths = [os.path.join(mini_repo, "code", "a.py"),         # a frozen file
             os.path.join(mini_repo, "tools", "prov.py"),     # tracked inside a directory whose tree hash is frozen
             os.path.join(mini_repo, "notes.md"),             # tracked, but neither listed nor in a frozen tree
             os.path.join(mini_repo, "code", "missing.py"),   # does not exist
             ignored, outside]
    assert FZ.unfrozen_inputs(mini_repo, man, paths) == sorted(
        ["notes.md", "code/missing.py", "tools/__pycache__/prov.cpython.pyc", f"{OUTSIDE}/genes.jsonl"])
    assert FZ.unfrozen_inputs(mini_repo, man, paths[:2]) == []


def test_gate_stage_refuses_loose_inputs_before_it_records_a_pass(mini_repo, terms_file, tmp_path):
    _frozen(mini_repo, terms_file)
    run = tmp_path / "run"
    with pytest.raises(FZ.GateRefused, match="not covered by the freeze manifest: notes.md"):
        FZ.gate_stage("requests", run_dir=str(run), case_ids=["toy-0002"], root=mini_repo,
                      inputs=[os.path.join(mini_repo, "code", "a.py"), os.path.join(mini_repo, "notes.md")])
    assert not run.exists()
    rec = FZ.gate_stage("requests", run_dir=str(run), case_ids=["toy-0002"], root=mini_repo,
                        inputs=[os.path.join(mini_repo, "code", "a.py"), os.path.join(mini_repo, "tools", "prov.py")])
    assert rec["stage"] == "requests" and (run / FZ.GATE_LOG).exists()
    # dev cases are not gated, whatever they read
    assert FZ.gate_stage("requests", run_dir=str(tmp_path / "dev"), case_ids=["toy-0001"], root=mini_repo,
                         inputs=[os.path.join(mini_repo, "notes.md")]) is None


# ------------------------------------------------------------------ command line (copy of the runtime)


def test_cli_gated_stages_read_frozen_inputs_only(tmp_path, terms_file):
    py = E.orgene_python()
    if not os.path.exists(py):
        pytest.skip(f"generation interpreter {py} not present on this host")
    root = copy_runtime_repo(tmp_path / "copy")
    cli = os.path.join(root, "runtime", "orgene_cli.py")
    _frozen(root, terms_file)
    loose = tmp_path / "loose"
    loose.mkdir()
    shutil.copy(os.path.join(root, "genes", "genes.r1.jsonl"), loose / "genes.r1.jsonl")
    shutil.copy(os.path.join(root, "configs", "r1_configs.json"), loose / "r1_configs.json")
    shutil.copytree(os.path.join(root, "conditions"), loose / "conditions")
    lex = os.path.join(root, "genes", "activation_lexicon.v1.json")
    if os.path.isfile(lex):
        shutil.copy(lex, loose / "activation_lexicon.v1.json")
    run = os.path.join(root, "experiments", "20261101-x-smoke-test-C0")
    req = ["requests", "--run", run, "--cases", os.path.join(root, "data", "cases", "smoke.jsonl"),
           "--split-dir", os.path.join(root, "data", "splits", "smoke"), "--split", "test", "--cond", "C0"]

    def cli_run(*args):
        return subprocess.run([sys.executable, cli, *args], capture_output=True, text=True, timeout=300)

    swaps = [("--genes", str(loose / "genes.r1.jsonl")), ("--configs", str(loose / "r1_configs.json")),
             ("--cond-dir", str(loose / "conditions"))]
    if os.path.isfile(lex):
        swaps.append(("--lexicon", str(loose / "activation_lexicon.v1.json")))
    for flag, path in swaps:
        p = cli_run(*req, flag, path)
        assert p.returncode != 0 and "not covered by the freeze manifest" in p.stderr, (flag, p.stderr)
        assert OUTSIDE in p.stderr and str(tmp_path) not in p.stderr, flag
        assert not os.path.exists(run), flag  # refused before the run directory or the gate log is written
    # a token-matched C1 reads the C1 matching report (E11): one outside the freeze is refused. The default report
    # exists since 2026-10-05 and is part of the freeze, so the gate does not refuse it (the request may still stop
    # later in this stripped copy, which has no dev cases to replay the matching on). The v5 character rule reads
    # no report.
    report = loose / "c1_matching_report.json"
    report.write_text("{}\n", encoding="utf-8")
    c1_req = req[:-1] + ["C1"]
    p = cli_run(*c1_req, "--c1-report", str(report))
    assert p.returncode != 0 and "not covered by the freeze manifest" in p.stderr, p.stderr
    assert "c1_matching_report.json" in p.stderr and str(tmp_path) not in p.stderr
    assert not os.path.exists(run)
    if os.path.exists(os.path.join(root, "conditions", "c1_matching_report.json")):
        run_default = os.path.join(root, "experiments", "20261101-x-smoke-test-C1default")
        p = cli_run(*[run_default if x == run else x for x in c1_req])
        assert "not covered by the freeze manifest" not in p.stderr, p.stderr
    run_chars = os.path.join(root, "experiments", "20261101-x-smoke-test-C1")
    p = cli_run(*[run_chars if x == run else x for x in c1_req], "--c1-match-mode", "chars")
    assert p.returncode == 0, p.stderr
    # a copy of the cases file outside the frozen tree is refused too
    shutil.copy(os.path.join(root, "data", "cases", "smoke.jsonl"), loose / "smoke.jsonl")
    p = cli_run("requests", "--run", run, "--cases", str(loose / "smoke.jsonl"), "--split-dir",
                os.path.join(root, "data", "splits", "smoke"), "--split", "test", "--cond", "C0")
    assert p.returncode != 0 and "not covered by the freeze manifest" in p.stderr and not os.path.exists(run)
    # the frozen inputs (the defaults) pass
    p = cli_run(*req)
    assert p.returncode == 0, p.stderr
    assert [json.loads(line)["stage"] for line in open(os.path.join(run, FZ.GATE_LOG))] == ["requests"]
    # validate on the gated run: a gene library outside the freeze is refused before anything runs
    p = cli_run("validate", "--run", run, "--cases", os.path.join(root, "data", "cases", "smoke.jsonl"), "--cond", "C3",
                "--genes", str(loose / "genes.r1.jsonl"))
    assert p.returncode != 0 and "not covered by the freeze manifest" in p.stderr, p.stderr
    assert [json.loads(line)["stage"] for line in open(os.path.join(run, FZ.GATE_LOG))] == ["requests"]


# ------------------------------------------------------------------ runner (stage "generate")


class _Backend:
    kind, model = "fake", "fake-model"
    token_counter = None
    token_counter_id = None

    def __init__(self):
        self.calls = 0

    def identity(self, refresh=False):
        return {"digest": "f" * 64}

    def build_body(self, messages, opts, fmt=None):
        return {"messages": messages, "options": dict(opts), "format": fmt}

    def sent_opts(self, body):
        return dict(body["options"])

    def inherited_defaults(self, sent):
        return {}

    def call(self, messages, opts, fmt=None, guard=None):
        self.calls += 1
        return {"ok": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1, "eval_duration_ns": 1,
                "seconds": 0.0, "wall_seconds": 0.0, "content": "x", "content_sha256": "0" * 64,
                "request_sha256": "0" * 64, "seed": opts.get("seed"), "started_at": "t0", "finished_at": "t1",
                "local_tokens": None, "local_tokens_counter": None, "local_tokens_error": None}


def _sealed_one():
    """One real sealed id (an id only), from the first split directory with a non-empty test_ids.json."""
    base = os.path.join(ROOT, "data", "splits")
    for d in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        p = os.path.join(base, d, "test_ids.json")
        ids = json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else []
        if ids:
            return ids[0]
    return None


@pytest.mark.skipif(_sealed_one() is None or os.path.exists(os.path.join(ROOT, FZ.DEFAULT_MANIFEST)),
                    reason="no sealed split in this tree, or a freeze manifest exists")
def test_runner_finds_sealed_cases_in_request_ids_without_case_id(tmp_path):
    from orgene import runner as RN
    msgs = [{"role": "system", "content": "You write PuLP programs."}, {"role": "user", "content": "Maximise x, x <= 1."}]
    reqs_file = tmp_path / "requests.jsonl"
    # a v5-style file: no case_id field; the sealed id (used as an id only) is in the request id
    reqs_file.write_text(json.dumps({"request_id": f"{_sealed_one()}.C0", "messages": msgs}) + "\n", encoding="utf-8")
    reqs = RN.load_requests(str(reqs_file))
    assert reqs[0]["case_id"] is None
    run = tmp_path / "20261101-x-handmade-C0"
    b = _Backend()
    with pytest.raises(SystemExit, match="refused by the test gate.*sealed case ids"):
        RN.run_batch(b, reqs, str(run / "gen.C0.r0"), {"temperature": 0.0, "seed": 1}, argv=["runner"])
    assert b.calls == 0 and not run.exists()
    # the same kind of file for a dev-style id runs
    reqs_file.write_text(json.dumps({"request_id": "smoke-0001.C0", "messages": msgs}) + "\n", encoding="utf-8")
    assert RN.run_batch(b, RN.load_requests(str(reqs_file)), str(run / "gen.C0.r0"), {"temperature": 0.0, "seed": 1},
                        argv=["runner"]) == 0 and b.calls == 1
