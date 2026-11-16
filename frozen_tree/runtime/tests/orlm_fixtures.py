"""Self-made fixtures for the ORLM anchor tests (E17): a stand-in `coptpy` package, programs and answers in ORLM's
output format, and a throw-away virtual environment that holds the stand-in.

No ORLM output, benchmark problem or COPT binary is used. The stand-in mirrors what matters in coptpy 8.0.7: the
package re-exports classes compiled into a module named `coptcore` (so `Model.__module__ == "coptcore"`), status
constants with COPT's codes, `Model.solve` that is not a Python function (the solve recorder sees it at its C_RETURN),
`model.status` / `model.objval`, and `getAttr("Cols" | "Rows" | "ObjSense")`. The outcome of a solve is scripted by
the model name: createModel("OPTIMAL:2600") solves to status OPTIMAL with objective 2600, createModel("SIZE_LIMIT")
raises like the license-free COPT does on a too large model.
"""
import os
import subprocess

PY = os.environ.get("ORGENE_PY", "/opt/homebrew/bin/python3")

FAKE_COPTCORE = '''"""Stand-in for coptpy's compiled core (tests only)."""


class COPT:
    __module__ = "coptcore"
    UNSTARTED, OPTIMAL, INFEASIBLE, UNBOUNDED, INF_OR_UNB, NUMERICAL, NODELIMIT = 0, 1, 2, 3, 4, 5, 6
    IMPRECISE, TIMEOUT, UNFINISHED, INTERRUPTED, ITERLIMIT = 7, 8, 9, 10, 11
    LOCAL_OPTIMAL, LOCAL_INFEASIBLE = 20, 21
    MINIMIZE, MAXIMIZE = 1, -1
    CONTINUOUS, BINARY, INTEGER = "C", "B", "I"


class CoptError(Exception):
    __module__ = "coptcore"


class _Expr:
    def __init__(self, *a):
        pass

    def _new(self, *a):
        return _Expr()

    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __neg__ = _new
    __le__ = __ge__ = __eq__ = _new
    __hash__ = object.__hash__


class Var(_Expr):
    __module__ = "coptcore"


class _BoundSolve:
    """Not a Python function: like coptpy's compiled method, the recorder sees the call at its C_RETURN."""
    __name__ = "solve"

    def __init__(self, model):
        self.__self__ = model

    def __call__(self):
        self.__self__._run_solve()


class _BoundSolveLP(_BoundSolve):
    __name__ = "solveLP"


class _Method:
    def __init__(self, bound):
        self.bound = bound

    def __get__(self, obj, tp=None):
        return self if obj is None else self.bound(obj)


class Model:
    __module__ = "coptcore"
    solve = _Method(_BoundSolve)
    solveLP = _Method(_BoundSolveLP)

    def __init__(self, name=""):
        self.name = name
        self.status = COPT.UNSTARTED
        self.objval = 0.0
        self._n_vars = 0
        self._n_cons = 0
        self._sense = COPT.MINIMIZE

    def addVar(self, lb=0.0, ub=None, obj=0.0, vtype="C", name=""):
        self._n_vars += 1
        return Var()

    def addConstr(self, expr, name=""):
        self._n_cons += 1
        return expr

    def setObjective(self, expr, sense=None):
        if sense is not None:
            self._sense = sense

    def setParam(self, name, value):
        pass

    def getAttr(self, name):
        return {"Cols": self._n_vars, "Rows": self._n_cons, "ObjSense": self._sense, "Status": self.status,
                "ObjVal": self.objval}[name]

    def _run_solve(self):
        head, _, value = self.name.partition(":")
        if head == "SIZE_LIMIT":
            raise CoptError("The size is limited to 2000 variables and 2000 constraints")
        self.status = getattr(COPT, head) if hasattr(COPT, head) else int(head)
        if value:
            self.objval = float(value)


class Envr:
    __module__ = "coptcore"

    def __init__(self):
        print("Cardinal Optimizer (stand-in for tests)")
        print("No license found. Starting COPT with size limitations for non-commercial use")

    def createModel(self, name=""):
        return Model(name)
'''

FAKE_COPTPY = {
    "coptpy/__init__.py": "from .coptcore import *  # noqa\nfrom .coptcore import COPT, CoptError, Envr, Model, Var  # noqa\n",
    "coptpy/coptcore.py": FAKE_COPTCORE,
    "coptpy-8.0.7.dist-info/METADATA": "Metadata-Version: 2.1\nName: coptpy\nVersion: 8.0.7\n",
    "coptpy-8.0.7.dist-info/RECORD": "",
}


def make_fake_venv(dest):
    """A venv (no pip) whose site-packages holds the stand-in coptpy. Returns its python, or None when it cannot be
    made. Only `dest` is written; the generation interpreter itself gets nothing installed."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        subprocess.run([PY, "-m", "venv", "--without-pip", dest], check=True, capture_output=True, timeout=120, env=env)
        py = os.path.join(dest, "bin", "python")
        site = subprocess.run([py, "-I", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                              check=True, capture_output=True, text=True, timeout=60, env=env).stdout.strip()
    except Exception:  # noqa: BLE001
        return None
    for rel_path, text in FAKE_COPTPY.items():
        p = os.path.join(site, rel_path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    return py


def program(outcome="OPTIMAL:2600", model_var="model", import_copt_name=True, main_function=False, extra=""):
    """A program in the style ORLM writes (coptpy, a global `model`, its own result printing)."""
    head = "import coptpy as cp\n" + ("from coptpy import COPT\n" if import_copt_name else "")
    body = (f"env = cp.Envr()\n"
            f"{model_var} = env.createModel({outcome!r})\n"
            f"x = {model_var}.addVar(lb=0, vtype=cp.COPT.INTEGER, name='x')\n"
            f"y = {model_var}.addVar(lb=0, vtype=cp.COPT.INTEGER, name='y')\n"
            f"{model_var}.addConstr(2*x + y <= 100, name='machining')\n"
            f"{model_var}.addConstr(x + y <= 80, name='assembly')\n"
            f"{model_var}.setObjective(40*x + 30*y, sense=cp.COPT.MAXIMIZE)\n"
            f"{model_var}.solve()\n"
            f"if {model_var}.status == cp.COPT.OPTIMAL:\n"
            f"    print(f'Maximum total profit: {{{model_var}.objval}}')\n"
            f"else:\n"
            f"    print('No optimal solution found.')\n")
    if main_function:
        body = "def main():\n" + "".join("    " + line + "\n" for line in body.splitlines()) + "\n\nmain()\n"
    return head + "\n" + body + extra


def answer(code, fence="```python", closing="```", tail="\n\nThe script builds the model, solves it and prints the result.\n"):
    """An answer in ORLM's layout: a mathematical model, then one fenced code block, then an explanation."""
    return (" ## Mathematical Model:\n### Decision Variables:\n- x, y: units of two products.\n"
            "### Objective Function:\n- Maximize 40x + 30y\n### Constraints:\n- 2x + y <= 100\n- x + y <= 80\n\n"
            "## Python Code Solution Using `coptpy`:\n"
            + fence + "\n" + code + (closing if closing is not None else "") + (tail if closing is not None else ""))
