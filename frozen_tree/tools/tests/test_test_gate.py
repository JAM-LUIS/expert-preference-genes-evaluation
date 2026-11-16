"""E21 test gate: stages that touch sealed cases need a complete, verified, OSF-registered freeze manifest.

Library tests use throw-away repositories. CLI tests on the real tree only check refusals: they never build a test
request (the refusal comes before anything is written) and print no case text. They feed the CLI the smoke cases or
self-made cases with invented text; a real sealed id is used as an id only, never with its problem text. The positive CLI test runs on a copy
of the runtime with the smoke case, whose ids are declared sealed there.
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import ROOT, commit_all, copy_runtime_repo, write

from orgene import env as E  # noqa: E402
from orgene import freeze as FZ  # noqa: E402

CLI = os.path.join(ROOT, "runtime", "orgene_cli.py")


def _frozen(root, terms_file, register=True):
    m = FZ.make(root, terms_file=terms_file)
    if register:
        FZ.register(root, osf_id="q7m2k")
    return m


# ------------------------------------------------------------------ when the gate applies


def test_sealed_ids_come_from_test_id_files_only(mini_repo):
    write(mini_repo, "data/splits_r1/toy_sub/test_ids.json", json.dumps(["toy-0003"]))
    write(mini_repo, "data/splits_r1/toy_sub/dev_ids.json", json.dumps(["toy-0001"]))
    assert FZ.sealed_ids(mini_repo) == {"toy-0002", "toy-0003"}


@pytest.mark.parametrize("split,ids,need", [
    ("test", [], True), ("eng_holdout", [], True), (None, ["toy-0002"], True), ("dev", ["toy-0001", "toy-0003"], True),
    ("dev", ["toy-0001"], False), (None, ["toy-0001", "smoke-0001"], False), (None, [], False)])
def test_gate_reason(mini_repo, split, ids, need):
    assert FZ.gate_reason(mini_repo, split, ids)[0] is need


def test_run_directory_case_ids_trigger_the_gate(mini_repo, tmp_path):
    run = tmp_path / "run"
    write(run, "requests.C0.jsonl", json.dumps({"case_id": "toy-0001"}) + "\n")
    ids, split, gated = FZ.run_case_ids(str(run))
    assert ids == {"toy-0001"} and split is None and not gated
    assert FZ.gate_stage("validate", run_dir=str(run), root=mini_repo) is None
    write(run, "gen.C0.r0/outputs/x.json", json.dumps({"case_id": "toy-0002", "content": ""}))
    with pytest.raises(FZ.GateRefused):
        FZ.gate_stage("validate", run_dir=str(run), root=mini_repo)
    run2 = tmp_path / "run2"
    write(run2, "run_config.json", json.dumps({"split": "test"}))
    with pytest.raises(FZ.GateRefused):
        FZ.gate_stage("score", run_dir=str(run2), root=mini_repo)
    run3 = tmp_path / "run3"
    write(run3, FZ.GATE_LOG, "{}\n")
    with pytest.raises(FZ.GateRefused):
        FZ.gate_stage("score", run_dir=str(run3), root=mini_repo)


# ------------------------------------------------------------------ refusals


def test_gate_refuses_without_manifest(mini_repo, tmp_path):
    with pytest.raises(FZ.GateRefused) as e:
        FZ.gate_stage("requests", run_dir=str(tmp_path / "run"), case_ids=["toy-0002"], root=mini_repo)
    assert "freeze first" in str(e.value)
    assert not (tmp_path / "run").exists()


def test_gate_refuses_a_rehearsal_manifest(mini_repo, terms_file):
    from conftest import MINI_SPEC
    spec = dict(MINI_SPEC, items=MINI_SPEC["items"] + [{"id": "later", "category": "text", "pending": "x"}])
    write(mini_repo, "configs/freeze_spec.json", json.dumps(spec, indent=2))
    commit_all(mini_repo, "spec")
    FZ.make(mini_repo, terms_file=terms_file, allow_incomplete=True)
    with pytest.raises(FZ.GateRefused) as e:
        FZ.check_gate(mini_repo)
    assert "rehearsal" in str(e.value)


def test_gate_refuses_an_unregistered_manifest(mini_repo, terms_file):
    _frozen(mini_repo, terms_file, register=False)
    with pytest.raises(FZ.GateRefused) as e:
        FZ.check_gate(mini_repo)
    assert "OSF" in str(e.value)


@pytest.mark.parametrize("value", ["", "tbd", "abcde", "11111"])
def test_gate_refuses_placeholder_osf_ids(mini_repo, terms_file, value):
    m = _frozen(mini_repo, terms_file, register=False)
    m["osf"] = {"registration_id": value, "registered_content_sha256": m["content_sha256"], "recorded_at": "x"}
    FZ.write_manifest(os.path.join(mini_repo, FZ.DEFAULT_MANIFEST), m)
    with pytest.raises(FZ.GateRefused):
        FZ.check_gate(mini_repo)


def test_gate_refuses_a_registration_for_other_content(mini_repo, terms_file):
    m = _frozen(mini_repo, terms_file)
    m = json.load(open(os.path.join(mini_repo, FZ.DEFAULT_MANIFEST)))
    m["osf"]["registered_content_sha256"] = "f" * 64
    FZ.write_manifest(os.path.join(mini_repo, FZ.DEFAULT_MANIFEST), m)
    with pytest.raises(FZ.GateRefused) as e:
        FZ.check_gate(mini_repo)
    assert "other content" in str(e.value)


def test_gate_refuses_after_any_frozen_file_changes(mini_repo, terms_file):
    _frozen(mini_repo, terms_file)
    assert FZ.check_gate(mini_repo)["osf_registration_id"] == "q7m2k"
    write(mini_repo, "conditions/t.md", "Solve the problem carefully.\n")
    commit_all(mini_repo, "prompt tweak after the freeze")
    with pytest.raises(FZ.GateRefused) as e:
        FZ.check_gate(mini_repo)
    assert "conditions/t.md" in str(e.value)


def test_gate_refuses_a_split_directory_outside_the_manifest(mini_repo, terms_file, tmp_path):
    _frozen(mini_repo, terms_file)
    other = tmp_path / "other_split"
    write(other, "test_ids.json", json.dumps(["toy-0002"]))
    with pytest.raises(FZ.GateRefused):
        FZ.gate_stage("requests", run_dir=str(tmp_path / "run"), case_ids=["toy-0002"], split="test",
                      split_dir=str(other), root=mini_repo)
    rec = FZ.gate_stage("requests", run_dir=str(tmp_path / "run"), case_ids=["toy-0002"], split="test",
                        split_dir=os.path.join(mini_repo, "data", "splits", "toy"), root=mini_repo)
    assert rec["reason"] == "split=test"


# ------------------------------------------------------------------ pass + record


def test_gate_passes_and_records_the_manifest_hash(mini_repo, terms_file, tmp_path):
    m = _frozen(mini_repo, terms_file)
    run = tmp_path / "20261101-m-toy-test-C0"
    rec = FZ.gate_stage("requests", run_dir=str(run), case_ids=["toy-0002", "toy-0003"], root=mini_repo)
    assert rec["content_sha256"] == m["content_sha256"] and rec["osf_registration_id"] == "q7m2k"
    assert rec["n_sealed_cases"] == 2 and rec["manifest"] == FZ.DEFAULT_MANIFEST
    FZ.gate_stage("validate", run_dir=str(run), case_ids=["toy-0002"], root=mini_repo)
    recs = [json.loads(line) for line in open(run / FZ.GATE_LOG)]
    assert [r["stage"] for r in recs] == ["requests", "validate"]
    assert all(r["manifest_file_sha256"] == FZ.sha_file(os.path.join(mini_repo, FZ.DEFAULT_MANIFEST)) for r in recs)
    assert mini_repo not in open(run / FZ.GATE_LOG).read()


def test_dev_stage_needs_no_manifest(mini_repo, tmp_path):
    assert FZ.gate_stage("requests", run_dir=str(tmp_path / "run"), case_ids=["toy-0001"], split="dev", root=mini_repo) is None
    assert not (tmp_path / "run").exists()


# ------------------------------------------------------------------ CLI on the real tree (refusals only)


def _cli(*args, cwd=None):
    return subprocess.run([sys.executable, CLI] + list(args), capture_output=True, text=True, timeout=300, cwd=cwd)


def _real_split_dirs():
    """Split directories with a non-empty test_ids.json (the E22 eng_holdout split has an empty one)."""
    base = os.path.join(ROOT, "data", "splits")
    dirs = [os.path.join(base, d) for d in sorted(os.listdir(base))] if os.path.isdir(base) else []
    return [d for d in dirs if os.path.isfile(os.path.join(d, "test_ids.json"))
            and json.load(open(os.path.join(d, "test_ids.json"), encoding="utf-8"))]


def _real_sealed_available():
    return any(os.path.isfile(os.path.join(d, "test_ids.json")) for d in _real_split_dirs())


@pytest.mark.skipif(os.path.exists(os.path.join(ROOT, FZ.DEFAULT_MANIFEST)), reason="a freeze manifest exists in this tree")
def test_cli_requests_for_test_is_refused_before_anything_is_written(tmp_path):
    # smoke ids are not sealed in this tree: the refusal must come from --split test alone
    run = tmp_path / "20261101-x-smoke-test-C0"
    p = _cli("requests", "--run", str(run), "--cases", os.path.join(ROOT, "data", "cases", "smoke.jsonl"),
             "--split", "test", "--cond", "C0")
    assert p.returncode != 0 and "refused by the test gate" in p.stderr and "split=test" in p.stderr
    assert not run.exists()


@pytest.mark.skipif(not _real_sealed_available() or os.path.exists(os.path.join(ROOT, FZ.DEFAULT_MANIFEST)),
                    reason="no sealed split in this tree, or a freeze manifest exists")
def test_cli_validate_and_score_refuse_a_run_with_sealed_ids(tmp_path):
    sd = next(d for d in _real_split_dirs() if os.path.isfile(os.path.join(d, "test_ids.json")))
    sealed_one = json.load(open(os.path.join(sd, "test_ids.json")))[0]
    run = tmp_path / "run"
    write(run, "requests.C0.jsonl", json.dumps({"request_id": "r", "case_id": sealed_one, "messages": []}) + "\n")
    smoke = os.path.join(ROOT, "data", "cases", "smoke.jsonl")
    for args in (["validate", "--run", str(run), "--cases", smoke, "--cond", "C0"],
                 ["score", "--run", str(run), "--cases", smoke, "--cond", "C0"]):
        p = _cli(*args)
        assert p.returncode != 0 and "refused by the test gate" in p.stderr
    assert sorted(os.listdir(run)) == ["requests.C0.jsonl"]


@pytest.mark.skipif(not _real_sealed_available() or os.path.exists(os.path.join(ROOT, FZ.DEFAULT_MANIFEST)),
                    reason="no sealed split in this tree, or a freeze manifest exists")
def test_cli_requests_without_split_on_a_file_with_sealed_cases_is_refused(tmp_path):
    # a self-made cases file (invented text) whose second case carries a real sealed id; no benchmark case is read,
    # so even a broken gate could not put sealed problem text into a request
    sd = next(d for d in _real_split_dirs() if os.path.isfile(os.path.join(d, "test_ids.json")))
    sealed_one = json.load(open(os.path.join(sd, "test_ids.json")))[0]
    rows = [{"case_id": cid, "source": "toy", "source_id": str(i), "text": "Maximise x subject to x <= 1.",
             "reference": {"objective": 1.0, "raw": "1", "status": None}, "extra": {}, "license": "CC0"}
            for i, cid in enumerate(("toy-0001", sealed_one))]
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    run = tmp_path / "run"
    p = _cli("requests", "--run", str(run), "--cases", str(cases), "--cond", "C0")
    assert p.returncode != 0 and "sealed case ids" in p.stderr
    assert not run.exists()


# ------------------------------------------------------------------ CLI end to end on a copy (pass, then refuse)


def test_cli_gate_end_to_end_on_a_copy(tmp_path, terms_file):
    py = E.orgene_python()
    if not os.path.exists(py):
        pytest.skip(f"generation interpreter {py} not present on this host")
    root = copy_runtime_repo(tmp_path / "copy")
    cli = os.path.join(root, "runtime", "orgene_cli.py")
    fz = os.path.join(root, "tools", "freeze.py")
    run = os.path.join(root, "experiments", "20261101-x-smoke-test-C0")
    req = ["requests", "--run", run, "--cases", os.path.join(root, "data", "cases", "smoke.jsonl"),
           "--split-dir", os.path.join(root, "data", "splits", "smoke"), "--split", "test", "--cond", "C0"]
    p = subprocess.run([sys.executable, cli] + req, capture_output=True, text=True, timeout=300)
    assert p.returncode != 0 and "refused by the test gate" in p.stderr and not os.path.exists(run)
    assert subprocess.run([sys.executable, fz, "make", "--anon-terms", terms_file], capture_output=True, text=True,
                          timeout=300).returncode == 0
    p = subprocess.run([sys.executable, cli] + req, capture_output=True, text=True, timeout=300)
    assert p.returncode != 0 and "OSF" in p.stderr and not os.path.exists(run)
    assert subprocess.run([sys.executable, fz, "register", "--osf", "q7m2k"], capture_output=True, text=True,
                          timeout=300).returncode == 0
    p = subprocess.run([sys.executable, cli] + req, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr
    recs = [json.loads(line) for line in open(os.path.join(run, FZ.GATE_LOG))]
    man = json.load(open(os.path.join(root, FZ.DEFAULT_MANIFEST)))
    assert recs[-1]["stage"] == "requests" and recs[-1]["content_sha256"] == man["content_sha256"]
    assert recs[-1]["osf_registration_id"] == "q7m2k" and recs[-1]["n_sealed_cases"] == 2
    # a dev request in the same tree needs no gate record
    dev_run = os.path.join(root, "experiments", "20261101-x-smoke-dev-C0")
    p = subprocess.run([sys.executable, cli, "requests", "--run", dev_run, "--cases", os.path.join(root, "data", "cases", "smoke.jsonl"),
                        "--split-dir", os.path.join(root, "data", "splits", "smoke"), "--split", "dev", "--cond", "C0"],
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr
    assert not os.path.exists(os.path.join(dev_run, FZ.GATE_LOG))
    # score on the gated run passes the gate (it then stops for lack of outputs; only the gate is under test here)
    p = subprocess.run([sys.executable, cli, "score", "--run", run, "--cases", os.path.join(root, "data", "cases", "smoke.jsonl"),
                        "--cond", "C0"], capture_output=True, text=True, timeout=300)
    assert "refused by the test gate" not in p.stderr
    assert [json.loads(line)["stage"] for line in open(os.path.join(run, FZ.GATE_LOG))] == ["requests", "score"]
    # change a frozen file after the registration: test stages are refused again
    with open(os.path.join(root, "runtime", "orgene", "score.py"), "a") as f:
        f.write("\n# edited after the freeze\n")
    commit_all(root, "edit scoring after the freeze")
    p = subprocess.run([sys.executable, cli, "score", "--run", run, "--cases", os.path.join(root, "data", "cases", "smoke.jsonl"),
                        "--cond", "C0"], capture_output=True, text=True, timeout=300)
    assert p.returncode != 0 and "runtime/orgene/score.py" in p.stderr


# ------------------------------------------------------------------ model calls (runner.run_batch, stage "generate")

# A backend without a model: counts calls and returns a fixed answer. Kept as source so the copy-based test below can
# run it with the copy's own runtime (whose freeze module then looks at the copy's manifest).
FAKE_BACKEND_SRC = '''
class GateFakeBackend:
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
'''
_ns = {}
exec(FAKE_BACKEND_SRC, _ns)  # noqa: S102 - test helper defined above
GateFakeBackend = _ns["GateFakeBackend"]
_MSGS = [{"role": "system", "content": "You write PuLP programs."}, {"role": "user", "content": "Maximise x with x <= 1."}]
_OPTS = {"temperature": 0.0, "seed": 1}


def _reqs(*case_ids):
    return [{"request_id": f"{c}.C0", "case_id": c, "condition": "C0", "messages": _MSGS} for c in case_ids]


def _run_batch(requests, out_dir):
    from orgene import runner as RN
    b = GateFakeBackend()
    try:
        return b, RN.run_batch(b, requests, str(out_dir), _OPTS, argv=["runner"])
    except SystemExit as e:
        return b, e


@pytest.mark.skipif(not _real_sealed_available() or os.path.exists(os.path.join(ROOT, FZ.DEFAULT_MANIFEST)),
                    reason="no sealed split in this tree, or a freeze manifest exists")
def test_runner_refuses_sealed_requests_before_any_call(tmp_path):
    # one real sealed id (as an id only; the messages are invented text) next to a smoke id
    sd = next(d for d in _real_split_dirs() if os.path.isfile(os.path.join(d, "test_ids.json")))
    sealed_one = json.load(open(os.path.join(sd, "test_ids.json")))[0]
    run = tmp_path / "20261101-x-mixed-dev-C0"
    b, res = _run_batch(_reqs("smoke-0001", sealed_one), run / "gen.C0.r0")
    assert isinstance(res, SystemExit) and "refused by the test gate" in str(res) and "generate" in str(res)
    assert "sealed case ids" in str(res) and b.calls == 0
    assert not run.exists()


@pytest.mark.skipif(os.path.exists(os.path.join(ROOT, FZ.DEFAULT_MANIFEST)), reason="a freeze manifest exists in this tree")
def test_runner_refuses_a_run_recorded_as_test(tmp_path):
    # smoke ids are not sealed in this tree: the refusal comes from the split in the run's run_config.json
    run = tmp_path / "20261101-x-smoke-test-C0"
    write(run, "run_config.json", json.dumps({"split": "test"}))
    b, res = _run_batch(_reqs("smoke-0001"), run / "gen.C0.r0")
    assert isinstance(res, SystemExit) and "split=test" in str(res) and b.calls == 0
    assert sorted(os.listdir(run)) == ["run_config.json"]


def test_runner_lets_dev_batches_through_without_a_manifest(tmp_path):
    run = tmp_path / "20261101-x-smoke-dev-C0"
    write(run, "run_config.json", json.dumps({"split": "dev"}))
    b, res = _run_batch(_reqs("smoke-0001", "smoke-0002"), run / "gen.C0.r0")
    assert res == 0 and b.calls == 2
    cfg = json.load(open(run / "gen.C0.r0" / "config.json"))
    assert cfg["freeze_gate"] is None and not (run / FZ.GATE_LOG).exists()


def test_runner_gate_on_a_copy_refuses_then_passes_after_the_freeze(tmp_path, terms_file):
    # the copy declares smoke-0002/0003 sealed; its runtime (runner + freeze) runs in a subprocess so that the gate
    # reads the copy's manifest
    root = copy_runtime_repo(tmp_path / "copy")
    run = os.path.join(root, "experiments", "20261101-x-smoke-test-C0")
    script = FAKE_BACKEND_SRC + f'''
import json, sys
sys.path.insert(0, {os.path.join(root, "runtime")!r})
from orgene import runner as RN
b = GateFakeBackend()
reqs = [{{"request_id": "smoke-0002.C0", "case_id": "smoke-0002", "condition": "C0", "messages": {_MSGS!r}}}]
try:
    rc = RN.run_batch(b, reqs, {os.path.join(run, "gen.C0.r0")!r}, {_OPTS!r}, argv=["runner"])
except SystemExit as e:
    print(str(e), file=sys.stderr)
    rc = 9
print(json.dumps({{"rc": rc, "calls": b.calls}}))
'''

    def attempt():
        p = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=300)
        return p, json.loads(p.stdout.strip().splitlines()[-1])

    p, out = attempt()
    assert out == {"rc": 9, "calls": 0} and "refused by the test gate" in p.stderr and "freeze first" in p.stderr
    assert not os.path.exists(run)
    _frozen(root, terms_file, register=False)
    p, out = attempt()
    assert out == {"rc": 9, "calls": 0} and "OSF" in p.stderr and not os.path.exists(run)
    FZ.register(root, osf_id="q7m2k")
    p, out = attempt()
    assert out == {"rc": 0, "calls": 1}, p.stderr
    man = json.load(open(os.path.join(root, FZ.DEFAULT_MANIFEST)))
    cfg = json.load(open(os.path.join(run, "gen.C0.r0", "config.json")))
    assert cfg["freeze_gate"]["stage"] == "generate" and cfg["freeze_gate"]["content_sha256"] == man["content_sha256"]
    recs = [json.loads(line) for line in open(os.path.join(run, FZ.GATE_LOG))]
    assert [r["stage"] for r in recs] == ["generate"] and recs[0]["n_sealed_cases"] == 1
    assert root not in open(os.path.join(run, FZ.GATE_LOG)).read()
