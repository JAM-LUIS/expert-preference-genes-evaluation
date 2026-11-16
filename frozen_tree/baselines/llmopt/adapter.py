"""LLMOPT anchor adapter (E18): two-step inference (Q2F -> F2C), program execution with CBC, objective extraction.

Method: LLMOPT (ICLR 2025; code github.com/antgroup/LLMOPT @1492dd3, no license file; weights HF
ant-opt/LLMOPT-Qwen2.5-14B @ed0ae2d, MIT per the model card), run as a Q8_0 GGUF on llama-server's native
/completion with the prompt rendered from the GGUF's chat template (templates.render_prompt; run.py).

  step 1  Q2F: one user message, the upstream Q2F(question) prompt -> the "five-element" model in a fenced block
  step 2  F2C: one user message, the upstream F2C(five elements) prompt -> a Pyomo program in a ```python block
  greedy decoding, one sample, no self-correction (the published self-correction loop is not released; stage-0 report
  2.4). Each step is exactly one user message, as in the upstream inference_q2f2c.py.

Extraction (extract_five_elements / extract_code) reproduces the behaviour of the upstream inference script
(inference/inference_q2f2c.py lines 38-47 and 70-71 at 1492dd3): the same unescaping of the raw response, then the
first ```text / ```plaintext / ``` block for the five elements, the first ```python block for the program. This is a
reimplementation of that behaviour, not a copy of the file.

Execution. The program runs unchanged except for a fixed prelude (SOLVER_PRELUDE, inserted after any
`from __future__` imports) that maps every Pyomo SolverFactory name to "cbc": the Homebrew CBC 2.10.13 of every other
configuration, instead of the glpk the model usually asks for. It runs under the solve recorder (E12) with the
baseline environment's interpreter (Pyomo), 60 s as for every configuration.

Objective (derive_result). The program must finish (return code 0, no timeout); a program that does not gets neither
a status nor an objective, whatever the solver found (the record's own status stays in record_status). This holds for
the status as much as for the objective: a non-numeric reference ("infeasible") is judged by the status, and the
typical crash of a Pyomo program -- reading variable values after an infeasible solve -- must not be credited. Then:
  1. the last solve the recorder saw decides: its termination condition gives the status (STATUS_MAP); when the status
     is Optimal, the recorded Pyomo objective value is the objective (objective_source "solve_record"); a solve that is
     not optimal gives no objective;
  2. only when there is no recorded solve with an objective value (no solve recorded, the record is incomplete, or an
     optimal solve without a readable objective) the printed output is parsed (parse_printed_objective, the backup
     parser; objective_source "stdout_regex").
The backup parser is a draft until it has been developed on dev outputs; PARSER_FROZEN must be set True (and the
module frozen) before any test run, which run.py enforces.
"""
import ast
import math
import re

ADAPTER_VERSION = "llmopt-adapter.v1"
CONDITION = "LLMOPT"
PARSER_VERSION = "llmopt-printed-objective.draft-1"
PARSER_FROZEN = False  # set True only after the dev rehearsal; test runs are refused while False

# ---------------------------------------------------------------------------------------------- messages


def q2f_messages(question, prompts):
    """Step 1 request: exactly one user message with the upstream Q2F prompt."""
    return [{"role": "user", "content": prompts.Q2F(question)}]


def f2c_messages(five_elements, prompts):
    """Step 2 request: exactly one user message with the upstream F2C prompt."""
    return [{"role": "user", "content": prompts.F2C(five_elements)}]


# ---------------------------------------------------------------------------------------------- extraction

BS = "\\"
# the raw response is unescaped in this order: backslash-backslash-n, &#39;, &lt;, &gt;, backslash-backslash-quote
_UNESCAPE = ((BS * 2 + "n", "\n"), ("&#39;", "'"), ("&lt;", "<"), ("&gt;", ">"), (BS * 2 + '"', '"'))
# print(" / print(f" followed by backslash-backslash-newline is joined back to one line
_PRINT_JOIN = (('print("' + BS * 2 + "\n", 'print("'), ('print(f"' + BS * 2 + "\n", 'print(f"'))


def unescape_response(text):
    for a, b in _UNESCAPE:
        text = text.replace(a, b)
    return text


def extract_five_elements(response):
    """The five-element text of a Q2F response, or None when the response has no fenced block."""
    c = unescape_response(response or "")
    for fence in ("```text", "```plaintext"):
        if fence in c:
            return c.split(fence)[1].split("```")[0]
    if "```" in c:
        return c.split("```")[1].split("```")[0]
    return None


def extract_code(response):
    """The program of an F2C response (first ```python block), or None."""
    c = unescape_response(response or "")
    if "```python" not in c:
        return None
    code = c.split("```python")[1].split("```")[0]
    for a, b in _PRINT_JOIN:
        code = code.replace(a, b)
    return code


# ---------------------------------------------------------------------------------------------- solver redirect

REDIRECT_TARGET = "cbc"
SOLVER_PRELUDE = (
    "def _orgene_llmopt_solver_redirect():  # evaluation harness (E18): every Pyomo solver name -> cbc\n"
    "    import pyomo.environ  # noqa: F401  (registers the solver plug-ins)\n"
    "    from pyomo.opt.base.solvers import SolverFactoryClass\n"
    "    original, depth = SolverFactoryClass.__call__, [0]\n"
    "    def __call__(self, _name=None, **kwds):\n"
    "        if _name is None or depth[0]:  # Pyomo's own nested calls (cbc -> _cbc_shell) pass through\n"
    "            return original(self, _name, **kwds)\n"
    "        for k in ('executable', 'solver_io', 'solver'):\n"
    "            kwds.pop(k, None)\n"
    "        depth[0] += 1\n"
    "        try:\n"
    "            return original(self, 'cbc', **kwds)\n"
    "        finally:\n"
    "            depth[0] -= 1\n"
    "    SolverFactoryClass.__call__ = __call__\n"
    "_orgene_llmopt_solver_redirect()\n"
    "del _orgene_llmopt_solver_redirect\n"
)
PRELUDE_LINES = SOLVER_PRELUDE.count("\n")
_SOLVER_NAME_RE = re.compile(r"SolverFactory\s*\(\s*(?:_name\s*=\s*)?(?:(['\"])([^'\"\n]*)\1|([^)\s]))")


def with_solver_redirect(code):
    """(program to run, line after which the prelude was inserted). The prelude goes first, or right after the
    leading `from __future__` imports (which must stay the first statements)."""
    after = 0
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        tree = None
    if tree is not None:
        for i, node in enumerate(tree.body):
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                after = node.end_lineno
            elif not (i == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                      and isinstance(node.value.value, str)):
                break
    if after == 0:
        return SOLVER_PRELUDE + code, 0
    lines = code.splitlines(keepends=True)
    head = "".join(lines[:after])
    if not head.endswith("\n"):
        head += "\n"
    return head + SOLVER_PRELUDE + "".join(lines[after:]), after


def requested_solvers(code):
    """Solver names the program passes to SolverFactory, in order ("<expr>" for a name that is not a literal)."""
    out = []
    for m in _SOLVER_NAME_RE.finditer(code or ""):
        out.append(m.group(2) if m.group(1) else "<expr>")
    return out


# ---------------------------------------------------------------------------------------------- objective

# Pyomo termination conditions -> the status words the scorer compares with non-numeric references
STATUS_MAP = {
    "optimal": "Optimal", "globallyOptimal": "Optimal", "locallyOptimal": "Optimal",
    "infeasible": "Infeasible", "unbounded": "Unbounded",
    "infeasibleOrUnbounded": "Undefined",  # not credited against an "infeasible" or "unbounded" reference
}
_PULP_STATUSES = ("Optimal", "Infeasible", "Unbounded", "Not Solved", "Undefined")
_COPT_MAP = {"OPTIMAL": "Optimal", "INFEASIBLE": "Infeasible", "UNBOUNDED": "Unbounded", "INF_OR_UNB": "Undefined"}


def map_status(rec):
    """Status word of one solve record: Optimal, Infeasible, Unbounded, Undefined or Not Solved."""
    s = rec.get("status")
    if rec.get("backend") == "pyomo":
        return STATUS_MAP.get(s, "Not Solved")
    if rec.get("backend") == "pulp":
        return s if s in _PULP_STATUSES else "Not Solved"
    if rec.get("backend") == "coptpy":
        return _COPT_MAP.get(s, "Not Solved")
    return "Not Solved"


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# backup parser (draft): an objective-like phrase, a separator (":", "=" or "is"), then a number
_NUM = r"([-+]?\s?\$?\s?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
_SEP = r"[^:=\n]{0,40}?(?:[:=]|\bis\b)\s*"
_NOUNS = (r"(?:value|objective|cost|costs|profit|profits|revenue|revenues|income|earnings|expense|expenses|"
          r"spending|penalty|penalties|distance|time|emission|emissions|waste|loss|losses|return|returns|payoff|"
          r"utility|benefit|benefits|price|amount|output|production|weight|risk)")
PRINTED_RULES = (  # highest priority first; within a rule the last matching line wins
    ("objective", re.compile(r"\bobjective\b" + _SEP + _NUM, re.IGNORECASE)),
    ("optimal_phrase", re.compile(r"\b(?:optimal|minimum|maximum|minimal|maximal|minimized|maximized|minimised|"
                                  r"maximised|min|max|lowest|highest|best)\b\s+(?:[\w-]+\s+){0,3}?" + _NOUNS + r"\b"
                                  + _SEP + _NUM, re.IGNORECASE)),
    ("total_phrase", re.compile(r"\btotal\b\s+(?:[\w-]+\s+){0,3}?" + _NOUNS + r"\b" + _SEP + _NUM, re.IGNORECASE)),
)


def _to_float(s):
    t = s.replace(",", "").replace("$", "").replace(" ", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parse_printed_objective(text):
    """(value, rule) from printed output, or (None, None). Draft rules; frozen after the dev rehearsal."""
    lines = (text or "").splitlines()
    for rule, rx in PRINTED_RULES:
        found = None
        for line in lines:
            m = rx.search(line)
            if m:
                v = _to_float(m.group(1))
                if v is not None:
                    found = v
        if found is not None:
            return found, rule
    return None, None


def derive_result(ex, rel_tol=1e-4, abs_tol=1e-4):
    """Status and objective of one execution (run_program's result) by the rules in the module docstring."""
    ex = ex or {}
    summ = ex.get("solve_recorder") or {}
    recs = ex.get("solve_records") or []
    printed, printed_rule = parse_printed_objective(ex.get("stdout_tail") or "")
    out = {"status": None, "objective": None, "objective_source": None, "failure": None,
           "record_complete": bool(summ.get("recorded")), "n_solves": summ.get("n_solves"),
           "n_problems": summ.get("n_problems"), "record_status": None, "record_objective": None,
           "record_solver": None, "record_error": None, "printed_objective": printed, "printed_rule": printed_rule,
           "printed_matches_record": None, "parser_version": PARSER_VERSION}
    last = recs[-1] if (out["record_complete"] and recs and not summ.get("capped")) else None
    if last is not None:
        out["record_status"], out["record_objective"] = last.get("status"), last.get("objective")
        out["record_solver"] = last.get("solver")
        out["record_error"] = (last.get("error") or {}).get("type") if last.get("error") else None
        if _finite(printed) and _finite(last.get("objective")):
            s = last["objective"]
            out["printed_matches_record"] = abs(printed - s) <= max(abs_tol, rel_tol * abs(s))
    if ex.get("timed_out"):
        out["failure"] = "timeout"
    elif not ex.get("exec_ok"):
        out["failure"] = "exec_failed"
    if out["failure"]:
        return out  # the program did not finish: no status, no objective (record_status keeps what the solver said)
    if last is not None:
        out["status"] = "Not Solved" if last.get("error") else map_status(last)
    if last is not None and not last.get("error"):
        if out["status"] != "Optimal":
            out["objective_source"] = "solve_record"
            return out
        if _finite(last.get("objective")):
            out["objective"], out["objective_source"] = float(last["objective"]), "solve_record"
            return out
    elif last is not None:  # the last solve raised, but the program finished
        out["objective_source"] = "solve_record"
        return out
    # no recorded solve with an objective value: the printed output (backup parser)
    if printed is not None:
        out["objective"], out["objective_source"] = printed, "stdout_regex"
    else:
        out["failure"] = "no_objective"
    return out


def exec_for_scoring(ex, derived):
    """The `exec` block the R1 scorer reads: run_program's result with status / objective from derive_result.
    protocol_ok stays False (LLMOPT prints no STATUS / FINAL_OBJECTIVE lines)."""
    e = dict(ex or {})
    e.update({"status": derived["status"], "objective": derived["objective"], "objective_raw": None,
              "objective_source": derived["objective_source"], "protocol_ok": False})
    return e


NO_EXEC = {"returncode": None, "timed_out": False, "seconds": None, "stdout_tail": "", "stderr_tail": "",
           "status": None, "objective": None, "objective_raw": None, "exec_ok": False, "protocol_ok": False,
           "solve_records": None, "solve_recorder": None, "objective_source": None}
