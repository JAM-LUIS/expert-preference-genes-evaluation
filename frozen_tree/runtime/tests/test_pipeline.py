"""pytest -q runtime/tests  (needs pulp with CBC for the execution tests)."""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import genes as G  # noqa: E402
from orgene.execute import parse_number, run_program  # noqa: E402
from orgene.extract import extract  # noqa: E402
from orgene.score import is_correct  # noqa: E402
from orgene.data import parse_reference  # noqa: E402
from orgene.conditions import build_system_prompts_v1  # noqa: E402
from orgene.selftest import GOOD_CODE, GOOD_SPEC, run_selftest  # noqa: E402

GENES = os.path.join(ROOT, "genes", "genes.r1.jsonl")  # R1 working library (v1.0 is checked in test_v1_regression.py)
COND = os.path.join(ROOT, "conditions")


def test_extract_blocks():
    txt = "<think>hmm</think>Here:\n```json\n{\"a\": 1}\n```\nand\n```python\nimport pulp\nprint(1)\n```\n"
    ex = extract(txt)
    assert ex["spec"] == {"a": 1} and ex["code"].startswith("import pulp")


def test_extract_unfenced_program():
    ex = extract("Sure.\nimport pulp\nprob = pulp.LpProblem('x', pulp.LpMinimize)\n")
    assert ex["code"] and "LpProblem" in ex["code"] and ex["spec"] is None


def test_parse_numbers():
    assert parse_number("FINAL: 1,234.5") == 1234.5
    assert parse_number("NA") is None
    assert parse_reference("The optimal value is $1,500.") == (1500.0, None)
    assert parse_reference("infeasible") == (None, "infeasible")
    assert parse_reference(42) == (42.0, None)


def test_score_tolerance():
    assert is_correct(2600.00001, 2600.0)[0]
    assert not is_correct(2599.0, 2600.0)[0]
    assert is_correct(None, None, "infeasible", status="Infeasible")[0]


def test_execute_good_program():
    r = run_program(GOOD_CODE, timeout=60)
    assert r["exec_ok"] and r["protocol_ok"] and r["status"] == "Optimal" and abs(r["objective"] - 2600) < 1e-6


def test_execute_timeout_and_error():
    r = run_program("import time\nwhile True: time.sleep(1)\n", timeout=2)
    assert r["timed_out"] and not r["exec_ok"]
    r = run_program("raise ValueError('boom')\n", timeout=10)
    assert not r["exec_ok"] and "boom" in r["stderr_tail"]


def test_gene_store_and_predicates():
    store = G.load_store(GENES)
    active, trace = G.activate(store, condition="C3")
    assert len(active) == len(store) and all(t["included"] for t in trace)
    ctx = {"case": {"text": "profit 40 and 30, hours 100 and 80, 2 hours"}, "spec": GOOD_SPEC, "code": GOOD_CODE, "exec": None}
    pre = G.validate(active, ctx, "pre_exec")
    assert not G.hard_failures(pre), [i for i in pre if i["ok"] is False]
    bad = dict(ctx, code=GOOD_CODE.replace("LpMaximize", "LpMinimize"))
    hard = G.hard_failures(G.validate(active, bad, "pre_exec"))
    assert any(i["geneId"] == "orgene.objective.sense_consistent" for i in hard)
    text, applied = G.repair_turn(active, G.validate(active, bad, "pre_exec"), {})
    assert "orgene.objective.sense_consistent" in applied and "Fix:" in text
    # budget exhausted -> no repair
    text2, applied2 = G.repair_turn(active, G.validate(active, bad, "pre_exec"), {"orgene.objective.sense_consistent": 1})
    assert text2 is None and applied2 == []


def test_prompts_length_match():
    prompts, info = build_system_prompts_v1(COND, GENES)
    assert info["c1_c3_match_ok"], info
    assert "Modeling contract" in prompts["C3"] and "Modeling contract" not in prompts["C2"]
    assert "problem_type" in prompts["C2"] and "problem_type" not in prompts["C0"] and "problem_type" not in prompts["C1"]
    assert 0.95 <= info["c1_c3_char_ratio"] <= 1.05


def test_selftest_end_to_end():
    assert run_selftest(ROOT, GENES, COND)


class _MockOpenAI(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        assert self.path.endswith("/chat/completions"), self.path
        assert "max_completion_tokens" in body
        out = {"id": "mock-1", "model": body["model"], "choices": [{"message": {"content": "```python\n" + GOOD_CODE + "```"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 20}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # silence
        pass


def test_api_runner_against_mock(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _MockOpenAI)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    reqs = tmp_path / "requests.jsonl"
    reqs.write_text(json.dumps({"request_id": "smoke-001.C0", "case_id": "smoke-001", "condition": "C0",
                                "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], "meta": {}}) + "\n")
    out = tmp_path / "gen"
    env = dict(os.environ, MOCK_KEY="x")
    p = subprocess.run([sys.executable, os.path.join(RUNTIME, "api_runner.py"), "--backend", "compat", "--base-url", f"http://127.0.0.1:{port}/v1",
                        "--api-key-env", "MOCK_KEY", "--model", "mock-model", "--requests", str(reqs), "--out", str(out)],
                       capture_output=True, text=True, env=env, timeout=60)
    srv.shutdown()
    assert p.returncode == 0, p.stderr
    rec = json.load(open(out / "outputs" / "smoke-001.C0.r0.json"))
    assert rec["ok"] and rec["eval_count"] == 20 and "import pulp" in rec["content"]
    # resume: second run does nothing new
    p2 = subprocess.run([sys.executable, os.path.join(RUNTIME, "api_runner.py"), "--backend", "compat", "--base-url", f"http://127.0.0.1:{port}/v1",
                         "--api-key-env", "MOCK_KEY", "--model", "mock-model", "--requests", str(reqs), "--out", str(out)],
                        capture_output=True, text=True, env=env, timeout=60)
    assert "already_done=1" in p2.stdout
