"""E18: the LLMOPT anchor -- prompts pinned and kept out of git, one-user-message requests, response extraction, the
solver redirect, objective from the solve record with the printed-output parser as backup, the chat template rendered
locally, the registry entry, and the driver end to end on llama-server's native /completion.

No model is called: llama-server is a stand-in (fake_llama_server.py, in process or as the launched program) and
llama-tokenize a stand-in script. The upstream prompt file is never needed: a synthetic stand-in with its own hash
replaces it. Programs are self-written; cases are the author-written smoke cases. Execution uses a stand-in `pyomo`
package in a throw-away venv (run with -I, exactly as run_program runs generated programs); the real Pyomo + CBC tests
run with ORGENE_BASELINES_PY set, the real-tokenizer test only with ORGENE_LLMOPT_GGUF on the model host.
"""
import argparse
import base64
import glob
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
for _p in (RUNTIME, ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from baselines import llamacpp_server as LS  # noqa: E402
from baselines.llmopt import adapter as A  # noqa: E402
from baselines.llmopt import prompts as PR  # noqa: E402
from baselines.llmopt import run as RUN  # noqa: E402
from baselines.llmopt import templates as T  # noqa: E402
from orgene import data as D  # noqa: E402
from orgene import model_registry as MR  # noqa: E402
from orgene import pipeline as P  # noqa: E402
from orgene import tokcount as TC  # noqa: E402
from orgene.backends.base import RegistryMismatch, registry_guard  # noqa: E402
from orgene.backends.llamacpp import LlamaCppCompletionBackend  # noqa: E402
from orgene.env import orgene_python  # noqa: E402
from orgene.execute import run_program  # noqa: E402
from fake_llama_server import FakeLlamaServer  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
REG_PATH = os.path.join(ROOT, "configs", "model_registry.json")
SMOKE_CASES = os.path.join(ROOT, "data", "cases", "smoke.jsonl")
ENTRY_ID = "llmopt-qwen25-14b-q8.anchor"
BS = "\\"

SYNTH_PROMPTS = ('def Q2F(ques):\n    return "SYNTHETIC-Q2F\\n```\\n" + ques + "\\n```\\n"\n\n\n'
                 'def F2C(five):\n    return "SYNTHETIC-F2C\\n```\\n" + five + "\\n```\\n"\n')
SYNTH_SHA = hashlib.sha256(SYNTH_PROMPTS.encode()).hexdigest()


def _synthetic_prompts():
    return PR.Prompts(SYNTH_PROMPTS, SYNTH_SHA)


# ============================================================================================ prompts


def test_prompts_load_only_the_pinned_bytes(tmp_path):
    p = tmp_path / "prompts.upstream"
    p.write_bytes(SYNTH_PROMPTS.encode())
    pr = PR.load(str(p), expected_sha256=SYNTH_SHA)
    assert pr.Q2F("q").startswith("SYNTHETIC-Q2F") and pr.sha256 == SYNTH_SHA
    with pytest.raises(PR.PromptsError, match="not the pinned"):
        PR.load(str(p))  # the real pin: these bytes are not the upstream file
    p.write_bytes(SYNTH_PROMPTS.replace("SYNTHETIC-Q2F", "SYNTHETIC-Q2G").encode())
    with pytest.raises(PR.PromptsError, match="not the pinned"):
        PR.load(str(p), expected_sha256=SYNTH_SHA)


def test_a_missing_prompt_file_says_how_to_install_it(tmp_path):
    with pytest.raises(PR.PromptsError, match="install"):
        PR.load(str(tmp_path / "absent"))


def test_install_takes_the_file_from_the_smoke_script_only_with_the_pinned_hash(tmp_path):
    script = 'X = 1\nLLMOPT_PROMPTS_B64 = "%s"\n' % base64.b64encode(SYNTH_PROMPTS.encode()).decode()
    data = PR.from_smoke_script(script)
    assert data == SYNTH_PROMPTS.encode()
    dest = PR.install(data, dest=str(tmp_path / "v" / "p.upstream"), expected_sha256=SYNTH_SHA)
    assert open(dest, "rb").read() == data
    with pytest.raises(PR.PromptsError, match="refused"):
        PR.install(data, dest=str(tmp_path / "w" / "p.upstream"))  # not the upstream bytes
    assert not (tmp_path / "w").exists()
    with pytest.raises(PR.PromptsError):
        PR.from_smoke_script("nothing here")


def test_the_prompt_file_stays_out_of_git_and_out_of_the_code_globs():
    assert PR.PROMPTS_SHA256 == PR.UPSTREAM["sha256"] and PR.UPSTREAM["commit"].startswith("1492dd3")
    with open(os.path.join(ROOT, "baselines", "llmopt", ".gitignore"), encoding="utf-8") as f:
        assert "vendor/" in f.read().split()


def test_the_prompt_file_matches_no_glob_of_the_freeze_spec(tmp_path):
    from orgene import freeze as FZ
    vendor_rel = os.path.relpath(PR.VENDOR_FILE, ROOT).replace(os.sep, "/")
    (tmp_path / vendor_rel).parent.mkdir(parents=True)
    (tmp_path / vendor_rel).write_text("x")
    (tmp_path / "baselines" / "llmopt" / "adapter.py").write_text("x")
    spec = json.load(open(os.path.join(ROOT, "configs", "freeze_spec.json"), encoding="utf-8"))
    hits = set()
    for it in spec["items"]:
        if it.get("glob"):
            hits |= set(FZ.expand_glob(str(tmp_path), it["glob"]))
    assert "baselines/llmopt/adapter.py" in hits and vendor_rel not in hits


@pytest.mark.skipif(not (shutil.which("git") and os.path.exists(os.path.join(ROOT, ".git"))), reason="not a git checkout")
def test_git_ignores_the_prompt_file():
    vendor_rel = os.path.relpath(PR.VENDOR_FILE, ROOT).replace(os.sep, "/")
    assert subprocess.run(["git", "check-ignore", "-q", vendor_rel], cwd=ROOT).returncode == 0


@pytest.mark.skipif(not os.path.isfile(PR.VENDOR_FILE), reason="the upstream prompt file is not installed here")
def test_the_installed_upstream_prompts_load_and_give_one_user_message():
    pr = PR.load()
    for msgs in (A.q2f_messages("A synthetic question.", pr), A.f2c_messages("## Sets:\nS\n", pr)):
        T.require_single_user_message(msgs)
        assert T.user_text_of(T.render_prompt(msgs)) == msgs[0]["content"]


# ============================================================================================ requests


def test_each_step_is_exactly_one_user_message():
    pr = _synthetic_prompts()
    assert A.q2f_messages("Q?", pr) == [{"role": "user", "content": pr.Q2F("Q?")}]
    assert A.f2c_messages("FIVE", pr) == [{"role": "user", "content": pr.F2C("FIVE")}]
    T.require_single_user_message(A.q2f_messages("Q?", pr))


@pytest.mark.parametrize("msgs", [
    [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}],
    [{"role": "user", "content": "U"}, {"role": "user", "content": "V"}],
    [{"role": "assistant", "content": "A"}],
    [{"role": "user", "content": "U", "images": ["x"]}],
    [{"role": "user", "content": None}],
    [],
])
def test_any_other_request_shape_is_refused(msgs):
    with pytest.raises(T.TemplateError):
        T.require_single_user_message(msgs)


# ============================================================================================ extraction


@pytest.mark.parametrize("resp,five", [
    ("intro\n```text\nSETS A\n```\nafter", "\nSETS A\n"),
    ("```plaintext\nSETS B\n```", "\nSETS B\n"),
    ("```\n\n## Sets: \n- P\n```\n", "\n\n## Sets: \n- P\n"),
    ("```text\nfirst\n```\n```text\nsecond\n```", "\nfirst\n"),
    ("## Sets: no fence at all", None),
    ("", None),
])
def test_five_elements_are_the_first_fenced_block(resp, five):
    assert A.extract_five_elements(resp) == five


def test_the_response_is_unescaped_as_upstream_does():
    raw = "```text\nline1" + BS * 2 + "nline2 &lt;= 3 &gt; 1 it&#39;s " + BS * 2 + '"q' + BS * 2 + '"\n```'
    assert A.extract_five_elements(raw) == "\nline1\nline2 <= 3 > 1 it's \"q\"\n"


def test_code_is_the_first_python_block_and_split_prints_are_joined():
    resp = "text\n```python\nfrom pyomo.environ import *\nprint(\"" + BS * 2 + "\nTotal\")\nprint(f\"" + BS * 2 + \
           "\n{x}\")\n```\nmore\n```python\nsecond\n```"
    assert A.extract_code(resp) == "\nfrom pyomo.environ import *\nprint(\"Total\")\nprint(f\"{x}\")\n"
    assert A.extract_code("```py\nx = 1\n```") is None  # only a ```python block counts (as upstream)
    assert A.extract_code("no code") is None and A.extract_code(None) is None


# ============================================================================================ solver redirect


def test_the_prelude_goes_first_or_right_after_future_imports():
    code = "x = 1\nprint(x)\n"
    prog, after = A.with_solver_redirect(code)
    assert prog == A.SOLVER_PRELUDE + code and after == 0
    fut = '"""doc"""\nfrom __future__ import annotations\nfrom __future__ import division\nimport os\n'
    prog, after = A.with_solver_redirect(fut)
    assert after == 3 and prog.startswith('"""doc"""\nfrom __future__ import annotations\nfrom __future__ import division\n')
    compile(prog, "p.py", "exec")
    with pytest.raises(SyntaxError):  # what a plain prepend would do to such a program
        compile(A.SOLVER_PRELUDE + fut, "p.py", "exec")
    bad = "def f(:\n"
    assert A.with_solver_redirect(bad) == (A.SOLVER_PRELUDE + bad, 0)
    assert A.PRELUDE_LINES == A.SOLVER_PRELUDE.count("\n") and "/" not in A.SOLVER_PRELUDE.replace("->", "")


def test_requested_solver_names_are_recorded():
    code = "a = SolverFactory('glpk')\nb = SolverFactory(\"cbc\", executable='x')\nc = SolverFactory(name)\n" \
           "d = pyo.SolverFactory(_name='ipopt')\n"
    assert A.requested_solvers(code) == ["glpk", "cbc", "<expr>", "ipopt"]
    assert A.requested_solvers("") == []


# ---------------------------------------------------------------------- a stand-in pyomo in a throw-away venv

FAKE_PYOMO = {
    "pyomo/__init__.py": "",
    "pyomo/version.py": 'version = "fake-1"\n',
    "pyomo/core/__init__.py": '''
minimize, maximize = 1, -1
NonNegativeReals = NonNegativeIntegers = Reals = "domain"


class _Comp:
    _model = None


class Var(_Comp):
    def __init__(self, *args, domain=None, within=None, lb=0.0, **kw):
        self.lb, self.value = lb, None

    def __call__(self):
        return self.value

    def __ge__(self, other):
        return ("ge", self, other)

    def __le__(self, other):
        return ("le", self, other)


class Objective(_Comp):
    def __init__(self, expr=None, rule=None, sense=minimize):
        self.expr, self.rule, self.sense = expr, rule, sense

    def __call__(self):
        if self.rule is not None:
            return self.rule(self._model)
        return self.expr() if callable(self.expr) else self.expr


class Constraint(_Comp):
    def __init__(self, expr=None, rule=None):
        self.expr = expr


class ConcreteModel:
    def __init__(self):
        object.__setattr__(self, "_c", [])

    def __setattr__(self, name, value):
        if isinstance(value, _Comp):
            value._model = self
            self._c.append(value)
        object.__setattr__(self, name, value)

    def component_data_objects(self, ctype, active=None, descend_into=True):
        return iter([c for c in self._c if isinstance(c, ctype)])


def value(obj, exception=True):
    return obj()
''',
    "pyomo/opt/__init__.py": "from pyomo.opt.base.solvers import OptSolver, SolverFactory, SolverFactoryClass, SolverStatus, "
                             "TerminationCondition  # noqa\n",
    "pyomo/opt/base/__init__.py": "",
    "pyomo/opt/base/solvers.py": '''
class _Enum:
    def __init__(self, v):
        self.value = v

    def __eq__(self, other):
        return getattr(other, "value", other) == self.value

    def __hash__(self):
        return hash(self.value)

    def __str__(self):
        return self.value


class TerminationCondition:
    optimal = _Enum("optimal")
    infeasible = _Enum("infeasible")


class SolverStatus:
    ok = _Enum("ok")
    warning = _Enum("warning")


class _Info:
    pass


class Results:
    def __init__(self, tc, st):
        self.solver = _Info()
        self.solver.termination_condition, self.solver.status = tc, st


class OptSolver:
    def __init__(self, name):
        self.name = name

    def solve(self, *args, **kwds):
        from pyomo.core import Constraint, Var
        model = args[0]
        vs = list(model.component_data_objects(Var))
        for v in vs:
            v.value = float(v.lb)
        cons = [c.expr for c in model.component_data_objects(Constraint)]
        for op, var, bound in cons:
            if op == "ge":
                var.value = max(var.value, float(bound))
        for op, var, bound in cons:
            if op == "le" and var.value > bound:
                for v in vs:
                    v.value = None
                return Results(TerminationCondition.infeasible, SolverStatus.warning)
        return Results(TerminationCondition.optimal, SolverStatus.ok)


class SolverFactoryClass:
    def __call__(self, _name=None, **kwds):
        if _name is None:
            return self
        if _name == "cbc":  # as Pyomo's CBC plug-in: the shell solver comes from a nested factory call
            shell = SolverFactory("_cbc_shell", **kwds)
            shell.name = "cbc"
            return shell
        return OptSolver(str(_name))


SolverFactory = SolverFactoryClass()
''',
    "pyomo/environ/__init__.py": "from pyomo.core import *  # noqa\nfrom pyomo.opt import SolverFactory, SolverStatus, "
                                 "TerminationCondition  # noqa\n",
}

PROG_OPT = '''
from pyomo.environ import *


class Workshop:
    def __init__(self):
        self.model = ConcreteModel()
        self.model.x = Var(domain=NonNegativeReals)
        self.model.profit = Objective(rule=lambda m: 2 * m.x.value, sense=maximize)
        self.model.c1 = Constraint(expr=self.model.x >= 1300)

    def solve(self):
        solver = SolverFactory('glpk')
        results = solver.solve(self.model, tee=False)
        if results.solver.termination_condition == TerminationCondition.optimal:
            print("Optimal solution found:")
            print(f"Units: {self.model.x.value}")
            print(f"Total profit: {self.model.profit()}")
        else:
            print("Solver Status: ", results.solver.status)


def main():
    Workshop().solve()


if __name__ == "__main__":
    main()
'''
PROG_INFEASIBLE = '''
from pyomo.environ import *

m = ConcreteModel()
m.x = Var(domain=NonNegativeReals)
m.cost = Objective(expr=m.x, sense=minimize)
m.c1 = Constraint(expr=m.x >= 5)
m.c2 = Constraint(expr=m.x <= 3)
r = SolverFactory('glpk').solve(m)
if r.solver.termination_condition == TerminationCondition.infeasible:
    print("No feasible solution found.")
print("Total cost: 42")
'''
PROG_CRASH_AFTER_SOLVE = PROG_OPT.replace('print(f"Total profit: {self.model.profit()}")',
                                          'print(f"Total profit: {self.model.profit()}")\n            raise KeyError("late")')
PROG_INFEASIBLE_CRASH = PROG_INFEASIBLE.replace('print("Total cost: 42")\n',
                                                'raise ValueError("No value for uninitialized NumericValue object x")\n')
PROG_NO_SOLVE = 'import pyomo.environ\nprint("Total profit: 2600.0")\n'


@pytest.fixture(scope="module")
def fake_py(tmp_path_factory):
    """A venv (standard library only) with the stand-in pyomo in its site-packages."""
    py = orgene_python()
    if not os.path.exists(py):
        pytest.skip(f"generation interpreter {py} not present")
    d = tmp_path_factory.mktemp("fakevenv")
    subprocess.run([py, "-m", "venv", "--without-pip", str(d / "v")], check=True, capture_output=True, timeout=120)
    site = glob.glob(str(d / "v" / "lib" / "python3*" / "site-packages"))[0]
    for rel_path, text in FAKE_PYOMO.items():
        p = os.path.join(site, rel_path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    return str(d / "v" / "bin" / "python")


def _run(code, py, redirect=True):
    prog = A.with_solver_redirect(code)[0] if redirect else code
    return run_program(prog, timeout=60, python=py)


def test_redirect_turns_a_glpk_request_into_a_cbc_solve_and_the_record_gives_the_objective(fake_py):
    ex = _run(PROG_OPT, fake_py)
    assert ex["exec_ok"], ex["stderr_tail"]
    assert ex["stdout_tail"] == "Optimal solution found:\nUnits: 1300.0\nTotal profit: 2600.0\n"
    (s,) = ex["solve_records"]
    assert s["backend"] == "pyomo" and s["solver"] == "cbc" and s["status"] == "optimal" and s["objective"] == 2600.0
    d = A.derive_result(ex)
    assert (d["status"], d["objective"], d["objective_source"], d["failure"]) == ("Optimal", 2600.0, "solve_record", None)
    assert d["printed_objective"] == 2600.0 and d["printed_matches_record"] is True
    # without the prelude the program would ask glpk (the stand-in keeps the requested name)
    plain = _run(PROG_OPT, fake_py, redirect=False)
    assert plain["solve_records"][0]["solver"] == "glpk"
    assert plain["stdout_tail"] == ex["stdout_tail"]


def test_the_redirect_leaves_pyomos_own_nested_factory_calls_alone(fake_py):
    """Pyomo's cbc plug-in makes its shell solver with a nested SolverFactory call; a redirect that rewrites that
    call too recurses and the program fails (the first version of the prelude did this with the real Pyomo)."""
    naive = ("import pyomo.environ\nfrom pyomo.opt.base.solvers import SolverFactoryClass\n_o = SolverFactoryClass.__call__\n"
             "SolverFactoryClass.__call__ = lambda self, _name=None, **k: _o(self) if _name is None else _o(self, 'cbc', **k)\n")
    bad = run_program(naive + PROG_OPT, timeout=60, python=fake_py)
    assert not bad["exec_ok"] and "RecursionError" in bad["stderr_tail"]
    good = _run(PROG_OPT, fake_py)
    assert good["exec_ok"] and good["solve_records"][0]["solver"] == "cbc"


def test_an_infeasible_solve_gives_no_objective_even_when_a_number_is_printed(fake_py):
    d = A.derive_result(_run(PROG_INFEASIBLE, fake_py))
    assert d["status"] == "Infeasible" and d["objective"] is None and d["objective_source"] == "solve_record"
    assert d["printed_objective"] == 42.0  # printed, but the record decides


def test_a_program_that_fails_after_solving_is_not_credited(fake_py):
    ex = _run(PROG_CRASH_AFTER_SOLVE, fake_py)
    assert not ex["exec_ok"] and ex["solve_records"][0]["objective"] == 2600.0
    d = A.derive_result(ex)
    assert d["failure"] == "exec_failed" and d["objective"] is None and d["status"] is None
    assert d["record_status"] == "optimal" and d["record_objective"] == 2600.0  # kept, but not credited


def test_a_program_that_fails_after_an_infeasible_solve_gets_no_status(fake_py):
    """The usual crash of a Pyomo program: reading values after an infeasible solve. Its status must not reach the
    scorer, or an "infeasible" reference would be credited to a program that did not finish."""
    ex = _run(PROG_INFEASIBLE_CRASH, fake_py)
    assert not ex["exec_ok"] and ex["solve_records"][0]["status"] == "infeasible"
    d = A.derive_result(ex)
    assert (d["status"], d["objective"], d["failure"], d["record_status"]) == (None, None, "exec_failed", "infeasible")


def test_a_program_that_never_solves_falls_back_to_the_printed_value(fake_py):
    ex = _run(PROG_NO_SOLVE, fake_py)
    d = A.derive_result(ex)
    assert ex["solve_recorder"]["recorded"] and ex["solve_recorder"]["n_solves"] == 0
    assert (d["objective"], d["objective_source"], d["status"]) == (2600.0, "stdout_regex", None)


# ============================================================================================ objective rules


def _ex(records=(), stdout="", recorded=True, exec_ok=True, timed_out=False, capped=False):
    return {"exec_ok": exec_ok, "timed_out": timed_out, "stdout_tail": stdout, "returncode": 0 if exec_ok else 1,
            "solve_records": list(records),
            "solve_recorder": {"recorded": recorded, "n_solves": len(records), "n_problems": len(records) and 1,
                               "capped": capped}}


def _pyomo(status, obj=None, solver="cbc", error=None):
    r = {"backend": "pyomo", "status": status, "objective": obj, "solver": solver}
    if error:
        r["error"] = {"type": error, "message": "x"}
    return r


@pytest.mark.parametrize("tc,status", [("optimal", "Optimal"), ("globallyOptimal", "Optimal"), ("infeasible", "Infeasible"),
                                       ("unbounded", "Unbounded"), ("infeasibleOrUnbounded", "Undefined"),
                                       ("maxTimeLimit", "Not Solved"), ("other", "Not Solved"), (None, "Not Solved")])
def test_termination_conditions_map_to_status_words(tc, status):
    assert A.map_status({"backend": "pyomo", "status": tc}) == status


def test_the_record_beats_the_printed_value():
    d = A.derive_result(_ex([_pyomo("optimal", 12.333333)], "Objective value: 12\n"))
    assert d["objective"] == 12.333333 and d["objective_source"] == "solve_record"
    assert d["printed_objective"] == 12.0 and d["printed_matches_record"] is False


def test_the_last_solve_counts():
    d = A.derive_result(_ex([_pyomo("optimal", 1.0), _pyomo("optimal", 5.0)]))
    assert d["objective"] == 5.0


@pytest.mark.parametrize("ex,expect", [
    (_ex([_pyomo("maxTimeLimit", 7.0)], "Objective: 7"), ("Not Solved", None, "solve_record", None)),
    (_ex([_pyomo("optimal", None)], "Objective value: 3.5"), ("Optimal", 3.5, "stdout_regex", None)),
    (_ex([_pyomo("optimal", None)], "done"), ("Optimal", None, None, "no_objective")),
    (_ex([_pyomo(None, None, error="ApplicationError")], "Objective value: 3"), ("Not Solved", None, "solve_record", None)),
    (_ex([], "Total cost = 1,234.5"), (None, 1234.5, "stdout_regex", None)),
    (_ex([], "Total cost = 9", recorded=False), (None, 9.0, "stdout_regex", None)),
    (_ex([_pyomo("optimal", 4.0)], "Objective value: 3", capped=True), (None, 3.0, "stdout_regex", None)),
    (_ex([_pyomo("optimal", 4.0)], "", exec_ok=False), (None, None, None, "exec_failed")),
    (_ex([_pyomo("optimal", 4.0)], "", exec_ok=False, timed_out=True), (None, None, None, "timeout")),
    (_ex([_pyomo("infeasible")], "Total cost: 3", exec_ok=False), (None, None, None, "exec_failed")),
    (_ex([], "Total cost: 3", exec_ok=False), (None, None, None, "exec_failed")),
    (_ex([], "nothing printed here"), (None, None, None, "no_objective")),
])
def test_derivation_rules(ex, expect):
    d = A.derive_result(ex)
    assert (d["status"], d["objective"], d["objective_source"], d["failure"]) == expect


def test_the_scorer_reads_the_derived_values(tmp_path):
    cases = {c["case_id"]: c for c in D.load_cases(SMOKE_CASES)}
    rows = []
    for cid, ex in (("smoke-0001", _ex([_pyomo("optimal", 2600.0)], "Total profit: 2600.0")),
                    ("smoke-0002", _ex([_pyomo("infeasible")], "Total cost: 5360")),
                    ("smoke-0003", _ex([], "Objective Value:  380.0"))):
        d = A.derive_result(ex)
        rows.append({"case_id": cid, "repeat": 0, "exec": A.exec_for_scoring(ex, d),
                     "rounds": [{"round": 0, "hard_failed_genes": [], "out_tokens": 5, "in_tokens": 7}]})
    with open(tmp_path / "final.LLMOPT.jsonl", "w", encoding="utf-8") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))
    m = P.score_condition(str(tmp_path), "LLMOPT", cases)
    res = {r["case_id"]: r for r in map(json.loads, open(tmp_path / "results.LLMOPT.jsonl", encoding="utf-8"))}
    assert [res[c]["correct"] for c in ("smoke-0001", "smoke-0002", "smoke-0003")] == [True, False, True]
    assert res["smoke-0001"]["verified_correct"] is True
    assert res["smoke-0003"]["misreport"]["reported_without_solve"] is True  # printed only, no recorded solve
    assert m["n_correct"] == 2 and not any(r["protocol_ok"] for r in res.values())


def test_an_infeasible_reference_is_credited_only_to_a_program_that_finished(tmp_path):
    """A self-made case with a non-numeric reference: the same infeasible solve, once in a program that finished and
    once in a program that crashed afterwards (and once with an undecided status, never credited)."""
    ref = {"objective": None, "status": "infeasible"}
    cases = {f"synthetic-{k}": {"case_id": f"synthetic-{k}", "source": "synthetic", "reference": dict(ref)}
             for k in ("finished", "crashed", "undecided")}
    runs = {"synthetic-finished": _ex([_pyomo("infeasible")], "No feasible solution found."),
            "synthetic-crashed": _ex([_pyomo("infeasible")], "", exec_ok=False),
            "synthetic-undecided": _ex([_pyomo("infeasibleOrUnbounded")], "")}
    with open(tmp_path / "final.LLMOPT.jsonl", "w", encoding="utf-8") as f:
        for cid, ex in runs.items():
            row = {"case_id": cid, "repeat": 0, "exec": A.exec_for_scoring(ex, A.derive_result(ex)),
                   "rounds": [{"round": 0, "hard_failed_genes": [], "out_tokens": 1, "in_tokens": 1}]}
            f.write(json.dumps(row) + "\n")
    P.score_condition(str(tmp_path), "LLMOPT", cases)
    res = {r["case_id"]: r for r in map(json.loads, open(tmp_path / "results.LLMOPT.jsonl", encoding="utf-8"))}
    assert (res["synthetic-finished"]["correct"], res["synthetic-crashed"]["correct"],
            res["synthetic-undecided"]["correct"]) == (True, False, False)
    assert res["synthetic-crashed"]["status"] is None and res["synthetic-undecided"]["status"] == "Undefined"


# ============================================================================================ backup parser (draft)


@pytest.mark.parametrize("text,value,rule", [
    ("Optimal solution found:\nUnits of product A: 20.0\nUnits of product B: 60.0\nTotal profit: 2600.0\n", 2600.0,
     "total_phrase"),
    ("Objective Value:  380.0\nx[1,1] = 50.0\nx[2,2] = 40.0\n", 380.0, "objective"),
    ("Number of trips (x_s): 10.0\nTotal transportation cost: 5360.0\n", 5360.0, "total_phrase"),
    ("Maximum profit = $2,600.50\n", 2600.5, "optimal_phrase"),
    ("Optimal objective value: -1.5e+03\n", -1500.0, "objective"),
    ("The objective function value is 45.2 units.\n", 45.2, "objective"),
    ("Total profit: 10\nObjective value: 12\n", 12.0, "objective"),
    ("Objective value: 5\nx = 1\nObjective value: 7\n", 7.0, "objective"),
    ("Minimum total cost: 1234\n", 1234.0, "optimal_phrase"),
])
def test_printed_objective_parser_finds_the_value(text, value, rule):
    assert A.parse_printed_objective(text) == (value, rule)


@pytest.mark.parametrize("text", [
    "Optimal solution found:\nx = 5\n",
    "Solver Status:  ok\n",
    "Total machining hours used: 100\n",
    "Objective: maximize profit\n",
    "Units of product A: 20.0\n",
    "Objective value: None\n",
    "x[1,1] = 50.0\n",
    "",
])
def test_printed_objective_parser_ignores_other_lines(text):
    assert A.parse_printed_objective(text) == (None, None)


def test_the_parser_is_a_draft_until_the_dev_rehearsal():
    assert A.PARSER_FROZEN is False and "draft" in A.PARSER_VERSION


# ============================================================================================ chat template


REF = json.load(open(os.path.join(FIX, "llmopt_template_reference.json"), encoding="utf-8"))
SINGLE = [c for c in REF["cases"] if len(c["messages"]) == 1 and c["messages"][0]["role"] == "user"]


def _sha_file(name):
    with open(os.path.join(FIX, name), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_template_fixtures_are_the_pinned_templates():
    assert _sha_file("llmopt_ollama_template.gotmpl") == T.MODELFILE_TEMPLATE_SHA256 == REF["go"]["template_sha256"]
    assert _sha_file("qwen25_chat_template.jinja") == T.GGUF_TEMPLATE_SHA256 == REF["jinja"]["template_sha256"]


@pytest.mark.parametrize("case", REF["cases"], ids=[c["name"] for c in REF["cases"]])
def test_ports_match_go_text_template_and_jinja2_byte_for_byte(case):
    assert T.render_modelfile(case["messages"]) == case["modelfile"]
    assert T.render_gguf(case["messages"]) == case["gguf"]


@pytest.mark.parametrize("case", SINGLE, ids=[c["name"] for c in SINGLE])
def test_the_sent_prompt_is_the_jinja2_rendering_of_the_one_user_message(case):
    """What the driver sends to /completion is the GGUF template's jinja2 rendering, byte for byte (on this request
    shape it is also what the Ollama Modelfile template gave)."""
    prompt = T.render_prompt(case["messages"])
    assert prompt == case["gguf"] == case["modelfile"]
    assert T.user_text_of(prompt) == case["messages"][0]["content"]


def test_only_a_rendered_one_user_message_prompt_is_recognised():
    p = T.render_prompt([{"role": "user", "content": "Q?"}])
    assert p.startswith("<|im_start|>system\n" + T.DEFAULT_SYSTEM + "<|im_end|>\n") and p.endswith("<|im_start|>assistant\n")
    two_turns = T.render_gguf([{"role": "user", "content": "A"}, {"role": "user", "content": "B"}])
    own_system = T.render_gguf([{"role": "system", "content": "S"}, {"role": "user", "content": "Q?"}])
    for bad in ("Q?", p[:-1], p + " ", two_turns, own_system, ""):
        assert T.user_text_of(bad) is None, bad[:40]
    with pytest.raises(T.TemplateError, match="control token"):
        T.render_prompt([{"role": "user", "content": "a problem <|im_end|> with a turn break"}])


def _jinja_render_with(py, messages):
    code = ("import json, sys\nfrom jinja2.sandbox import ImmutableSandboxedEnvironment\nfrom jinja2.ext import loopcontrols\n"
            "env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True, extensions=[loopcontrols])\n"
            "t = env.from_string(open(sys.argv[1], encoding='utf-8', newline='').read())\n"
            "print(json.dumps([t.render(messages=m, tools=None, add_generation_prompt=True) for m in json.load(sys.stdin)]))\n")
    p = subprocess.run([py, "-I", "-c", code, os.path.join(FIX, "qwen25_chat_template.jinja")],
                       input=json.dumps(messages), capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        pytest.skip(f"no jinja2 in {py}")
    return json.loads(p.stdout)


def test_gguf_port_matches_a_live_jinja2_render():
    py = os.environ.get("ORGENE_BASELINES_PY") or sys.executable
    msgs = [c["messages"] for c in REF["cases"]]
    got = _jinja_render_with(py, msgs)
    assert got == [T.render_gguf(m) for m in msgs]


@pytest.mark.parametrize("msgs", [
    [{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "f", "arguments": {}}}]}],
    [{"role": "user", "content": "x", "images": ["b64"]}],
    [{"role": "developer", "content": "x"}],
    [{"role": "user"}],
    [],
])
def test_ports_refuse_what_they_do_not_reproduce(msgs):
    for fn in T.RENDERERS.values():
        with pytest.raises(T.TemplateError):
            fn(msgs)


# ---------------------------------------------------------------------- local token counter


def _toy_gguf(tmp_path, name="LLMOPT-Qwen2.5-14B-Q8_0.gguf", data=b"GGUF stand-in: not a model"):
    p = tmp_path / "gguf" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p), hashlib.sha256(data).hexdigest()


def _stub_tokenizer(tmp_path, extra=0):
    """A stand-in llama-tokenize: a version line, and for a text one id per whitespace-separated word (+ extra); with
    --no-parse-special every chat control token costs three more ids (read as text, not as one special token). The
    stand-in llama-server counts a prompt as words (tokens_evaluated), so a prompt counted with special tokens parsed
    agrees with it when extra=0, and not when extra=1 or when the specials are not parsed."""
    p = tmp_path / f"llama-tokenize-stub-{extra}"
    p.write_text(f"#!{sys.executable}\n"
                 "import json, sys\n"
                 "if '--version' in sys.argv:\n"
                 "    print('version: 0 (stand-in)')\n"
                 "    sys.exit(0)\n"
                 "text = sys.stdin.buffer.read().decode('utf-8')\n"
                 "n = len(text.split()) + (3 * text.count('<|') if '--no-parse-special' in sys.argv else 0)\n"
                 f"print(json.dumps(list(range(n + {extra}))))\n", encoding="utf-8")
    p.chmod(0o755)
    return str(p)


def test_the_counter_checks_the_gguf_and_counts_the_rendered_prompt(tmp_path):
    gguf, digest = _toy_gguf(tmp_path)
    stub = _stub_tokenizer(tmp_path)
    with pytest.raises(TC.TokenizerError, match="sha256"):
        T.GgufCounter(gguf, "0" * 64, binary=stub)
    c = T.GgufCounter(gguf, digest, binary=stub)
    prompt = T.render_prompt([{"role": "user", "content": "Say one word."}])
    lt = c.local_tokens([{"role": "user", "content": prompt}], "Hello there")
    assert lt["rendered_prompt"] == len(prompt.split()) and lt["prompt_is_rendered"] is True
    assert lt["content_total"] == 3 and lt["completion"] == 2 and lt["tokenizer_sha256"] == c.identity_sha256
    ident = c.identity()
    assert ident["gguf_sha256"] == digest and ident["gguf_file"] == os.path.basename(gguf)
    assert ident["prompt_template_sha256"] == T.GGUF_TEMPLATE_SHA256 and str(tmp_path) not in json.dumps(ident)


def test_real_tokenizer_counts_the_smoke_q2f_prompts_as_the_hf_tokenizer():
    """On the model host: ORGENE_LLMOPT_GGUF names the LLMOPT GGUF, the upstream prompts are installed and llama.cpp's
    llama-tokenize is present. The three smoke Q2F prompts count 554 / 549 / 564 tokens, the HF tokenizer's counts
    recorded by the baseline-environment task."""
    gguf = os.environ.get("ORGENE_LLMOPT_GGUF")
    if not gguf or not os.path.isfile(gguf) or not os.path.isfile(PR.VENDOR_FILE):
        pytest.skip("set ORGENE_LLMOPT_GGUF to the LLMOPT GGUF on the model host (with the upstream prompts installed)")
    try:
        c = T.GgufCounter(gguf, MR.read(REG_PATH)["entries"][ENTRY_ID]["digest"])
    except TC.TokenizerError as e:
        pytest.skip(f"llama-tokenize not usable here: {e}")
    pr = PR.load()
    counts = [c.count_prompt(T.render_prompt(A.q2f_messages(x["text"], pr))) for x in D.load_cases(SMOKE_CASES)]
    assert counts == [554, 549, 564]


# ============================================================================================ registry entry


def _reg():
    return MR.read(REG_PATH)


def test_the_committed_llmopt_entry():
    reg = _reg()
    assert MR.validate(reg) == []
    e, anchor = reg["entries"][ENTRY_ID], reg["anchors"]["llmopt"]
    assert e["backend"] == "llamacpp_completion" and e["model"] == T.SERVER_ALIAS and e["seed_rule"] == "fixed"
    assert e["digest"] == anchor["gguf"]["sha256"] and e["identity"]["gguf_file"] == anchor["gguf"]["file"]
    assert e["opts"] == {"temperature": 0.0, "top_k": 0, "top_p": 1.0, "min_p": 0.0, "typical_p": 1.0,
                         "repeat_penalty": 1.0, "presence_penalty": 0.0, "frequency_penalty": 0.0, "dry_multiplier": 0.0,
                         "xtc_probability": 0.0, "mirostat": 0, "seed": 1, "n_predict": 8192, "cache_prompt": False,
                         "stop": ["<|im_end|>", "<|endoftext|>"]}
    assert e["identity"]["server"] == {"ctx_size": 32768, "parallel": 1, "cache_type_k": "f16", "cache_type_v": "f16",
                                       "flash_attn": "off", "gpu_layers": "all", "batch_size": 2048, "ubatch_size": 512,
                                       "context_shift": False, "cache_ram_mib": 0, "cache_reuse": 0}
    assert e["identity"]["prompt_template_sha256"] == T.GGUF_TEMPLATE_SHA256
    assert e["identity"]["llama_cpp_build"] == reg["baselines"]["llama_cpp"]["build"]
    assert e["status"] == "pending" and MR.entry_pending(e)  # the one pending marker
    assert "chat_template" not in e and ENTRY_ID in anchor["run_settings"] and "llamacpp_completion" in anchor["run_settings"]
    assert any(b.startswith("n_predict 8192 per step") and "fidelity to the original method" in b for b in e["basis"])
    # the ORLM anchor's neutral samplers (only the output budget and the stop strings differ)
    o = reg["entries"]["orlm-llama3-8b.anchor"]["opts"]
    assert {k: v for k, v in e["opts"].items() if k not in ("n_predict", "stop")} == \
        {k: v for k, v in o.items() if k not in ("n_predict", "stop")}


@pytest.mark.parametrize("value,ok", [("pending", True), ("PENDING", False), ("final", False), (None, False), (1, False)])
def test_validate_accepts_only_the_pending_status(value, ok):
    reg = _reg()
    reg["entries"][ENTRY_ID]["status"] = value
    probs = [p for p in MR.validate(reg) if ".status:" in p]
    assert (probs == []) is ok
    del reg["entries"][ENTRY_ID]["status"]  # a final entry has no status key
    assert MR.validate(reg) == [] and not MR.entry_pending(reg["entries"][ENTRY_ID])


def test_the_chat_template_exception_is_gone_with_the_ollama_entry():
    """No runner entry chats with the LLMOPT model through Ollama any more, so the registry is back to one rule: an
    Ollama runner entry's model must chat with its template blob, and `chat_template` is no entry key."""
    reg = _reg()
    snap = json.load(open(os.path.join(ROOT, reg["generated"]["snapshot"]), encoding="utf-8"))
    mism, notes = MR.compare_snapshot(reg, snap)
    assert mism == [] and not any("chat_template" in n for n in notes)
    o = reg["anchors"]["llmopt"]["ollama"]
    back = json.loads(json.dumps(reg))
    back["entries"]["llmopt-ollama.test"] = {
        "backend": "ollama", "model": o["model"], "digest": o["digest"], "seed_rule": "fixed", "purpose": "test entry",
        "opts": {"temperature": 0.0, "top_k": 20, "top_p": 0.8, "seed": 1, "num_ctx": 32768, "num_predict": 8192,
                 "think": False, "keep_alive": 0}}
    assert any("/api/show template differs from the template blob" in m for m in MR.compare_snapshot(back, snap)[0])
    declared = json.loads(json.dumps(reg))
    declared["entries"][ENTRY_ID]["chat_template"] = {"template_blob_sha256": T.MODELFILE_TEMPLATE_SHA256}
    assert any("unknown key 'chat_template'" in p for p in MR.validate(declared))
    q = reg["entries"]["qwen3-8b.main"]
    cfg = {"backend": "ollama",
           "identity": {"model": "qwen3:8b", "digest": q["digest"], "template_sha256": T.GGUF_TEMPLATE_SHA256},
           "opts": {k: v for k, v in q["opts"].items() if k != "seed"}, "seed_base": 1,
           "registry": {"entry_id": "qwen3-8b.main", "entry_sha256": MR.entry_sha256(q)}}
    assert any("template" in p for p in MR.verify_run_config(reg, cfg))


def test_the_backend_guard_and_the_registry_agree_on_the_llmopt_entry():
    e = _reg()["entries"][ENTRY_ID]
    b = LlamaCppCompletionBackend(e["model"], host="http://127.0.0.1:9", digest=e["digest"])
    b._identity = {"digest": e["digest"]}
    msgs = [{"role": "user", "content": T.render_prompt([{"role": "user", "content": "x"}])}]
    sent = b.sent_opts(b.build_body(msgs, dict(e["opts"])))
    registry_guard(e, backend=b)(sent)
    assert MR.compare_sent(e, sent, backend_kind=b.kind, model=e["model"], digest=e["digest"]) == []
    for bad in (dict(e["opts"], n_predict=6000), dict(e["opts"], cache_prompt=True), dict(e["opts"], temperature=0.7),
                dict(e["opts"], seed=2), dict(e["opts"], stop=["<|im_end|>"])):
        with pytest.raises(RegistryMismatch):
            registry_guard(e, backend=b)(b.sent_opts(b.build_body(msgs, bad)))


def test_the_server_command_line_comes_from_the_entry():
    argv = LS.server_argv(_reg()["entries"][ENTRY_ID], "/tmp/x/LLMOPT-Qwen2.5-14B-Q8_0.gguf", port=8123,
                          prefix="[llmopt]")
    s = " ".join(argv)
    for frag in ("-m /tmp/x/LLMOPT-Qwen2.5-14B-Q8_0.gguf", "--alias llmopt-qwen25-14b-q8", "--port 8123", "-c 32768",
                 "-np 1", "-ctk f16", "-ctv f16", "-fa off", "-ngl all", "--no-context-shift", "--cache-ram 0",
                 "--cache-reuse 0"):
        assert frag in s, frag


# ============================================================================================ driver end to end


def _answer_for(prompt):
    """The stand-in model: answers the synthetic Q2F and F2C prompts by content."""
    text = T.user_text_of(prompt) or ""
    if text.startswith("SYNTHETIC-Q2F"):
        mark = "W" if "workshop" in text else "L" if "logistics" in text else "Z"
        return f"```text\n## Sets: \nFIVE[{mark}]\n```"
    if "FIVE[W]" in text:
        return "```python\n" + PROG_OPT + "```"
    if "FIVE[L]" in text:
        return "Here it is:\n```python\n" + PROG_INFEASIBLE + "```"
    return "I cannot write this model."


@pytest.fixture
def e2e(tmp_path, monkeypatch, fake_py):
    gguf, digest = _toy_gguf(tmp_path)
    reg = MR.read(REG_PATH)
    reg["entries"][ENTRY_ID]["digest"] = digest  # the stand-in GGUF, under the registered file name
    reg["baselines"]["packages"]["pyomo"] = "fake-1"  # the stand-in package
    reg["execution"]["cbc_version"] = "9.9.9-fake"
    reg_path = tmp_path / "model_registry.json"
    reg_path.write_text(json.dumps(reg))
    cbc = tmp_path / "bin" / "cbc"
    cbc.parent.mkdir()
    cbc.write_text("#!/bin/sh\necho 'Welcome to a stand-in CBC'\necho 'Version: 9.9.9-fake'\n")
    cbc.chmod(0o755)
    monkeypatch.setattr(PR, "load", lambda *a, **k: _synthetic_prompts())
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))  # execute prepends the CBC directory; restored afterwards
    fake = FakeLlamaServer(answer_for=_answer_for, model_path=os.path.join(os.sep + "models", os.path.basename(gguf)),
                           n_ctx=32768, slots=1, alias=T.SERVER_ALIAS)
    yield argparse.Namespace(reg=str(reg_path), out=str(tmp_path / "run"), fake=fake, py=fake_py, cbc=str(cbc),
                             entry=reg["entries"][ENTRY_ID], gguf=gguf, tmp=tmp_path)
    fake.close()


def _prepare(e, out=None, reg=None):
    RUN.main(["prepare", "--source", "smoke", "--split", "smoke", "--out", out or e.out, "--registry", reg or e.reg])


def _gen(e, step, *extra, out=None, reg=None, local=False):
    return [step, "--out", out or e.out, "--registry", reg or e.reg, "--gguf", e.gguf, "--host", e.fake.url,
            "--retry-sleep", "0", *([] if local else ["--no-local-tokens"]), *extra]


def _stage(out, step):
    return json.load(open(os.path.join(out, "run_config.json"), encoding="utf-8"))["stages"][f"generate:{step}"]


def test_driver_runs_both_steps_on_llama_server_executes_and_scores(e2e):
    e = e2e
    _prepare(e)
    cfg = json.load(open(os.path.join(e.out, "run_config.json"), encoding="utf-8"))
    assert cfg["case_ids"] == ["smoke-0001", "smoke-0002", "smoke-0003"] and cfg["not_for_release"] == RUN.NOT_FOR_RELEASE
    assert RUN.main(_gen(e, "q2f")) == 0
    assert RUN.main(_gen(e, "f2c")) == 0
    bodies = e.fake.completions()
    assert len(bodies) == 6 and not any(p != "/completion" for p, _ in e.fake.posts)
    for body in bodies:
        assert T.user_text_of(body["prompt"]) is not None  # one user message rendered with the GGUF template
        assert {k: body[k] for k in e.entry["opts"]} == e.entry["opts"] and body["model"] == T.SERVER_ALIAS
        assert body["cache_prompt"] is False and body["n_predict"] == 8192 and body["temperature"] == 0
    smoke = D.load_cases(SMOKE_CASES)
    assert bodies[0]["prompt"] == T.render_prompt(A.q2f_messages(smoke[0]["text"], _synthetic_prompts()))
    gcfg = json.load(open(os.path.join(e.out, "gen.q2f", "config.json"), encoding="utf-8"))
    assert gcfg["registry"]["entry_id"] == ENTRY_ID and gcfg["backend"] == "llamacpp_completion"
    assert MR.verify_run_config(MR.read(e.reg), gcfg) == []
    s = _stage(e.out, "q2f")
    assert s["summary"]["n_ok"] == 3 and s["summary"]["n_prompt_tokens_mismatch"] == 0 and s["local_tokens"] is False
    assert s["gguf_file"] == os.path.basename(e.gguf) and not s["server_launched_by_driver"]
    extract = {r["case_id"]: r for r in map(json.loads, open(os.path.join(e.out, "extract.q2f.jsonl"), encoding="utf-8"))}
    assert all(r["five_elements_found"] for r in extract.values())
    RUN.main(["execute", "--out", e.out, "--registry", e.reg, "--python", e.py, "--cbc", e.cbc])
    xcfg = json.load(open(os.path.join(e.out, "exec_config.json"), encoding="utf-8"))
    assert xcfg["pyomo_version"] == "fake-1" and xcfg["redirect_target"] == "cbc" and not os.path.isabs(xcfg["python"])
    final = {r["case_id"]: r for r in map(json.loads, open(os.path.join(e.out, "final.LLMOPT.jsonl"), encoding="utf-8"))}
    f1, f2, f3 = final["smoke-0001"], final["smoke-0002"], final["smoke-0003"]
    assert (f1["exec"]["objective"], f1["exec"]["objective_source"]) == (2600.0, "solve_record")
    assert f1["llmopt"]["record_solver"] == "cbc" and f1["llmopt"]["stop_type"] == {"q2f": "eos", "f2c": "eos"}
    assert f1["llmopt"]["requested_solvers"] == ["glpk"] and f1["n_model_calls"] == 2
    q, f = (RUN._outputs(os.path.join(e.out, d))["smoke-0001"] for d in ("gen.q2f", "gen.f2c"))
    assert f1["rounds"][0]["in_tokens"] == q["prompt_eval_count"] + f["prompt_eval_count"] > 0
    assert (f2["exec"]["status"], f2["exec"]["objective"]) == ("Infeasible", None)
    assert f3["program"] is None and f3["llmopt"]["failure"] == "no_code" and f3["exec"]["exec_ok"] is False
    RUN.main(["score", "--out", e.out, "--registry", e.reg])
    res = {r["case_id"]: r for r in map(json.loads, open(os.path.join(e.out, "results.LLMOPT.jsonl"), encoding="utf-8"))}
    assert [res[c]["correct"] for c in ("smoke-0001", "smoke-0002", "smoke-0003")] == [True, False, False]


def test_the_server_must_count_every_prompt_as_the_local_tokenizer(e2e, monkeypatch):
    e = e2e
    monkeypatch.setenv(TC.ENV_LLAMA_TOKENIZE, _stub_tokenizer(e.tmp, extra=0))
    _prepare(e)
    assert RUN.main(_gen(e, "q2f", local=True)) == 0
    s = _stage(e.out, "q2f")
    assert s["local_tokens"] is True and s["summary"]["n_local_counted"] == 3
    assert s["summary"]["n_prompt_tokens_mismatch"] == 0
    for r in RUN._outputs(os.path.join(e.out, "gen.q2f")).values():
        assert r["local_tokens"]["rendered_prompt"] == r["prompt_eval_count"] and r["local_tokens"]["prompt_is_rendered"]
    gcfg = json.load(open(os.path.join(e.out, "gen.q2f", "config.json"), encoding="utf-8"))
    assert gcfg["local_tokens_counter"] == "baselines.llmopt.templates:GgufCounter"
    # a tokenizer that counts one token more than the server: the step fails
    monkeypatch.setenv(TC.ENV_LLAMA_TOKENIZE, _stub_tokenizer(e.tmp, extra=1))
    out2 = str(e.tmp / "run2")
    _prepare(e, out=out2)
    assert RUN.main(_gen(e, "q2f", local=True, out=out2)) == 4
    assert _stage(out2, "q2f")["summary"]["n_prompt_tokens_mismatch"] == 3


def test_driver_refuses_another_model_file_or_server_before_any_call(e2e):
    e = e2e
    _prepare(e)
    other = e.tmp / "other.gguf"
    other.write_bytes(b"x")
    args = _gen(e, "q2f")
    with pytest.raises(SystemExit, match="registry names"):
        RUN.main([str(other) if a == e.gguf else a for a in args])
    same_name, _ = _toy_gguf(e.tmp / "elsewhere", data=b"another model under the registered name")
    with pytest.raises(SystemExit, match="differs from the registry entry's digest"):
        RUN.main([same_name if a == e.gguf else a for a in args])
    e.fake.n_ctx = 8192
    with pytest.raises(SystemExit, match="llama-server differs from the registry entry: context"):
        RUN.main(args)
    assert e.fake.completions() == []


def test_driver_refuses_a_request_that_is_not_one_rendered_user_message(e2e):
    e = e2e
    _prepare(e)
    p = os.path.join(e.out, "requests.q2f.jsonl")
    rows = [json.loads(line) for line in open(p, encoding="utf-8")]

    def write(rs):
        with open(p, "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rs))
    bad = json.loads(json.dumps(rows))
    bad[0]["messages"].insert(0, {"role": "system", "content": "S"})
    write(bad)
    with pytest.raises(SystemExit, match="one user message"):
        RUN.main(_gen(e, "q2f"))
    raw = json.loads(json.dumps(rows))
    raw[0]["messages"][0]["content"] = T.user_text_of(raw[0]["messages"][0]["content"])  # the user text, not rendered
    write(raw)
    with pytest.raises(SystemExit, match="not a prompt rendered with the GGUF chat template"):
        RUN.main(_gen(e, "q2f"))
    assert e.fake.completions() == []


def test_driver_steps_must_run_in_order(e2e):
    e = e2e
    _prepare(e)
    with pytest.raises(SystemExit, match="q2f is not complete"):
        RUN.main(_gen(e, "f2c"))
    with pytest.raises(SystemExit, match="f2c has not been prepared"):
        RUN.main(["execute", "--out", e.out, "--registry", e.reg, "--python", e.py, "--cbc", e.cbc])


def _registry_with(e, name, section, key, value):
    reg = json.load(open(e.reg, encoding="utf-8"))
    (reg[section]["packages"] if section == "baselines" else reg[section])[key] = value
    p = os.path.join(os.path.dirname(e.reg), name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(reg, f)
    return p


def test_a_registry_entry_changed_after_prepare_is_refused(e2e):
    e = e2e
    _prepare(e)
    reg = json.load(open(e.reg, encoding="utf-8"))
    reg["entries"][ENTRY_ID]["opts"]["n_predict"] = 6000
    changed = os.path.join(os.path.dirname(e.reg), "r_changed.json")
    with open(changed, "w", encoding="utf-8") as f:
        json.dump(reg, f)
    with pytest.raises(SystemExit, match="changed since `prepare`"):
        RUN.main(_gen(e, "q2f", reg=changed))
    assert e.fake.completions() == []


def test_execution_environment_must_match_the_registry(e2e):
    e = e2e
    _prepare(e)
    RUN.main(_gen(e, "q2f"))
    RUN.main(_gen(e, "f2c"))
    for reg, msg in ((_registry_with(e, "r_pyomo.json", "baselines", "pyomo", "6.10.1"), "Pyomo fake-1 is not the registry's"),
                     (_registry_with(e, "r_cbc.json", "execution", "cbc_version", "2.10.13"), "CBC version 9.9.9-fake")):
        with pytest.raises(SystemExit, match=msg):
            RUN.main(["execute", "--out", e.out, "--python", e.py, "--cbc", e.cbc, "--registry", reg])
    assert not os.path.exists(os.path.join(e.out, "final.LLMOPT.jsonl"))


def test_test_split_needs_a_frozen_parser_a_final_entry_and_the_test_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(PR, "load", lambda *a, **k: _synthetic_prompts())
    out = str(tmp_path / "t")
    with pytest.raises(SystemExit, match="not frozen"):
        RUN.main(["prepare", "--source", "smoke", "--split", "test", "--out", out])
    monkeypatch.setattr(A, "PARSER_FROZEN", True)
    with pytest.raises(SystemExit, match="still pending"):  # the committed entry is still pending
        RUN.main(["prepare", "--source", "smoke", "--split", "test", "--out", out])
    reg = MR.read(REG_PATH)
    reg["entries"][ENTRY_ID]["notes"] = "pending in words only: the status key decides"
    del reg["entries"][ENTRY_ID]["status"]
    fixed = tmp_path / "registry_fixed.json"
    fixed.write_text(json.dumps(reg))
    if os.path.exists(os.path.join(ROOT, "FREEZE_MANIFEST.json")):
        pytest.skip("a freeze manifest exists in this checkout")
    with pytest.raises(SystemExit, match="test gate"):
        RUN.main(["prepare", "--source", "smoke", "--split", "test", "--out", out, "--registry", str(fixed)])
    assert not os.path.exists(os.path.join(out, "requests.q2f.jsonl"))


def test_a_sealed_run_must_launch_the_server_itself(e2e, monkeypatch):
    e = e2e
    reg = json.load(open(e.reg, encoding="utf-8"))
    del reg["entries"][ENTRY_ID]["status"]  # as if decided
    fixed = os.path.join(os.path.dirname(e.reg), "r_fixed.json")
    with open(fixed, "w", encoding="utf-8") as f:
        json.dump(reg, f)
    _prepare(e, reg=fixed)
    p = os.path.join(e.out, "run_config.json")
    cfg = json.load(open(p, encoding="utf-8"))
    cfg["split"] = "test"  # as if the requests were for sealed cases
    json.dump(cfg, open(p, "w", encoding="utf-8"))
    monkeypatch.setattr(A, "PARSER_FROZEN", True)
    with pytest.raises(SystemExit, match="--launch"):
        RUN.main(_gen(e, "q2f", reg=fixed))
    assert e.fake.completions() == []


class _OllamaPs:
    """A minimal stand-in for Ollama's /api/ps."""

    def __init__(self, ps):
        self.ps = ps
        me = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                data = json.dumps(me.ps if self.path == "/api/ps" else {}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_launch_starts_llama_server_with_the_entry_settings_and_stops_it(e2e, monkeypatch):
    e = e2e
    wrapper = e.tmp / "llama-server"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {os.path.join(HERE, 'fake_llama_server.py')} \"$@\"\n")
    wrapper.chmod(0o755)
    argv_file = e.tmp / "argv.json"
    monkeypatch.setenv("FAKE_LLAMA_ARGV_FILE", str(argv_file))
    monkeypatch.setenv("FAKE_LLAMA_ANSWER", "```text\n## Sets: \nFIVE[W]\n```")
    port = _free_port()
    ollama = _OllamaPs({"models": [{"name": "some-model:latest"}]})  # an Ollama that holds a model
    try:
        _prepare(e)
        gen = ["q2f", "--out", e.out, "--registry", e.reg, "--gguf", e.gguf, "--launch", "--llama-server", str(wrapper),
               "--port", str(port), "--server-wait", "60", "--retry-sleep", "0", "--no-local-tokens"]
        with pytest.raises(SystemExit, match="Ollama holds 1 model"):
            RUN.main(gen + ["--ollama-host", ollama.url])
        assert not argv_file.exists()  # nothing was started
        ollama.ps = {"models": []}
        assert RUN.main(gen + ["--ollama-host", ollama.url]) == 0
    finally:
        ollama.close()
    argv = json.load(open(argv_file, encoding="utf-8"))
    for flag, value in (("-c", "32768"), ("-np", "1"), ("-ctk", "f16"), ("-ctv", "f16"), ("-fa", "off"),
                        ("--cache-ram", "0"), ("--cache-reuse", "0"), ("--alias", T.SERVER_ALIAS)):
        assert argv[argv.index(flag) + 1] == value, flag
    assert "--no-context-shift" in argv
    s = _stage(e.out, "q2f")
    assert s["server_launched_by_driver"] and s["summary"]["n_ok"] == 3 and s["launch"]["stopped_at"]
    assert s["launch"]["argv"][2] == "<outside-root>/" + os.path.basename(e.gguf)  # the model path is not recorded
    assert os.path.exists(os.path.join(e.out, "gen.q2f", "llama_server.log"))
    with pytest.raises(OSError):  # the server was stopped
        socket.create_connection(("127.0.0.1", port), timeout=2).close()


# ============================================================================================ real Pyomo + CBC (optional)

needs_baselines = pytest.mark.skipif(not os.environ.get("ORGENE_BASELINES_PY"),
                                     reason="set ORGENE_BASELINES_PY to the baseline interpreter (Pyomo)")
REAL_PROG = '''
from pyomo.environ import *


class ProductMix:
    def __init__(self):
        m = self.model = ConcreteModel()
        m.P = Set(initialize=['A', 'B'])
        m.profit = Param(m.P, initialize={'A': 40, 'B': 30})
        m.x = Var(m.P, domain=NonNegativeReals)
        m.obj = Objective(expr=sum(m.profit[p] * m.x[p] for p in m.P), sense=maximize)
        m.machining = Constraint(expr=2 * m.x['A'] + m.x['B'] <= 100)
        m.assembly = Constraint(expr=m.x['A'] + m.x['B'] <= 80)

    def solve(self):
        results = SolverFactory('glpk').solve(self.model, tee=False)
        if results.solver.termination_condition == TerminationCondition.optimal:
            print(f"Total profit: {self.model.obj()}")


def main():
    ProductMix().solve()


if __name__ == "__main__":
    main()
'''


@needs_baselines
def test_real_pyomo_glpk_request_is_solved_by_cbc_and_recorded(monkeypatch):
    py = os.environ["ORGENE_BASELINES_PY"]
    monkeypatch.setenv("PATH", os.path.dirname(RUN.DEFAULT_CBC) + os.pathsep + os.environ.get("PATH", ""))
    ex = _run(REAL_PROG, py)
    assert ex["exec_ok"], ex["stderr_tail"]
    (s,) = ex["solve_records"]
    assert s["solver"] == "cbc" and s["status"] == "optimal" and abs(s["objective"] - 2600) < 1e-6
    d = A.derive_result(ex)
    assert d["objective_source"] == "solve_record" and abs(d["objective"] - 2600) < 1e-6 and d["printed_matches_record"]
    infeasible = REAL_PROG.replace("<= 100)", "<= 100)\n        m.bad = Constraint(expr=m.x['A'] >= 200)")
    d2 = A.derive_result(_run(infeasible, py))
    assert d2["status"] == "Infeasible" and d2["objective"] is None
    # reading the values after that infeasible solve raises in Pyomo: the program did not finish, no status
    crash = infeasible.replace("        if results.solver.termination_condition == TerminationCondition.optimal:\n", "") \
        .replace('            print(f"Total profit: {self.model.obj()}")', '        print(f"Total profit: {value(self.model.obj)}")')
    ex3 = _run(crash, py)
    d3 = A.derive_result(ex3)
    assert not ex3["exec_ok"] and (d3["status"], d3["record_status"], d3["failure"]) == (None, "infeasible", "exec_failed")
    # a traceback through the baseline environment's packages: run_program keeps no home-directory path (E12)
    broken = REAL_PROG.replace("initialize={'A': 40, 'B': 30}", "initialize={'A': 40}")  # Pyomo raises on profit['B']
    ex = _run(broken, py)
    assert not ex["exec_ok"] and "Traceback" in ex["stderr_tail"]
    from orgene.paths import find_absolute_paths
    assert not find_absolute_paths(json.dumps(ex)) and os.path.expanduser("~") + os.sep not in json.dumps(ex)


@needs_baselines
def test_real_execution_environment_matches_the_registry(monkeypatch):
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    ns = argparse.Namespace(cbc=RUN.DEFAULT_CBC, python=os.environ["ORGENE_BASELINES_PY"])
    cfg = RUN.exec_env(ns, MR.read(REG_PATH))
    assert cfg["pyomo_version"] == "6.10.1" and cfg["cbc_version"] == "2.10.13" and cfg["timeout_s"] == 60
