"""Author-approved packet_it0 predicates (2026-09-30); integration of gene proposals (new genes G1-G4 and modified genes M1-M7).

Interface (same as code/orgene/genes.py):
    fn(ctx, params) -> (ok: bool, detail: str)
    ctx = {"case": {"case_id", "text"}, "spec": dict | None, "code": str | None, "exec": dict | None}

Rules followed by every predicate here:
  * deterministic; reads only the program text (AST), the spec, the stored execution result and the problem text;
    never executes the program, never calls a model, never touches files or the network;
  * never raises: every predicate body runs inside _safe(), which turns an internal error into ok=True with a
    detail that starts with "analysis skipped", so a bug in a draft predicate can never trigger a repair;
  * when there is nothing to check (no parseable program, no decision variables, no spec, wrong phase data) the
    predicate returns ok=True; where the packet's rerun tool has a matching not-applicable string it is reused;
  * detail strings go verbatim into C3/C3L repair messages: they name program line numbers and the program's own
    variable names at most, never problem data, entity names or reference values.

Load with:
    python3 code/rerun_predicates.py --genes proposals/genes_proposed.jsonl \
        --extra-predicates proposals/predicates_draft.py --lexicon proposals/lexicon.draft.json \
        --examples proposals/activation_examples.draft.json
"""
import ast
import math
import re

# Base predicates are supplied by genes.py after its v1 registry is initialized.
# This avoids a circular import and keeps all approved predicate bodies unchanged.
_G = None


def bind_base(module):
    global _G
    _G = module
    return PREDICATES


_DASHES = {0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2212: "-"}


def _norm_text(text):
    """Same normalisation as features.normalize_text (unicode dashes -> '-', whitespace runs -> one space), so the
    text cues of a predicate and the lexicon feature of its activation rule see the same string."""
    return " ".join(str(text or "").translate(_DASHES).split())


NA_PARSE = "code does not parse; checked by the syntax/execution genes"
NA_NOVARS = "no decision variables detected"
NA_NOSPEC = "no spec to check (condition without a spec)"


def _safe(fn):
    def wrapped(ctx, params):
        try:
            return fn(ctx or {}, params or {})
        except Exception as e:  # noqa: BLE001
            return True, f"analysis skipped (internal error: {type(e).__name__})"
    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


# ----------------------------------------------------------------------------- AST helpers

def _parse(code):
    try:
        return ast.parse(code or "")
    except (SyntaxError, ValueError):
        return None


def _dotted(f):
    parts = []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    return ".".join(reversed(parts))


def _tail(call):
    return _dotted(call.func).split(".")[-1] if isinstance(call, ast.Call) else ""


def _num(node):
    """Numeric literal value (int/float, unary minus allowed) or None."""
    try:
        v = ast.literal_eval(node)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _cat_kind(node):
    """'bin' | 'int' | 'cont' | None (unknown) for a cat= argument."""
    if node is None:
        return "cont"
    s = ast.unparse(node) if hasattr(ast, "unparse") else ""
    if "Binary" in s:
        return "bin"
    if "Integer" in s:
        return "int"
    if "Continuous" in s:
        return "cont"
    return None


def _decl_from_call(call):
    """Bounds and category of LpVariable(...) / LpVariable.dicts(...) / LpVariable.matrix(...)."""
    t = _tail(call)
    is_container = t in ("dicts", "matrix")
    off = 1 if is_container else 0
    kw = {k.arg: k.value for k in call.keywords if k.arg}
    pos = list(call.args)
    lb = kw.get("lowBound", pos[1 + off] if len(pos) > 1 + off else None)
    ub = kw.get("upBound", pos[2 + off] if len(pos) > 2 + off else None)
    cat = kw.get("cat", pos[3 + off] if len(pos) > 3 + off else None)
    kind = _cat_kind(cat)
    lbv, ubv = (_num(lb) if lb is not None else None), (_num(ub) if ub is not None else None)
    if kind == "int" and ubv == 1 and (lbv in (0.0, None)):
        kind = "binlike"
    if kind == "bin":
        lbv, ubv = 0.0, 1.0
    return {"container": is_container, "kind": kind, "lb": lbv, "ub": ubv,
            "lb_given": lb is not None, "line": getattr(call, "lineno", None)}


def _is_var_call(n):
    return isinstance(n, ast.Call) and _tail(n) in ("LpVariable", "dicts", "matrix")


def _var_decls(tree):
    """name -> declaration info for names bound directly to LpVariable calls or to containers of them."""
    out = {}
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Assign) and n.targets):
            continue
        tgt, val = n.targets[0], n.value
        name, container = None, False
        if isinstance(tgt, ast.Name):
            name = tgt.id
        elif isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name):
            name, container = tgt.value.id, True
        if name is None:
            continue
        call = None
        if _is_var_call(val):
            call = val
        elif isinstance(val, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
            inner = val.value if isinstance(val, ast.DictComp) else val.elt
            if _is_var_call(inner):
                call, container = inner, True
        elif isinstance(val, (ast.List, ast.Tuple)) and val.elts and all(_is_var_call(e) for e in val.elts):
            call, container = val.elts[0], True
        elif isinstance(val, ast.Dict) and val.values and all(_is_var_call(e) for e in val.values):
            call, container = val.values[0], True
        if call is None:
            continue
        info = _decl_from_call(call)
        info["container"] = info["container"] or container
        prev = out.get(name)
        if prev is None:
            out[name] = info
        elif prev != info:  # re-declared with different bounds/category: keep the weaker (unknown) facts
            out[name] = dict(prev, kind=prev["kind"] if prev["kind"] == info["kind"] else None,
                             lb=prev["lb"] if prev["lb"] == info["lb"] else None,
                             ub=prev["ub"] if prev["ub"] == info["ub"] else None)
    return out


def _numeric_constants(tree):
    """Module-level names assigned exactly one numeric literal (e.g. M = 1000)."""
    seen = {}
    for n in tree.body if tree is not None else []:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            v = _num(n.value)
            name = n.targets[0].id
            seen.setdefault(name, []).append(v)
    return {k: v[0] for k, v in seen.items() if len(v) == 1 and v[0] is not None}


def _constraint_nodes(tree):
    """(line, Compare) for every `<obj> += <cmp>` / `<obj> += (<cmp>, name)` / `<obj>.addConstraint(<cmp>, ...)`."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Add):
            v = n.value
            if isinstance(v, ast.Tuple) and v.elts:
                v = v.elts[0]
            if isinstance(v, ast.Compare):
                out.append((n.lineno, v))
        elif isinstance(n, ast.Call) and _tail(n) == "addConstraint" and n.args and isinstance(n.args[0], ast.Compare):
            out.append((n.lineno, n.args[0]))
    return sorted(out, key=lambda x: x[0])


# ----------------------------------------------------------------------------- linear forms (sign analysis only)

class _Lin:
    """Affine form: {term_key: coefficient} + constant. Term keys are variable names, container reads (unparsed),
    or 'SUM[...]' for a generator sum whose element has a known sign pattern."""

    def __init__(self, terms=None, const=0.0):
        self.terms = dict(terms or {})
        self.const = const

    def add(self, other, s=1.0):
        t = dict(self.terms)
        for k, v in other.terms.items():
            t[k] = t.get(k, 0.0) + s * v
        return _Lin(t, self.const + s * other.const)

    def scale(self, c):
        return _Lin({k: c * v for k, v in self.terms.items()}, c * self.const)


def _lin(node, decls, consts, depth=0):
    if depth > 60:
        return None
    if isinstance(node, ast.Constant):
        v = _num(node)
        return None if v is None else _Lin({}, v)
    if isinstance(node, ast.Name):
        d = decls.get(node.id)
        if d is not None and not d["container"]:
            return _Lin({node.id: 1.0}, 0.0)
        if node.id in consts:
            return _Lin({}, consts[node.id])
        return None
    if isinstance(node, ast.Subscript):
        base = node.value
        while isinstance(base, ast.Subscript):
            base = base.value
        if isinstance(base, ast.Name) and base.id in decls and decls[base.id]["container"]:
            return _Lin({ast.unparse(node): 1.0}, 0.0)
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        r = _lin(node.operand, decls, consts, depth + 1)
        if r is None:
            return None
        return r.scale(-1.0) if isinstance(node.op, ast.USub) else r
    if isinstance(node, ast.BinOp):
        a = _lin(node.left, decls, consts, depth + 1)
        b = _lin(node.right, decls, consts, depth + 1)
        if a is None or b is None:
            return None
        if isinstance(node.op, ast.Add):
            return a.add(b, 1.0)
        if isinstance(node.op, ast.Sub):
            return a.add(b, -1.0)
        if isinstance(node.op, ast.Mult):
            if not a.terms:
                return b.scale(a.const)
            if not b.terms:
                return a.scale(b.const)
            return None
        if isinstance(node.op, ast.Div):
            if b.terms or b.const == 0:
                return None
            return a.scale(1.0 / b.const)
        return None
    if isinstance(node, ast.Call) and _tail(node) in ("lpSum", "sum") and len(node.args) == 1:
        arg = node.args[0]
        if isinstance(arg, (ast.List, ast.Tuple)):
            acc = _Lin()
            for e in arg.elts:
                r = _lin(e, decls, consts, depth + 1)
                if r is None:
                    return None
                acc = acc.add(r)
            return acc
        if isinstance(arg, (ast.GeneratorExp, ast.ListComp)):
            r = _lin(arg.elt, decls, consts, depth + 1)
            if r is None or r.const != 0.0 or not r.terms:
                return None
            if not all(_term_nonneg(k, decls) for k in r.terms):
                return None  # the sum's sign is only known when every summed term is non-negative
            signs = {math.copysign(1.0, v) for v in r.terms.values() if v != 0}
            if len(signs) != 1:
                return None
            return _Lin({"SUM[" + ast.unparse(arg.elt) + "]": signs.pop()}, 0.0)
        return None
    return None


def _term_nonneg(key, decls):
    if key.startswith("SUM["):
        return True  # created by _lin only when every summed term is a non-negative variable
    base = re.match(r"[A-Za-z_]\w*", key)
    d = decls.get(base.group(0)) if base else None
    return d is not None and _nonneg(d)


def _nonneg(d):
    return d["kind"] in ("bin",) or (d["lb"] is not None and d["lb"] >= 0)


# ============================================================================= G1
@_safe
def p_optimum_not_trivial_zero(ctx, params):
    """G1 (post_exec). An Optimal status with objective value 0 means the model is satisfied by doing nothing or by
    a trivial assignment; benchmark-type problems almost never have a zero optimum, so this is treated as a
    formulation defect to re-check (a missing activity-forcing requirement, a meaningless variable such as a
    self-assignment, or an objective that does not measure what is asked)."""
    ex = ctx.get("exec")
    if not isinstance(ex, dict):
        return True, "program not executed; checked by the execution genes"
    st = str(ex.get("status") or "").strip().lower()
    if st != "optimal":
        return True, "status is not Optimal; checked by the status gene"
    obj = ex.get("objective")
    if isinstance(obj, bool) or not isinstance(obj, (int, float)) or obj != obj:
        return True, "no numeric objective reported"
    tol = float(params.get("abs_tol", 1e-6))
    if abs(obj) <= tol:
        return False, ("the solver reports an optimal objective of 0; check that no requirement from the text is "
                       "missing and that the objective measures the quantity the question asks for")
    return True, "optimal objective is non-zero"


# ============================================================================= G2
_DECISION_VERBS = (
    r"(?:produc(?:e|es|ed|ing)|manufactur(?:e|es|ed|ing)|mak(?:e|es|ing)|made|order(?:s|ed|ing)?|us(?:e|es|ed|ing)|"
    r"open(?:s|ed|ing)?|buil(?:d|ds|t|ding)|select(?:s|ed|ing)?|choos(?:e|es|ing)|chose|chosen|tak(?:e|es|en|ing)|"
    r"took|buy(?:s|ing)?|bought|purchas(?:e|es|ed|ing)|ship(?:s|ped|ping)?|send(?:s|ing)?|sent|assign(?:s|ed|ing)?|"
    r"invest(?:s|ed|ing)?|hir(?:e|es|ed|ing)|rent(?:s|ed|ing)?|leas(?:e|es|ed|ing)|run(?:s|ning)?|ran|"
    r"operat(?:e|es|ed|ing)|process(?:es|ed|ing)?|install(?:s|ed|ing)?|locat(?:e|es|ed|ing)|visit(?:s|ed|ing)?|"
    r"grow(?:s|n|ing)?|grew|plant(?:s|ed|ing)?|schedul(?:e|es|ed|ing)|includ(?:e|es|ed|ing)|accept(?:s|ed|ing)?|"
    r"launch(?:es|ed|ing)?|fund(?:s|ed|ing)?|decid(?:e|es|ed|ing) to|sign(?:s|ed|ing)?|contract(?:s|ed|ing)?)")
_COND_RE = re.compile(r"\b(?:if|only if|unless|whenever|provided that)\b[^.;:?!]{0,60}?\b" + _DECISION_VERBS + r"\b",
                      re.I)
_COND2_RE = re.compile(r"\b(?:if|whenever)\b[^.;:?!]{0,100}?,[^.;:?!]{0,60}?\b(?:must also|will also|should also|must not|"
                       r"will not|cannot|can not|can't|may not|should not|is not allowed to|are not allowed to)\b",
                       re.I)  # "if A is done, B must also / will not be done": an implication stated on the consequent
_EXCL_RE = re.compile(r"\b(?:not both|mutually exclusive|(?:cannot|can ?not|can't|must not|may not|should not) both|"
                      r"only one of (?:the|these|those|them)|at most one of (?:the|these|those|them))\b", re.I)
_COUNT_RE = re.compile(r"\b(?:at most|at least|exactly|no more than|not more than|more than|no fewer than|fewer than|"
                       r"up to|only) (?:one|two|three|four|five|six|seven|eight|nine|ten|\d+) "
                       r"(?:(?:different|distinct) \w+|types?|kinds?|of (?:the|these|those|them))\b", re.I)
_CUE_NAMES = {"conditional": "a conditional requirement between decisions (if one is taken, another must or must "
                             "not be)",
              "exclusive": "an exclusive choice (not both / only one of them)",
              "count": "a limit on how many different options may be used"}


def _sentences(text):
    t = _norm_text(text)
    return [s for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]


def logic_cues(text):
    """Kinds of logical conditions stated in declarative (non-question) sentences of the problem text."""
    kinds = []
    for s in _sentences(text):
        if s.rstrip().endswith("?"):
            continue
        for name, rx in (("conditional", _COND_RE), ("conditional", _COND2_RE), ("exclusive", _EXCL_RE),
                         ("count", _COUNT_RE)):
            if name not in kinds and rx.search(s):
                kinds.append(name)
    return kinds


@_safe
def p_logic_uses_indicators(ctx, params):
    """G2 (pre_exec). The problem text states a logical condition between decisions (if-then between decisions,
    not-both, a limit on how many different options are used) but the program declares no 0/1 variable at all.
    Such conditions cannot be written on the quantities themselves; they need indicator binaries linked to the
    quantities (Williams 2013, ch. 9)."""
    kinds = logic_cues((ctx.get("case") or {}).get("text") or "")
    if not kinds:
        return True, "no logical condition between decisions in the problem text"
    tree = _parse(ctx.get("code"))
    if tree is None:
        return True, NA_PARSE
    decls = _var_decls(tree)
    if not decls:
        return True, NA_NOVARS
    if any(d["kind"] in ("bin", "binlike") for d in decls.values()):
        return True, "the program declares 0/1 variables for the logical conditions"
    what = "; ".join(_CUE_NAMES[k] for k in kinds)
    return False, ("the problem states " + what + ", but the program declares no 0/1 (binary) variable; such a "
                   "condition cannot be expressed on the quantities themselves, so it is either missing or "
                   "encoded wrongly (e.g. as a sum of quantities bounded by 1 or 0, or as an unconditional bound)")


# ============================================================================= G3
@_safe
def p_rows_sign_feasible(ctx, params):
    """G3 (pre_exec). Sign check of each single constraint whose coefficients are numeric: with every variable in
    it non-negative and all coefficients of one sign, a row  sum(a_j x_j) <= -b  (b > 0) cannot be satisfied at
    all, and a row with right-hand side 0 forces every variable in it to zero. Either is a sign or direction error,
    or a logical condition written on quantities. Single-variable rows fixed at zero are allowed (explicit fixing);
    rows with symbolic (data-dependent) coefficients are skipped."""
    tree = _parse(ctx.get("code"))
    if tree is None:
        return True, NA_PARSE
    decls = _var_decls(tree)
    if not decls:
        return True, NA_NOVARS
    consts = _numeric_constants(tree)
    min_terms = int(params.get("min_terms_zero_forcing", 2))
    infeasible, zero = [], []
    for line, cmp in _constraint_nodes(tree):
        if len(cmp.ops) != 1:
            continue
        op = cmp.ops[0]
        left = _lin(cmp.left, decls, consts)
        right = _lin(cmp.comparators[0], decls, consts)
        if left is None or right is None:
            continue
        row = left.add(right, -1.0)  # row: sum(a_k t_k) + c  (op)  0
        terms = {k: v for k, v in row.terms.items() if abs(v) > 1e-12}
        c = row.const
        if not terms or not all(_term_nonneg(k, decls) for k in terms):
            continue
        pos = all(v > 0 for v in terms.values())
        neg = all(v < 0 for v in terms.values())
        if not (pos or neg):
            continue
        s = 1.0 if pos else -1.0          # normalise to  sum(|a| t) + s*c (op') 0
        cc = s * c
        if isinstance(op, (ast.LtE, ast.Lt)):
            kind = "le" if pos else "ge"
        elif isinstance(op, (ast.GtE, ast.Gt)):
            kind = "ge" if pos else "le"
        elif isinstance(op, ast.Eq):
            kind = "eq"
        else:
            continue
        # with |a|-weighted non-negative sum S >= 0:  le: S <= -cc ; eq: S == -cc ; ge: always satisfiable
        if kind in ("le", "eq"):
            n_terms = len(terms)  # a generator sum counts once: forcing one family subset to zero can be intended
            if cc > 1e-9:
                infeasible.append(line)
            elif abs(cc) <= 1e-9 and n_terms >= min_terms:
                zero.append(line)
    if infeasible or zero:
        parts = []
        if infeasible:
            parts.append("the constraint(s) on line(s) " + ", ".join(map(str, infeasible[:6]))
                         + " cannot hold for any non-negative values of their variables")
        if zero:
            parts.append("the constraint(s) on line(s) " + ", ".join(map(str, zero[:6]))
                         + " can only hold when every variable in them is zero")
        return False, ("; ".join(parts) + " (all their variables are non-negative and enter with the same sign); "
                       "this is a sign or direction error, or a logical condition written on the quantities")
    return True, "every analysable constraint leaves its variables room to be positive"


# ============================================================================= G4 (C3 only)
_FRACTION_OK_RE = re.compile(
    r"\b(?:fractions?|fractional(?:ly)?|divisible|non-?integers?|non-?integral|real[- ]valued|real numbers?|"
    r"continuous (?:quantit(?:y|ies)|amounts?|variables?|values?)|partial (?:units?|batch(?:es)?|lots?|loads?)|"
    r"any (?:non-?negative |positive )?(?:amount|quantity)|need not be (?:an )?integers?|"
    r"(?:does|do) not (?:need|have) to be (?:an )?(?:integers?|whole))\b", re.I)


def fraction_permitted(text):
    return bool(_FRACTION_OK_RE.search(_norm_text(text)))


def _objective_node(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Add):
            v = n.value
            if isinstance(v, ast.Tuple) and v.elts:
                v = v.elts[0]
            if not isinstance(v, ast.Compare):
                return v
        if isinstance(n, ast.Call) and _tail(n) == "setObjective" and n.args:
            return n.args[0]
    return None


def _index_positions(node):
    """ids of nodes that only index: range() arguments and subscript slices."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and _tail(n) == "range":
            out.update(id(c) for a in n.args for c in ast.walk(a))
        if isinstance(n, ast.Subscript):
            out.update(id(c) for c in ast.walk(n.slice))
    return out


def _literal_numbers(node):
    """Numeric literals of `node` that carry data (not range() arguments or subscript indices)."""
    skip = _index_positions(node)
    out = []
    for n in ast.walk(node):
        if id(n) in skip:
            continue
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            out.append(float(n.value))
    return out


def _all_integral(vals):
    return all(abs(v - round(v)) <= 1e-9 for v in vals)


@_safe
def p_fractional_count_optimum(ctx, params):
    """G4 (post_exec; C3 scope). Every decision variable is continuous, the text never says fractional amounts are
    allowed, every coefficient of the objective (literals in the objective and in the data tables it reads) is an
    integer, yet the optimal objective value is fractional. Then some decision variables take fractional values;
    if they count indivisible units the integrality requirement was relaxed silently (Williams 2013, ch. 8-9)."""
    text = (ctx.get("case") or {}).get("text") or ""
    if fraction_permitted(text):
        return True, "the problem text allows fractional amounts"
    ex = ctx.get("exec")
    if not isinstance(ex, dict):
        return True, "program not executed; checked by the execution genes"
    if str(ex.get("status") or "").strip().lower() != "optimal":
        return True, "status is not Optimal; checked by the status gene"
    obj = ex.get("objective")
    if isinstance(obj, bool) or not isinstance(obj, (int, float)) or obj != obj:
        return True, "no numeric objective reported"
    tol = max(1e-6, 1e-9 * abs(obj))
    if abs(obj - round(obj)) <= tol:
        return True, "objective value is integral"
    tree = _parse(ctx.get("code"))
    if tree is None:
        return True, NA_PARSE
    decls = _var_decls(tree)
    if not decls:
        return True, NA_NOVARS
    if any(d["kind"] != "cont" for d in decls.values()):
        return True, "the program already declares integer or binary variables (or their category is unclear)"
    objn = _objective_node(tree)
    if objn is None:
        return True, "no objective expression detected"
    vals = _literal_numbers(objn)
    if any(isinstance(n, (ast.BinOp,)) and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Pow, ast.Mod))
           for n in ast.walk(objn)):
        return True, "the objective contains divisions or powers; coefficients may be fractional"
    # data tables the objective reads: every module-level literal assigned to a referenced non-variable name
    referenced = {n.id for n in ast.walk(objn) if isinstance(n, ast.Name) and n.id not in decls}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                and n.targets[0].id in referenced:
            try:
                ast.literal_eval(n.value)
            except Exception:  # noqa: BLE001  (a computed table: coefficients unknown)
                return True, "objective coefficients are computed; integrality unknown"
            vals += _literal_numbers(n.value)
    if not vals:
        vals = [1.0]  # a plain sum of variables: every coefficient is 1
    if not _all_integral(vals):
        return True, "objective coefficients are not all integers"
    return False, ("every decision variable is continuous and every objective coefficient is an integer, yet the "
                   "optimal objective value is fractional, so some decisions take fractional values; the problem "
                   "text does not say that fractional amounts are allowed")


# ============================================================================= M1: binary_cardinality_linked v2
def _signed_names(node, sign=1.0, out=None):
    """Syntactic sign of every Name read in an additive expression: + for terms added, - for terms subtracted or
    negated; multiplicative factors keep the sign of their term (data coefficients are taken as positive)."""
    if out is None:
        out = {}
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        _signed_names(node.left, sign, out)
        _signed_names(node.right, sign if isinstance(node.op, ast.Add) else -sign, out)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        _signed_names(node.operand, -sign, out)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
        _signed_names(node.operand, sign, out)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        neg = any(isinstance(side, ast.UnaryOp) and isinstance(side.op, ast.USub) and _num(side) is not None
                  for side in (node.left, node.right))
        for side in (node.left, node.right):
            _signed_names(side, -sign if neg else sign, out)
    else:
        for n in ast.walk(node):
            if isinstance(n, ast.Name):
                out.setdefault(n.id, set()).add(sign)
    return out


@_safe
def p_binary_cardinality_linked_v2(ctx, params):
    """A binary that appears in a cardinality constraint (only binaries on one side, a constant on the other) must
    also bound the quantity it switches (an upper link). v2 changes against v1: (a) a program whose decision
    variables are all binary passes, because then the binaries are the decisions themselves (selection, covering,
    assignment) and there is no quantity to switch; (b) only decision variables (and names holding expressions of
    them) are read, so a cardinality constraint written with lpSum over a generator is recognised; (c) upper links
    are recognised in any arrangement, x <= M*b, M*b >= x, x - M*b <= 0, M*b - x >= 0, and in addConstraint(...)
    calls; (d) 0/1 integers (cat Integer with bounds 0..1, keyword or positional) count as binaries."""
    tree = _parse(ctx.get("code"))
    if tree is None:
        return True, NA_PARSE
    decls = _var_decls(tree)
    bins = {n for n, d in decls.items() if d["kind"] in ("bin", "binlike")}
    if _G is not None:
        bins |= _G._binary_names(tree)
    if not bins:
        return True, "no binary variables declared"
    quantities = {n for n, d in decls.items() if d["kind"] not in ("bin", "binlike")} - bins
    if not quantities:
        return True, "all decision variables are binary; there is no quantity for the binaries to switch"
    # names that hold an expression of decision variables (e.g. total = lpSum(x[i] for i in I)) count as quantities
    var_like = set(decls) | bins
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            nm = n.targets[0].id
            if nm not in var_like and {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)} & set(decls):
                quantities.add(nm)
    var_like |= quantities
    in_card, linked = set(), set()
    for _line, cmp in _constraint_nodes(tree):
        if len(cmp.ops) != 1:
            continue
        op, left, right = cmp.ops[0], cmp.left, cmp.comparators[0]
        vl = {x.id for x in ast.walk(left) if isinstance(x, ast.Name)} & var_like
        vr = {x.id for x in ast.walk(right) if isinstance(x, ast.Name)} & var_like
        for a, b in ((vl, vr), (vr, vl)):
            if a and a <= bins and not b:
                in_card |= a
        signs = {k: v for k, v in _signed_names(left, 1.0).items() if k in var_like}
        for k, v in _signed_names(right, -1.0).items():
            if k in var_like:
                signs.setdefault(k, set()).update(v)
        # row: (left - right) op 0.  Upper link for op <=: the binary with sign -, a quantity with sign +;
        # for op >=: the binary with sign +, a quantity with sign -.
        if isinstance(op, (ast.LtE, ast.Lt)):
            bsign, qsign = -1.0, 1.0
        elif isinstance(op, (ast.GtE, ast.Gt)):
            bsign, qsign = 1.0, -1.0
        else:
            continue
        if any(qsign in signs.get(q, set()) for q in quantities):
            linked |= {b for b in bins if bsign in signs.get(b, set())}
    missing = sorted(in_card - linked)
    if missing:
        return False, ("binary variable(s) " + ", ".join(missing[:6])
                       + " are counted in a cardinality constraint but never bound the quantity they switch; "
                         "add `quantity <= M * b` with M derived from the data, otherwise the count is toothless")
    return True, "binaries used in cardinality constraints are upper-linked"


# ============================================================================= M8: sparse_index_guard v2
@_safe
def p_sparse_index_guard_v2(ctx, params):
    """post_exec. v1's static finding is reported only when the program did not run cleanly. v1 cannot see every
    valid guard (a read guarded by membership in the table the mapping was built from, `if (i, j) in capacity`, or
    an off-diagonal read written against a fixed index, `flow[0, j] for j if j != 0`), and a program that ran to
    completion cannot have hit a missing key; so a clean run passes."""
    ex = ctx.get("exec")
    if isinstance(ex, dict) and ex.get("exec_ok") and not ex.get("timed_out"):
        return True, "program ran without a missing-key error"
    if _G is None:
        return True, "analysis skipped (orgene.genes not importable)"
    return _G.p_sparse_index_guard(ctx, params)


# ============================================================================= M2: linear_expressions_only v2
def _refs_decision(node, names):
    """True if `node` reads a decision variable outside pulp.value(...) / .varValue / .value()."""
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Call):
            if _tail(n) in ("value", "valueOrDefault"):
                continue
        if isinstance(n, ast.Attribute) and n.attr in ("varValue", "value"):
            continue
        if isinstance(n, ast.Name) and n.id in names:
            return True
        stack.extend(ast.iter_child_nodes(n))
    return False


@_safe
def p_linear_expressions_only_v2(ctx, params):
    """v1 checks plus four more non-linear uses of a decision variable: the modulo operator, a power, integer
    division with a variable numerator, a data table indexed by a decision variable (a table lookup is a non-linear
    function of the variable), and a Python if / while / conditional expression tested on a variable."""
    if _G is None:
        return True, "analysis skipped (orgene.genes not importable)"
    ok1, det1 = _G.p_linear_expressions_only(ctx, params)
    tree = _parse(ctx.get("code"))
    if tree is None:
        return True, NA_PARSE
    names = _G._decision_var_names(tree)
    if not names:
        return (ok1, det1) if not ok1 else (True, NA_NOVARS)
    extra = []
    for n in ast.walk(tree):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod) and (
                _refs_decision(n.left, names) or _refs_decision(n.right, names)):
            extra.append("the % operator applied to a decision variable")
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Pow) and (
                _refs_decision(n.left, names) or _refs_decision(n.right, names)):
            extra.append("a power of a decision variable")
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.FloorDiv) and _refs_decision(n.left, names):
            extra.append("integer division of a decision variable")
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id not in names \
                and _refs_decision(n.slice, names):
            extra.append("a data table indexed by a decision variable")
        if isinstance(n, (ast.If, ast.While, ast.IfExp)) and _refs_decision(n.test, names):
            extra.append("a Python if/while test on a decision variable")
    if not extra:
        return ok1, det1
    probs = sorted(set(extra))
    if not ok1:
        return False, det1 + "; also: " + "; ".join(probs[:3])
    return False, ("the model is not linear as written: " + "; ".join(probs[:4])
                   + ". Introduce auxiliary variables and linearize (one 0/1 variable per allowed value, "
                     "indicator binaries with a data-derived big-M, or an integer variable for a multiple)")


# ============================================================================= M5: no_invented_numbers v2
_NUM2_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?!\w|\.\d)")
_NUM_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
              "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
              "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
              "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
              "thousand": 1000, "half": 0.5, "twice": 2, "double": 2, "triple": 3, "thrice": 3, "dozen": 12}
_NUM_WORD_RE = re.compile(r"\b(" + "|".join(_NUM_WORDS) + r")\b", re.I)
_UNIT_FACTORS = (100, 60, 24, 7, 12, 365, 1000)


@_safe
def p_no_invented_numbers_v2(ctx, params):
    """v1 with a corrected number reader. v1's text pattern skips every number that ends a sentence ("... is $40.")
    and numbers written as words, and its code pattern also reads numbers inside comments and strings. v2 reads the
    program's numeric literals from the AST (comments and strings ignored), reads sentence-final numbers and number
    words from the text (a comma is read both as a thousands separator and as a list separator), skips literals
    that only index (range() arguments, subscripts), and also accepts a literal that is a text number times or
    divided by a common unit factor (100, 60, 24, 7, 12, 365, 1000). Other rules as v1 (soft; ignores |x| <= 3 and
    the same common constants)."""
    code, text = ctx.get("code") or "", (ctx.get("case") or {}).get("text") or ""
    tree = _parse(code)
    if tree is None:
        return True, NA_PARSE
    ignore = {0.0, 1.0, 2.0, 3.0, 10.0, 100.0, 1000.0, 0.5, 60.0, 24.0, 7.0, 12.0, 365.0, 1e6, 1e9}
    tv = set()
    norm = _norm_text(text)
    for variant in (norm.replace(",", ""), norm.replace(",", " ")):  # "100,000" and "[35,94]" both occur
        for t in _NUM2_RE.findall(variant):
            try:
                tv.add(round(float(t), 6))
            except ValueError:
                pass
    for w in _NUM_WORD_RE.findall(text):
        tv.add(float(_NUM_WORDS[w.lower()]))
    index_positions = set()  # literals that index rather than carry data: range(...) arguments, subscripts
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _tail(n) == "range":
            index_positions.update(id(c) for a in n.args for c in ast.walk(a))
        if isinstance(n, ast.Subscript):
            index_positions.update(id(c) for c in ast.walk(n.slice))
    unmatched = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)):
            continue
        if id(n) in index_positions:
            continue
        v = round(float(n.value), 6)
        if abs(v) in ignore or abs(v) <= 3 or v in tv or -v in tv:
            continue
        if any(round(v * f, 6) in tv or round(v / f, 6) in tv for f in _UNIT_FACTORS):
            continue
        unmatched.append(v)
    shown = sorted(set(unmatched))[:12]
    if shown:
        return False, "numeric literals not found in the problem text: " + ", ".join(
            str(int(x)) if float(x).is_integer() else str(x) for x in shown)
    return True, "all numeric literals traceable to the text"


# ============================================================================= M7: spec genes v2 (C3 only)
def _spec_ok(spec):
    return isinstance(spec, dict)


@_safe
def p_objective_sense_consistent_v2(ctx, params):
    """v1, except: (a) no parseable spec -> not applicable (orgene.artifact.spec_present reports it); (b) a program
    that declares no sense uses PuLP's default, LpMinimize (LpProblem(name, sense=1), LpMinimize = 1)."""
    spec, code = ctx.get("spec"), ctx.get("code") or ""
    if not _spec_ok(spec):
        return True, NA_NOSPEC
    o = spec.get("objective")
    s = str((o.get("sense") or o.get("direction") or "") if isinstance(o, dict) else "").strip().lower()
    s = "min" if s.startswith("min") else "max" if s.startswith("max") else None
    if s is None:
        return False, "spec objective sense missing"
    has_min, has_max = "LpMinimize" in code, "LpMaximize" in code
    code_sense = "max" if has_max and not has_min else "min" if has_min and not has_max else (
        "min" if not (has_min or has_max) else None)
    if code_sense is None:
        return True, "program mentions both senses; not checked"
    if code_sense != s:
        extra = " (no sense given, so PuLP minimizes)" if not (has_min or has_max) else ""
        return False, f"spec says {'maximize' if s == 'max' else 'minimize'} but the program " \
                      f"{'maximizes' if code_sense == 'max' else 'minimizes'}{extra}"
    return True, f"sense={s} consistent"


@_safe
def p_variable_domains_consistent_v2(ctx, params):
    """v1, except that no parseable spec (or a spec without decision variables) is not applicable here:
    orgene.artifact.spec_present already reports it."""
    spec = ctx.get("spec")
    if not _spec_ok(spec):
        return True, NA_NOSPEC
    vs = spec.get("decision_variables") or spec.get("variables") or []
    if not [v for v in vs if isinstance(v, dict)]:
        return True, "spec lists no decision variables; reported by orgene.artifact.spec_present"
    if _G is None:
        return True, "analysis skipped (orgene.genes not importable)"
    return _G.p_variable_domains_consistent(ctx, params)


@_safe
def p_constraints_added_v2(ctx, params):
    """v1, except: no parseable spec (or no spec constraints) is not applicable here (spec_present reports it), and
    the program's constraints are counted from the AST (any `<problem> += <comparison>` or addConstraint call), so a
    problem object with another name is not miscounted."""
    spec, code = ctx.get("spec"), ctx.get("code") or ""
    if not _spec_ok(spec):
        return True, NA_NOSPEC
    cons = [c for c in (spec.get("constraints") or []) if isinstance(c, (dict, str))]
    if not cons:
        return True, "spec lists no constraints; reported by orgene.artifact.spec_present"
    tree = _parse(code)
    if tree is None:
        return True, NA_PARSE
    n_code = len(_constraint_nodes(tree))
    if n_code < 1:
        return False, "the program adds no constraint to the problem"
    return True, f"spec constraints={len(cons)}, program constraint statements={n_code}"


PREDICATES = {
    "predicate.optimum_not_trivial_zero.v1": p_optimum_not_trivial_zero,
    "predicate.logic_uses_indicators.v1": p_logic_uses_indicators,
    "predicate.rows_sign_feasible.v1": p_rows_sign_feasible,
    "predicate.fractional_count_optimum.v1": p_fractional_count_optimum,
    "predicate.binary_cardinality_linked.v2": p_binary_cardinality_linked_v2,
    "predicate.linear_expressions_only.v2": p_linear_expressions_only_v2,
    "predicate.sparse_index_guard.v2": p_sparse_index_guard_v2,
    "predicate.no_invented_numbers.v2": p_no_invented_numbers_v2,
    "predicate.objective_sense_consistent.v2": p_objective_sense_consistent_v2,
    "predicate.variable_domains_consistent.v2": p_variable_domains_consistent_v2,
    "predicate.constraints_added.v2": p_constraints_added_v2,
}

