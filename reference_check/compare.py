#!/usr/bin/env python3
"""Compare the two blind re-derivation batches with each other and with the reference answers.

Run by the coordinator after both batches have returned (never by a re-derivation agent or a gene writer):

  python3 compare.py                       # all 16 groups must be complete
  python3 compare.py --allow-incomplete    # progress check; missing rows are routed to the queue as *_MISSING
  options: --results-root DIR (default stage1/annotation_agent), --hidden DIR (default stage1/annotation_agent_hidden),
           --out DIR (default <hidden>/comparison), --model A=<model id> --model B=<model id>,
           --rerun (re-execute every main model script and compare its FINAL_OBJECTIVE; runs agent-written code)

Reads   <results-root>/batch_{A,B}/<group>/results.jsonl and models/; <hidden>/references.json
Writes  <out>/comparison.json   per-case detail incl. reference and re-derived values (stays in the hidden directory)
        <out>/routing.csv       all 125 cases: scope, route and reason codes only (no values, no text)
        <out>/summary.json      counts and agreement statistics only
Prints  counts and case ids only (no statement text, no values).

Rules (fixed 2026-09-29 by the main session, before any re-derivation result existed):
  tolerance: E13 primary tier, |x - ref| <= max(1e-4, 1e-4*|ref|); A vs B: same rule in either direction.
  All 125 cases are compared with their reference.
  reference check, sampled scope (the 66 cases of reference_check_sample.json):
    AUTO_CORRECT <=> for both batches: row present and valid, status Optimal, objective within tolerance of the
                     reference, issue NONE, confidence not LOW, printed FINAL_OBJECTIVE consistent with the reported
                     objective (and with --rerun: the re-run reproduces it).
    otherwise ADJUDICATE; reason codes say why. ROUNDED = the reference equals the batch value rounded/truncated to
    some precision (CORRECT_ROUNDED candidate); ALT_MATCH = the reference matches another reading, the integer-relaxed
    value or the asked quantity of that batch (AMBIGUOUS candidate).
  full screening, unsampled scope (the 59 IndustryOR cases outside the sample):
    SCREEN_FLAG <=> the two batches agree with each other (tolerance rule, or the same infeasible/unbounded status)
                    and neither batch's main value is within tolerance of the reference -> adjudicated ("全量筛查发现")
    otherwise SCREEN_KEEP: the original reference is kept; the case only enters the agreement statistics.
  type label (the 100 IndustryOR cases; main-session rule 2026-09-29: only nonlinear or uncertain cases go to the
  adjudicator):
    ADJUDICATE <=> either batch labels NL_LINEARIZABLE or NL_NOT_LINEARIZABLE (this covers every disagreement on
                   "nonlinear / linearisable"), or either type_confidence is LOW, or a row / its type fields are
                   missing or invalid.
    otherwise both labels are in LP/MILP/IP:
      AUTO              both labels equal
      AUTO_BY_REFERENCE labels differ and exactly one batch's objective matches the reference: that batch's label
      UNRESOLVED        labels differ and both or neither match: label LINEAR_UNRESOLVED (linear, class unresolved);
                        dropped only from type-stratified analyses, no effect on the analysis sets
  audit round 1: AUDIT = the first 10 AUTO_CORRECT reference checks and the first 10 automatically settled type labels
         (AUTO or AUTO_BY_REFERENCE) in the order of sha256(f"{seed}|{case_id}").
  audit round 2 (only for an audit whose round 1 overturns >= 1 case; decided after round 1 by make_adjudication.py
         --round2): the first 10 of the remaining eligible cases in the order of sha256(f"{seed2}|{case_id}"); the
         candidates are fixed here (audit.round2_candidates). No third round. Seeds in _common.py.
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

PY = "/opt/anaconda3/bin/python3"
REQUIRED = ("case_id", "status", "objective", "sense", "model_file", "output_file", "solver", "model_summary",
            "integrality_ambiguous", "issue", "confidence")
OPTIONAL = ("integer_relaxed_objective", "asked_value", "issue_note", "readings", "problem_type",
            "type_after_linearization", "type_rationale", "type_confidence", "notes")
FINAL_RE = re.compile(r"^FINAL_OBJECTIVE:\s*(.*?)\s*$")
STATUS_RE = re.compile(r"^STATUS:\s*(.*?)\s*$")


# ------------------------------------------------------------------ reading one batch

def parse_output(path):
    """(status, final objective or None, parsed?) from a saved script output."""
    st, fo, seen = None, None, False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = STATUS_RE.match(line)
            if m:
                st = m.group(1)
            m = FINAL_RE.match(line)
            if m:
                seen = True
                fo = C.num(m.group(1))
    return st, fo, seen


def consistency(reported, printed, seen):
    if not seen:
        return "unparsed"
    if reported is None and printed is None:
        return "consistent"
    if reported is None or printed is None:
        return "inconsistent"
    if abs(reported - printed) <= 1e-9 * max(1.0, abs(printed)):
        return "consistent"
    return "approx" if C.within(reported, printed) else "inconsistent"


def normalize(row, gdir, needs_type):
    """Validate one results.jsonl row. Problems name fields only (never their content)."""
    core, typ, warn = [], [], []
    unknown = sorted(k for k in row if k not in REQUIRED + OPTIONAL)
    if unknown:
        warn.append(f"unknown keys {[k[:30] for k in unknown]}")
    for k in REQUIRED:
        if k not in row:
            core.append(f"missing {k}")
    status = row.get("status")
    if status not in C.STATUSES:
        core.append("status outside the list")
    issue = row.get("issue")
    if issue not in C.ISSUES:
        core.append("issue outside the list")
    obj_raw = row.get("objective")
    obj = C.num(obj_raw)
    if obj_raw is not None and obj is None:
        core.append("objective is not a number")
    if isinstance(obj_raw, str):
        warn.append("objective given as a string")
    value = obj if status in C.VALUE_STATUSES else None
    if status in C.VALUE_STATUSES and obj is None and issue != "UNDERSPECIFIED":
        core.append(f"objective missing for status {status}")
    if status not in C.VALUE_STATUSES and obj is not None:
        core.append("objective given for a status without a value")
    if row.get("sense") not in ("max", "min"):
        core.append("sense must be max/min")
    if row.get("solver") not in C.SOLVERS:
        warn.append("solver outside the list")
    confidence = C.conf(row.get("confidence"))
    if confidence is None:
        core.append("confidence outside HIGH/MEDIUM/LOW")
    ia = row.get("integrality_ambiguous")
    if not isinstance(ia, bool):
        core.append("integrality_ambiguous must be true/false")
    relaxed = C.num(row.get("integer_relaxed_objective"))
    if ia is True and relaxed is None and status in C.VALUE_STATUSES:
        core.append("integer_relaxed_objective missing although integrality_ambiguous is true")
    if issue in ("AMBIGUOUS", "UNDERSPECIFIED") and not str(row.get("issue_note") or "").strip():
        core.append(f"issue_note missing for {issue}")
    readings = row.get("readings") or []
    if not isinstance(readings, list) or not all(isinstance(r, dict) for r in readings):
        core.append("readings must be a list of objects")
        readings = []
    if issue == "AMBIGUOUS" and len(readings) < 2:
        core.append("AMBIGUOUS needs at least 2 readings")
    alts = []
    if relaxed is not None:
        alts.append(("integer_relaxed", relaxed))
    asked = C.num(row.get("asked_value"))
    if asked is not None:
        alts.append(("asked_value", asked))
    for i, r in enumerate(readings, 1):
        v = C.num(r.get("objective"))
        if v is not None:
            alts.append((f"reading_{i}", v))
    files = {}
    for k in ("model_file", "output_file"):
        rel = row.get(k)
        ok = isinstance(rel, str) and rel.startswith("models/") and ".." not in rel and os.path.isfile(os.path.join(gdir, rel))
        files[k] = rel if ok else None
        if not ok and status != "TypeOnly":
            core.append(f"{k} missing or not under models/")
    out_check, printed_status = "missing", None
    if files["output_file"]:
        printed_status, printed, seen = parse_output(os.path.join(gdir, files["output_file"]))
        out_check = consistency(value if status in C.VALUE_STATUSES else None, printed, seen)
    ptype = row.get("problem_type")
    after = row.get("type_after_linearization")
    tconf = C.conf(row.get("type_confidence"))
    if needs_type:
        if ptype not in C.TYPE_LABELS:
            typ.append("problem_type outside the list")
        if ptype == "NL_LINEARIZABLE" and after not in C.POST_LIN:
            typ.append("NL_LINEARIZABLE needs type_after_linearization LP/MILP/IP")
        if ptype != "NL_LINEARIZABLE" and after not in (None, ""):
            typ.append("type_after_linearization given for a label other than NL_LINEARIZABLE")
        if not str(row.get("type_rationale") or "").strip():
            typ.append("type_rationale missing")
        if tconf is None:
            typ.append("type_confidence outside HIGH/MEDIUM/LOW")
    special = {"Infeasible": "infeasible", "Unbounded": "unbounded"}.get(status)
    return {
        "present": True, "status": status, "value": value, "special": special, "issue": issue,
        "confidence": confidence, "integrality_ambiguous": ia is True, "alts": alts,
        "type": ptype if ptype in C.TYPE_LABELS else None,
        "type_after_linearization": after if after in C.POST_LIN else None,
        "effective_type": C.effective_type(ptype, after), "type_confidence": tconf,
        "model_file": files["model_file"], "output_file": files["output_file"],
        "output_check": out_check, "printed_status": printed_status,
        "core_problems": core, "type_problems": typ, "warnings": warn,
    }


def read_batch(results_root, batch, groups, case_meta):
    rows, problems, groups_state = {}, [], {}
    for g, ids in groups.items():
        gdir = C.group_dir(results_root, batch, g)
        n_man, man_probs = C.verify_manifest(gdir) if os.path.isdir(gdir) else (0, ["group directory missing"])
        path = os.path.join(gdir, "results.jsonl")
        state = {"manifest_files": n_man, "manifest_problems": man_probs, "results_file": os.path.exists(path),
                 "n_lines": 0, "n_rows": 0}
        for mp in man_probs:
            problems.append(f"{g}: {mp}")
        if not os.path.exists(path):
            groups_state[g] = state
            continue
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                state["n_lines"] += 1
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    problems.append(f"{g} line {i}: not valid JSON")
                    continue
                cid = r.get("case_id") if isinstance(r, dict) else None
                if not (isinstance(cid, str) and C.CASE_ID_RE.match(cid)):
                    problems.append(f"{g} line {i}: case_id missing or malformed (not shown)")
                    continue
                if cid not in ids:
                    problems.append(f"{g} line {i}: {cid} is not in this group")
                    continue
                if cid in rows:
                    problems.append(f"{g}: {cid} appears more than once (first row kept)")
                    continue
                rows[cid] = normalize(r, gdir, case_meta[cid]["needs_type_label"])
                rows[cid]["group"] = g
                state["n_rows"] += 1
        groups_state[g] = state
    return rows, problems, groups_state


def rerun(results_root, batch, cid, n, timeout):
    gdir = C.group_dir(results_root, batch, n["group"])
    if not n.get("model_file"):
        return "no_script"
    try:
        p = subprocess.run([PY, n["model_file"]], cwd=gdir, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "timeout"
    printed, seen = None, False
    for line in p.stdout.splitlines():
        m = FINAL_RE.match(line)
        if m:
            seen, printed = True, C.num(m.group(1))
    if p.returncode != 0 and not seen:
        return "error"
    c = consistency(n["value"], printed, seen)
    return {"consistent": "reproduced", "approx": "reproduced_approx"}.get(c, "not_reproduced")


# ------------------------------------------------------------------ comparing

def missing():
    return {"present": False, "value": None, "special": None, "alts": [], "status": None, "issue": None,
            "confidence": None, "type": None, "effective_type": None, "type_confidence": None,
            "core_problems": ["no row"], "type_problems": ["no row"], "output_check": "missing"}


def vs_reference(n, ref_obj):
    if not n["present"]:
        return "MISSING", None
    v = n["value"]
    if v is None:
        return ("MISMATCH", n["special"]) if n["special"] else ("NO_VALUE", None)
    if C.within(v, ref_obj):
        return "MATCH", None
    rr = C.rounding_relation(v, ref_obj)
    if rr:
        return "ROUNDED", rr
    for label, alt in n["alts"]:
        if C.within(alt, ref_obj):
            return "ALT_MATCH", label
    return "MISMATCH", None


def ab_relation(a, b):
    if not (a["present"] and b["present"]):
        return "NA"
    if a["value"] is None and b["value"] is None:
        if a["special"] and a["special"] == b["special"]:
            return "AGREE"
        return "NA"
    if a["value"] is None or b["value"] is None:
        return "DISAGREE"
    return "AGREE" if C.same_value(a["value"], b["value"]) else "DISAGREE"


def ref_route(cid, na, nb, ref_obj, rerun_state):
    res = {}
    codes = []
    for X, n in (("A", na), ("B", nb)):
        r, detail = vs_reference(n, ref_obj)
        res[X] = {"result": r, "detail": detail, "tiers": C.tiers(n["value"], ref_obj) if n["value"] is not None else None,
                  "value_looks_like_rounded_reference": bool(n["value"] is not None and r != "MATCH"
                                                              and C.rounding_relation(ref_obj, n["value"]))}
        if not n["present"]:
            codes.append(f"{X}_MISSING")
            continue
        if n["core_problems"]:
            codes.append(f"{X}_INVALID")
        if r != "MATCH":
            codes.append(f"{X}_{r}")
        if n["status"] != "Optimal":
            codes.append(f"{X}_STATUS_{n['status']}")
        if n["issue"] in ("AMBIGUOUS", "UNDERSPECIFIED"):
            codes.append(f"{X}_{n['issue']}")
        if n["confidence"] == "LOW":
            codes.append(f"{X}_LOW_CONFIDENCE")
        if n["output_check"] not in ("consistent", "approx"):
            codes.append(f"{X}_OUTPUT_{n['output_check'].upper()}")
        rr = rerun_state.get(X)
        if rr is not None and rr not in ("reproduced", "reproduced_approx"):
            codes.append(f"{X}_RERUN_{rr.upper()}")
    ab = ab_relation(na, nb)
    if ab == "DISAGREE":
        codes.append("AB_DISAGREE")
    if ab == "AGREE" and res["A"]["result"] != "MATCH" and res["B"]["result"] != "MATCH":
        codes.append("AB_AGREE_BOTH_OFF_REFERENCE")
    route = "AUTO_CORRECT" if not codes else "ADJUDICATE"
    return route, sorted(set(codes)), res, ab


def type_route(na, nb, ra, rb):
    """-> (route, reason codes, automatic label or None). ra / rb: each batch's objective result vs the reference."""
    codes = []
    for X, n in (("A", na), ("B", nb)):
        if not n["present"]:
            codes.append(f"{X}_MISSING")
            continue
        if n["type_problems"] or n["type"] not in C.TYPE_LABELS:
            codes.append(f"{X}_TYPE_INVALID")
        if n["type"] in C.NL_LABELS:
            codes.append(f"{X}_{n['type']}")
        if n["type_confidence"] == "LOW":
            codes.append(f"{X}_TYPE_LOW_CONFIDENCE")
    if codes:
        if na["present"] and nb["present"] and na["type"] != nb["type"]:
            codes.append("TYPE_DISAGREE")
        return "ADJUDICATE", sorted(set(codes)), None
    if na["type"] == nb["type"]:
        return "AUTO", [], na["type"]
    ma, mb = ra == "MATCH", rb == "MATCH"
    if ma != mb:
        return "AUTO_BY_REFERENCE", ["TYPE_DISAGREE_LINEAR", "A_MATCHES_REFERENCE" if ma else "B_MATCHES_REFERENCE"], \
            (na["type"] if ma else nb["type"])
    return "UNRESOLVED", ["TYPE_DISAGREE_LINEAR", "BOTH_MATCH_REFERENCE" if ma else "NEITHER_MATCHES_REFERENCE"], \
        C.LINEAR_UNRESOLVED


def screen_category(res, ab):
    ra, rb = res["A"]["result"], res["B"]["result"]
    if "MISSING" in (ra, rb):
        return "incomplete"
    if ra == rb == "MATCH":
        return "both_match"
    if "MATCH" in (ra, rb):
        return "one_matches"
    if ab == "AGREE":
        return "both_off_and_agree"
    return "both_off_not_agreeing"


def counter(it):
    """Count table with string keys (None -> "none") so that the JSON dump can sort it."""
    return dict(collections.Counter("none" if x is None else str(x) for x in it))


def draw(ids, seed, n):
    return sorted(sorted(ids, key=lambda c: C.rank_hash(seed, c))[:n])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-root", default=C.PKG)
    ap.add_argument("--package", default=C.PKG, help=argparse.SUPPRESS)
    ap.add_argument("--hidden", default=C.HIDDEN_DEFAULT)
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", action="append", default=[], help="A=<model id> / B=<model id> (recorded only)")
    ap.add_argument("--allow-incomplete", action="store_true")
    ap.add_argument("--rerun", action="store_true")
    ap.add_argument("--rerun-timeout", type=int, default=900)
    a = ap.parse_args()
    out = a.out or os.path.join(a.hidden, "comparison")

    case_set = C.load_case_set(a.package)
    groups = C.load_groups(a.package)["groups"]
    refs = C.load_references(a.hidden)["cases"]
    meta = {e["case_id"]: e for e in case_set["cases"]}
    if set(meta) != set(refs):
        sys.exit("case_set.json and references.json disagree on the case ids")

    batches, problems, gstate = {}, {}, {}
    for b in C.BATCHES:
        batches[b], problems[b], gstate[b] = read_batch(a.results_root, b, groups[b], meta)
    n_missing = {b: len(set(meta) - set(batches[b])) for b in C.BATCHES}
    complete = not any(n_missing.values())
    if not complete and not a.allow_incomplete:
        for b in C.BATCHES:
            print(f"batch {b}: {len(batches[b])}/125 rows; groups without results.jsonl: "
                  f"{[g for g, s in gstate[b].items() if not s['results_file']]}")
        sys.exit("not all rows are in; rerun with --allow-incomplete for a progress check")

    rerun_state = collections.defaultdict(dict)
    if a.rerun:
        for b in C.BATCHES:
            for cid, n in sorted(batches[b].items()):
                rerun_state[cid][b] = rerun(a.results_root, b, cid, n, a.rerun_timeout)

    cases, routing = {}, []
    for cid in sorted(meta):
        m = meta[cid]
        na, nb = batches["A"].get(cid) or missing(), batches["B"].get(cid) or missing()
        ref = refs[cid]["reference"]
        entry = {"case_id": cid, "benchmark": m["benchmark"], "split": m["split"],
                 "needs_reference_check": m["needs_reference_check"], "needs_type_label": m["needs_type_label"],
                 "A": {k: v for k, v in na.items()}, "B": {k: v for k, v in nb.items()},
                 "ab_relation": ab_relation(na, nb), "rerun": rerun_state.get(cid, {}), "reference": ref}
        route, codes, res, ab = ref_route(cid, na, nb, ref["objective"], rerun_state.get(cid, {}))
        if m["needs_reference_check"]:
            scope = "sample"
        else:
            scope = "screening"
            flag = (ab == "AGREE" and res["A"]["result"] not in ("MATCH", "MISSING", "NO_VALUE")
                    and res["B"]["result"] not in ("MATCH", "MISSING", "NO_VALUE"))
            route = "SCREEN_FLAG" if flag else "SCREEN_KEEP"
            if flag:
                codes = ["SCREEN_AB_AGREE_BOTH_OFF_REFERENCE"] + [c for c in codes if c != "AB_AGREE_BOTH_OFF_REFERENCE"]
        entry["reference_check"] = {"scope": scope, "route": route, "reasons": codes, "per_batch": res,
                                    "category": screen_category(res, ab)}
        row = {"case_id": cid, "benchmark": m["benchmark"], "split": m["split"],
               "needs_reference_check": m["needs_reference_check"], "needs_type_label": m["needs_type_label"],
               "ref_scope": scope, "ref_route": route, "ref_reasons": ";".join(codes), "type_route": "",
               "type_reasons": ""}
        if m["needs_type_label"]:
            troute, tcodes, tlabel = type_route(na, nb, res["A"]["result"], res["B"]["result"])
            entry["type_label"] = {"route": troute, "auto_kind": troute, "reasons": tcodes, "auto_label": tlabel}
            row["type_route"], row["type_reasons"] = troute, ";".join(tcodes)
        cases[cid] = entry
        routing.append(row)

    auto_ref = [r["case_id"] for r in routing if r["ref_route"] == "AUTO_CORRECT"]
    auto_type = [r["case_id"] for r in routing if r["type_route"] in ("AUTO", "AUTO_BY_REFERENCE")]
    audit_ref = draw(auto_ref, C.REF_AUDIT_SEED, C.N_AUDIT)
    audit_type = draw(auto_type, C.TYPE_AUDIT_SEED, C.N_AUDIT)
    round2 = {"reference_check": draw([c for c in auto_ref if c not in audit_ref], C.REF_AUDIT_SEED_2, C.N_AUDIT),
              "type_label": draw([c for c in auto_type if c not in audit_type], C.TYPE_AUDIT_SEED_2, C.N_AUDIT)}
    for r in routing:
        if r["case_id"] in audit_ref:
            r["ref_route"] = "AUDIT"
        if r["case_id"] in audit_type:
            r["type_route"] = "AUDIT"
        r["for_adjudicator"] = "Y" if (r["ref_route"] in ("ADJUDICATE", "AUDIT", "SCREEN_FLAG")
                                       or r["type_route"] in ("ADJUDICATE", "AUDIT")) else "N"
        cases[r["case_id"]]["routing"] = {k: r[k] for k in ("ref_scope", "ref_route", "type_route", "for_adjudicator")}

    # ---------------- statistics (counts only)
    smp_rows = [r for r in routing if r["ref_scope"] == "sample"]
    scr_rows = [r for r in routing if r["ref_scope"] == "screening"]
    typ_rows = [r for r in routing if r["needs_type_label"]]

    def vs_counts(rows, b):
        return counter((cases[r["case_id"]]["reference_check"]["per_batch"][b]["result"] for r in rows))

    def rates(rows):
        n = len(rows)
        cat = collections.Counter(cases[r["case_id"]]["reference_check"]["category"] for r in rows)
        res = lambda b: sum(cases[r["case_id"]]["reference_check"]["per_batch"][b]["result"] == "MATCH" for r in rows)
        ab = sum(cases[r["case_id"]]["ab_relation"] == "AGREE" for r in rows)
        f = lambda x: round(x / n, 4) if n else None
        return {"n": n, "categories": dict(cat), "A_matches_reference": f(res("A")), "B_matches_reference": f(res("B")),
                "both_match_reference": f(cat["both_match"]), "A_B_agree": f(ab)}

    per_batch = {}
    for b in C.BATCHES:
        rows = batches[b]
        per_batch[b] = {
            "rows": len(rows), "missing": n_missing[b],
            "rows_with_core_problems": sum(bool(n["core_problems"]) for n in rows.values()),
            "rows_with_type_problems": sum(bool(n["type_problems"]) for cid, n in rows.items()
                                           if meta[cid]["needs_type_label"]),
            "status": counter((n["status"] for n in rows.values())),
            "issue": counter((n["issue"] for n in rows.values())),
            "confidence": counter((n["confidence"] for n in rows.values())),
            "output_check": counter((n["output_check"] for n in rows.values())),
            "vs_reference_sample": vs_counts(smp_rows, b),
            "vs_reference_screening": vs_counts(scr_rows, b),
            "type_counts": counter((cases[r["case_id"]][b]["type"] for r in typ_rows)),
            "problems": problems[b],
            "groups": gstate[b],
        }
    ta = [(cases[r["case_id"]]["A"]["type"], cases[r["case_id"]]["B"]["type"]) for r in typ_rows]
    te = [(cases[r["case_id"]]["A"]["effective_type"], cases[r["case_id"]]["B"]["effective_type"]) for r in typ_rows]
    tn = [(str(x == "NL_NOT_LINEARIZABLE"), str(y == "NL_NOT_LINEARIZABLE")) for x, y in ta if x and y]
    k5, ke, kn = C.kappa(ta), C.kappa(te), C.kappa(tn)
    rc_counts = lambda rows, key: counter((c for r in rows for c in r[key].split(";") if c))
    summary = {
        "schema": "orgene-r1/annotation_agent/comparison_summary/v2",
        "complete": complete,
        "models": dict(x.split("=", 1) for x in a.model if "=" in x),
        "rules": {"tolerance": "abs(x - ref) <= max(1e-4, 1e-4*abs(ref))",
                  "sample": "AUTO_CORRECT iff both batches match the reference (Optimal, no issue, not LOW, output "
                            "consistent); otherwise ADJUDICATE",
                  "screening": "unsampled IndustryOR: SCREEN_FLAG (adjudicated) iff A and B agree with each other and "
                               "neither matches the reference; otherwise SCREEN_KEEP (original reference kept)",
                  "type_label": "ADJUDICATE iff either batch says NL_* or LOW type confidence (or a type field is "
                                "missing/invalid); equal LP/MILP/IP labels -> AUTO; differing LP/MILP/IP labels -> the "
                                "label of the only batch whose objective matches the reference (AUTO_BY_REFERENCE), "
                                "otherwise LINEAR_UNRESOLVED (UNRESOLVED)",
                  "audit_seeds": {"reference_check": C.REF_AUDIT_SEED, "type_label": C.TYPE_AUDIT_SEED,
                                  "reference_check_round2": C.REF_AUDIT_SEED_2, "type_label_round2": C.TYPE_AUDIT_SEED_2},
                  "audit_rule": "round 2 (10 more, fixed seed) only for an audit whose round 1 overturns >= 1 case; "
                                "no third round",
                  "n_audit": C.N_AUDIT, "rerun": a.rerun},
        "per_batch": per_batch,
        "reference_check_sample": {
            **rates(smp_rows),
            "route": counter((r["ref_route"] for r in smp_rows)),
            "auto_correct_before_audit": len(auto_ref),
            "ab_relation": counter((cases[r["case_id"]]["ab_relation"] for r in smp_rows)),
            "reasons": rc_counts(smp_rows, "ref_reasons"),
            "adjudicate_ids": [r["case_id"] for r in smp_rows if r["ref_route"] == "ADJUDICATE"],
            "audit_ids": audit_ref,
        },
        "screening_unsampled_industryor": {
            **rates(scr_rows),
            "route": counter((r["ref_route"] for r in scr_rows)),
            "flag_ids": [r["case_id"] for r in scr_rows if r["ref_route"] == "SCREEN_FLAG"],
            "flag_reasons": rc_counts([r for r in scr_rows if r["ref_route"] == "SCREEN_FLAG"], "ref_reasons"),
        },
        "type_label": {
            "n": len(typ_rows),
            "route": counter((r["type_route"] for r in typ_rows)),
            "auto_before_audit": len(auto_type),
            "raw_agreement_5class": round(sum(x == y for x, y in ta if x and y) / max(1, k5[1]), 4),
            "kappa_5class": k5[0], "kappa_effective_type": ke[0], "kappa_nl_not_linearizable_vs_rest": kn[0],
            "n_both_labelled": k5[1],
            "reasons": rc_counts(typ_rows, "type_reasons"),
            "adjudicate_ids": [r["case_id"] for r in typ_rows if r["type_route"] == "ADJUDICATE"],
            "auto_by_reference_ids": [r["case_id"] for r in typ_rows
                                      if cases[r["case_id"]]["type_label"]["auto_kind"] == "AUTO_BY_REFERENCE"],
            "unresolved_ids": [r["case_id"] for r in typ_rows if r["type_route"] == "UNRESOLVED"],
            "audit_ids": audit_type,
        },
        "audit_round2_candidates": round2,
        "for_adjudicator": {"rows": sum(r["for_adjudicator"] == "Y" for r in routing),
                            "ids": [r["case_id"] for r in routing if r["for_adjudicator"] == "Y"]},
    }

    os.makedirs(out, exist_ok=True)
    comp = {"schema": "orgene-r1/annotation_agent/comparison/v2",
            "WARNING": "contains reference answers and re-derived values: coordinator and adjudicator only",
            "complete": complete, "summary": summary, "cases": cases,
            "audit": {"reference_check": audit_ref, "type_label": audit_type, "round2_candidates": round2},
            "inputs": {"case_set_sha256": C.sha256_file(os.path.join(a.package, "case_set.json")),
                       "groups_sha256": C.sha256_file(os.path.join(a.package, "groups.json")),
                       "references_sha256": C.sha256_file(os.path.join(a.hidden, "references.json")),
                       "results_sha256": {f"{b}/{g}": (C.sha256_file(os.path.join(C.group_dir(a.results_root, b, g),
                                                                                  "results.jsonl"))
                                                       if gstate[b][g]["results_file"] else None)
                                          for b in C.BATCHES for g in groups[b]}}}
    h_comp = C.dump_json(os.path.join(out, "comparison.json"), comp)
    h_sum = C.dump_json(os.path.join(out, "summary.json"), summary)
    fields = ["case_id", "benchmark", "split", "needs_reference_check", "needs_type_label", "ref_scope", "ref_route",
              "ref_reasons", "type_route", "type_reasons", "for_adjudicator"]
    C.write_csv(os.path.join(out, "routing.csv"), fields, routing)
    C.write_manifest(out, skip_agent_outputs=False)

    # ---------------- console (counts and ids only)
    for b in C.BATCHES:
        pb = per_batch[b]
        print(f"batch {b}: rows {pb['rows']}/125, core problems {pb['rows_with_core_problems']}, "
              f"type problems {pb['rows_with_type_problems']}, status {pb['status']}, issue {pb['issue']}, "
              f"output check {pb['output_check']}, file problems {len(pb['problems'])}")
        for pr in pb["problems"][:30]:
            print("   -", pr)
    rc, sc, tl = summary["reference_check_sample"], summary["screening_unsampled_industryor"], summary["type_label"]
    print(f"reference check (sample, {rc['n']}): routes {rc['route']}, auto CORRECT before audit "
          f"{rc['auto_correct_before_audit']}, categories {rc['categories']}")
    print(f"  adjudicate ({len(rc['adjudicate_ids'])}): {' '.join(rc['adjudicate_ids']) or '(none)'}")
    print(f"  audit ({len(rc['audit_ids'])}): {' '.join(rc['audit_ids']) or '(none)'}")
    print(f"full screening (unsampled IndustryOR, {sc['n']}): routes {sc['route']}, categories {sc['categories']}, "
          f"A match {sc['A_matches_reference']}, B match {sc['B_matches_reference']}, A-B agree {sc['A_B_agree']}")
    print(f"  flagged ({len(sc['flag_ids'])}): {' '.join(sc['flag_ids']) or '(none)'}")
    print(f"type label ({tl['n']}): routes {tl['route']}, kappa 5-class {tl['kappa_5class']}, "
          f"effective {tl['kappa_effective_type']}, NL_NOT vs rest {tl['kappa_nl_not_linearizable_vs_rest']}")
    print(f"  adjudicate ({len(tl['adjudicate_ids'])}): {' '.join(tl['adjudicate_ids']) or '(none)'}")
    print(f"  audit ({len(tl['audit_ids'])}): {' '.join(tl['audit_ids']) or '(none)'}")
    print(f"  auto by reference {len(tl['auto_by_reference_ids'])}, unresolved {len(tl['unresolved_ids'])}: "
          f"{' '.join(tl['unresolved_ids']) or '(none)'}")
    print(f"audit round-2 candidates (used only if round 1 overturns a case): reference "
          f"{len(round2['reference_check'])}, type {len(round2['type_label'])}")
    print(f"rows for the adjudicator: {summary['for_adjudicator']['rows']}")
    print(f"wrote {os.path.relpath(out, os.path.dirname(C.PKG))}: comparison.json {h_comp[:12]}, summary.json {h_sum[:12]}, "
          "routing.csv")
    return 0

if __name__ == "__main__":
    sys.exit(main())
