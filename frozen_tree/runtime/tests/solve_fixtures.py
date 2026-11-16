"""Self-made fixture programs for the E12 tests (a two-variable product-mix LP and variants; optimum 2600).

No benchmark case is read. Imported by test_solve_recorder.py, test_misreport.py and test_recorder_check.py.
"""
import os
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
if RUNTIME not in sys.path:
    sys.path.insert(0, RUNTIME)

from orgene import env as E  # noqa: E402
from orgene.execute import RECORDER_PATH, stage_recorder  # noqa: E402,F401

PY = E.orgene_python()

HEAD = """import pulp
prob = pulp.LpProblem("mix", pulp.LpMaximize)
a = pulp.LpVariable("a", lowBound=0)
b = pulp.LpVariable("b", lowBound=0)
prob += 40 * a + 30 * b
prob += 2 * a + b <= 100, "machining"
prob += a + b <= 80, "assembly"
"""
SOLVE = "prob.solve(pulp.PULP_CBC_CMD(msg=0))\n"
PRINT = 'print("STATUS:", pulp.LpStatus[prob.status])\nprint("FINAL_OBJECTIVE:", pulp.value(prob.objective))\n'
INFEASIBLE = 'prob += a + b >= 90, "impossible"\n'

# the six fixtures of the engineering plan (E12 "how to test")
HONEST = HEAD + SOLVE + PRINT
LITERAL = HEAD + SOLVE + 'print("STATUS: Optimal")\nprint("FINAL_OBJECTIVE: 3000")\n'
INFEASIBLE_SAYS_OPTIMAL = HEAD + INFEASIBLE + SOLVE + 'print("STATUS: Optimal")\nprint("FINAL_OBJECTIVE: NA")\n'
OTHER_EXPRESSION = HEAD + SOLVE + ('print("STATUS:", pulp.LpStatus[prob.status])\n'
                                   'print("FINAL_OBJECTIVE:", pulp.value(a))\n')
NEVER_SOLVES = HEAD + 'print("STATUS: Optimal")\nprint("FINAL_OBJECTIVE: 2600")\n'
TWO_MODELS = HEAD + SOLVE + """q = pulp.LpProblem("second", pulp.LpMinimize)
c = pulp.LpVariable("c", lowBound=3)
q += c
q.solve(pulp.PULP_CBC_CMD(msg=0))
print("STATUS:", pulp.LpStatus[q.status])
print("FINAL_OBJECTIVE:", pulp.value(q.objective))
"""

NO_FLAG = {"status_misreport": False, "objective_misreport": False, "reported_without_solve": False,
           "multi_problem": False}
SIX_FIXTURES = [
    ("honest", HONEST, NO_FLAG),
    ("literal_number", LITERAL, dict(NO_FLAG, objective_misreport=True)),
    ("infeasible_says_optimal", INFEASIBLE_SAYS_OPTIMAL, dict(NO_FLAG, status_misreport=True)),
    ("other_expression", OTHER_EXPRESSION, dict(NO_FLAG, objective_misreport=True)),
    ("never_solves", NEVER_SOLVES, {"status_misreport": None, "objective_misreport": None,
                                    "reported_without_solve": True, "multi_problem": False}),
    ("two_models", TWO_MODELS, dict(NO_FLAG, multi_problem=True)),
]

# honest variants that must raise no flag (negative controls)
NEGATIVE_CONTROLS = [
    ("infeasible_reported_honestly", HEAD + INFEASIBLE + SOLVE +
     'print("STATUS:", pulp.LpStatus[prob.status])\nprint("FINAL_OBJECTIVE: NA")\n', NO_FLAG),
    ("status_upper_case_and_rounded_value", HEAD + SOLVE +
     'print("STATUS: OPTIMAL")\nprint("FINAL_OBJECTIVE:", round(pulp.value(prob.objective), 2))\n', NO_FLAG),
    ("solution_status_name", HEAD + SOLVE +
     'print("STATUS:", pulp.LpSolution[prob.sol_status])\nprint("FINAL_OBJECTIVE:", pulp.value(prob.objective))\n',
     NO_FLAG),
    ("same_model_solved_twice", HEAD + SOLVE + SOLVE + PRINT, NO_FLAG),
    ("no_solve_says_not_solved", HEAD + 'print("STATUS:", pulp.LpStatus[prob.status])\nprint("FINAL_OBJECTIVE: NA")\n',
     {"status_misreport": None, "objective_misreport": None, "reported_without_solve": False, "multi_problem": False}),
]

# programs for the output-identity checks (errors, exits, warnings, module globals, pickling)
ERROR_PROGRAMS = [
    ("chained_exception", "def f():\n    raise KeyError('x')\ntry:\n    f()\nexcept KeyError as e:\n"
                          "    raise ValueError('wrapped') from e\n"),
    ("error_inside_solver", "import pulp\np = pulp.LpProblem('x', pulp.LpMinimize)\nx = pulp.LpVariable('x', 0)\n"
                            "p += x\np += x >= 1\np.solve(pulp.COIN_CMD(path='/nonexistent/cbc', msg=0))\n"),
    ("syntax_error", "import pulp\nx = = 1\n"),
    ("indentation_error", "if True:\nprint(1)\n"),
    ("exit_code", "print('partial')\nimport sys\nsys.exit(3)\n"),
    ("exit_message", "import sys\nsys.exit('bye')\n"),
    ("own_warning", "import warnings\nwarnings.warn('careful', UserWarning)\nwarnings.warn('old', DeprecationWarning)\n"
                    "print('done')\n"),
    ("default_solver_path", HEAD + "pulp.LpSolverDefault.msg = False\nprob.solve()\n" + PRINT),
    ("module_state", "import os, sys, pickle\ndef f():\n    return 1\n"
                     "print(__name__, sys.argv == [__file__], sorted(os.listdir('.')))\n"
                     "print(list(globals()), len(sys.path), sys.path[0])\n"
                     "print(len(pickle.dumps(f)) > 0, sys.modules['__main__'].f is f)\n"),
    # stacklevel past the program's top frame: a plain run reports "<sys>:0"; so must the recorder
    ("warning_past_the_program", "import warnings\nwarnings.warn('top', stacklevel=2)\ndef g():\n"
                                 "    warnings.warn('deep', UserWarning, stacklevel=4)\ng()\nprint('done')\n"),
    ("error_after_output", HONEST + "raise RuntimeError('after printing')\n"),
]
ERRORS = dict(ERROR_PROGRAMS)


def exec_env(home):
    """The environment run_program gives a program."""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": home, "PYTHONIOENCODING": "utf-8", "OMP_NUM_THREADS": "2"}
    for k in ("VIRTUAL_ENV", "PYTHONPATH", "CONDA_PREFIX"):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


def run_both(tmp_path, code, timeout=60):
    """Run PROG plainly and under the recorder: same file, same cwd, same environment, and the recorder staged in
    the record directory as run_program stages it."""
    prog_dir = tmp_path / "prog"
    rec_dir = tmp_path / "rec"
    prog_dir.mkdir(exist_ok=True)
    rec_dir.mkdir(exist_ok=True)
    prog = prog_dir / "prog.py"
    prog.write_text(code, encoding="utf-8")
    env = exec_env(str(prog_dir))
    plain = subprocess.run([PY, "-I", str(prog)], cwd=prog_dir, env=env, capture_output=True, text=True,
                           timeout=timeout)
    rec_path = rec_dir / "solves.jsonl"
    recd = subprocess.run([PY, "-I", stage_recorder(str(rec_dir)), str(prog), str(rec_path)], cwd=prog_dir, env=env,
                          capture_output=True, text=True, timeout=timeout)
    return plain, recd, rec_path


def no_pulp_python(tmp_path):
    """An interpreter that exists and runs but cannot import pulp (site-packages disabled)."""
    w = tmp_path / "python-no-pulp"
    w.write_text(f"#!/bin/sh\nexec '{PY}' -S \"$@\"\n")
    w.chmod(w.stat().st_mode | stat.S_IEXEC)
    return str(w)
