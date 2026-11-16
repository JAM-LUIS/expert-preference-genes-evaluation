"""The interpreter that executes generated programs, and the check that it can really solve an LP.

The interpreter is fixed: ORGENE_PY if set, else /opt/homebrew/bin/python3 (PuLP 3.3.2 with the arm64 Homebrew CBC
linked into PuLP's solverdir). It is never taken from PATH: a non-interactive shell finds a system python3 without
pulp there, and every generated program would then fail to execute.

The check follows the v5 start-up check: `listSolvers(onlyAvailable=True)` only tests that a file exists, so the only
check that counts is to make PULP_CBC_CMD solve a one-variable LP and return `Optimal 1.0`.
"""
import json
import os
import subprocess
import sys

DEFAULT_PYTHON = "/opt/homebrew/bin/python3"
ENV_VAR = "ORGENE_PY"

_CHECK_CODE = r'''
import json, platform, subprocess, sys, os
out = {"python_version": sys.version.split()[0], "machine": platform.machine(), "ok": False}
try:
    import pulp
except Exception as e:
    out["error"] = "import pulp failed: %s: %s" % (type(e).__name__, e)
    print(json.dumps(out)); sys.exit(0)
out["pulp_version"] = pulp.__version__
try:
    cmd = pulp.PULP_CBC_CMD(msg=0)
    out["cbc_path"] = cmd.path
    out["cbc_realpath"] = os.path.realpath(cmd.path) if cmd.path else None
    try:
        b = subprocess.run([cmd.path, "-quit"], capture_output=True, text=True, timeout=20).stdout
        v = [l.split(":", 1)[1].strip() for l in b.splitlines() if l.strip().lower().startswith("version")]
        out["cbc_version"] = v[0] if v else None
    except Exception as e:
        out["cbc_version"] = None
    p = pulp.LpProblem("t", pulp.LpMinimize)
    x = pulp.LpVariable("x", 0)
    p += x
    p += x >= 1
    p.solve(cmd)
    out["lp_status"] = pulp.LpStatus[p.status]
    out["lp_objective"] = pulp.value(p.objective)
    out["ok"] = out["lp_status"] == "Optimal" and abs(out["lp_objective"] - 1.0) < 1e-9
    if not out["ok"]:
        out["error"] = "test LP did not return Optimal 1.0"
except Exception as e:
    out["error"] = "CBC test solve failed: %s: %s" % (type(e).__name__, e)
print(json.dumps(out))
'''

_CACHE = {}


def orgene_python():
    """The interpreter for generated programs: $ORGENE_PY, else /opt/homebrew/bin/python3. Never PATH."""
    return os.environ.get(ENV_VAR) or DEFAULT_PYTHON


def _scrub(s):
    """Record interpreter/solver paths without a home directory in them."""
    if not isinstance(s, str):
        return s
    home = os.path.expanduser("~")
    if home and home != "/" and s.startswith(home):
        return "~" + s[len(home):]
    return s


def check_env(python=None, timeout=120):
    """Run the start-up check with `python`. Returns a dict with ok=True/False; never raises."""
    python = python or orgene_python()
    res = {"interpreter": _scrub(python), "interpreter_source": ENV_VAR if os.environ.get(ENV_VAR) else "default",
           "ok": False}
    if not os.path.exists(python):
        res["error"] = "interpreter not found"
        return res
    res["interpreter_realpath"] = _scrub(os.path.realpath(python))
    try:
        p = subprocess.run([python, "-I", "-c", _CHECK_CODE], capture_output=True, text=True, timeout=timeout,
                           env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"})
    except Exception as e:  # noqa: BLE001
        res["error"] = f"could not run interpreter: {type(e).__name__}"
        return res
    line = (p.stdout or "").strip().splitlines()[-1:] or [""]
    try:
        info = json.loads(line[0])
    except ValueError:
        res["error"] = f"check produced no result (rc={p.returncode})"
        return res
    for k in ("cbc_path", "cbc_realpath"):
        info[k] = _scrub(info.get(k))
    res.update(info)
    return res


def require_env(python=None):
    """check_env, cached per interpreter; exits with a message when the interpreter cannot solve the test LP."""
    python = python or orgene_python()
    if python not in _CACHE:
        _CACHE[python] = check_env(python)
    res = _CACHE[python]
    if not res.get("ok"):
        raise SystemExit(f"[env] interpreter {res.get('interpreter')} is not usable for generated programs: "
                         f"{res.get('error')}. Set {ENV_VAR} to a python with pulp + a working CBC.")
    return res


if __name__ == "__main__":
    r = check_env(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(r, indent=2))
    sys.exit(0 if r.get("ok") else 1)
