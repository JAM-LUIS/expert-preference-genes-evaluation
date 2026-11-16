"""Solve recorder (E12): run a generated program unchanged and log every solver call it makes.

Usage (with the generation interpreter, isolated exactly like a plain run):

    python -I solve_recorder.py PROG REC

PROG runs as `__main__` the way `python -I PROG` runs it: sys.argv == [PROG], nothing prepended to sys.path (-I),
same cwd and environment, same stdout, stderr and return code. REC receives one JSON object per line, flushed as it
is written, so a program killed by the execution timeout keeps every line written before the kill:

    {"type": "header", ...}          recorder version, interpreter, which solver back ends are hooked
    {"type": "solve_start", ...}     an outermost solver call began (a start without a "solve" = killed mid-solve)
    {"type": "solve", ...}           it returned, or raised ("error" is set)
    {"type": "fallback", ...}        PROG was handed to the plain interpreter and ran unrecorded (see below)
    {"type": "footer", ...}          PROG finished (normally, by exception or by sys.exit); lists other solver
                                     modules it imported whose calls are not recorded

How calls are seen. Nothing is wrapped: a wrapper adds a stack frame, and that changes warning attribution (PuLP warns
with stacklevel=3 from inside LpProblem.solve) and tracebacks, i.e. the stderr text that repair messages quote.
The recorder uses sys.monitoring (PEP 669) instead, which adds no frames:
  - PuLP, imported up front: PY_START / PY_RETURN on LpProblem.solve / sequentialSolve / resolve, LpSolver.solve and
    every solver class's actualSolve / actualResolve; PY_UNWIND catches a solve that raises. Nested calls
    (LpProblem.solve -> actualSolve) give one record, taken when the outermost call ends.
  - Pyomo and coptpy, only when installed and never imported by the recorder: CALL events on PROG's own code
    objects. A call to a Pyomo `solve` function registers that function's code as above; a call to coptpy
    Model.solve / solveLP (a C method) is recorded at its C_RETURN / C_RAISE.
Every callback body is guarded, so the recorder never raises into PROG.

Frames below PROG. PROG's top frame has the recorder's module and main() frames under it. Uncaught tracebacks are
trimmed to PROG's frames. execute.run_program runs a copy of this file from its per-call temp directory
(execute.stage_recorder), so a program that prints the whole stack shows a temp path, never a host path, and the
directory name makes the warnings module skip these two frames (a stacklevel past PROG's top frame gives "<sys>:0",
as in a plain run).

Fallback. When PROG does not compile, or no solver back end can be hooked, the recorder writes a "fallback" line and
exec()s the plain interpreter on PROG (same flags), so output is identical by construction. A PROG that does not
compile never runs, so its (empty) record is still complete.

Per solve: status (name and code), objective value, numbers of variables and constraints, objective sense, an
ordinal of the problem object (distinct models in this run), solver, seconds. Standard library only; it must not
import anything from the orgene package (it runs with -I, outside the package).
"""
import builtins
import importlib.machinery
import importlib.util
import json
import math
import os
import sys
import time
import types
import weakref

VERSION = 1
TOOL_NAME = "orgene-solve-recorder"
TOOL_IDS = (3, 4)  # not the conventional debugger / coverage / profiler / optimizer ids
SELF_PATH = os.path.abspath(__file__)
MAX_SOLVE_LINES = 10000

PULP_PROBLEM_ENTRIES = ("solve", "sequentialSolve", "resolve")
PULP_SOLVER_ENTRIES = ("solve", "actualSolve", "actualResolve")
PYOMO_ENTRIES = ("solve",)
# C-level solve methods, keyed by (top-level module of the object's type, type name). coptpy's classes are compiled
# into a module named `coptcore` (coptpy 8.0.7: Model.__module__ == "coptcore"), so that root names COPT's Model too;
# its records carry the backend name "coptpy" (E17).
C_SOLVE_METHODS = {("coptpy", "Model"): ("solve", "solveLP"), ("coptcore", "Model"): ("solve", "solveLP")}
BACKEND_NAMES = {"coptcore": "coptpy"}
COPT_STATUS_NAMES = ("UNSTARTED", "OPTIMAL", "INFEASIBLE", "UNBOUNDED", "INF_OR_UNB", "NUMERICAL", "NODELIMIT",
                     "IMPRECISE", "TIMEOUT", "UNFINISHED", "INTERRUPTED", "ITERLIMIT", "LOCAL_OPTIMAL",
                     "LOCAL_INFEASIBLE")
# solver modules whose calls are NOT recorded; listed in the footer when PROG imported them
OTHER_SOLVER_MODULES = ("scipy.optimize", "ortools", "cvxpy", "gurobipy", "highspy", "mip", "docplex", "cplex",
                        "pyscipopt", "xpress", "mosek", "cylp", "swiglpk")
SENSES = {1: "minimize", -1: "maximize"}


def _num(x):
    """JSON-safe number: finite float, 'inf' / 'nan' as a string, None for anything else."""
    if x is None or isinstance(x, bool):
        return None
    try:
        f = float(x)
    except Exception:  # noqa: BLE001
        return None
    return f if math.isfinite(f) else repr(f)


def _root(obj):
    return (getattr(obj, "__module__", None) or "").split(".", 1)[0]


def _try(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


def _code_objects(code):
    yield code
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            yield from _code_objects(c)


class Recorder:
    """Owns the REC file and the sys.monitoring tool. Usable in-process (tests) as well as from main()."""

    def __init__(self, rec_path, c_methods=None, scrub_dirs=()):
        self.out = open(rec_path, "a", encoding="utf-8")
        # directories replaced by "<prog-dir>" in recorded messages (the temp dirs of run_program; no host paths)
        dirs = set()
        for d in scrub_dirs:
            if d:
                dirs |= {os.path.abspath(d), os.path.realpath(d)}
        self.scrub_dirs = sorted((d for d in dirs if d != os.sep), key=len, reverse=True)
        self.t0 = time.perf_counter()
        self.c_methods = dict(C_SOLVE_METHODS if c_methods is None else c_methods)
        self.c_names = frozenset(n for names in self.c_methods.values() for n in names)
        self.call_names = self.c_names | frozenset(PYOMO_ENTRIES)
        self.seq = 0
        self.n_solve_lines = 0
        self.capped = False
        self.entries = {}      # code object -> backend, for monitored Python-level solve functions
        self.stack = []        # [(frame, backend, qualname, seq, t_start)] monitored calls in progress
        self.pending_c = {}    # (code, offset) -> [(obj, backend, entry, seq, t_start)] C solve calls in progress
        self.prog_codes = []
        self.ordinals = {}     # id(problem object) -> ordinal
        self._refs = {}
        self.n_problems = 0
        self.tool = None
        self.M = getattr(sys, "monitoring", None)

    # ------------------------------------------------------------------ output
    def t(self):
        return round(time.perf_counter() - self.t0, 6)

    def message(self, exc):
        s = _try(lambda: str(exc)) or ""
        for d in self.scrub_dirs:
            s = s.replace(d, "<prog-dir>")
        return s[:300]

    def write(self, obj):
        try:
            self.out.write(json.dumps(obj, ensure_ascii=True, default=str) + "\n")
            self.out.flush()
        except Exception:  # noqa: BLE001
            pass

    def _emit_solve_line(self, obj):
        if self.n_solve_lines >= MAX_SOLVE_LINES:
            if not self.capped:
                self.capped = True
                self.write({"type": "cap_reached", "max_solve_lines": MAX_SOLVE_LINES, "seq": obj.get("seq")})
            return
        self.n_solve_lines += 1
        self.write(obj)

    # ------------------------------------------------------------------ monitoring
    def start(self):
        """Claim a sys.monitoring tool id and register callbacks. Returns None, or the reason it cannot."""
        M = self.M
        if M is None:
            return "sys.monitoring unavailable"
        for tid in TOOL_IDS:
            if M.get_tool(tid) is None:
                M.use_tool_id(tid, TOOL_NAME)
                self.tool = tid
                break
        else:
            return "no free sys.monitoring tool id"
        E = M.events
        M.register_callback(self.tool, E.PY_START, self._on_start)
        M.register_callback(self.tool, E.PY_RETURN, self._on_return)
        M.register_callback(self.tool, E.PY_UNWIND, self._on_unwind)
        M.register_callback(self.tool, E.CALL, self._on_call)
        M.register_callback(self.tool, E.C_RETURN, self._on_c_return)
        M.register_callback(self.tool, E.C_RAISE, self._on_c_raise)
        M.set_events(self.tool, E.PY_UNWIND)
        return None

    def stop(self):
        M, tool = self.M, self.tool
        if tool is None:
            return
        self.tool = None
        try:
            E = M.events
            M.set_events(tool, 0)
            for code in list(self.entries) + self.prog_codes:
                M.set_local_events(tool, code, 0)
            for ev in (E.PY_START, E.PY_RETURN, E.PY_UNWIND, E.CALL, E.C_RETURN, E.C_RAISE):
                M.register_callback(tool, ev, None)
            M.free_tool_id(tool)
        except Exception:  # noqa: BLE001
            pass
        self.stack.clear()
        self.pending_c.clear()

    def watch(self, func, backend):
        """Monitor calls of a Python-level solve function."""
        code = getattr(func, "__code__", None)
        if not isinstance(code, types.CodeType) or self.tool is None:
            return False
        if code not in self.entries:
            self.entries[code] = backend
            E = self.M.events
            self.M.set_local_events(self.tool, code, E.PY_START | E.PY_RETURN)
        return True

    def watch_pulp(self, pulp):
        n = 0
        for name in PULP_PROBLEM_ENTRIES:
            n += self.watch(pulp.LpProblem.__dict__.get(name), "pulp")
        base = getattr(pulp, "LpSolver", None)
        seen, todo = set(), [base] if isinstance(base, type) else []
        while todo:
            cls = todo.pop()
            if cls in seen:
                continue
            seen.add(cls)
            todo.extend(cls.__subclasses__())
            for name in PULP_SOLVER_ENTRIES:
                n += self.watch(cls.__dict__.get(name), "pulp")
        return n

    def watch_prog(self, code):
        """CALL events on PROG's code objects (for Pyomo / coptpy, which the recorder does not import)."""
        E = self.M.events
        for c in _code_objects(code):
            self.prog_codes.append(c)
            self.M.set_local_events(self.tool, c, E.CALL)

    # ------------------------------------------------------------------ problem identity
    def ordinal(self, obj):
        """1, 2, ... per distinct problem object alive in this run (weak references, so ids are not confused)."""
        if obj is None:
            return None
        k = id(obj)
        o = self.ordinals.get(k)
        if o is None:
            self.n_problems += 1
            o = self.ordinals[k] = self.n_problems
            d, r = self.ordinals, self._refs
            try:
                r[k] = weakref.ref(obj, lambda _ref, k=k: (d.pop(k, None), r.pop(k, None)))
            except TypeError:
                pass
        return o

    # ------------------------------------------------------------------ Python-level solve functions
    def _begin(self, backend, entry):
        """A new outermost solve: next sequence number, and a solve_start line (so a kill mid-solve shows)."""
        self.seq += 1
        self._emit_solve_line({"type": "solve_start", "seq": self.seq, "backend": backend, "entry": entry,
                               "t": self.t()})
        return self.seq

    # In a sys.monitoring callback, sys._getframe(1) is the frame of the monitored code itself.
    def _on_start(self, code, offset):
        try:
            backend = self.entries.get(code)
            if backend is None:
                return
            frame = sys._getframe(1)
            seq = self._begin(backend, code.co_qualname) if not self.stack else None
            self.stack.append((frame, backend, code.co_qualname, seq, time.perf_counter()))
        except Exception:  # noqa: BLE001
            pass

    def _pop(self, code, frame):
        if code not in self.entries or not self.stack:
            return None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] is frame:
                item = self.stack[i]
                del self.stack[i:]
                return item
        return None

    def _on_return(self, code, offset, retval):
        try:
            frame = sys._getframe(1)
            item = self._pop(code, frame)
            if item is not None and not self.stack:
                self._record(item, frame, retval, None)
        except Exception:  # noqa: BLE001
            pass

    def _on_unwind(self, code, offset, exc):
        try:
            if code not in self.entries:  # PY_UNWIND is global: return at once for every other frame
                return
            frame = sys._getframe(1)
            item = self._pop(code, frame)
            if item is not None and not self.stack:
                self._record(item, frame, None, exc)
        except Exception:  # noqa: BLE001
            pass

    def _record(self, item, frame, retval, exc):
        _, backend, entry, seq, t_start = item
        rec = {"type": "solve", "seq": seq, "backend": backend, "entry": entry,
               "seconds": round(time.perf_counter() - t_start, 6), "t": self.t()}
        if exc is not None:
            rec["error"] = {"type": type(exc).__name__, "message": self.message(exc)}
        try:
            if backend == "pulp":
                rec.update(self._pulp_state(frame, entry))
            elif backend == "pyomo":
                rec.update(self._pyomo_state(frame, retval))
        except Exception as e:  # noqa: BLE001
            rec["record_error"] = f"{type(e).__name__}: {e}"[:300]
        self._emit_solve_line(rec)

    def _pulp_state(self, frame, entry):
        pulp = sys.modules.get("pulp")
        loc = frame.f_locals
        prob = loc.get("self") if entry.startswith("LpProblem.") else loc.get("lp")
        if prob is None or not isinstance(prob, pulp.LpProblem):
            prob = next((v for v in list(loc.values()) if isinstance(v, pulp.LpProblem)), None)
        solver = loc.get("self") if not entry.startswith("LpProblem.") else getattr(prob, "solver", None)
        if solver is None:
            solver = loc.get("solver")
        st = getattr(prob, "status", None)
        sol = getattr(prob, "sol_status", None)
        return {
            "problem_ordinal": self.ordinal(prob),
            "problem_name": _try(lambda: str(prob.name)[:120]),
            "solver": type(solver).__name__ if solver is not None else None,
            "status_code": st if isinstance(st, int) else None,
            "status": pulp.LpStatus.get(st) if isinstance(st, int) else None,
            "sol_status_code": sol if isinstance(sol, int) else None,
            "sol_status": getattr(pulp, "LpSolution", {}).get(sol) if isinstance(sol, int) else None,
            "objective": _num(_try(lambda: pulp.value(prob.objective))),
            "sense": SENSES.get(getattr(prob, "sense", None)),
            "n_variables": _try(prob.numVariables),
            "n_constraints": _try(prob.numConstraints),
        }

    def _pyomo_state(self, frame, results):
        loc = frame.f_locals
        args = loc.get("args") or ()
        kwds = loc.get("kwds") or {}
        model = next((a for a in list(args) + list(kwds.values()) if hasattr(a, "component_data_objects")), None)
        opt = loc.get("self")
        info = getattr(results, "solver", None)
        tc = getattr(info, "termination_condition", None)
        ss = getattr(info, "status", None)
        out = {"problem_ordinal": self.ordinal(model),
               "solver": _try(lambda: str(getattr(opt, "name", None) or type(opt).__name__)),
               "status": str(getattr(tc, "value", tc)) if tc is not None else None,
               "solver_status": str(getattr(ss, "value", ss)) if ss is not None else None}
        core = sys.modules.get("pyomo.core") or sys.modules.get("pyomo.environ")
        if model is not None and core is not None:
            objs = _try(lambda: list(model.component_data_objects(core.Objective, active=True))) or []
            out["n_objectives"] = len(objs)
            if len(objs) == 1:
                out["objective"] = _num(_try(lambda: core.value(objs[0], exception=False)))
                out["sense"] = SENSES.get(_try(lambda: int(objs[0].sense)))
            out["n_variables"] = _try(lambda: sum(1 for _ in model.component_data_objects(core.Var, descend_into=True)))
            out["n_constraints"] = _try(lambda: sum(1 for _ in model.component_data_objects(
                core.Constraint, active=True, descend_into=True)))
        return out

    # ------------------------------------------------------------------ calls from PROG's code
    def _on_call(self, code, offset, callable_, arg0):
        try:
            name = getattr(callable_, "__name__", None)
            if name not in self.call_names:
                return self.M.DISABLE
            func = getattr(callable_, "__func__", callable_)
            if isinstance(func, types.FunctionType):
                if name in PYOMO_ENTRIES and _root(func) == "pyomo":
                    self.watch(func, "pyomo")
                return None
            if name not in self.c_names:
                return None
            obj = getattr(callable_, "__self__", None)
            if obj is None or isinstance(obj, types.ModuleType):
                obj = arg0  # unbound method descriptor called as a method: self is the first argument
            tp = type(obj)
            names = self.c_methods.get((_root(tp), tp.__name__))
            if names and name in names:
                backend, entry = BACKEND_NAMES.get(_root(tp), _root(tp)), f"{tp.__name__}.{name}"
                seq = self._begin(backend, entry)
                self.pending_c.setdefault((code, offset), []).append((obj, backend, entry, seq, time.perf_counter()))
            return None
        except Exception:  # noqa: BLE001
            return None

    def _c_done(self, code, offset, raised):
        if not self.pending_c:  # C_RETURN fires for every C call in PROG's code: return at once
            return
        lst = self.pending_c.get((code, offset))
        if not lst:
            return
        obj, backend, entry, seq, t_start = lst.pop()
        if not lst:
            del self.pending_c[(code, offset)]
        rec = {"type": "solve", "seq": seq, "backend": backend, "entry": entry,
               "seconds": round(time.perf_counter() - t_start, 6), "t": self.t(),
               "problem_ordinal": self.ordinal(obj)}
        if raised:
            # C_RAISE does not hand the exception to the callback; PROG's own output shows it
            rec["error"] = {"type": None, "message": "the solve call raised"}
        if backend == "coptpy":
            try:
                rec.update(self._copt_state(obj))
            except Exception as e:  # noqa: BLE001
                rec["record_error"] = f"{type(e).__name__}: {e}"[:300]
        self._emit_solve_line(rec)

    def _on_c_return(self, code, offset, callable_, arg0):
        try:
            self._c_done(code, offset, False)
        except Exception:  # noqa: BLE001
            pass

    def _on_c_raise(self, code, offset, callable_, arg0):
        try:
            self._c_done(code, offset, True)
        except Exception:  # noqa: BLE001
            pass

    def _copt_state(self, m):
        COPT = getattr(sys.modules.get("coptpy"), "COPT", None)
        names = {}
        for n in COPT_STATUS_NAMES:
            v = getattr(COPT, n, None)
            if isinstance(v, int):
                names.setdefault(v, n)
        st = _try(lambda: m.status)
        if st is None:
            st = _try(lambda: m.getAttr("Status"))
        obj = _try(lambda: m.objval)
        if obj is None:
            obj = _try(lambda: m.getAttr("ObjVal"))
        return {"status_code": st if isinstance(st, int) else None,
                "status": names.get(st) if isinstance(st, int) else None,
                "objective": _num(obj),
                "sense": SENSES.get(_try(lambda: int(m.getAttr("ObjSense")))),
                "n_variables": _try(lambda: int(m.getAttr("Cols"))),
                "n_constraints": _try(lambda: int(m.getAttr("Rows")))}


# ---------------------------------------------------------------------- running PROG


def strip_traceback(tb, prog):
    """Drop the recorder's leading frames (up to PROG's first frame) and any recorder frame further down."""
    frames = []
    while tb is not None:
        frames.append(tb)
        tb = tb.tb_next
    i = 0
    while i < len(frames) and frames[i].tb_frame.f_code.co_filename != prog:
        i += 1
    kept = [t for t in frames[i:] if t.tb_frame.f_code.co_filename != SELF_PATH]
    for a, b in zip(kept, kept[1:]):
        a.tb_next = b
    if kept:
        kept[-1].tb_next = None
    return kept[0] if kept else None


def _exec_plain(prog, recorder_arg):
    """Replace this process by the plain interpreter on PROG, with the same interpreter flags."""
    argv = list(getattr(sys, "orig_argv", None) or [])
    try:
        idx = argv.index(recorder_arg)
    except ValueError:
        argv, idx = [sys.executable, "-I"], 2
    new_argv = argv[:idx] + [prog]
    for s in (sys.stdout, sys.stderr):
        _try(s.flush)
    os.execv(sys.executable, new_argv)


def _other_solver_modules():
    return sorted(m for m in OTHER_SOLVER_MODULES if m in sys.modules)


def main():
    recorder_arg = sys.argv[0]
    args = sys.argv[1:]
    if len(args) != 2:
        sys.stderr.write("usage: solve_recorder.py PROG REC\n")
        raise SystemExit(2)
    prog, rec_path = args
    rec = Recorder(rec_path, scrub_dirs=(os.path.dirname(os.path.abspath(prog)), os.getcwd(),
                                         os.path.dirname(os.path.abspath(rec_path))))
    header = {"type": "header", "recorder": "orgene.solve_recorder", "version": VERSION,
              "python": sys.version.split()[0], "hooks": {}}
    reason, code = None, None
    try:
        with open(prog, "rb") as fh:
            src = fh.read()
        code = compile(src, prog, "exec", dont_inherit=True)
    except (SyntaxError, ValueError) as e:  # does not compile: plain interpreter reports it, nothing can run
        reason = "does_not_compile:" + type(e).__name__
    except Exception as e:  # noqa: BLE001
        reason = "unreadable:" + type(e).__name__
    call_sites = False
    if reason is None:
        reason = rec.start()
    if reason is None:
        try:
            import pulp  # noqa: F401  (up front, so its solve functions can be monitored)
            n = rec.watch_pulp(pulp)
            header["hooks"]["pulp"] = f"monitored:{n}"
            header["pulp_version"] = getattr(pulp, "__version__", None)
        except Exception as e:  # noqa: BLE001
            header["hooks"]["pulp"] = "unavailable:" + type(e).__name__
            if not (isinstance(e, ModuleNotFoundError) and e.name == "pulp"):
                # installed but broken: a half-imported pulp could make PROG's own import behave differently
                reason = "pulp_import_failed:" + type(e).__name__
        for mod in ("pyomo", "coptpy"):
            present = _try(lambda: importlib.util.find_spec(mod)) is not None
            header["hooks"][mod] = "call_sites" if present else "absent"
            call_sites |= present
        if reason is None and not call_sites and not header["hooks"]["pulp"].startswith("monitored"):
            reason = "no_solver_backend"
    header["monitoring_tool_id"] = rec.tool
    rec.write(header)
    if reason is not None:
        rec.write({"type": "fallback", "reason": reason})
        rec.stop()
        _try(rec.out.close)
        _exec_plain(prog, recorder_arg)
        raise SystemExit(1)  # not reached: execv does not return
    if call_sites:
        rec.watch_prog(code)

    # PROG becomes __main__ (and stays so, as in a plain run); this module object is kept alive for the callbacks
    # keys in the order a plain run's __main__ has them (ModuleType supplies __name__ .. __spec__ first)
    mod = types.ModuleType("__main__")
    mod.__dict__.update({"__package__": None, "__spec__": None,
                         "__loader__": importlib.machinery.SourceFileLoader("__main__", prog),
                         "__builtins__": builtins, "__file__": prog, "__cached__": None})
    global _RECORDER_MODULE
    _RECORDER_MODULE = sys.modules.get("__main__")
    sys.modules["__main__"] = mod
    sys.argv[:] = [prog]
    exit_kind = "normal"
    try:
        exec(code, mod.__dict__)
    except SystemExit as e:
        exit_kind = f"system_exit:{e.code!r}"[:80]
        raise
    except KeyboardInterrupt:
        exit_kind = "keyboard_interrupt"
        raise
    except BaseException as e:  # noqa: BLE001  uncaught exception: report it the way the plain interpreter does
        exit_kind = "exception:" + type(e).__name__
        tb = strip_traceback(e.__traceback__, prog)
        e.__traceback__ = tb
        sys.excepthook(type(e), e, tb)
        raise SystemExit(1) from None
    finally:
        rec.write({"type": "footer", "exit": exit_kind, "n_solves": rec.seq, "n_problems": rec.n_problems,
                   "capped": rec.capped, "other_solver_modules": _other_solver_modules(), "t": rec.t()})
        rec.stop()
        _try(rec.out.close)


_RECORDER_MODULE = None

if __name__ == "__main__":
    main()
