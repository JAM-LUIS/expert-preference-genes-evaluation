"""Run a generated program in a subprocess and parse its reported STATUS / FINAL_OBJECTIVE lines.

By default the program runs under the solve recorder (solve_recorder.py, E12), which logs every solver call without
changing the program's stdout, stderr or return code; the result then carries `solve_records` and `solve_recorder`.

What the result records is neutral (paths.neutral_exec_text): the per-call temporary directories are dropped from
stdout_tail, stderr_tail, the recorded solver error messages and the recorder's fallback reason (a traceback names
"prog.py", as repair messages always did), and the home directory becomes "~" (a traceback through a virtual
environment under the home directory, such as the baseline environment, would otherwise record the user's name).
The protocol lines are parsed from the raw output. This holds for every interpreter the executor runs: the
generation interpreter, the baseline environment (the anchors) and the AlphaOPT evaluation.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

from .env import orgene_python
from .paths import neutral_exec_text

RECORDER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solve_recorder.py")
MAX_KEPT_SOLVE_RECORDS = 50  # the result keeps the last 50 solve records; counts cover all of them
# The recorder runs from a byte-identical copy in the per-call temp dir, never from the checkout. Its two frames sit
# below the program's, so anything that walks the whole stack (traceback.print_stack, inspect.stack) would otherwise
# print the checkout path, i.e. a host path, into stderr_tail and repair messages. The directory name holds both
# "importlib" and "_bootstrap": the warnings module skips frames whose file name contains both (CPython
# _warnings.c is_internal_filename), so a warning whose stacklevel reaches past the program's top frame is reported
# as "<sys>:0", exactly as in a plain run, instead of pointing into the recorder.
RECORDER_STAGE_DIR = "importlib_bootstrap"


def stage_recorder(dest_dir):
    """Copy solve_recorder.py into dest_dir/RECORDER_STAGE_DIR/ and return the copy's path (what run_program runs)."""
    d = os.path.join(dest_dir, RECORDER_STAGE_DIR)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, "solve_recorder.py")
    shutil.copyfile(RECORDER_PATH, dst)
    return dst

STATUS_RE = re.compile(r"^\s*STATUS\s*:\s*(.+?)\s*$", re.MULTILINE)
OBJ_RE = re.compile(r"^\s*FINAL_OBJECTIVE\s*:\s*(.+?)\s*$", re.MULTILINE)

PROTOCOL_TEXT = (
    "At the very end, print exactly two lines and nothing after them:\n"
    "STATUS: <pulp.LpStatus[prob.status]>\n"
    "FINAL_OBJECTIVE: <pulp.value(prob.objective) as a plain number, or NA if the problem was not solved to optimality>"
)


def parse_number(s):
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace("$", "")
    if t.upper() in ("NA", "NONE", "NULL", ""):
        return None
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", t)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def read_solve_log(path, keep=MAX_KEPT_SOLVE_RECORDS):
    """Parse the recorder's JSON-lines log into (solve_records, summary).

    summary["recorded"] is True when the log accounts for every solve the program could have made: the recorder
    ran the program, or the program did not compile (then it never ran). It is False when the log is missing or the
    recorder handed the program to the plain interpreter for another reason (no solver back end to hook).
    """
    header, fallback, footer, capped = None, None, None, False
    solves, starts = [], set()
    lines = []
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    for line in lines:
        try:
            o = json.loads(line)
        except ValueError:  # a line cut by the timeout kill
            continue
        t = o.get("type")
        if t == "header":
            header = o
        elif t == "fallback":
            fallback = o.get("reason")
        elif t == "solve_start":
            starts.add(o.get("seq"))
        elif t == "solve":
            solves.append(o)
            starts.discard(o.get("seq"))
        elif t == "cap_reached":
            capped = True
        elif t == "footer":
            footer = o
    ran = header is not None and fallback is None
    no_compile = bool(fallback) and str(fallback).startswith("does_not_compile")
    summary = {
        "recorded": ran or no_compile,
        "version": (header or {}).get("version"),
        "hooks": (header or {}).get("hooks"),
        "fallback": fallback,
        "n_solves": len(solves) if not capped else (footer or {}).get("n_solves", len(solves)),
        "n_problems": len({s.get("problem_ordinal") for s in solves if s.get("problem_ordinal") is not None})
        if not capped else (footer or {}).get("n_problems"),
        "in_flight": bool(starts) and ran,  # a solve had started when the program was killed
        "capped": capped,
        "finished": footer is not None,
        "exit": (footer or {}).get("exit"),
        "other_solver_modules": (footer or {}).get("other_solver_modules"),
    }
    return solves[-keep:], summary


def run_program(code: str, timeout: int = 60, python: str = None, workdir: str = None, record_solves: bool = True):
    """Execute `code` with a fresh interpreter. Returns a dict; never raises.

    The interpreter defaults to env.orgene_python() ($ORGENE_PY, else /opt/homebrew/bin/python3), never PATH.
    With record_solves (default) the program runs under solve_recorder.py; the result adds `solve_records` (last
    MAX_KEPT_SOLVE_RECORDS solver calls) and `solve_recorder` (counts, hooks, fallback). Both are None otherwise.
    """
    python = python or orgene_python()
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix="orgene_exec_")
    path = os.path.join(tmp, "prog.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    rec_dir = tempfile.mkdtemp(prefix="orgene_rec_") if record_solves else None  # outside the program's cwd
    rec_path = os.path.join(rec_dir, "solves.jsonl") if rec_dir else None
    cmd = [python, "-I", stage_recorder(rec_dir), path, rec_path] if record_solves else [python, "-I", path]
    env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp, "PYTHONIOENCODING": "utf-8", "OMP_NUM_THREADS": "2"}
    for k in ("VIRTUAL_ENV", "PYTHONPATH", "CONDA_PREFIX"):
        if k in os.environ:
            env[k] = os.environ[k]
    res = {"returncode": None, "timed_out": False, "seconds": None, "stdout_tail": "", "stderr_tail": "",
           "status": None, "objective": None, "objective_raw": None, "exec_ok": False, "protocol_ok": False,
           "solve_records": None, "solve_recorder": None}
    try:
        p = subprocess.run(cmd, cwd=workdir or tmp, env=env, capture_output=True,
                           text=True, timeout=timeout)
        res["returncode"] = p.returncode
        out, err = p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired as e:
        res["timed_out"] = True
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = (e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
    except Exception as e:  # noqa: BLE001
        out, err = "", repr(e)
    res["seconds"] = round(time.time() - t0, 3)
    res["stdout_tail"] = neutral_exec_text(out)[-4000:]  # neutral first, then cut: no half path is left at the start
    res["stderr_tail"] = neutral_exec_text(err)[-4000:]
    res["exec_ok"] = (res["returncode"] == 0) and not res["timed_out"]
    sm = STATUS_RE.findall(out)
    om = OBJ_RE.findall(out)
    if sm:
        res["status"] = sm[-1].strip()
    if om:
        res["objective_raw"] = om[-1].strip()
        res["objective"] = parse_number(om[-1])
    res["protocol_ok"] = bool(sm) and bool(om)
    if record_solves:
        res["solve_records"], res["solve_recorder"] = read_solve_log(rec_path)
        for r in res["solve_records"]:
            if isinstance(r.get("error"), dict) and isinstance(r["error"].get("message"), str):
                r["error"]["message"] = neutral_exec_text(r["error"]["message"])
        if isinstance(res["solve_recorder"].get("fallback"), str):
            res["solve_recorder"]["fallback"] = neutral_exec_text(res["solve_recorder"]["fallback"])
        shutil.rmtree(rec_dir, ignore_errors=True)
    try:
        for fn in os.listdir(tmp):
            os.remove(os.path.join(tmp, fn))
        os.rmdir(tmp)
    except Exception:  # noqa: BLE001
        pass
    return res
