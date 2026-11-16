"""E12: the solve recorder and its use in execute.run_program.

Fixtures are self-made small programs (solve_fixtures.py); no benchmark case is read. The execution tests need the
generation interpreter (ORGENE_PY, default /opt/homebrew/bin/python3) with PuLP + CBC.
"""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import solve_fixtures as FX  # noqa: E402

from orgene import paths as PA  # noqa: E402
from orgene import solve_recorder as SR  # noqa: E402
from orgene.execute import RECORDER_PATH, read_solve_log, run_program, stage_recorder  # noqa: E402

needs_py = pytest.mark.skipif(not os.path.exists(FX.PY), reason=f"generation interpreter {FX.PY} not present")
TEMP_NAME = re.compile(r"orgene_exec_[A-Za-z0-9_]+")


# ------------------------------------------------------------------ what is recorded


@needs_py
def test_record_fields_of_an_honest_solve():
    r = run_program(FX.HONEST, timeout=60)
    summ, recs = r["solve_recorder"], r["solve_records"]
    assert summ["recorded"] and summ["finished"] and summ["exit"] == "normal" and summ["fallback"] is None
    assert summ["hooks"]["pulp"].startswith("monitored:") and summ["hooks"]["pyomo"] in ("absent", "call_sites")
    assert summ["n_solves"] == 1 and summ["n_problems"] == 1 and not summ["in_flight"] and not summ["capped"]
    (s,) = recs
    assert s["backend"] == "pulp" and s["entry"] == "LpProblem.solve" and s["solver"] == "PULP_CBC_CMD"
    assert s["status"] == "Optimal" and s["status_code"] == 1 and s["sol_status"] == "Optimal Solution Found"
    assert abs(s["objective"] - 2600.0) < 1e-6 and s["sense"] == "maximize"
    assert s["n_variables"] == 2 and s["n_constraints"] == 2 and s["problem_ordinal"] == 1
    assert "error" not in s


@needs_py
def test_infeasible_solve_is_recorded_as_infeasible():
    r = run_program(FX.INFEASIBLE_SAYS_OPTIMAL, timeout=60)
    assert r["status"] == "Optimal"  # what the program printed
    assert r["solve_records"][-1]["status"] == "Infeasible"  # what the solver returned


@needs_py
def test_distinct_problems_are_counted():
    r = run_program(FX.TWO_MODELS, timeout=60)
    assert [s["problem_ordinal"] for s in r["solve_records"]] == [1, 2] and r["solve_recorder"]["n_problems"] == 2
    r = run_program(FX.HEAD + FX.SOLVE + FX.SOLVE + FX.PRINT, timeout=60)
    assert r["solve_recorder"]["n_solves"] == 2 and r["solve_recorder"]["n_problems"] == 1


@needs_py
@pytest.mark.parametrize("call,entry", [
    ("prob.solve(pulp.PULP_CBC_CMD(msg=0))", "LpProblem.solve"),
    ("pulp.PULP_CBC_CMD(msg=0).solve(prob)", "LpSolver.solve"),
    ("pulp.PULP_CBC_CMD(msg=0).actualSolve(prob)", "PULP_CBC_CMD.actualSolve"),
])
def test_every_pulp_entry_point_gives_exactly_one_record(call, entry):
    r = run_program(FX.HEAD + call + "\n" + FX.PRINT, timeout=60)
    assert r["solve_recorder"]["n_solves"] == 1, r["solve_records"]
    (s,) = r["solve_records"]
    assert s["entry"] == entry and s["status"] == "Optimal" and abs(s["objective"] - 2600) < 1e-6


@needs_py
def test_a_solve_that_raises_is_recorded_with_its_error_and_no_temp_path():
    r = run_program(FX.ERRORS["error_inside_solver"], timeout=60)
    assert not r["exec_ok"] and "PulpSolverError" in r["stderr_tail"]
    (s,) = r["solve_records"]
    assert s["error"]["type"] == "PulpSolverError" and s["status"] == "Not Solved"
    assert "orgene_exec_" not in s["error"]["message"] and "<prog-dir>" in s["error"]["message"]


@needs_py
def test_program_does_not_see_the_record_file():
    r = run_program("import os\nprint('STATUS: x')\nprint('FINAL_OBJECTIVE:', len(os.listdir('.')))\n", timeout=30)
    assert r["objective"] == 1.0  # only prog.py in its working directory


@needs_py
def test_record_solves_false_leaves_the_fields_empty():
    r = run_program(FX.HONEST, timeout=60, record_solves=False)
    assert r["solve_records"] is None and r["solve_recorder"] is None and r["objective"] == 2600.0


def test_stage_recorder_copies_the_recorder_byte_for_byte(tmp_path):
    p = stage_recorder(str(tmp_path))
    with open(p, "rb") as a, open(RECORDER_PATH, "rb") as b:
        assert a.read() == b.read()
    assert p.startswith(str(tmp_path)) and "importlib" in p and "_bootstrap" in p


@needs_py
def test_a_program_that_prints_the_whole_stack_shows_no_checkout_path():
    """The recorder's frames lie below PROG's; run_program runs a staged copy from its per-call record directory, and
    that directory is dropped from what is recorded (paths.neutral_exec_text), so neither the checkout nor a
    temporary directory shows."""
    code = ("import traceback, inspect\ntraceback.print_stack()\n"
            "print('STATUS: x')\nprint('FINAL_OBJECTIVE:', len(inspect.stack()))\n")
    r = run_program(code, timeout=30)
    assert r["exec_ok"], r["stderr_tail"]
    out = r["stdout_tail"] + r["stderr_tail"]
    assert FX.ROOT not in out and FX.RUNTIME not in out
    assert 'File "importlib_bootstrap/solve_recorder.py"' in r["stderr_tail"] and 'File "prog.py"' in r["stderr_tail"]
    assert "orgene_rec_" not in out and "orgene_exec_" not in out


# ------------------------------------------------------------------ neutral output (E12, wave2 merge)
# run_program records program output without host paths, whichever interpreter runs the program: the generation
# interpreter (the main configurations, and the AlphaOPT evaluation, which runs its programs through run_program), or
# a virtual environment under the home directory (the baseline environment of the anchors). The protocol lines are
# parsed from the raw output.


@needs_py
def test_generation_interpreter_output_names_no_temporary_directory():
    code = ("import os, sys\nprint('cwd', os.getcwd())\nprint('home', os.environ['HOME'])\n"
            "print('file', __file__ if '__file__' in dir() else sys.argv[0])\n"
            "print('STATUS: Optimal')\nprint('FINAL_OBJECTIVE: 1.5')\nraise ValueError('late: ' + os.getcwd())\n")
    r = run_program(code, timeout=30)
    assert not r["exec_ok"] and r["objective"] == 1.5 and r["status"] == "Optimal"  # parsed from the raw output
    out = r["stdout_tail"] + r["stderr_tail"]
    assert "cwd <prog-dir>" in r["stdout_tail"] and "home <prog-dir>" in r["stdout_tail"]
    assert 'File "prog.py"' in r["stderr_tail"] and "ValueError: late: <prog-dir>" in r["stderr_tail"]
    assert "orgene_exec_" not in out and "orgene_rec_" not in out and not PA.find_absolute_paths(out)
    temp_root = os.path.realpath(tempfile.gettempdir())
    assert temp_root not in out and tempfile.gettempdir() not in out


@needs_py
def test_a_traceback_through_a_venv_under_home_records_no_home_path(tmp_path, monkeypatch):
    """The baseline environment lives under the home directory; a traceback through its packages names that path."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))  # this process's home; the program's HOME is its temporary directory
    venv = home / "venvs" / "b"
    subprocess.run([FX.PY, "-m", "venv", "--without-pip", str(venv)], check=True, capture_output=True, timeout=120)
    site = next((venv / "lib").glob("python3*")) / "site-packages"
    _write(site / "boom" / "__init__.py", "import os\nraise ValueError('see ' + os.path.join("
                                          + repr(str(home)) + ", 'venvs', 'b', 'x.log'))\n")
    r = run_program("import boom\n", timeout=60, python=str(venv / "bin" / "python"))
    assert not r["exec_ok"] and "ValueError: see ~/venvs/b/x.log" in r["stderr_tail"]
    assert 'File "~/venvs/b/lib/python' in r["stderr_tail"] and "/site-packages/boom/__init__.py" in r["stderr_tail"]
    assert str(home) not in json.dumps(r) and os.path.realpath(str(home)) not in json.dumps(r)


@needs_py
def test_the_tail_is_cut_after_the_paths_are_neutral(tmp_path, monkeypatch):
    """stderr_tail keeps the last 4000 characters; cut first, a path at the cut would leave part of the home path."""
    home = str(tmp_path / "h_cut_home_component")
    monkeypatch.setenv("HOME", home)
    path = home + "/venvs/b/y.log"
    after = 4000 - len(home) // 2 - len("/venvs/b/y.log\n")  # the raw cut falls in the middle of the home path
    code = ("import sys\nsys.stderr.write('x' * 5000 + " + repr(path) + " + '\\n' + 'z' * " + str(after) + ")\n")
    r = run_program(code, timeout=30, record_solves=False)
    assert r["exec_ok"] and "~/venvs/b/y.log" in r["stderr_tail"] and len(r["stderr_tail"]) == 4000
    assert "h_cut_home_component" not in r["stderr_tail"] and "cut_home" not in r["stderr_tail"]


@needs_py
def test_solver_error_messages_are_recorded_without_home_paths(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    raising = ("class Boom(pulp.LpSolver):\n    def actualSolve(self, lp, **kw):\n"
               "        raise pulp.PulpSolverError('log at ' + " + repr(os.path.join(str(home), "venvs", "b", "x.log"))
               + ")\n")
    r = run_program(FX.HEAD + raising + "prob.solve(Boom())\n" + FX.PRINT, timeout=60)
    (s,) = r["solve_records"]
    assert s["error"]["type"] == "PulpSolverError" and s["error"]["message"] == "log at ~/venvs/b/x.log"
    assert str(home) not in json.dumps(r)


# ------------------------------------------------------------------ timeouts


@needs_py
def test_timeout_keeps_the_records_written_before_the_kill():
    r = run_program(FX.HONEST + "import time\nwhile True:\n    time.sleep(0.2)\n", timeout=5)
    assert r["timed_out"] and not r["exec_ok"]
    summ = r["solve_recorder"]
    assert summ["recorded"] and summ["n_solves"] == 1 and not summ["finished"] and not summ["in_flight"]
    assert r["solve_records"][0]["status"] == "Optimal"


@needs_py
def test_timeout_inside_a_solve_is_marked_in_flight():
    slow = ("class Slow(pulp.LpSolver):\n    def actualSolve(self, lp, **kw):\n        import time\n"
            "        time.sleep(60)\n")
    r = run_program(FX.HEAD + slow + "prob.solve(Slow())\n" + FX.PRINT, timeout=5)
    assert r["timed_out"]
    summ = r["solve_recorder"]
    assert summ["in_flight"] is True and summ["n_solves"] == 0 and r["solve_records"] == []


# ------------------------------------------------------------------ no interference


ALL_PROGRAMS = [(n, c) for n, c, _ in FX.SIX_FIXTURES + FX.NEGATIVE_CONTROLS] + FX.ERROR_PROGRAMS


@needs_py
@pytest.mark.parametrize("name,code", ALL_PROGRAMS, ids=[p[0] for p in ALL_PROGRAMS])
def test_recorder_leaves_stdout_stderr_and_returncode_unchanged(tmp_path, name, code):
    plain, recd, rec_path = FX.run_both(tmp_path, code)
    assert recd.returncode == plain.returncode
    assert recd.stdout == plain.stdout
    assert recd.stderr == plain.stderr
    _, summ = read_solve_log(str(rec_path))
    assert summ["recorded"] is True, summ


@needs_py
@pytest.mark.parametrize("name,code", ALL_PROGRAMS, ids=[p[0] for p in ALL_PROGRAMS])
def test_run_program_gives_the_same_result_with_and_without_the_recorder(name, code):
    a = run_program(code, timeout=60, record_solves=False)
    b = run_program(code, timeout=60, record_solves=True)
    for k in ("returncode", "timed_out", "stdout_tail", "status", "objective", "objective_raw", "exec_ok",
              "protocol_ok"):
        assert a[k] == b[k], k
    # stderr names the per-call temp directory of prog.py; equal once that name is masked
    assert TEMP_NAME.sub("X", a["stderr_tail"]) == TEMP_NAME.sub("X", b["stderr_tail"])


# ------------------------------------------------------------------ fallback to the plain interpreter


@needs_py
def test_syntax_error_goes_to_the_plain_interpreter_and_counts_as_recorded():
    r = run_program(FX.ERRORS["syntax_error"], timeout=30)
    summ = r["solve_recorder"]
    assert summ["fallback"] == "does_not_compile:SyntaxError" and summ["recorded"] is True
    assert summ["n_solves"] == 0 and "SyntaxError" in r["stderr_tail"] and "solve_recorder" not in r["stderr_tail"]


@needs_py
def test_without_any_solver_backend_the_program_runs_plain_and_is_not_recorded(tmp_path):
    r = run_program(FX.HONEST, timeout=60, python=FX.no_pulp_python(tmp_path))
    summ = r["solve_recorder"]
    assert summ["fallback"] == "no_solver_backend" and summ["recorded"] is False
    assert not r["exec_ok"] and "pulp" in r["stderr_tail"] and "solve_recorder" not in r["stderr_tail"]


@needs_py
def test_an_installed_but_broken_pulp_goes_to_the_plain_interpreter(tmp_path):
    _write(tmp_path / "site" / "pulp" / "__init__.py", "raise RuntimeError('broken install')\n")
    prog = tmp_path / "prog.py"
    prog.write_text(FX.HONEST, encoding="utf-8")
    rec = tmp_path / "solves.jsonl"
    env = dict(FX.exec_env(str(tmp_path)), PYTHONPATH=str(tmp_path / "site"), PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([FX.PY, RECORDER_PATH, str(prog), str(rec)], cwd=tmp_path, env=env, capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 1 and "RuntimeError: broken install" in p.stderr and "solve_recorder" not in p.stderr
    _, summ = read_solve_log(str(rec))
    assert summ["fallback"] == "pulp_import_failed:RuntimeError" and summ["recorded"] is False


def test_solve_lines_stop_at_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(SR, "MAX_SOLVE_LINES", 4)
    path = tmp_path / "r.jsonl"
    rec = SR.Recorder(str(path))
    rec.write({"type": "header", "version": 1, "hooks": {}})
    for i in range(1, 5):
        rec._emit_solve_line({"type": "solve_start", "seq": i})
        rec._emit_solve_line({"type": "solve", "seq": i, "problem_ordinal": i})
    rec.write({"type": "footer", "n_solves": 4, "n_problems": 4})
    rec.out.close()
    solves, summ = read_solve_log(str(path))
    assert summ["capped"] is True and summ["n_solves"] == 4 and summ["n_problems"] == 4 and len(solves) == 2
    assert sum(1 for line in open(path) if '"cap_reached"' in line) == 1


def test_read_solve_log_ignores_a_line_cut_by_the_kill(tmp_path):
    p = tmp_path / "solves.jsonl"
    p.write_text('{"type": "header", "version": 1, "hooks": {}}\n{"type": "solve_start", "seq": 1}\n'
                 '{"type": "solve", "seq": 1, "problem_ordinal": 1, "status": "Optimal"}\n'
                 '{"type": "solve_start", "seq": 2}\n{"type": "solve", "seq": 2, "stat')
    solves, summ = read_solve_log(str(p))
    assert len(solves) == 1 and summ["n_solves"] == 1 and summ["in_flight"] is True and not summ["finished"]
    assert read_solve_log(str(tmp_path / "missing.jsonl"))[1]["recorded"] is False


# ------------------------------------------------------------------ Pyomo / coptpy hooks


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


FAKE_PYOMO = {
    "pyomo/__init__.py": "",
    "pyomo/core/__init__.py": (
        "class Objective: pass\nclass Var: pass\nclass Constraint: pass\nminimize, maximize = 1, -1\n"
        "class VarData:\n    def __init__(self, lb):\n        self.lb, self.value = lb, None\n"
        "class ObjData:\n    def __init__(self, expr, sense):\n        self.expr, self.sense = expr, sense\n"
        "class ConData: pass\n"
        "class ConcreteModel:\n    def __init__(self):\n        self.c = {Objective: [], Var: [], Constraint: []}\n"
        "    def add(self, kind, obj):\n        self.c[kind].append(obj)\n        return obj\n"
        "    def component_data_objects(self, ctype, active=None, descend_into=True):\n"
        "        return iter(self.c.get(ctype, []))\n"
        "def value(obj, exception=True):\n    return obj.expr()\n"),
    "pyomo/opt/__init__.py": (
        "from pyomo.core import Var\n"
        "class Info:\n    termination_condition = 'optimal'\n    status = 'ok'\n"
        "class Results:\n    solver = Info()\n"
        "class OptSolver:\n    name = 'fakecbc'\n    def solve(self, *args, **kwds):\n"
        "        for v in args[0].c[Var]:\n            v.value = v.lb\n        return Results()\n"
        "def SolverFactory(name):\n    return OptSolver()\n"),
}
FAKE_PYOMO_PROG = (
    "from pyomo.core import ConcreteModel, Objective, Var, Constraint, minimize, VarData, ObjData, ConData\n"
    "from pyomo.opt import SolverFactory\n"
    "m = ConcreteModel()\nx = m.add(Var, VarData(3))\nm.add(Objective, ObjData(lambda: 2 * x.value, minimize))\n"
    "m.add(Constraint, ConData())\nres = SolverFactory('cbc').solve(m)\n"
    "print('STATUS:', res.solver.termination_condition)\nprint('FINAL_OBJECTIVE:', 2 * x.value)\n")


@needs_py
def test_pyomo_solve_called_from_the_program_is_recorded(tmp_path):
    """Plumbing check with a stand-in `pyomo` package (the real one is not in the generation interpreter)."""
    for rel_path, text in FAKE_PYOMO.items():
        _write(tmp_path / "site" / rel_path, text)
    prog = tmp_path / "prog.py"
    prog.write_text(FAKE_PYOMO_PROG, encoding="utf-8")
    rec = tmp_path / "solves.jsonl"
    env = dict(FX.exec_env(str(tmp_path)), PYTHONPATH=str(tmp_path / "site"), PYTHONDONTWRITEBYTECODE="1")
    # without -I so that PYTHONPATH reaches the stand-in package
    p = subprocess.run([FX.PY, RECORDER_PATH, str(prog), str(rec)], cwd=tmp_path, env=env, capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert p.stdout == "STATUS: optimal\nFINAL_OBJECTIVE: 6\n"
    solves, summ = read_solve_log(str(rec))
    assert summ["hooks"]["pyomo"] == "call_sites" and summ["n_solves"] == 1
    (s,) = solves
    assert s["backend"] == "pyomo" and s["entry"] == "OptSolver.solve" and s["status"] == "optimal"
    assert s["objective"] == 6.0 and s["sense"] == "minimize" and s["n_variables"] == 1 and s["n_constraints"] == 1
    assert s["solver"] == "fakecbc" and s["solver_status"] == "ok"


@pytest.mark.skipif(not os.environ.get("ORGENE_BASELINES_PY"), reason="set ORGENE_BASELINES_PY to a python with pyomo")
def test_real_pyomo_with_cbc_is_recorded():
    """Optional: the baseline environment's real Pyomo + CBC (E18 reads its objective from the record)."""
    code = ("import pyomo.environ as pe\nm = pe.ConcreteModel()\nm.a = pe.Var(within=pe.NonNegativeReals)\n"
            "m.b = pe.Var(within=pe.NonNegativeReals)\nm.o = pe.Objective(expr=40 * m.a + 30 * m.b, sense=pe.maximize)\n"
            "m.c1 = pe.Constraint(expr=2 * m.a + m.b <= 100)\nm.c2 = pe.Constraint(expr=m.a + m.b <= 80)\n"
            "r = pe.SolverFactory('cbc', executable='/opt/homebrew/bin/cbc').solve(m)\n"
            "print('STATUS:', r.solver.termination_condition)\nprint('FINAL_OBJECTIVE:', pe.value(m.o))\n")
    py = os.environ["ORGENE_BASELINES_PY"]
    r = run_program(code, timeout=120, python=py)
    assert r["exec_ok"], r["stderr_tail"]
    (s,) = r["solve_records"]
    assert s["backend"] == "pyomo" and s["status"] == "optimal" and abs(s["objective"] - 2600) < 1e-6
    assert s["sense"] == "maximize" and s["n_variables"] == 2 and s["n_constraints"] == 2
    # same output with and without the recorder, also when the solve itself raises (solver executable missing)
    broken = code.replace("executable='/opt/homebrew/bin/cbc'", "executable='/nonexistent/cbc'")
    for c in (code, broken):
        a = run_program(c, timeout=120, python=py, record_solves=False)
        b = run_program(c, timeout=120, python=py, record_solves=True)
        assert (a["returncode"], a["stdout_tail"]) == (b["returncode"], b["stdout_tail"])
        assert TEMP_NAME.sub("X", a["stderr_tail"]) == TEMP_NAME.sub("X", b["stderr_tail"])
    assert b["returncode"] != 0 and b["solve_recorder"]["recorded"]


def test_c_method_solves_are_recorded_at_program_call_sites(tmp_path):
    """The coptpy path (Model.solve is a C method) with a stand-in C method: collections.deque.clear."""
    path = tmp_path / "r.jsonl"
    rec = SR.Recorder(str(path), c_methods={("collections", "deque"): ("clear",)})
    if rec.start() is not None:
        pytest.skip("no free sys.monitoring tool id in this process")
    try:
        src = ("import collections\nd = collections.deque([1])\nd.clear()\nf = d.clear\nf()\n"
               "e = collections.deque()\ne.clear()\nlen(d)\n")
        code = compile(src, "fake_prog.py", "exec")
        rec.watch_prog(code)
        exec(code, {"__name__": "fake_prog"})
    finally:
        rec.stop()
        rec.out.close()
    solves, _ = read_solve_log(str(path))
    assert [s["entry"] for s in solves] == ["deque.clear"] * 3 and all(s["backend"] == "collections" for s in solves)
    assert [s["problem_ordinal"] for s in solves] == [1, 1, 2]


def test_copt_state_reads_status_objective_and_size(monkeypatch, tmp_path):
    fake = types.ModuleType("coptpy")

    class COPT:
        UNSTARTED, OPTIMAL, INFEASIBLE, INF_OR_UNB = 0, 1, 2, 4

    fake.COPT = COPT
    monkeypatch.setitem(sys.modules, "coptpy", fake)

    class Model:
        status, objval = 1, 12.5

        def getAttr(self, name):
            return {"Cols": 3, "Rows": 2, "ObjSense": -1, "Status": 1}[name]

    rec = SR.Recorder(str(tmp_path / "r.jsonl"))
    st = rec._copt_state(Model())
    rec.out.close()
    assert st == {"status_code": 1, "status": "OPTIMAL", "objective": 12.5, "sense": "maximize", "n_variables": 3,
                  "n_constraints": 2}


def test_recorder_uses_only_the_standard_library():
    """It runs with -I outside the package: it must not import orgene or any third-party module up front."""
    tree = ast.parse(open(RECORDER_PATH, encoding="utf-8").read())
    imports = set()
    for node in tree.body:  # module level; `import pulp` inside main() is the deliberate up-front solver import
        if isinstance(node, ast.Import):
            imports |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imports.add((node.module or ".").split(".")[0] if node.level == 0 else ".")
    assert imports == {"builtins", "importlib", "json", "math", "os", "sys", "time", "types", "weakref"}, imports
