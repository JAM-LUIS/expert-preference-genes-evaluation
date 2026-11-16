#!/usr/bin/env python3
"""Measurement check of the solver-based accuracy measure (prereg/MEASUREMENT_CHECK_PLAN.md; E20b): sample, booklet,
workbooks, disagreement list and analysis.

  $PY analysis/r1/measurement_check.py sample [--registry ...] [--set main] [--model qwen3:8b] [--register]
        --out experiments/measurement_check/sample.json
  $PY analysis/r1/measurement_check.py export --sample <sample.json> --out <export dir>
        -> booklet.html, items.json, key.json, export_manifest.json
  $PY analysis/r1/measurement_check.py workbooks --template 05_judgment_workbook_template.xlsx --export <dir> --step 1|3
        -> judgments_R1.xlsx, judgments_R2.xlsx (step 1) / gene_review_R1.xlsx, gene_review_R2.xlsx (step 3)
  $PY analysis/r1/measurement_check.py consensus --template ... --export <dir> --r1 <xlsx> --r2 <xlsx>
        -> consensus.xlsx (step 2)
  $PY analysis/r1/measurement_check.py analyze --export <dir> --r1 <xlsx> --r2 <xlsx> --consensus <xlsx> --out report.json

sample and export run where the sealed runs are (standard library only; the registry passes the freeze gate before any
test row or program is read) and print counts and ids only. export writes the problem statements and the programs into
booklet.html, which goes to the reviewers only; items.json holds codes only, and key.json (kept by the authors) holds
ids, strata, weights, verdicts and program identities, no statement and no program text. workbooks, consensus and
analyze read items.json / key.json and the workbooks only, so they can run anywhere; they need openpyxl, and analyze
needs scipy for the Beta quantiles.

Plan sections: frame, program identity and D (3.1); two-part sample, allocation, selection, weights (3.2-3.3); what is
judged (4); display normalization, codes (5); agreement and resolution (7); rates (8); bounds (9). SEED = 20261008.
"""
import argparse
import ast
import hashlib
import io
import json
import math
import os
import random
import re
import sys
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "runtime"))

from common import (ROOT, AnalysisError, dumps, read_jsonl, rel, resolve, sha256_file, sha256_text,  # noqa: E402
                    write_json, write_text)

SEED = 20261008
SAMPLE_SCHEMA = "orgene.r1.measurement_check.sample.v1"
KEY_SCHEMA = "orgene.r1.measurement_check.key.v1"
ITEMS_SCHEMA = "orgene.r1.measurement_check.items.v1"
REPORT_SCHEMA = "orgene.r1.measurement_check.report.v1"
WORKBOOK_SCHEMA = "orgene.r1.measurement_check.workbook.v1"
BENCH_ORDER = ("mamo_complex_lp", "industryor")
LABELS = {"C0": "C0", "C3E": "C3E@2", "C3L": "C3L@2"}      # condition -> registry label (final programs)
CONDS = ("C0", "C3E", "C3L")
PART1_TARGET, PART2_TARGET = 24, 10
D_TYPES = ("l_correct_e_incorrect", "l_incorrect_e_correct", "same_verdict")
NO_PROGRAM = "NO_PROGRAM"
MASK = '"[MASKED]"'
# string literals naming a condition, a rule, the model or run metadata are masked on display (plan 5)
MASK_RE = re.compile(r"(?<![A-Za-z0-9])(?:C0R-?E|C0|C3[ELTA]?)(?![A-Za-z0-9])|"      # judged condition names
                     r"(?i:orgene|(?<![a-z])genes?(?![a-z])|gene_?id|repair|(?<![a-z])round[ _-]?\d|request_id|"
                     r"qwen|gpt-oss|ollama)")
JUDGMENTS = ("correct", "incorrect", "cannot_judge")
CATEGORIES = ("missing_constraint", "objective_sense", "integrality", "big_m", "data_misread", "other")
ASPECTS = ("variables", "objective", "constraints", "data_use")
FIRST_ROW = 3


def h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ program identity (plan 3.1)


def _logical_lines(toks):
    line, out = [], []
    for t in toks:
        line.append(t)
        if t.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
            out.append(line)
            line = []
    if line:
        out.append(line)
    return out


def program_identity(code):
    """(key, method). Python tokens without comments, docstrings (stand-alone string statements) and layout:
    INDENT / DEDENT / NEWLINE by type only, every other token as (type, text). Tokenize failure: '#' lines removed
    and all whitespace dropped (method 'fallback'). No program: NO_PROGRAM."""
    if not isinstance(code, str) or not code.strip():
        return NO_PROGRAM, "none"
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(code).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        kept = "".join(ln for ln in code.splitlines() if not ln.lstrip().startswith("#"))
        return h("fallback:" + re.sub(r"\s+", "", kept)), "fallback"
    seq = []
    for line in _logical_lines(toks):
        sig = [t for t in line if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING, tokenize.INDENT,
                                                 tokenize.DEDENT, tokenize.NEWLINE, tokenize.ENDMARKER)]
        lead = [t for t in line if t.type in (tokenize.INDENT, tokenize.DEDENT)]
        if sig and all(t.type == tokenize.STRING for t in sig):
            seq += [[tokenize.tok_name[t.type]] for t in lead]     # keep the block structure, drop the string
            continue
        for t in line:
            if t.type in (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING):
                continue
            if t.type in (tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE, tokenize.ENDMARKER):
                seq.append([tokenize.tok_name[t.type]])
            else:
                seq.append([tokenize.tok_name[t.type], t.string])
    return h(json.dumps(seq, ensure_ascii=False)), "tokens"


# ------------------------------------------------------------------ allocation and selection (plan 3.3)


def allocate(sizes, target):
    """sizes: [(stratum, N_h)] in the fixed stratum order -> {stratum: n_h}. Every non-empty stratum gets 1; the rest
    is allocated in proportion to N_h - 1 by the largest-remainder method (ties in stratum order), never above N_h.
    If the strata hold no more than `target` problems, every problem is taken."""
    nonempty = [(k, n) for k, n in sizes if n > 0]
    if sum(n for _, n in nonempty) <= target:
        return {k: n for k, n in nonempty}
    if len(nonempty) > target:
        raise AnalysisError(f"{len(nonempty)} non-empty strata for a target of {target}")
    alloc = {k: 1 for k, _ in nonempty}
    rest = target - len(nonempty)
    base = sum(n - 1 for _, n in nonempty)
    quota = {k: rest * (n - 1) / base for k, n in nonempty} if base else {k: 0.0 for k, _ in nonempty}
    for k, n in nonempty:
        alloc[k] += min(int(math.floor(quota[k])), n - 1)
    left = target - sum(alloc.values())
    order = {k: i for i, (k, _) in enumerate(nonempty)}
    cap = dict(nonempty)
    for k in sorted(quota, key=lambda k: (-(quota[k] - math.floor(quota[k])), order[k])):
        if left <= 0:
            break
        if alloc[k] < cap[k]:
            alloc[k] += 1
            left -= 1
    for k in sorted(cap, key=lambda k: order[k]):            # only if caps blocked the remainders
        while left > 0 and alloc[k] < cap[k]:
            alloc[k] += 1
            left -= 1
    return alloc


def select(ids, n, seed=SEED):
    return sorted(ids, key=lambda c: h(f"{seed}:{c}"))[:n]


def d_type(s_l, s_e):
    if s_l and not s_e:
        return D_TYPES[0]
    if s_e and not s_l:
        return D_TYPES[1]
    return D_TYPES[2]


def draw_sample(frame, seed=SEED):
    """frame: {case_id: {"benchmark", "S": {cond: bool}, "X": {cond: bool}, "id": {cond: key}}} -> sample dict."""
    D = sorted(c for c, v in frame.items() if v["id"]["C3L"] != v["id"]["C3E"])
    outside = sorted(set(frame) - set(D))
    census = len(D) <= PART1_TARGET
    strata = []
    p1 = [((b, t), [c for c in D if frame[c]["benchmark"] == b and d_type(frame[c]["S"]["C3L"],
                                                                         frame[c]["S"]["C3E"]) == t])
          for b in BENCH_ORDER for t in D_TYPES]
    p2 = [((b, s), [c for c in outside if frame[c]["benchmark"] == b and bool(frame[c]["S"]["C3L"]) == s])
          for b in BENCH_ORDER for s in (True, False)]
    chosen = []
    for part, groups, target in ((1, p1, PART1_TARGET), (2, p2, PART2_TARGET)):
        alloc = allocate([(k, len(v)) for k, v in groups], target)
        for k, ids in groups:
            n_h = alloc.get(k, 0)
            name = f"{k[0]}|{k[1] if part == 1 else ('C3L_correct' if k[1] else 'C3L_incorrect')}"
            w = (len(ids) / n_h) if n_h else None
            strata.append({"part": part, "stratum": name, "N_h": len(ids), "n_h": n_h, "weight": w})
            for c in select(ids, n_h, seed):
                chosen.append({"case_id": c, "benchmark": frame[c]["benchmark"], "part": part, "stratum": name,
                               "weight": w, "in_D": part == 1})
    order = sorted(chosen, key=lambda r: h(f"{seed}:order:{r['case_id']}"))
    for i, r in enumerate(order, 1):
        r["problem_id"] = f"P{i:02d}"
    digest = h(json.dumps({"selected": sorted(r["case_id"] for r in order), "N_D": len(D),
                           "strata": [(s["part"], s["stratum"], s["N_h"], s["n_h"]) for s in strata]}))
    return {"N": len(frame), "N_D": len(D), "census_D": census, "D": D, "strata": strata, "selected": order,
            "digest": digest}


# ------------------------------------------------------------------ sample (sealed side)


def load_frame(reg_path, set_name, model, root, allow_pending=False):
    import registry as RG
    reg = RG.load_registry(reg_path, root=root)
    m = RG.build_matrix(reg, root=root, labels=list(LABELS.values()), models=[model])
    aset = RG.resolve_set(set_name, root=root, allow_pending=allow_pending)
    m = RG.restrict(m, aset)
    bench = RG.bench_map(aset)
    rows = {}
    for r in m.rows:
        if r["repeat"] != 0:
            raise AnalysisError(f"{r['label']}: repeat {r['repeat']} found; the check uses the single main run")
        rows[(r["label"], r["case_id"])] = r
    entries = [e for e in reg.runs if e["model"] == model and e["label"] in LABELS.values()]
    programs, locs = {}, {}
    for e in entries:
        fn = e.get("final") or f"final.{e['config']}.jsonl"
        p = os.path.join(resolve(e["path"], root), fn)
        if not os.path.isfile(p):
            raise AnalysisError(f"{e['label']} / {e['benchmark']}: final programs {rel(p, root)} missing")
        if e.get("final_sha256") and sha256_file(p) != e["final_sha256"]:
            raise AnalysisError(f"{e['label']} / {e['benchmark']}: {rel(p, root)} does not match final_sha256")
        for i, fr in enumerate(read_jsonl(p)):
            if int(fr.get("repeat", 0)) != 0 or fr["case_id"] not in bench:
                continue
            k = (e["label"], fr["case_id"])
            if k in programs:
                raise AnalysisError(f"{e['label']}: two final programs for {fr['case_id']}")
            programs[k] = fr.get("code") if fr.get("has_code", True) not in (False, "False") else None
            locs[k] = {"file": rel(p, root), "row": i}
    frame, missing = {}, []
    for c in sorted(bench):
        v = {"benchmark": bench[c], "S": {}, "X": {}, "id": {}, "id_method": {}, "loc": {}}
        for cond, lab in LABELS.items():
            r = rows.get((lab, c))
            if r is None or (lab, c) not in programs:
                missing.append(f"{lab}:{c}")
                continue
            v["S"][cond], v["X"][cond] = bool(r["correct"]), bool(r["exec_ok"])
            v["id"][cond], v["id_method"][cond] = program_identity(programs[(lab, c)])
            v["loc"][cond] = locs[(lab, c)]
        frame[c] = v
    if missing:
        raise AnalysisError(f"{len(missing)} (label, case) without a result row or a final program: {missing[:8]}")
    return frame, m, aset


def cmd_sample(a):
    root = a.root or ROOT
    frame, m, aset = load_frame(a.registry, a.set, a.model, root, a.allow_pending)
    s = draw_sample(frame, a.seed)
    N = s["N"]
    acc = {c: sum(frame[i]["S"][c] for i in frame) / N for c in CONDS}
    for r in s["selected"]:
        f = frame[r["case_id"]]
        r["conditions"] = {c: {"S": f["S"][c], "X": f["X"][c], "identity": f["id"][c], "id_method": f["id_method"][c],
                               "loc": f["loc"][c]} for c in CONDS}
    doc = {"schema": SAMPLE_SCHEMA, "data": m.label, "seed": a.seed, "model": a.model, "labels": LABELS,
           "frame": {"set": aset["name"], "sha256": aset["sha256"], "N": N,
                     "by_benchmark": {b: len(v) for b, v in aset["by_benchmark"].items()}},
           "python": sys.version.split()[0], "identity": "tokens without comments, docstrings and layout (plan 3.1)",
           "accuracy": acc, "delta_C3L_C3E": acc["C3L"] - acc["C3E"],
           "delta_C3L_C0": acc["C3L"] - acc["C0"], "delta_C3E_C0": acc["C3E"] - acc["C0"],
           "N_D": s["N_D"], "census_D": s["census_D"], "D": s["D"], "strata": s["strata"],
           "selected": s["selected"], "digest": s["digest"],
           "inputs": {k: m.header[k] for k in ("registry", "runs", "freeze_gate")}}
    out = a.out
    reg_path = resolve(a.registry, root)
    if a.register and "measurement_sample" in json.load(open(reg_path, encoding="utf-8")) and not a.replace:
        raise AnalysisError("the run registry already holds a measurement sample; it is drawn once")
    write_json(out, doc)
    fallback = sum(1 for v in frame.values() for c in CONDS if v["id_method"][c] == "fallback")
    print(f"[sample] {m.label} frame {aset['name']} N={N}  N_D={s['N_D']} ({'census' if s['census_D'] else 'sampled'})"
          f"  selected {len(s['selected'])}  identity fallbacks {fallback}  digest {s['digest'][:16]}")
    for st in s["strata"]:
        print(f"  part {st['part']} {st['stratum']}: N_h={st['N_h']} n_h={st['n_h']}")
    print("  ids:", " ".join(f"{r['problem_id']}={r['case_id']}" for r in s["selected"]))
    if a.register:
        reg = json.load(open(reg_path, encoding="utf-8"))
        reg["measurement_sample"] = {"file": rel(out, root), "sha256": sha256_file(out), "digest": s["digest"],
                                     "seed": a.seed, "N": N, "N_D": s["N_D"], "census_D": s["census_D"],
                                     "strata": [{k: st[k] for k in ("part", "stratum", "N_h", "n_h")}
                                                for st in s["strata"]],
                                     "selected": sorted(r["case_id"] for r in s["selected"])}
        write_json(reg_path, reg)
        print(f"[sample] registered in {rel(reg_path, root)}")
    print("wrote", rel(out, root))
    return 0


# ------------------------------------------------------------------ display normalization (plan 5)


def _char_col(line, byte_col):
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def _docstring_nodes(tree):
    out = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if isinstance(body, list):
                for st in body:
                    if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
                        out.append((node, field, st))
    return out


def _masked(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(MASK_RE.search(node.value))
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.Constant) and isinstance(v.value, str) and MASK_RE.search(v.value)
                   for v in node.values)
    return False


class _Canon(ast.NodeTransformer):
    """The AST a display must keep: docstrings removed (an emptied body becomes `pass`), masked strings -> MASK."""

    def generic_visit(self, node):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if isinstance(body, list) and body and all(isinstance(s, ast.stmt) for s in body):
                kept = [s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                                                and isinstance(s.value.value, str))]
                if not kept and not isinstance(node, ast.Module):
                    kept = [ast.Pass()]
                setattr(node, field, kept)
        super().generic_visit(node)
        return node

    def visit_Constant(self, node):
        return ast.Constant(value="[MASKED]") if _masked(node) else node

    def visit_JoinedStr(self, node):
        return ast.Constant(value="[MASKED]") if _masked(node) else self.generic_visit(node)


def canon_dump(code):
    return ast.dump(_Canon().visit(ast.parse(code)), include_attributes=False)


def _tidy(lines):
    out, blank = [], 0
    for ln in lines:
        ln = ln.rstrip()
        if not ln:
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(ln)
    while out and not out[0]:
        out.pop(0)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out) + "\n"


def display_program(code):
    """-> (text, flags). Comments and docstrings removed, matching string literals masked, blank lines and trailing
    whitespace normalized, nothing else changed; the result must have the original's AST up to those changes.
    A program that does not parse only loses its comments (flag unparsable)."""
    code = code.replace("\r\n", "\n")
    lines = code.split("\n")
    edits = {}                                  # line index -> [(start char, end char, replacement)]
    drop = set()
    toks, tok_ok = [], True
    try:
        for t in tokenize.generate_tokens(io.StringIO(code).readline):
            toks.append(t)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        tok_ok = False                          # comments found before the failure are still removed
    for t in toks:
        if t.type == tokenize.COMMENT:
            edits.setdefault(t.start[0] - 1, []).append((t.start[1], len(lines[t.start[0] - 1]), ""))
    last = toks[-1].end[0] if toks else 0
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = None
    if tree is None:
        if not tok_ok:                          # past the failure point only whole '#' lines can be told apart
            drop.update(i for i, ln in enumerate(lines) if i >= last and ln.lstrip().startswith("#"))
        return _tidy(_apply(lines, edits, drop)), ["unparsable"]
    doc_ids = set()
    for node, field, st in _docstring_nodes(tree):
        doc_ids.add(id(st.value))
        body = getattr(node, field)
        only = all(s is st or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                               and isinstance(s.value.value, str)) for s in body)
        a, b = st.lineno - 1, st.end_lineno - 1
        sc, ec = _char_col(lines[a], st.col_offset), _char_col(lines[b], st.end_col_offset)
        if only and not isinstance(node, ast.Module) and st is body[0]:
            if a == b:
                edits.setdefault(a, []).append((sc, ec, "pass"))
            else:
                edits.setdefault(a, []).append((sc, len(lines[a]), "pass" + lines[b][ec:]))
                drop.update(range(a + 1, b + 1))
        elif lines[a][:sc].strip() or lines[b][ec:].strip():
            raise AnalysisError("a string statement shares its line with other code; normalize this program by hand")
        else:
            drop.update(range(a, b + 1))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Constant, ast.JoinedStr)) and id(node) not in doc_ids and _masked(node):
            if isinstance(node, ast.Constant) and any(id(node) in [id(v) for v in getattr(p, "values", [])]
                                                      for p in ast.walk(tree) if isinstance(p, ast.JoinedStr)):
                continue                        # a part of an f-string: the whole f-string is masked
            a, b = node.lineno - 1, node.end_lineno - 1
            sc, ec = _char_col(lines[a], node.col_offset), _char_col(lines[b], node.end_col_offset)
            if a == b:
                edits.setdefault(a, []).append((sc, ec, MASK))
            else:
                edits.setdefault(a, []).append((sc, len(lines[a]), MASK + lines[b][ec:]))
                drop.update(range(a + 1, b + 1))
    text = _tidy(_apply(lines, edits, drop))
    try:
        same = canon_dump(text) == canon_dump(code)
    except SyntaxError:
        same = False
    if not same:
        raise AnalysisError("display normalization changed the program's syntax tree")
    return text, []


def _apply(lines, edits, drop):
    out = []
    for i, ln in enumerate(lines):
        if i in drop:
            continue
        for s, e, rep in sorted(edits.get(i, []), reverse=True):
            ln = ln[:s] + rep + ln[e:]
        if i in edits and not ln.strip() and all(rep == "" for _, _, rep in edits[i]):
            continue                            # a comment-only line
        out.append(ln)
    return out


# ------------------------------------------------------------------ export


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


BOOKLET_CSS = """body{font-family:Arial,Helvetica,sans-serif;max-width:60em;margin:2em auto;padding:0 1em;color:#111}
h1{font-size:1.4em}h2{margin-top:2.5em;border-top:2px solid #444;padding-top:.6em}
.stmt{white-space:pre-wrap;background:#f6f6f6;padding:.8em;border-left:4px solid #888}
pre{background:#fbfbf2;border:1px solid #ccc;padding:.8em;overflow-x:auto;font-size:.9em;line-height:1.35}
nav a{margin-right:.6em}@media print{h2{page-break-before:always}}"""


def cmd_export(a):
    root = a.root or ROOT
    doc = json.load(open(a.sample, encoding="utf-8"))
    if doc.get("schema") != SAMPLE_SCHEMA:
        raise AnalysisError("not a measurement sample file")
    from orgene import freeze as FZ
    sealed = doc["data"] != "DEV"
    if sealed:
        try:
            gate = FZ.check_gate(root)
        except FZ.GateRefused as x:
            raise AnalysisError(f"export of a {doc['data']} sample: {x}") from None
    else:
        gate = None
    cases = {}
    for b in BENCH_ORDER:
        p = resolve(f"data/cases/{b}.jsonl", root)
        for r in read_jsonl(p):
            if not r.get("_header"):
                cases[r["case_id"]] = r
    finals = {}
    problems, key_problems = [], []
    flags_n = {"unparsable": 0, "display_merged": 0}
    for r in sorted(doc["selected"], key=lambda r: r["problem_id"]):
        cid = r["case_id"]
        stmt = cases[cid]["text"]
        groups = {}                             # display text -> {identities, conditions, flags}
        for c in CONDS:
            info = r["conditions"][c]
            if info["identity"] == NO_PROGRAM:
                continue
            loc = info["loc"]
            if loc["file"] not in finals:
                finals[loc["file"]] = read_jsonl(resolve(loc["file"], root))
            fr = finals[loc["file"]][loc["row"]]
            if fr["case_id"] != cid or program_identity(fr.get("code"))[0] != info["identity"]:
                raise AnalysisError(f"{r['problem_id']}: the final program of {c} changed since the sample was drawn")
            text, fl = display_program(fr["code"])
            g = groups.setdefault(text, {"identities": [], "conditions": [], "flags": set()})
            if info["identity"] not in g["identities"]:
                g["identities"].append(info["identity"])
            g["conditions"].append(c)
            g["flags"].update(fl)
        progs = sorted(groups.items(), key=lambda kv: min(h(f"{doc['seed']}:program:{cid}:{i}")
                                                          for i in kv[1]["identities"]))
        plist, kprogs = [], []
        for j, (text, g) in enumerate(progs):
            pid = f"{r['problem_id']}-{'ABCDEFG'[j]}"
            fl = sorted(g["flags"] | ({"display_merged"} if len(g["identities"]) > 1 else set()))
            for f in fl:
                if f in flags_n:
                    flags_n[f] += 1
            plist.append((pid, text))
            kprogs.append({"program_id": pid, "conditions": g["conditions"], "identities": g["identities"],
                           "display_sha256": sha256_text(text), "flags": fl})
        problems.append((r["problem_id"], stmt, plist))
        cond_map = {}
        for c in CONDS:
            info = r["conditions"][c]
            pid = next((p["program_id"] for p in kprogs if c in p["conditions"]), None)
            cond_map[c] = {"program_id": pid, "S": info["S"], "X": info["X"], "identity": info["identity"]}
        key_problems.append({"problem_id": r["problem_id"], "case_id": cid, "benchmark": r["benchmark"],
                             "part": r["part"], "stratum": r["stratum"], "weight": r["weight"], "in_D": r["in_D"],
                             "programs": kprogs, "conditions": cond_map})
    os.makedirs(a.out, exist_ok=True)
    html = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Measurement check booklet</title>",
            f"<style>{BOOKLET_CSS}</style></head><body><h1>Measurement check: problems and programs</h1>",
            "<p>Judge each program against the statement shown above it, following the reviewer guide. "
            "Program IDs match the workbook.</p><nav>"]
    html += [f"<a href='#{p}'>{p}</a>" for p, _, _ in problems]
    html.append("</nav>")
    for pid, stmt, plist in problems:
        html.append(f"<h2 id='{pid}'>{pid}</h2><div class='stmt'>{_esc(stmt)}</div>")
        for prid, text in plist:
            html.append(f"<h3 id='{prid}'>Program {prid}</h3><pre><code>{_esc(text)}</code></pre>")
    html.append("</body></html>\n")
    booklet = os.path.join(a.out, "booklet.html")
    write_text(booklet, "\n".join(html))
    items = {"schema": ITEMS_SCHEMA, "problems": [{"problem_id": p, "programs": [x for x, _ in pl]}
                                                  for p, _, pl in problems]}
    key = {"schema": KEY_SCHEMA, "data": doc["data"], "seed": doc["seed"], "model": doc["model"],
           "sample": {"file": os.path.basename(a.sample), "sha256": sha256_file(a.sample), "digest": doc["digest"]},
           "N": doc["frame"]["N"], "N_D": doc["N_D"], "census_D": doc["census_D"], "strata": doc["strata"],
           "accuracy": doc["accuracy"], "delta_C3L_C3E": doc["delta_C3L_C3E"], "delta_C3L_C0": doc["delta_C3L_C0"],
           "delta_C3E_C0": doc["delta_C3E_C0"], "problems": key_problems, "freeze_gate": gate}
    write_json(os.path.join(a.out, "items.json"), items)
    write_json(os.path.join(a.out, "key.json"), key)
    files = {f: sha256_file(os.path.join(a.out, f)) for f in ("booklet.html", "items.json", "key.json")}
    export_id = h(json.dumps(files, sort_keys=True))[:12]
    man = {"schema": "orgene.r1.measurement_check.export.v1", "export_id": export_id, "files": files,
           "n_problems": len(problems), "n_programs": sum(len(pl) for _, _, pl in problems)}
    write_json(os.path.join(a.out, "export_manifest.json"), man)
    print(f"[export] {doc['data']}: {man['n_problems']} problems, {man['n_programs']} programs, "
          f"unparsable {flags_n['unparsable']}, merged on display {flags_n['display_merged']}, export_id {export_id}")
    return 0


# ------------------------------------------------------------------ workbooks (openpyxl)


def _load_export(d):
    man = json.load(open(os.path.join(d, "export_manifest.json"), encoding="utf-8"))
    items = json.load(open(os.path.join(d, "items.json"), encoding="utf-8"))
    for f, s in man["files"].items():
        p = os.path.join(d, f)
        if os.path.exists(p) and sha256_file(p) != s:
            raise AnalysisError(f"{f} does not match the export manifest")
    return man, items


def _set_meta(wb, role, rater, man):
    ws = wb["meta"]
    vals = {"file_role": role, "rater_id": rater, "export_id": man["export_id"],
            "booklet_sha256": man["files"]["booklet.html"], "n_problems": man["n_problems"],
            "n_programs": man["n_programs"]}
    for row in ws.iter_rows(min_row=2):
        if row[0].value in vals:
            row[1].value = vals[row[0].value]


def _keep(wb, sheets):
    for ws in list(wb.worksheets):
        if ws.title not in sheets:
            wb.remove(ws)


def cmd_workbooks(a):
    from openpyxl import load_workbook
    man, items = _load_export(a.export)
    rows = [(p["problem_id"], pid) for p in items["problems"] for pid in p["programs"]]
    if len(rows) > 200:
        raise AnalysisError("the template carries validation for 200 rows")
    for rater in ("R1", "R2"):
        wb = load_workbook(a.template)
        if a.step == 1:
            _keep(wb, ("README", "judgments", "example", "meta", "lists"))
            ws = wb["judgments"]
            for i, (p, pid) in enumerate(rows, FIRST_ROW):
                ws.cell(i, 1).value, ws.cell(i, 2).value = p, pid
            role, name = "judgments", f"judgments_{rater}.xlsx"
        else:
            _keep(wb, ("README", "gene_review", "meta", "lists"))
            role, name = "gene_review", f"gene_review_{rater}.xlsx"
        _set_meta(wb, role, rater, man)
        wb.save(os.path.join(a.out or a.export, name))
        print("wrote", name)
    return 0


def _code(v):
    if v is None:
        return None
    s = str(v).strip()
    return s.split()[0] if s else None


def read_judgments(path, items, rater):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    meta = {r[0]: r[1] for r in wb["meta"].iter_rows(min_row=2, values_only=True) if r[0]}
    if meta.get("schema") != WORKBOOK_SCHEMA or meta.get("file_role") != "judgments":
        raise AnalysisError(f"{os.path.basename(path)}: not a judgments workbook of {WORKBOOK_SCHEMA}")
    ws = wb["judgments"]
    keys = [c.value for c in ws[1]]
    want = {pid for p in items["problems"] for pid in p["programs"]}
    out, problems = {}, []
    for row in ws.iter_rows(min_row=FIRST_ROW, values_only=True):
        r = dict(zip(keys, row))
        pid = r.get("program_id")
        if not pid:
            continue
        if pid not in want:
            problems.append(f"{pid}: not in the export")
            continue
        j = {k: _code(r.get(k)) for k in ASPECTS + ("overall", "error_category")}
        j["notes"] = (r.get("notes") or "").strip() if isinstance(r.get("notes"), str) else ""
        if j["overall"] not in JUDGMENTS or any(j[k] not in JUDGMENTS for k in ASPECTS):
            problems.append(f"{pid}: judgment missing or outside the list")
        elif j["overall"] == "incorrect" and j["error_category"] not in CATEGORIES:
            problems.append(f"{pid}: incorrect without a valid error category")
        elif j["overall"] == "cannot_judge" and not j["notes"]:
            problems.append(f"{pid}: cannot_judge without a note")
        out[pid] = j
    missing = sorted(want - set(out))
    if missing or problems:
        raise AnalysisError(f"{rater} workbook: {len(missing)} program(s) not judged {missing[:6]}; "
                            + "; ".join(problems[:6]))
    return out


def disagreements(j1, j2):
    out = []
    for pid in sorted(j1):
        a, b = j1[pid], j2[pid]
        if a["overall"] != b["overall"]:
            out.append((pid, "overall_differs"))
        elif a["overall"] == "incorrect" and a["error_category"] != b["error_category"]:
            out.append((pid, "category_differs"))
    return out


def cmd_consensus(a):
    from openpyxl import load_workbook
    man, items = _load_export(a.export)
    j1, j2 = read_judgments(a.r1, items, "R1"), read_judgments(a.r2, items, "R2")
    dis = disagreements(j1, j2)
    wb = load_workbook(a.template)
    _keep(wb, ("README", "consensus", "meta", "lists"))
    ws = wb["consensus"]
    for i, (pid, why) in enumerate(dis, FIRST_ROW):
        vals = [pid.split("-")[0], pid, why, j1[pid]["overall"], j2[pid]["overall"], j1[pid]["error_category"],
                j2[pid]["error_category"], j1[pid]["notes"], j2[pid]["notes"]]
        for col, v in enumerate(vals, 1):
            ws.cell(i, col).value = v
    _set_meta(wb, "consensus", "R1+R2", man)
    out = a.out or os.path.join(a.export, "consensus.xlsx")
    wb.save(out)
    print(f"[consensus] {len(dis)} program(s) listed "
          f"({sum(w == 'overall_differs' for _, w in dis)} overall, {sum(w == 'category_differs' for _, w in dis)} "
          f"category); wrote {os.path.basename(out)}")
    return 0


def read_consensus(path, listed):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    ws = wb["consensus"]
    keys = [c.value for c in ws[1]]
    out = {}
    for row in ws.iter_rows(min_row=FIRST_ROW, values_only=True):
        r = dict(zip(keys, row))
        if not r.get("program_id"):
            continue
        fo, fc = _code(r.get("final_overall")), _code(r.get("final_error_category"))
        if fo not in JUDGMENTS + ("unresolved",):
            raise AnalysisError(f"consensus {r['program_id']}: final_overall missing or outside the list")
        if fo == "incorrect" and fc not in CATEGORIES:
            raise AnalysisError(f"consensus {r['program_id']}: incorrect without a final category")
        out[r["program_id"]] = (fo, fc)
    if set(out) != set(listed):
        raise AnalysisError(f"consensus file lists {sorted(set(out) ^ set(listed))[:6]} unlike the disagreement list")
    return out


# ------------------------------------------------------------------ statistics


def cohen_kappa(pairs, cats):
    n = len(pairs)
    if n == 0:
        return None
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in cats)
    return None if pe == 1 else (po - pe) / (1 - pe)


def hyper_cdf(m, N, K, n):
    """P(Y <= m), Y ~ hypergeometric(population N, K marked, n drawn)."""
    tot = math.comb(N, n)
    return sum(math.comb(K, y) * math.comb(N - K, n - y) for y in range(0, m + 1)) / tot


def k_upper(m, N_D, n_D, alpha=0.025):
    """Largest K in {m, ..., N_D - n_D + m} with P(Y <= m) >= alpha (plan 9.2)."""
    best = m
    for K in range(m, N_D - n_D + m + 1):
        if hyper_cdf(m, N_D, K, n_D) >= alpha:
            best = K
    return best


def cp_interval(x, n, level=0.95):
    """Clopper-Pearson at non-integer counts (Beta quantiles)."""
    from scipy.stats import beta
    if n <= 0:
        return (None, None)
    al = (1 - level) / 2
    lo = 0.0 if x <= 0 else float(beta.ppf(al, x, n - x + 1))
    hi = 1.0 if x >= n else float(beta.ppf(1 - al, x + 1, n - x))
    return (lo, hi)


def weighted_rate(units):
    """units: [(weight, numerator bool)] over the denominator -> rate, n_eff and the Korn-Graubard interval."""
    sw = sum(w for w, _ in units)
    if sw == 0:
        return {"rate": None, "n": 0, "n_eff": 0, "ci": [None, None]}
    p = sum(w for w, x in units if x) / sw
    neff = sw ** 2 / sum(w * w for w, _ in units)
    lo, hi = cp_interval(p * neff, neff)
    return {"rate": p, "n": len(units), "n_eff": neff, "ci": [lo, hi], "weighted_den": sw}


def census_bounds(delta, N, ds):
    """ds: [(d or None, d_min, d_max)] over D (plan 9.1)."""
    res = sum(d for d, _, _ in ds if d is not None)
    lo = res + sum(a for d, a, _ in ds if d is None)
    hi = res + sum(b for d, _, b in ds if d is None)
    return {"point": delta + res / N, "L": delta + lo / N, "U": delta + hi / N}


def sample_bounds(delta, N, N_D, judged):
    """judged: [(weight, d)] over the judged problems of D without NA (plan 9.2)."""
    n_D = len(judged)
    mm = sum(max(-d, 0) for _, d in judged)
    mp = sum(max(d, 0) for _, d in judged)
    km, kp = k_upper(mm, N_D, n_D), k_upper(mp, N_D, n_D)
    return {"point": delta + sum(w * d for w, d in judged) / N, "L": delta - km / N, "U": delta + kp / N,
            "n_D": n_D, "m_minus": mm, "m_plus": mp, "K_minus": km, "K_plus": kp,
            "double_units": sum(1 for _, d in judged if abs(d) == 2)}


# ------------------------------------------------------------------ analyze


def final_labels(j1, j2, cons):
    out = {}
    for pid in j1:
        a, b = j1[pid], j2[pid]
        if pid in cons:
            fo, fc = cons[pid]
        else:
            fo, fc = a["overall"], a["error_category"] if a["overall"] == "incorrect" else None
        out[pid] = {"overall": fo, "category": fc if fo == "incorrect" else None,
                    "H": {"correct": 1, "incorrect": 0}.get(fo)}           # cannot_judge / unresolved -> NA
    return out


def _T(cinfo, labels):
    if cinfo["program_id"] is None or not cinfo["X"]:
        return 0
    return labels[cinfo["program_id"]]["H"]


def kappa_bootstrap(problems, j1, j2, field, cats, n_boot=10000, seed=1):
    by = {}
    for p in problems:
        by.setdefault((p["part"], p["stratum"]), []).append(p)
    rng = random.Random(seed)
    vals = []
    for _ in range(n_boot):
        pairs = []
        for grp in by.values():
            for _ in range(len(grp)):
                p = grp[rng.randrange(len(grp))]
                pairs += [(j1[x["program_id"]][field], j2[x["program_id"]][field]) for x in p["programs"]]
        k = cohen_kappa(pairs, cats)
        if k is not None:
            vals.append(k)
    vals.sort()
    if not vals:
        return [None, None]
    return [vals[int(0.025 * (len(vals) - 1))], vals[int(math.ceil(0.975 * (len(vals) - 1)))]]


def analyze(key, j1, j2, cons, n_boot=10000):
    probs = key["problems"]
    allp = [x["program_id"] for p in probs for x in p["programs"]]
    pairs = [(j1[x]["overall"], j2[x]["overall"]) for x in allp]
    agree = {"n_programs": len(allp), "kappa": cohen_kappa(pairs, JUDGMENTS),
             "kappa_ci": kappa_bootstrap(probs, j1, j2, "overall", JUDGMENTS, n_boot),
             "percent_agreement": sum(a == b for a, b in pairs) / len(pairs) if pairs else None,
             "kappa_aspects": {f: cohen_kappa([(j1[x][f], j2[x][f]) for x in allp], JUDGMENTS) for f in ASPECTS},
             "kappa_binary_excl_cannot_judge": cohen_kappa(
                 [(j1[x]["overall"], j2[x]["overall"]) for x in allp
                  if "cannot_judge" not in (j1[x]["overall"], j2[x]["overall"])], ("correct", "incorrect")),
             "reference_value": 0.60}
    labels = final_labels(j1, j2, cons)
    resolution = {"listed": len(cons), "unresolved": sum(1 for v in cons.values() if v[0] == "unresolved"),
                  "NA": sum(1 for v in labels.values() if v["H"] is None)}
    N = key["N"]
    rows = []                                   # (problem, cond, w, S, X, T)
    for p in probs:
        for c in CONDS:
            ci = p["conditions"][c]
            rows.append((p, c, p["weight"], ci["S"], ci["X"], _T(ci, labels)))

    def rates(sel, weighted=True):
        fp = [((w if weighted else 1), T == 0) for p, c, w, S, X, T in sel if S and T is not None]
        fn = [((w if weighted else 1), T == 1) for p, c, w, S, X, T in sel if not S and T is not None]
        fnx = [((w if weighted else 1), T == 1) for p, c, w, S, X, T in sel if not S and X and T is not None]
        return {"FP": weighted_rate(fp), "FN": weighted_rate(fn), "FN_executed": weighted_rate(fnx)}

    per_cond = {c: {"weighted": rates([r for r in rows if r[1] == c]),
                    "unweighted": rates([r for r in rows if r[1] == c], False),
                    "part1": rates([r for r in rows if r[1] == c and r[0]["part"] == 1]),
                    "part2": rates([r for r in rows if r[1] == c and r[0]["part"] == 2]),
                    "by_benchmark": {b: rates([r for r in rows if r[1] == c and r[0]["benchmark"] == b])
                                     for b in BENCH_ORDER}} for c in CONDS}
    units, mixed = {}, 0                        # overall: distinct programs, once per (verdict, executed)
    for p, c, w, S, X, T in rows:
        pid = p["conditions"][c]["program_id"]
        k = (pid or f"{p['problem_id']}:none:{c}", S, X)
        units.setdefault(k, (p, c, w, S, X, T))
    seen = {}
    for (pid, S, X) in units:
        seen.setdefault(pid, set()).add((S, X))
    mixed = sum(1 for v in seen.values() if len(v) > 1)
    overall = {"weighted": rates(list(units.values())), "unweighted": rates(list(units.values()), False),
               "programs_with_differing_verdicts": mixed}
    not_run_correct = sum(1 for p in probs for x in p["programs"] if labels[x["program_id"]]["H"] == 1
                          and not any(p["conditions"][c]["X"] for c in x["conditions"]))
    corrected = {c: key["accuracy"][c] + sum(w * (T - S) for p, cc, w, S, X, T in rows if cc == c and T is not None) / N
                 for c in CONDS}

    def d_of(p, a, b, tl=None, te=None):
        A, B = p["conditions"][a], p["conditions"][b]
        Ta = _T(A, labels) if tl is None else tl
        Tb = _T(B, labels) if te is None else te
        if Ta is None or Tb is None:
            return None
        return (Ta - A["S"]) - (Tb - B["S"])

    def possible(ci):
        if ci["program_id"] is None or not ci["X"]:
            return [0]
        hv = labels[ci["program_id"]]["H"]
        return [0, 1] if hv is None else [hv]

    delta = key["delta_C3L_C3E"]
    Dp = [p for p in probs if p["in_D"]]
    if key["census_D"]:
        ds = []
        for p in Dp:
            d = d_of(p, "C3L", "C3E")
            opts = [(tl - p["conditions"]["C3L"]["S"]) - (te - p["conditions"]["C3E"]["S"])
                    for tl in possible(p["conditions"]["C3L"]) for te in possible(p["conditions"]["C3E"])]
            ds.append((d, min(opts), max(opts)))
        main = dict(census_bounds(delta, N, ds), design="census", n_D=len(Dp),
                    n_NA=sum(1 for d, _, _ in ds if d is None))
        main["worst_case_NA"] = {"L": main["L"], "U": main["U"]}
    else:
        judged = [(p["weight"], d_of(p, "C3L", "C3E")) for p in Dp if d_of(p, "C3L", "C3E") is not None]
        main = dict(sample_bounds(delta, N, key["N_D"], judged), design="sample",
                    n_NA=sum(1 for p in Dp if d_of(p, "C3L", "C3E") is None))
        lo = judged + [(p["weight"], (0 - p["conditions"]["C3L"]["S"]) - (1 - p["conditions"]["C3E"]["S"]))
                       for p in Dp if d_of(p, "C3L", "C3E") is None]
        hi = judged + [(p["weight"], (1 - p["conditions"]["C3L"]["S"]) - (0 - p["conditions"]["C3E"]["S"]))
                       for p in Dp if d_of(p, "C3L", "C3E") is None]
        main["worst_case_NA"] = {"L": sample_bounds(delta, N, key["N_D"], lo)["L"],
                                 "U": sample_bounds(delta, N, key["N_D"], hi)["U"]}
    main.update({"delta": delta, "N": N, "N_D": key["N_D"]})
    secondary = {}
    for a, b, dk in (("C3L", "C0", "delta_C3L_C0"), ("C3E", "C0", "delta_C3E_C0")):
        js = [(p["weight"], d_of(p, a, b)) for p in probs if d_of(p, a, b) is not None]
        secondary[f"{a}-{b}"] = {"delta": key[dk], "point": key[dk] + sum(w * d for w, d in js) / N}
    cats = {}
    for c in CONDS:
        tab = {k: {"n": 0, "weighted": 0.0} for k in CATEGORIES}
        for p in probs:
            pid = p["conditions"][c]["program_id"]
            if pid and labels[pid]["overall"] == "incorrect" and labels[pid]["category"] in tab:
                tab[labels[pid]["category"]]["n"] += 1
                tab[labels[pid]["category"]]["weighted"] += p["weight"]
        cats[c] = tab
    comp = {"N_D": key["N_D"], "census_D": key["census_D"], "strata": key["strata"], "n_problems": len(probs),
            "n_programs": len(allp),
            "programs_per_problem": {str(k): sum(1 for p in probs if len(p["programs"]) == k) for k in (0, 1, 2, 3)}}
    return {"schema": REPORT_SCHEMA, "data": key["data"], "composition": comp, "agreement": agree,
            "resolution": resolution, "rates": {"by_condition": per_cond, "overall": overall,
                                                "correct_but_not_run": not_run_correct},
            "corrected_accuracy": corrected, "accuracy": key["accuracy"], "main_effect_bounds": main,
            "secondary_point_estimates": secondary, "error_categories": cats,
            "labels": {pid: v for pid, v in sorted(labels.items())}}


def cmd_analyze(a):
    man, items = _load_export(a.export)
    key = json.load(open(os.path.join(a.export, "key.json"), encoding="utf-8"))
    j1, j2 = read_judgments(a.r1, items, "R1"), read_judgments(a.r2, items, "R2")
    listed = [pid for pid, _ in disagreements(j1, j2)]
    cons = read_consensus(a.consensus, listed) if listed else {}
    doc = analyze(key, j1, j2, cons, a.n_boot)
    doc["inputs"] = {"export_id": man["export_id"], "r1": sha256_file(a.r1), "r2": sha256_file(a.r2),
                     "consensus": sha256_file(a.consensus) if listed else None}
    write_json(a.out, doc)
    m = doc["main_effect_bounds"]
    print(f"[analyze] {doc['data']}: kappa {doc['agreement']['kappa']:.3f}; delta {100 * m['delta']:.1f} pp, "
          f"corrected {100 * m['point']:.1f} pp, [L, U] = [{100 * m['L']:.1f}, {100 * m['U']:.1f}] ({m['design']})")
    return 0


# ------------------------------------------------------------------ CLI


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--registry", default="experiments/run_registry.json")
    s.add_argument("--set", default="main")
    s.add_argument("--model", default="qwen3:8b")
    s.add_argument("--seed", type=int, default=SEED)
    s.add_argument("--allow-pending", action="store_true", help="dev only")
    s.add_argument("--register", action="store_true", help="add the sample to the run registry")
    s.add_argument("--replace", action="store_true", help=argparse.SUPPRESS)
    s.add_argument("--root", default=None)
    s.add_argument("--out", required=True)
    e = sub.add_parser("export")
    e.add_argument("--sample", required=True)
    e.add_argument("--root", default=None)
    e.add_argument("--out", required=True)
    w = sub.add_parser("workbooks")
    w.add_argument("--template", required=True)
    w.add_argument("--export", required=True)
    w.add_argument("--step", type=int, choices=(1, 3), default=1)
    w.add_argument("--out", default=None)
    c = sub.add_parser("consensus")
    c.add_argument("--template", required=True)
    c.add_argument("--export", required=True)
    c.add_argument("--r1", required=True)
    c.add_argument("--r2", required=True)
    c.add_argument("--out", default=None)
    z = sub.add_parser("analyze")
    z.add_argument("--export", required=True)
    z.add_argument("--r1", required=True)
    z.add_argument("--r2", required=True)
    z.add_argument("--consensus", required=True)
    z.add_argument("--n-boot", type=int, default=10000)
    z.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        return {"sample": cmd_sample, "export": cmd_export, "workbooks": cmd_workbooks, "consensus": cmd_consensus,
                "analyze": cmd_analyze}[a.cmd](a)
    except AnalysisError as x:
        print(f"[measurement_check] REFUSED: {x}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
