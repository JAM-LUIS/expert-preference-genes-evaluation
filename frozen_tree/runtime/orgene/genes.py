"""Expert preference genes v3: load, activate, compile into a contract, validate with executable predicates, build repair turns.

A gene is one JSON line in the gene library (R1 working library genes/genes.r1.jsonl; v5 library 1.0 = releases/v1.0/genes.v3.jsonl):
{
  "schemaVersion": "orgene.gene.v3", "geneId": "orgene.objective.sense_consistent", "version": "1.0.0",
  "lifecycle": {"state": "active", "createdAt": "...", "supersedes": []},
  "scope": {"task": "lp_milp_modeling", "conditions": ["C3"]},
  "preference": {"statement": "...", "rationale": "...", "priority": 90},
  "contract": {"required": ["..."], "forbidden": ["..."], "checks": ["..."]},
  "targets": ["spec.objective.sense", "code"],
  "validation": {"mode": "executable" | "prompt_only", "predicateId": "...", "params": {}, "severity": "hard" | "soft", "phase": "pre_exec" | "post_exec"},
  "repair": {"instruction": "...", "maxApplications": 1, "safetyClass": "structural_safe"},
  "audit": {"sourceType": "seed_structural" | "dev_failure_derived", "devCaseIds": [], "createdAt": "...", "note": "..."},
  "activation": {"rule": <rule>, "rationale": "...", "devEvidence": ["<dev case id>", ...]}      (optional, E04)
}
Predicates receive a context dict: {"case": case_record, "spec": dict|None, "code": str|None, "exec": dict|None}
and return (ok: bool, detail: str).
`activation.rule` is evaluated on problem-text features only (features.py); a gene without `activation` is always
active, so records written before E04 (the v1.0 library) keep their digests.
"""
import copy
import hashlib
import json
import re

from . import features as F

SCHEMA_VERSION = "orgene.gene.v3"
ACTIVATION_MODES = ("per_problem", "all", "none")

# ----------------------------------------------------------------------------- store


def load_store(path, lexicon=None):
    """Load and check a gene library. `lexicon` (path or features.Lexicon; default genes/activation_lexicon.v1.json)
    is read only when some gene's activation rule refers to a feature, to check names and types at load time."""
    genes = []
    types = None
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            g = json.loads(line)
            if g.get("schemaVersion") != SCHEMA_VERSION:
                raise ValueError(f"line {i}: schemaVersion must be {SCHEMA_VERSION}")
            for k in ("geneId", "version", "lifecycle", "scope", "preference", "contract", "validation", "repair", "audit"):
                if k not in g:
                    raise ValueError(f"line {i}: gene {g.get('geneId')} missing field '{k}'")
            v = g["validation"]
            if v.get("mode") == "executable" and v.get("predicateId") not in PREDICATES:
                raise ValueError(f"line {i}: gene {g['geneId']} references unknown predicate {v.get('predicateId')}")
            if "activation" in g:
                where = f"line {i}: gene {g['geneId']} activation"
                if F.check_activation(g["activation"], None, where):
                    if types is None:
                        types = F.feature_types(lexicon)
                    F.check_activation(g["activation"], types, where)
            genes.append(g)
    ids = [(g["geneId"], g["version"]) for g in genes]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate (geneId, version) in store")
    return genes


def activate(genes, condition="C3", task="lp_milp_modeling", features=None, mode="per_problem"):
    """Active = lifecycle.state == active, scope matches, and (mode per_problem) the activation rule holds on the
    problem's features. Returns (active_list, trace); order: priority descending, then geneId.

    mode "per_problem": a gene whose rule refers to a feature needs `features` (features.extract_features of the
        problem statement); calling without them raises instead of silently including or dropping the gene.
    mode "all": the rules are ignored (the all-active ablation); with `features` the trace still records each value.
    mode "none": no gene is active (configurations without genes).
    Trace per gene: geneId, version, included, reasons, activation_rule, activation_value (None = not evaluated),
    features_used.
    """
    if mode not in ACTIVATION_MODES:
        raise ValueError(f"activation mode {mode!r} not in {ACTIVATION_MODES}")
    active, trace = [], []
    for g in genes:
        reasons = []
        if g["lifecycle"].get("state") != "active":
            reasons.append(f"lifecycle={g['lifecycle'].get('state')}")
        sc = g.get("scope", {})
        if sc.get("task") not in (None, task):
            reasons.append(f"task={sc.get('task')}")
        if sc.get("conditions") and condition not in sc["conditions"]:
            reasons.append(f"condition {condition} not in {sc['conditions']}")
        rule = F.gene_rule(g)
        if rule == F.ALWAYS:
            value = True
        elif not F.rule_features(rule):  # a constant rule such as {"not": "always"} needs no features
            value = F.eval_rule(rule, {})
        elif features is not None:
            value = F.eval_rule(rule, features)
        else:
            value = None
        if mode == "none":
            reasons.append("activation mode none")
        elif mode == "per_problem" and not reasons:
            if value is None:
                raise ValueError(f"gene {g['geneId']} {g['version']}: its activation rule needs the problem features "
                                 f"(mode per_problem called without features)")
            if not value:
                reasons.append("activation rule false")
        trace.append({"geneId": g["geneId"], "version": g["version"], "included": not reasons, "reasons": reasons,
                      "activation_rule": copy.deepcopy(rule), "activation_value": value,
                      "features_used": sorted(F.rule_features(rule))})
        if not reasons:
            active.append(g)
    active.sort(key=lambda g: (-int(g["preference"].get("priority", 0)), g["geneId"]))
    return active, trace


def activate_case(genes, case, lexicon=None, condition="C3", task="lp_milp_modeling", mode="per_problem"):
    """activate() on one case record: features come from case["text"] (the problem statement) only.
    Returns (active, trace, info) with info = {mode, features, features_sha256, lexicon_sha256}."""
    lex = F.load_lexicon(lexicon)
    feats = F.extract_features(case["text"], lex)
    active, trace = activate(genes, condition=condition, task=task, features=feats, mode=mode)
    return active, trace, {"mode": mode, "features": feats, "features_sha256": F.features_sha256(feats),
                           "lexicon_sha256": lex.sha256}


def activation_summary(traces):
    """Per-gene activation counts and rates over many problems (for run_config). `traces` = iterable of activate()
    traces, one per problem. Keyed "<geneId>@<version>"."""
    out = {}
    for tr in traces:
        for t in tr:
            d = out.setdefault(f"{t['geneId']}@{t['version']}", {
                "geneId": t["geneId"], "version": t["version"], "n": 0, "n_included": 0, "n_rule_true": 0,
                "n_rule_not_evaluated": 0})
            d["n"] += 1
            d["n_included"] += bool(t["included"])
            if t.get("activation_value") is None:
                d["n_rule_not_evaluated"] += 1
            elif t["activation_value"]:
                d["n_rule_true"] += 1
    for d in out.values():
        d["included_rate"] = round(d["n_included"] / d["n"], 4) if d["n"] else None
        n_eval = d["n"] - d["n_rule_not_evaluated"]
        d["rule_true_rate"] = round(d["n_rule_true"] / n_eval, 4) if n_eval else None
    return dict(sorted(out.items()))


def store_digest(active):
    canon = json.dumps([{k: g[k] for k in sorted(g)} for g in active], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------- compile


# The four framing lines of a compiled contract. A prompt rewrite (conditions/variants/<v>/C3_contract_frame.json,
# E11) may reword them; the gene texts themselves are never rewritten. With the default frame the contract text, and
# so every recorded contract and prompt hash, is exactly the v5 one.
CONTRACT_FRAME_KEYS = ("heading", "required", "forbidden", "checks")
DEFAULT_CONTRACT_FRAME = {
    "heading": "## Modeling contract (compiled from {n} versioned expert review rules)",
    "required": "Required:",
    "forbidden": "Forbidden:",
    "checks": "Your output will be checked automatically for:",
}


def check_contract_frame(frame):
    """A contract frame: exactly the four keys, one-line non-empty strings; the heading carries {n} once."""
    if not isinstance(frame, dict) or set(frame) != set(CONTRACT_FRAME_KEYS):
        raise ValueError(f"a contract frame has exactly the keys {list(CONTRACT_FRAME_KEYS)}")
    for k in CONTRACT_FRAME_KEYS:
        v = frame[k]
        if not isinstance(v, str) or not v.strip() or "\n" in v or v != v.strip():
            raise ValueError(f"contract frame {k!r} must be one non-empty line without surrounding blanks")
        rest = v.replace("{n}", "") if k == "heading" else v
        if "{" in rest or "}" in rest or (k == "heading" and v.count("{n}") != 1):
            raise ValueError(f"contract frame {k!r}: only the heading may use a placeholder, exactly one {{n}}")
    return frame


def compile_contract(active, frame=None):
    """Turn the active gene set into prompt text. Deterministic; the digest of this text is recorded per request.
    `frame` rewords the four framing lines (default: DEFAULT_CONTRACT_FRAME, the v5 text)."""
    fr = DEFAULT_CONTRACT_FRAME if frame is None else check_contract_frame(frame)
    req, forb, checks = [], [], []
    for g in active:
        c = g.get("contract", {})
        for t in c.get("required", []):
            req.append((g["geneId"], t))
        for t in c.get("forbidden", []):
            forb.append((g["geneId"], t))
        for t in c.get("checks", []):
            checks.append((g["geneId"], t))
    lines = [fr["heading"].replace("{n}", str(len(active)))]
    if req:
        lines.append(fr["required"])
        lines += [f"{i}. {t}" for i, (_, t) in enumerate(req, 1)]
    if forb:
        lines.append(fr["forbidden"])
        lines += [f"{i}. {t}" for i, (_, t) in enumerate(forb, 1)]
    if checks:
        lines.append(fr["checks"])
        lines += [f"- {t}" for (_, t) in checks]
    text = "\n".join(lines) + "\n"
    return text, {"required": req, "forbidden": forb, "checks": checks,
                  "contract_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


# ----------------------------------------------------------------------------- predicates

_NUM_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w.])")


def _spec_vars(spec):
    if not isinstance(spec, dict):
        return []
    v = spec.get("decision_variables") or spec.get("variables") or []
    return [x for x in v if isinstance(x, dict)]


def _spec_cons(spec):
    if not isinstance(spec, dict):
        return []
    c = spec.get("constraints") or []
    return [x for x in c if isinstance(x, (dict, str))]


def _sense(spec):
    if not isinstance(spec, dict):
        return None
    o = spec.get("objective")
    if isinstance(o, dict):
        s = str(o.get("sense") or o.get("direction") or "").strip().lower()
    else:
        s = ""
    if s.startswith("min"):
        return "min"
    if s.startswith("max"):
        return "max"
    return None


def p_spec_present(ctx, params):
    spec = ctx.get("spec")
    if not isinstance(spec, dict):
        return False, "no parseable JSON spec block"
    missing = []
    if not _spec_vars(spec):
        missing.append("decision_variables")
    if _sense(spec) is None:
        missing.append("objective.sense")
    if not _spec_cons(spec):
        missing.append("constraints")
    return (not missing), ("missing: " + ", ".join(missing) if missing else "spec has variables, objective sense, constraints")


def p_code_present(ctx, params):
    code = ctx.get("code") or ""
    if "pulp" not in code:
        return False, "no python program using pulp found"
    return True, "program found"


def p_objective_sense_consistent(ctx, params):
    spec, code = ctx.get("spec"), ctx.get("code") or ""
    s = _sense(spec)
    if s is None:
        return False, "spec objective sense missing"
    has_min, has_max = "LpMinimize" in code, "LpMaximize" in code
    if s == "min" and has_max and not has_min:
        return False, "spec says minimize but code uses LpMaximize"
    if s == "max" and has_min and not has_max:
        return False, "spec says maximize but code uses LpMinimize"
    if not (has_min or has_max):
        return False, "code does not declare LpMinimize/LpMaximize"
    return True, f"sense={s} consistent"


def p_variable_domains_consistent(ctx, params):
    spec, code = ctx.get("spec"), ctx.get("code") or ""
    vs = _spec_vars(spec)
    if not vs:
        return False, "no decision variables in spec"
    doms = [str(v.get("domain") or v.get("type") or v.get("cat") or "").lower() for v in vs]
    need_int = any(d.startswith("int") for d in doms)
    need_bin = any(d.startswith("bin") for d in doms)
    code_int = bool(re.search(r"(LpInteger|cat\s*=\s*['\"]Integer['\"])", code))
    code_bin = bool(re.search(r"(LpBinary|cat\s*=\s*['\"]Binary['\"])", code))
    problems = []
    if need_int and not code_int and not code_bin:
        problems.append("spec declares integer variables but code declares none")
    if need_bin and not code_bin and not code_int:
        problems.append("spec declares binary variables but code declares none")
    return (not problems), ("; ".join(problems) if problems else "variable domains consistent")


def p_constraints_added(ctx, params):
    spec, code = ctx.get("spec"), ctx.get("code") or ""
    n_spec = len(_spec_cons(spec))
    n_code = len(re.findall(r"^\s*(?:prob|model|problem|m|lp)\s*\+=", code, re.MULTILINE))
    n_code += len(re.findall(r"\.addConstraint\(", code))
    if n_spec == 0:
        return False, "spec lists no constraints"
    if n_code < 2:
        return False, f"code adds {max(0, n_code - 1)} constraints (expected at least 1 besides the objective)"
    return True, f"spec constraints={n_spec}, code constraint statements={n_code - 1}"


def p_solve_before_report(ctx, params):
    code = ctx.get("code") or ""
    i_solve = code.find(".solve(")
    i_obj = code.find("FINAL_OBJECTIVE")
    if i_solve == -1:
        return False, "program never calls .solve()"
    if i_obj == -1:
        return False, "program does not print FINAL_OBJECTIVE"
    if i_obj < i_solve:
        return False, "FINAL_OBJECTIVE printed before .solve()"
    tail = code[i_obj: i_obj + 300]
    if re.search(r"FINAL_OBJECTIVE\s*:?\s*['\"]?\s*,?\s*\)?\s*[-+]?\d", tail) and "value(" not in tail:
        return False, "FINAL_OBJECTIVE appears to print a literal number instead of the solver value"
    return True, "solve() precedes the report"


def p_status_reported(ctx, params):
    code = ctx.get("code") or ""
    if "LpStatus" not in code and "STATUS" not in code:
        return False, "program does not print solver STATUS via pulp.LpStatus"
    return True, "status reported"


def p_executes(ctx, params):
    ex = ctx.get("exec")
    if not ex:
        return False, "program not executed"
    if ex.get("timed_out"):
        return False, f"timed out after {params.get('timeout', '?')}s"
    if not ex.get("exec_ok"):
        return False, "runtime error: " + (ex.get("stderr_tail") or "")[-600:].strip()
    if not ex.get("protocol_ok"):
        return False, "STATUS / FINAL_OBJECTIVE lines missing from stdout"
    return True, "executed and reported"


def p_status_optimal_or_justified(ctx, params):
    ex = ctx.get("exec") or {}
    st = (ex.get("status") or "").lower()
    if not st:
        return False, "no STATUS reported"
    if st == "optimal":
        return True, "optimal"
    spec = ctx.get("spec") if isinstance(ctx.get("spec"), dict) else {}
    notes = " ".join(str(a) for a in (spec.get("assumptions") or [])).lower()
    if st in ("infeasible", "unbounded") and st in notes:
        return True, f"{st} and justified in assumptions"
    return False, f"solver status {st}: re-check constraint directions, bounds, and data; state in assumptions if the instance is truly {st}"


def p_no_invented_numbers(ctx, params):
    """Soft: numeric literals in code should appear in the problem text (ignoring small integers and common constants)."""
    code, text = ctx.get("code") or "", (ctx.get("case") or {}).get("text") or ""
    ignore = {"0", "1", "2", "3", "10", "100", "1000", "0.0", "1.0", "0.5", "60", "24", "7", "12", "365", "1e6", "1e9"}
    text_nums = set(_NUM_RE.findall(text.replace(",", "")))
    text_vals = set()
    for t in text_nums:
        try:
            text_vals.add(round(float(t), 6))
        except ValueError:
            pass
    unmatched = []
    for lit in _NUM_RE.findall(code):
        if lit in ignore:
            continue
        try:
            v = round(float(lit), 6)
        except ValueError:
            continue
        if abs(v) <= 3 or v in text_vals or (v * 100 in text_vals) or (v / 100 in text_vals):
            continue
        unmatched.append(lit)
    unmatched = sorted(set(unmatched), key=lambda s: (len(s), s))[:12]
    if unmatched:
        return False, "numeric literals not found in the problem text: " + ", ".join(unmatched)
    return True, "all numeric literals traceable to the text"


def p_bigm_bounded(ctx, params):
    code = ctx.get("code") or ""
    big = [lit for lit in _NUM_RE.findall(code) if abs(float(lit)) >= float(params.get("threshold", 1e6))]
    big += re.findall(r"\b1e[6-9]\b|\b1e1\d\b", code)
    if big:
        return False, "very large constants (possible loose big-M): " + ", ".join(sorted(set(big))[:6])
    return True, "no loose big-M constants"


# --------------------------------------------------------------- AST helpers (dev-derived genes)

import ast as _ast


def _parse(code):
    try:
        return _ast.parse(code or "")
    except SyntaxError:
        return None


def _walk(tree):
    return list(_ast.walk(tree)) if tree is not None else []


def _is_pulp_call(node, *names):
    """True for pulp.X(...) / LpVariable.X(...) whose dotted tail matches one of `names`."""
    if not isinstance(node, _ast.Call):
        return False
    f = node.func
    parts = []
    while isinstance(f, _ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, _ast.Name):
        parts.append(f.id)
    dotted = ".".join(reversed(parts))
    return any(dotted == n or dotted.endswith("." + n) for n in names)


def _elt_is_tuple(node):
    """The element produced by a comprehension/generator is a tuple."""
    return isinstance(node, (_ast.GeneratorExp, _ast.ListComp, _ast.SetComp)) and isinstance(node.elt, _ast.Tuple)


def _tuple_keyed_names(tree):
    """Names bound to a mapping whose keys are tuples (LpVariable.dicts over tuples, dict comps, dict literals)."""
    out = set()
    for n in _walk(tree):
        if not isinstance(n, _ast.Assign) or not n.targets:
            continue
        tgt = n.targets[0]
        if not isinstance(tgt, _ast.Name):
            continue
        v = n.value
        if _is_pulp_call(v, "LpVariable.dicts", "dicts") and len(v.args) >= 2 and _elt_is_tuple(v.args[1]):
            out.add(tgt.id)
        elif isinstance(v, _ast.DictComp) and isinstance(v.key, _ast.Tuple):
            out.add(tgt.id)
        elif isinstance(v, _ast.Dict) and v.keys and all(isinstance(k, _ast.Tuple) for k in v.keys if k is not None):
            out.add(tgt.id)
    return out


def _decision_var_names(tree):
    """Names bound to LpVariable(...) or to a container of them."""
    out = set()
    for n in _walk(tree):
        if isinstance(n, _ast.Assign) and n.targets and isinstance(n.targets[0], _ast.Name):
            v = n.value
            if _is_pulp_call(v, "LpVariable", "LpVariable.dicts", "dicts"):
                out.add(n.targets[0].id)
            elif isinstance(v, (_ast.ListComp, _ast.DictComp, _ast.SetComp, _ast.GeneratorExp)):
                if any(_is_pulp_call(c, "LpVariable") for c in _walk(v)):
                    out.add(n.targets[0].id)
            elif isinstance(v, _ast.Dict) and any(_is_pulp_call(c, "LpVariable") for c in _walk(v)):
                out.add(n.targets[0].id)
        elif isinstance(n, _ast.Assign) and n.targets and isinstance(n.targets[0], _ast.Subscript):
            base = n.targets[0].value
            if isinstance(base, _ast.Name) and _is_pulp_call(n.value, "LpVariable"):
                out.add(base.id)
    return out


def _refs_variable(node, varnames):
    for n in _walk(node) + [node]:
        if isinstance(n, _ast.Name) and n.id in varnames:
            return True
    return False


def p_tuple_key_indexing(ctx, params):
    """A mapping whose keys are tuples must be read as d[i, j]; d[i][j] looks up d[i] and raises KeyError."""
    code = ctx.get("code") or ""
    tree = _parse(code)
    if tree is None:
        return True, "code does not parse; checked by the syntax/execution genes"
    tupled = _tuple_keyed_names(tree)
    if not tupled:
        return True, "no tuple-keyed mapping found"
    bad = []
    for n in _walk(tree):
        if (isinstance(n, _ast.Subscript) and isinstance(n.value, _ast.Subscript)
                and isinstance(n.value.value, _ast.Name) and n.value.value.id in tupled):
            bad.append(n.value.value.id)
    if bad:
        names = sorted(set(bad))
        return False, ("tuple-keyed mapping(s) " + ", ".join(names)
                       + " are indexed as d[i][j]; their keys are tuples, so write d[i, j]")
    return True, f"tuple-keyed mappings indexed correctly: {', '.join(sorted(tupled))}"


def _is_diagonal_only_test(node):
    """True for a condition that only excludes i == j (so the mapping is the full product minus its diagonal)."""
    if isinstance(node, _ast.BoolOp):
        return all(_is_diagonal_only_test(v) for v in node.values)
    return (isinstance(node, _ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], _ast.NotEq)
            and isinstance(node.left, _ast.Name)
            and isinstance(node.comparators[0], _ast.Name))


def _sparsely_built_names(tree):
    """Mappings built only on selected keys. Returns (arbitrary_sparse, diagonal_sparse).

    A mapping built under `if i != j` alone is dense apart from its diagonal, so reading it under the same
    `i != j` guard is correct; only genuinely arbitrary sparsity needs a membership test.
    """
    arbitrary, diagonal = set(), set()
    def _record(name, conds):
        if conds and all(_is_diagonal_only_test(c) for c in conds):
            diagonal.add(name)
        else:
            arbitrary.add(name)
    for n in _walk(tree):
        if isinstance(n, _ast.Assign) and n.targets and isinstance(n.targets[0], _ast.Name):
            v = n.value
            if isinstance(v, _ast.DictComp) and any(g.ifs for g in v.generators):
                _record(n.targets[0].id, [c for g in v.generators for c in g.ifs])
        if isinstance(n, (_ast.For, _ast.While)):
            for sub in _ast.walk(n):
                if isinstance(sub, _ast.If):
                    for a in _ast.walk(sub):
                        if (isinstance(a, _ast.Assign) and a.targets
                                and isinstance(a.targets[0], _ast.Subscript)
                                and isinstance(a.targets[0].value, _ast.Name)):
                            _record(a.targets[0].value.id, [sub.test])
    return arbitrary - diagonal, diagonal - arbitrary


def _literal_sparse_pair_dicts(tree):
    """Dict literals keyed by 2-tuples. Returns (arbitrary_sparse, diagonal_sparse)."""
    out, diag = set(), set()
    for n in _walk(tree):
        if not (isinstance(n, _ast.Assign) and n.targets and isinstance(n.targets[0], _ast.Name)):
            continue
        v = n.value
        if not (isinstance(v, _ast.Dict) and v.keys):
            continue
        pairs = []
        for k in v.keys:
            if isinstance(k, _ast.Tuple) and len(k.elts) == 2:
                try:
                    pairs.append((_ast.literal_eval(k.elts[0]), _ast.literal_eval(k.elts[1])))
                except (ValueError, TypeError):
                    return out
            else:
                pairs = []
                break
        if len(pairs) < 4:
            continue
        idx = sorted({a for a, _ in pairs} | {b for _, b in pairs}, key=repr)
        full, off_diag = len(idx) * len(idx), len(idx) * len(idx) - len(idx)
        if len(pairs) == off_diag and not any(a == b for a, b in pairs):
            diag.add(n.targets[0].id)
        elif len(pairs) < full:
            out.add(n.targets[0].id)
    return out, diag


def _guarded_by_membership(comp, name):
    """The comprehension restricts keys with `... in name`."""
    for g in comp.generators:
        for cond in g.ifs:
            for c in _ast.walk(cond):
                if isinstance(c, _ast.Compare) and any(isinstance(o, _ast.In) for o in c.ops):
                    for cmp_node in c.comparators:
                        if isinstance(cmp_node, _ast.Name) and cmp_node.id == name:
                            return True
    return False


def _guarded_off_diagonal(comp):
    """The comprehension excludes i == j."""
    return any(_is_diagonal_only_test(c) for g in comp.generators for c in g.ifs)


def p_sparse_index_guard(ctx, params):
    """Reading a mapping that was built on a subset of index pairs must be restricted to the keys it actually has."""
    code = ctx.get("code") or ""
    tree = _parse(code)
    if tree is None:
        return True, "code does not parse; checked by the syntax/execution genes"
    built_arb, built_diag = _sparsely_built_names(tree)
    lit_arb, lit_diag = _literal_sparse_pair_dicts(tree)
    arbitrary, diagonal = built_arb | lit_arb, (built_diag | lit_diag) - (built_arb | lit_arb)
    if not (arbitrary or diagonal):
        return True, "no sparsely built mapping found"
    offenders = set()
    for comp in _walk(tree):
        if not isinstance(comp, (_ast.GeneratorExp, _ast.ListComp, _ast.SetComp)):
            continue
        read = set()
        for n in _ast.walk(comp.elt):
            if isinstance(n, _ast.Subscript) and isinstance(n.value, _ast.Name) and n.value.id in (arbitrary | diagonal):
                read.add(n.value.id)
        for name in read:
            if _guarded_by_membership(comp, name):
                continue
            if name in diagonal and _guarded_off_diagonal(comp):
                continue
            offenders.add(name)
    if offenders:
        names = sorted(offenders)
        return False, ("mapping(s) " + ", ".join(names)
                       + " are built on a subset of index pairs but read over the full index product; "
                         "iterate their own keys or add an `if (i, j) in <mapping>` guard")
    return True, "sparse mappings are read with a matching guard"


_PULP_API = {
    "LpProblem", "LpVariable", "LpConstraint", "LpAffineExpression", "lpSum", "lpDot", "value",
    "LpMinimize", "LpMaximize", "LpStatus", "LpStatusOptimal", "LpInteger", "LpBinary", "LpContinuous",
    "LpConstraintEQ", "LpConstraintLE", "LpConstraintGE", "PULP_CBC_CMD", "COIN_CMD", "HiGHS", "HiGHS_CMD",
    "GLPK_CMD", "listSolvers", "getSolver", "LpSolverDefault", "const", "pulp", "LpElement", "allcombinations",
    "combination", "permutation", "makeDict", "splitDict", "LpFractionConstraint", "lpDot", "isNumber",
}


def p_pulp_api_exists(ctx, params):
    """Only real PuLP attributes may be used; invented ones raise AttributeError at run time."""
    code = ctx.get("code") or ""
    tree = _parse(code)
    if tree is None:
        return True, "code does not parse; checked by the syntax/execution genes"
    allowed = set(_PULP_API) | set(params.get("extra_allowed") or [])
    bad = set()
    for n in _walk(tree):
        if (isinstance(n, _ast.Attribute) and isinstance(n.value, _ast.Name)
                and n.value.id == "pulp" and n.attr not in allowed):
            bad.add("pulp." + n.attr)
    if bad:
        return False, ("these PuLP attributes do not exist: " + ", ".join(sorted(bad))
                       + "; PuLP models linear expressions only, so there is no product/constant helper of that kind")
    return True, "all pulp attributes are real"


def p_linear_expressions_only(ctx, params):
    """Decision variables may only enter linear expressions: no min/max/abs/round on them, no variable x variable,
    no division by a variable, no comparison used as an arithmetic term."""
    code = ctx.get("code") or ""
    tree = _parse(code)
    if tree is None:
        return True, "code does not parse; checked by the syntax/execution genes"
    varnames = _decision_var_names(tree)
    if not varnames:
        return True, "no decision variables detected"
    problems = []
    for n in _walk(tree):
        if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name) and n.func.id in ("min", "max", "abs", "round"):
            if any(_refs_variable(a, varnames) for a in n.args):
                problems.append(f"{n.func.id}() applied to a decision variable")
        if isinstance(n, _ast.BinOp) and isinstance(n.op, _ast.Mult):
            if _refs_variable(n.left, varnames) and _refs_variable(n.right, varnames):
                problems.append("a product of two expressions that both contain decision variables")
        if isinstance(n, _ast.BinOp) and isinstance(n.op, (_ast.Div, _ast.FloorDiv)):
            if _refs_variable(n.right, varnames):
                problems.append("a division whose denominator contains a decision variable")
        if isinstance(n, _ast.BinOp) and (isinstance(n.left, _ast.Compare) or isinstance(n.right, _ast.Compare)):
            problems.append("a comparison (a == b) used as a term inside an arithmetic expression")
    if problems:
        seen = sorted(set(problems))
        return False, ("the model is not linear as written: " + "; ".join(seen[:4])
                       + ". Introduce auxiliary variables and linearize (indicator binaries with a data-derived "
                         "big-M, or cross-multiplied ratio constraints)")
    return True, "all expressions containing decision variables are linear"


def _objective_expr(tree):
    """The first `prob += <expr>` whose right-hand side is not a comparison is the objective."""
    for n in _walk(tree):
        if isinstance(n, _ast.AugAssign) and isinstance(n.op, _ast.Add):
            v = n.value
            if isinstance(v, _ast.Tuple) and v.elts:
                v = v.elts[0]
            if not isinstance(v, _ast.Compare):
                return v
    return None


def p_objective_aggregates_variables(ctx, params):
    """Soft: an objective that names a single decision variable out of many is usually a mis-stated aggregate
    (the classic case is a network-flow objective set to one arc instead of the net outflow of the source)."""
    code = ctx.get("code") or ""
    tree = _parse(code)
    if tree is None:
        return True, "code does not parse; checked by the syntax/execution genes"
    varnames = _decision_var_names(tree)
    obj = _objective_expr(tree)
    if obj is None or not varnames:
        return True, "no objective expression detected"
    if any(isinstance(n, _ast.Call) and _is_pulp_call(n, "lpSum", "lpDot") for n in _walk(obj)):
        return True, "objective aggregates with lpSum/lpDot"
    families = {r.id for r in _walk(obj) if isinstance(r, _ast.Name) and r.id in varnames}
    if len(families) != 1:
        return True, "objective references several variable families"
    fam = families.pop()

    def _elements(node):
        """(distinct subscript keys of `fam`, whether any key is symbolic i.e. stands for a whole index set)."""
        keys, symbolic = set(), False
        for n in _walk(node):
            if isinstance(n, _ast.Subscript) and isinstance(n.value, _ast.Name) and n.value.id == fam:
                sub = n.slice
                if any(isinstance(x, _ast.Name) for x in _walk(sub)) or isinstance(sub, _ast.Slice):
                    symbolic = True
                try:
                    keys.add(_ast.unparse(n))
                except Exception:  # noqa: BLE001
                    keys.add(repr(n))
        return keys, symbolic

    in_obj, obj_symbolic = _elements(obj)
    if len(in_obj) != 1 or obj_symbolic:
        return True, f"objective references {len(in_obj)} element(s) of {fam}" + (" over an index set" if obj_symbolic else "")
    used_elsewhere, elsewhere_symbolic = set(), False
    for n in _walk(tree):
        if isinstance(n, _ast.AugAssign) and n.value is not obj:
            k, sym = _elements(n.value)
            used_elsewhere |= k
            elsewhere_symbolic = elsewhere_symbolic or sym
    if elsewhere_symbolic or len(used_elsewhere) >= int(params.get("min_family_size", 3)):
        return False, (f"the objective is the single element {sorted(in_obj)[0]} while the constraints range over "
                       f"the whole index set of {fam}; if the goal is a total "
                       "it must be an lpSum over the relevant "
                       "index set, not one element")
    return True, "objective looks like an aggregate"


def _binary_names(tree):
    out = set()
    for n in _walk(tree):
        if isinstance(n, _ast.Assign) and n.targets and isinstance(n.targets[0], _ast.Name):
            for c in _walk(n.value):
                if isinstance(c, _ast.Call) and _is_pulp_call(c, "LpVariable", "LpVariable.dicts", "dicts"):
                    for kw in c.keywords:
                        if kw.arg == "cat" and isinstance(kw.value, _ast.Constant) and kw.value.value == "Binary":
                            out.add(n.targets[0].id)
                        if kw.arg == "cat" and isinstance(kw.value, _ast.Attribute) and kw.value.attr == "LpBinary":
                            out.add(n.targets[0].id)
    return out


def p_binary_cardinality_linked(ctx, params):
    """Soft: a binary that appears in a cardinality constraint (sum of binaries <op> k) must also bound the
    quantity it switches, via `quantity <= M * b`; otherwise the count constraint has no effect."""
    code = ctx.get("code") or ""
    tree = _parse(code)
    if tree is None:
        return True, "code does not parse; checked by the syntax/execution genes"
    bins = _binary_names(tree)
    if not bins:
        return True, "no binary variables declared"
    in_cardinality, upper_linked = set(), set()
    for n in _walk(tree):
        if not (isinstance(n, _ast.AugAssign) and isinstance(n.op, _ast.Add)):
            continue
        v = n.value
        if isinstance(v, _ast.Tuple) and v.elts:
            v = v.elts[0]
        if not isinstance(v, _ast.Compare):
            continue
        left, right = v.left, (v.comparators[0] if v.comparators else None)
        names_l = {x.id for x in _walk(left) if isinstance(x, _ast.Name)} & bins
        names_r = {x.id for x in _walk(right) if isinstance(x, _ast.Name)} & bins if right is not None else set()
        others_l = {x.id for x in _walk(left) if isinstance(x, _ast.Name)} - bins
        # cardinality: only binaries on one side, a constant on the other
        if names_l and not others_l and right is not None and not _walk(right) == [] and \
                not ({x.id for x in _walk(right) if isinstance(x, _ast.Name)}):
            in_cardinality |= names_l
        # upper linking: a real quantity bounded by the binary (quantity <= coef * b, or coef * b >= quantity).
        # The cardinality constraint itself must not count as its own link, so a non-binary must take part.
        others_r = {x.id for x in _walk(right) if isinstance(x, _ast.Name)} - bins if right is not None else set()
        if names_r and others_l and isinstance(v.ops[0], _ast.LtE):
            upper_linked |= names_r
        if names_l and others_r and isinstance(v.ops[0], _ast.GtE):
            upper_linked |= names_l
    missing = sorted(in_cardinality - upper_linked)
    if missing:
        return False, ("binary variable(s) " + ", ".join(missing[:6])
                       + " are counted in a cardinality constraint but never bound the quantity they switch; "
                         "add `quantity <= M * b` with M derived from the data, otherwise the count is toothless")
    return True, "binaries used in cardinality constraints are upper-linked"


_REQ_CUES = ("at least", "at most", "exactly", "must", "cannot", "can not", "no more than", "not exceed",
             "no fewer than", "minimum of", "maximum of", "is limited to", "up to", "should be", "no less than")


def p_constraints_cover_requirements(ctx, params):
    """Soft: the spec should carry at least as many constraints as the problem text has requirement sentences."""
    spec = ctx.get("spec")
    text = (ctx.get("case") or {}).get("text") or ""
    if not isinstance(spec, dict):
        return True, "no spec to check (condition without a spec)"
    sentences = [t for t in re.split(r"(?<=[.;:!?])\s+|\n", text) if t.strip()]
    cues = [t for t in sentences if any(c in t.lower() for c in _REQ_CUES)]
    n_cons = len(_spec_cons(spec))
    ratio = float(params.get("ratio", 1.0))
    need = ratio * len(cues)
    if cues and n_cons < need:
        return False, (f"the text has {len(cues)} requirement sentences but the spec lists only {n_cons} constraints; "
                       "check for a limit, ratio, exclusivity or balance condition that was not written down")
    return True, f"{n_cons} constraints vs {len(cues)} requirement sentences"


PREDICATES = {
    "predicate.spec_present.v1": p_spec_present,
    "predicate.code_present.v1": p_code_present,
    "predicate.objective_sense_consistent.v1": p_objective_sense_consistent,
    "predicate.variable_domains_consistent.v1": p_variable_domains_consistent,
    "predicate.constraints_added.v1": p_constraints_added,
    "predicate.solve_before_report.v1": p_solve_before_report,
    "predicate.status_reported.v1": p_status_reported,
    "predicate.executes.v1": p_executes,
    "predicate.status_optimal_or_justified.v1": p_status_optimal_or_justified,
    "predicate.no_invented_numbers.v1": p_no_invented_numbers,
    "predicate.bigm_bounded.v1": p_bigm_bounded,
    # dev-failure-derived (2026-09-06)
    "predicate.tuple_key_indexing.v1": p_tuple_key_indexing,
    "predicate.sparse_index_guard.v1": p_sparse_index_guard,
    "predicate.pulp_api_exists.v1": p_pulp_api_exists,
    "predicate.linear_expressions_only.v1": p_linear_expressions_only,
    "predicate.objective_aggregates_variables.v1": p_objective_aggregates_variables,
    "predicate.binary_cardinality_linked.v1": p_binary_cardinality_linked,
    "predicate.constraints_cover_requirements.v1": p_constraints_cover_requirements,
}


# ----------------------------------------------------------------------------- validate / repair


def validate(active, ctx, phase):
    """Run every executable predicate of the given phase. Returns list of issue records (one per gene)."""
    issues = []
    for g in active:
        v = g["validation"]
        if v.get("phase", "pre_exec") != phase:
            continue
        rec = {"geneId": g["geneId"], "version": g["version"], "predicateId": v.get("predicateId"),
               "severity": v.get("severity", "hard"), "phase": phase}
        if v.get("mode") != "executable":
            rec.update({"ok": None, "detail": "not_executed_prompt_only"})
        else:
            try:
                ok, detail = PREDICATES[v["predicateId"]](ctx, v.get("params") or {})
            except Exception as e:  # noqa: BLE001
                ok, detail = False, f"predicate error: {e!r}"
            rec.update({"ok": bool(ok), "detail": detail})
        issues.append(rec)
    return issues


def hard_failures(issues):
    return [i for i in issues if i.get("ok") is False and i.get("severity") == "hard"]


def soft_failures(issues):
    return [i for i in issues if i.get("ok") is False and i.get("severity") == "soft"]


# ----------------------------------------------------------------------------- repair profiles (E05)
#
# How each repairing configuration repairs. `gene_scope` is the gene scope it validates with (gene records keep
# listing only the scope names C3, C3L and C3E, so adding a configuration never changes a gene or a digest);
# `repair` is "gene" (the failed gene's own detail and repair.instruction: C3, C3L) or "generic" (the fixed
# execution-feedback template below: C3E = C0 + generic repair, C2E = C2 + generic repair); `closing` is what the
# model must send back ("program", or "spec_and_program" for the configurations whose answers carry a JSON spec).
# E03's configuration registry carries the same three fields; repair_turn() takes them as arguments, and this table is
# the default for the four configurations that repair.
REPAIR_PROFILES = {
    "C3": {"gene_scope": "C3", "repair": "gene", "closing": "spec_and_program"},
    "C3L": {"gene_scope": "C3L", "repair": "gene", "closing": "program"},
    "C3E": {"gene_scope": "C3E", "repair": "generic", "closing": "program"},
    "C2E": {"gene_scope": "C3E", "repair": "generic", "closing": "spec_and_program"},
}
# D8: every repairing configuration runs to at most two repair rounds. The "at most one round" point and round 0 are
# cut from that same run (ladder.py); they are never run separately.
MAX_REPAIR_ROUNDS = 2


def gene_scope(condition):
    """The gene scope a configuration validates with (C2E -> C3E); any other name is its own scope."""
    p = REPAIR_PROFILES.get(condition)
    return p["gene_scope"] if p else condition


def repair_profile(condition):
    if condition not in REPAIR_PROFILES:
        raise ValueError(f"configuration {condition!r} does not repair (repairing configurations: {sorted(REPAIR_PROFILES)})")
    return dict(REPAIR_PROFILES[condition])


def _exhausted(gene, applications):
    """True once the gene has been applied repair.maxApplications times. Both repair modes use this bookkeeping."""
    return applications.get(gene["geneId"], 0) >= int(gene["repair"].get("maxApplications", 1))


# A generated program runs in a fresh temporary directory (execute.run_program), so its traceback names a random path
# such as <tmp>/orgene_exec_k3j2x9/prog.py. Left in a repair message, the same repair request would differ between two
# runs of the same unit (request hashes, the reverse-order determinism check). Both repair modes keep the file name only.
_EXEC_DIR_RE = re.compile(r"""[^\s"'<>]*orgene_exec_[^\s"'/<>]+/""")


def scrub_exec_paths(text):
    return _EXEC_DIR_RE.sub("", text) if text else text


# ----------------------------------------------------------------------------- gene repair (C3, C3L)

# C3L never asked for a spec, so it must not be told to return one.
GENE_CLOSING = {
    "spec_and_program": "Return the complete corrected answer in the same format (the JSON spec block followed by the "
                        "full Python program). Do not explain; do not omit any part.",
    "program": "Return the complete corrected Python program in a single ```python block. Do not explain; do not omit "
               "any part.",
}


def gene_repair_message(issues, exec_result, applications, active, closing):
    """Hard failures of active genes with applications left, each with its detail and the gene's Fix: instruction;
    soft failures as warnings; the program's stderr."""
    by_id = {g["geneId"]: g for g in active}
    lines, applied = [], []
    for i in hard_failures(issues):
        g = by_id.get(i["geneId"])
        if not g or _exhausted(g, applications):
            continue
        applied.append(g["geneId"])
        lines.append(f"- [{g['geneId']}] {scrub_exec_paths(i['detail'])}\n  Fix: {g['repair'].get('instruction', '')}")
    if not lines:
        return None, []
    softs = [f"- [{i['geneId']}] (warning) {scrub_exec_paths(i['detail'])}" for i in soft_failures(issues)]
    msg = ["Automatic review of your previous answer found the following problems:", *lines]
    if softs:
        msg += ["Warnings (fix only if they are real errors):", *softs]
    if exec_result and exec_result.get("stderr_tail"):
        msg += ["Program stderr (last lines):", "```", scrub_exec_paths(exec_result["stderr_tail"])[-1200:].strip(), "```"]
    msg += ["", GENE_CLOSING[closing]]
    return "\n".join(msg), applied


# ----------------------------------------------------------------------------- generic repair (C3E, C2E)
#
# The generic (execution-feedback) baseline must be told *that* the program failed, never *how to model*. Its message
# is built only from the lines below and from the run itself (the program's stderr, the solver status). It uses
# neither a gene's repair.instruction nor a predicate's detail string: several details carry modelling advice
# (e.g. "re-check constraint directions, bounds, and data"). The wording is v5's C3E template, unchanged; E05 adds
# the C2E closing and the maxApplications bookkeeping. The template is frozen with generic_template_sha256().
GENERIC_TIMEOUT = "Your program did not finish within the time limit."
GENERIC_STDERR_HEAD = "Your program failed to run. stderr:"
GENERIC_NO_OUTPUT = "Your program did not produce the two required output lines."
GENERIC_STATUS = "The solver reported status: {status}."
GENERIC_PROTOCOL = ("Your program must call .solve() and then print exactly two final lines:\n"
                    "STATUS: <pulp.LpStatus[prob.status]>\nFINAL_OBJECTIVE: <the objective value as a plain number>")
GENERIC_FENCE = "```"
GENERIC_STDERR_CHARS = 1200
GENERIC_CLOSING = {
    "program": "Fix it and return the complete corrected Python program in a single ```python block. "
               "Do not explain; do not omit any part.",
    "spec_and_program": "Fix it and return the complete corrected answer in the same format (the JSON spec block "
                        "followed by the full Python program). Do not explain; do not omit any part.",
}
# Which template line a failed check produces. Keyed by predicate, so a new protocol or execution gene maps onto the
# same lines; a gene whose predicate is not listed here cannot be validated in a generic configuration at all.
GENERIC_LINE_FOR_PREDICATE = {
    "predicate.code_present.v1": "run",
    "predicate.executes.v1": "run",
    "predicate.status_optimal_or_justified.v1": "status",
    "predicate.solve_before_report.v1": "protocol",
    "predicate.status_reported.v1": "protocol",
}


def generic_template():
    """The generic repair template as data: every fixed line, the two closings and the predicate -> line map."""
    return {
        "schemaVersion": "orgene.generic_repair_template.v1",
        "lines": {"timeout": GENERIC_TIMEOUT, "stderr_head": GENERIC_STDERR_HEAD, "no_output": GENERIC_NO_OUTPUT,
                  "status": GENERIC_STATUS, "protocol": GENERIC_PROTOCOL},
        "stderr_block": {"fence": GENERIC_FENCE, "tail_chars": GENERIC_STDERR_CHARS},
        "closing": dict(GENERIC_CLOSING),
        "line_for_predicate": dict(GENERIC_LINE_FOR_PREDICATE),
    }


def generic_template_sha256():
    """SHA-256 of the canonical JSON of generic_template(); recorded in the freeze manifest."""
    canon = json.dumps(generic_template(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def generic_whitelist():
    """Every line a generic repair message may contain outside its stderr block ({status} stays a placeholder)."""
    lines = {GENERIC_TIMEOUT, GENERIC_STDERR_HEAD, GENERIC_NO_OUTPUT, GENERIC_STATUS, ""}
    lines.update(GENERIC_PROTOCOL.split("\n"))
    lines.update(GENERIC_CLOSING.values())
    return lines


def check_generic_scope(active):
    """A generic configuration may only validate with protocol and execution checks (never a modelling gene)."""
    bad = [g["geneId"] for g in active
           if (g.get("validation") or {}).get("predicateId") not in GENERIC_LINE_FOR_PREDICATE]
    if bad:
        raise ValueError(f"genes without a line in the generic repair template: {bad}; a generic configuration "
                         f"validates only with {sorted(GENERIC_LINE_FOR_PREDICATE)}")


def _generic_line(kind, ex):
    if kind == "run":
        tail = scrub_exec_paths(ex.get("stderr_tail") or "").strip()
        if ex.get("timed_out"):
            return GENERIC_TIMEOUT
        if tail:
            return f"{GENERIC_STDERR_HEAD}\n{GENERIC_FENCE}\n{tail[-GENERIC_STDERR_CHARS:]}\n{GENERIC_FENCE}"
        return GENERIC_NO_OUTPUT
    if kind == "status":
        return GENERIC_STATUS.format(status=ex.get("status") or "unknown")
    return GENERIC_PROTOCOL


def generic_repair_message(issues, exec_result, applications, active, closing):
    """Fixed template (C3E, C2E), with the same bookkeeping as the gene path: a failed check is reported only while its
    gene is active and has applications left (repair.maxApplications). Returns (text, applied_gene_ids) or (None, [])."""
    if closing not in GENERIC_CLOSING:
        raise ValueError(f"unknown closing {closing!r}")
    check_generic_scope(active)
    by_id = {g["geneId"]: g for g in active}
    ex = exec_result or {}
    lines, applied = [], []
    for i in hard_failures(issues):
        g = by_id.get(i["geneId"])
        if not g or _exhausted(g, applications):
            continue
        kind = GENERIC_LINE_FOR_PREDICATE[g["validation"]["predicateId"]]
        applied.append(g["geneId"])
        lines.append(_generic_line(kind, ex))
    if not lines:
        return None, []
    seen, uniq = set(), []
    for t in lines:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return "\n".join(uniq + ["", GENERIC_CLOSING[closing]]), applied


_GENERIC_STATUS_RE = re.compile("^" + re.escape(GENERIC_STATUS).replace(re.escape("{status}"), "(.*)") + "$")


def generic_message_violations(msg, exec_result=None, closing=None):
    """Lines of a generic repair message that the fixed template cannot produce. [] means clean.

    The stderr block (the lines between the fence after GENERIC_STDERR_HEAD and the last fence line) and the status
    value are the only free text. With `exec_result` both are also checked against the run (scrubbed stderr tail,
    reported status); with `closing` the last line must be that closing. Used by the tests and by the dev rehearsal
    check that counts non-template lines in C3E, C2E and ORA repair messages."""
    if msg is None:
        return []
    out = []
    lines = msg.split("\n")
    allowed = generic_whitelist()
    ex = exec_result or {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == GENERIC_STDERR_HEAD:
            fences = [j for j in range(i + 2, len(lines)) if lines[j] == GENERIC_FENCE]
            if i + 1 >= len(lines) or lines[i + 1] != GENERIC_FENCE or not fences:
                out.append((i, line, "stderr head without a fenced block"))
                i += 1
                continue
            end = fences[-1]
            if exec_result is not None:
                want = scrub_exec_paths(ex.get("stderr_tail") or "").strip()[-GENERIC_STDERR_CHARS:]
                if "\n".join(lines[i + 2:end]) != want:
                    out.append((i + 2, "<stderr block>", "stderr block is not the program's stderr tail"))
            i = end + 1
            continue
        m = _GENERIC_STATUS_RE.match(line)
        if m:
            if exec_result is not None and m.group(1) != (ex.get("status") or "unknown"):
                out.append((i, line, "status value is not the reported status"))
        elif line not in allowed:
            out.append((i, line, "not a template line"))
        i += 1
    if closing is not None:
        if closing not in GENERIC_CLOSING:
            raise ValueError(f"unknown closing {closing!r}")
        if len(lines) < 2 or lines[-1] != GENERIC_CLOSING[closing] or lines[-2] != "":
            out.append((len(lines) - 1, lines[-1] if lines else "", f"message does not end with the {closing} closing"))
    return out


# ----------------------------------------------------------------------------- checklist repair (C3T, C3A; D12)
#
# Detection with generic content. The trigger and the bookkeeping are those of gene repair (every hard failure of an
# active gene with applications left counts, and is recorded as applied), but text of genes outside the generic-repair
# scope never reaches the model: no gene id, no predicate detail, no Fix line, no soft warning. When at least one such
# gene fails, one fixed generic review checklist is sent instead (conditions/review_checklist.md, the first bullets of
# the C1 pool). Failures of the protocol and execution genes (GENERIC_LINE_FOR_PREDICATE) are rendered exactly as gene
# repair renders them, so a unit where nothing else failed and no warning was raised gets the gene-repair message byte
# for byte. `force` (C3A, round 0 only) sends the checklist to an answer without any hard failure.
CHECKLIST_HEAD = "One or more additional modeling checks failed. Re-check the program against this list:"
REVIEW_HEAD = "Review your previous answer against this list:"
REVIEW_CLOSING = ("Return the complete Python program in a single ```python block, unchanged if it is already correct. "
                  "Do not explain; do not omit any part.")


def checklist_template():
    """The fixed lines of the checklist repair mode (the checklist itself is a frozen template file)."""
    return {"schemaVersion": "orgene.checklist_repair_template.v1", "checklist_head": CHECKLIST_HEAD,
            "review_head": REVIEW_HEAD, "review_closing": REVIEW_CLOSING}


def checklist_template_sha256():
    canon = json.dumps(checklist_template(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _in_generic_scope(gene):
    return (gene.get("validation") or {}).get("predicateId") in GENERIC_LINE_FOR_PREDICATE


def _check_checklist(checklist):
    if not isinstance(checklist, str) or not checklist.strip():
        raise ValueError("checklist repair needs the review checklist text (conditions.review_checklist)")
    return checklist.strip()


def checklist_repair_message(issues, exec_result, applications, active, closing, checklist, force=False):
    """Returns (text, applied_gene_ids) or (None, []). See the section comment."""
    if closing != "program":
        raise ValueError("checklist repair returns a program only")
    checklist = _check_checklist(checklist)
    by_id = {g["geneId"]: g for g in active}
    lines, applied, other = [], [], False
    for i in hard_failures(issues):
        g = by_id.get(i["geneId"])
        if not g or _exhausted(g, applications):
            continue
        applied.append(g["geneId"])
        if _in_generic_scope(g):
            lines.append(f"- [{g['geneId']}] {scrub_exec_paths(i['detail'])}\n  Fix: {g['repair'].get('instruction', '')}")
        else:
            other = True
    if not applied:
        if force and not hard_failures(issues):
            return "\n".join([REVIEW_HEAD, checklist, "", REVIEW_CLOSING]), []
        return None, []
    msg = []
    if lines:
        msg += ["Automatic review of your previous answer found the following problems:", *lines]
    softs = [f"- [{i['geneId']}] (warning) {scrub_exec_paths(i['detail'])}" for i in soft_failures(issues)
             if i["geneId"] in by_id and _in_generic_scope(by_id[i["geneId"]])]
    if softs:
        msg += ["Warnings (fix only if they are real errors):", *softs]
    if other:
        msg += [CHECKLIST_HEAD, checklist]
    if exec_result and exec_result.get("stderr_tail"):
        msg += ["Program stderr (last lines):", "```", scrub_exec_paths(exec_result["stderr_tail"])[-1200:].strip(), "```"]
    msg += ["", GENE_CLOSING[closing]]
    return "\n".join(msg), applied


# ----------------------------------------------------------------------------- repair turn


def repair_turn(active, issues, applications, exec_result=None, condition="C3", repair=None, closing=None,
                checklist=None, force=False):
    """Build the repair user message. `applications` = {geneId: times already applied}.

    `repair` ("gene" | "generic" | "gene_generic") and `closing` ("program" | "spec_and_program") default to the
    profile of `condition` (REPAIR_PROFILES). `checklist` and `force` belong to "gene_generic" (checklist repair).
    Returns (text, applied_gene_ids) or (None, [])."""
    if repair is None or closing is None:
        prof = repair_profile(condition)
        repair = repair or prof["repair"]
        closing = closing or prof["closing"]
    if repair == "generic":
        return generic_repair_message(issues, exec_result, applications, active, closing)
    if repair == "gene":
        if closing not in GENE_CLOSING:
            raise ValueError(f"unknown closing {closing!r}")
        return gene_repair_message(issues, exec_result, applications, active, closing)
    if repair == "gene_generic":
        return checklist_repair_message(issues, exec_result, applications, active, closing, checklist, force=force)
    raise ValueError(f"unknown repair mode {repair!r}")


# Author-approved development iteration 0: new predicate IDs only; v1 IDs stay unchanged.
from . import predicates_it0 as _it0  # noqa: E402
import sys as _sys  # noqa: E402
_it0_predicates = _it0.bind_base(_sys.modules[__name__])
if set(PREDICATES) & set(_it0_predicates):
    raise RuntimeError("iteration-0 predicate IDs overlap the existing registry")
PREDICATES.update(_it0_predicates)
