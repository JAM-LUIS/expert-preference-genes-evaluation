#!/usr/bin/env python3
"""Merge the filled adjudication sheet(s) with the automatic settlements into the text-free files read by R1's E14
ingest (data/ingest_annotations.py -> runtime/orgene/annotations.py -> refs.build_overrides_doc of E13).

  python3 export_for_ingest.py --sheet <filled adjudication_C.xlsx> [--sheet2 <filled adjudication_C_round2.xlsx>]
      [--hidden DIR] [--comparison DIR] [--adjudication DIR] [--adjudication2 DIR] [--out DIR]
      [--legacy-methods] [--strict]

Reads   from each filled workbook ONLY the columns case_id, final_verdict, final_value, final_type,
        final_type_after_linearization, minutes. The reason column and every other free-text column are never read;
        a cell outside its closed vocabulary is reported as INVALID / NON_NUMERIC without its content.
        <hidden>/comparison/comparison.json, <hidden>/adjudication/adjudication_rows.json (round 1),
        <hidden>/adjudication_round2/adjudication_rows.json (round 2, when needed), <hidden>/references.json,
        stage1/data/reference_check_sample.json
Writes  <out>/ (default <hidden>/ingest/):
          ref_check.csv                 E14 ref_check format: the 66 sampled cases + the full-screening findings
          reference_check_scope.json    E14 --sample input: the 66 rows of reference_check_sample.json, unchanged,
                                        + one row per full-screening finding (checker A+B); no answers in it
          type_final_labels.csv         E14 type_final_labels format: the 100 IndustryOR cases
          adjudication_summary.json     counts only: routes, verdicts, methods, audit rounds and overturn rates, labels
Prints  counts and case ids only.

Audit rounds (main-session rule 2026-09-29): if round 1 of the reference audit (or of the type audit) overturns >= 1
case, the 10 round-2 candidates of that audit (fixed in comparison.json) must be adjudicated too (--sheet2); overturned
cases take the adjudicator's decision; there is no third round.
Codes (never names): A = batch A agents, B = batch B agents, C = the adjudicator.
Method field (proposed R1 vocabulary, INGEST_E13_E14.md):
  automatic settlement (both batches match / agree, or the LP/MILP/IP tie-break by the objective check), also when a
  random audit confirms it                                                         -> independent_agent_rederivation
  adjudicator decision on a reference check or a screening finding                 -> adjudication (+ adjudicator C)
  adjudicator decision on the type label                                           -> third_party  (+ adjudicator C)
  --legacy-methods writes independent_agreement instead of independent_agent_rederivation (only if R1 keeps its current
  vocabulary; say so in RECORDS). LINEAR_UNRESOLVED (registered in PREREG_R1) is written with the automatic method;
  R1 needs the F2 label supplement (annotations.LINEAR_UNRESOLVED, 2026-10-08) to ingest it.
checker column: A+B; A+B+C where the adjudicator's random audit confirmed an automatic settlement.
Deviations (--deviations FILE, 2026-10-10): the returned round-1 sheet left gaps and the adjudicator was not asked
again. No cell is filled in for the adjudicator; each gap is closed by a fixed rule that reads no statement, and every
use is written to the `deviation` column (ref_check.csv), the `note` column (type_final_labels.csv) and the summary:
  round2_not_performed            the round-2 audit of that kind was not run: its candidates keep their automatic
                                  settlement (audit_outcome round2_not_performed)
  no_verdict_fall_back_to_agreement  a row returned without a verdict: the reference is kept only if both batches
                                  match it within tolerance (method = the automatic one, no adjudicator)
  after_linearization_from_batches   NL_LINEARIZABLE returned without the class after linearisation: the class both
                                  batches gave, only if they gave the same one
  label_cell_stands               a class after linearisation returned next to a label other than NL_LINEARIZABLE:
                                  the label cell is the decision, the dependent cell is dropped
A rule that does not apply to the sheet as returned stops the export (a deviation file cannot override a decision).
Unsampled IndustryOR cases that the screening did not flag get no ref_check row: original reference.
"""
import argparse
import collections
import copy
import csv
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

AUTO_METHOD = "independent_agent_rederivation"
LEGACY_AUTO_METHOD = "independent_agreement"
KEEP = ("case_id", "final_verdict", "final_value", "final_type", "final_type_after_linearization", "minutes")
CLOSED = {"final_verdict": C.VERDICTS, "final_type": C.TYPE_LABELS, "final_type_after_linearization": C.POST_LIN}
REF_FIELDS = ["case_id", "benchmark", "split", "checker", "reference", "scope", "route", "result_A", "value_A",
              "result_B", "value_B", "audit_outcome", "final_verdict", "final_value", "method", "adjudicator", "deviation"]
TYPE_FIELDS = ["case_id", "split", "final_label", "final_type_after_linearization", "method", "adjudicator", "note",
               "route", "audit_outcome"]
SCREEN_REASON = ("full screening (main-session rule 2026-09-29): unsampled IndustryOR case; both agent batches agree "
                 "with each other within max(1e-4, 1e-4*|x|) and neither matches the reference; adjudicated by C")
KINDS = ("reference_check", "type_label")
DEV_SCHEMA = "orgene-r1/annotation_agent/adjudication_deviations/v1"
DEV_RULES = ("no_verdict_fall_back_to_agreement", "after_linearization_from_batches", "label_cell_stands")
DEV_TEXT = {
    "round2_not_performed": "round-2 audit not performed (deviation 2026-10-10): automatic settlement kept",
    "no_verdict_fall_back_to_agreement": "no verdict returned by C (deviation 2026-10-10): reference kept because "
                                         "batches A and B both match it within tolerance",
    "after_linearization_from_batches": "class after linearisation not given by C (deviation 2026-10-10): the class "
                                        "batches A and B both gave",
    "label_cell_stands": "C gave a class after linearisation next to a label other than NL_LINEARIZABLE (deviation "
                         "2026-10-10): the label cell stands, the dependent cell is dropped",
}


def load_deviations(path):
    if not path:
        return {"round2_not_performed": [], "cases": {}}, None
    doc = C.load_json(path)
    if doc.get("schema") != DEV_SCHEMA:
        sys.exit(f"--deviations: schema must be {DEV_SCHEMA}")
    r2 = list(doc.get("round2_not_performed") or [])
    cases = {cid: (v or {}).get("rule") for cid, v in (doc.get("cases") or {}).items()}
    if [k for k in r2 if k not in KINDS] or [r for r in cases.values() if r not in DEV_RULES]:
        sys.exit(f"--deviations: round2_not_performed takes {list(KINDS)}; case rules are {list(DEV_RULES)}")
    return {"round2_not_performed": r2, "cases": cases}, C.sha256_file(path)


def sanitize(key, v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        s = repr(float(v))
    else:
        s = "" if v is None else str(v).strip()
    if s == "" or key == "case_id":
        return s
    if key in CLOSED:
        return s if s in CLOSED[key] else "INVALID"
    if key == "final_value":
        if s.lower() in C.SPECIAL_VALUES:
            return s.lower()
        x = C.num(s)
        return "NON_NUMERIC" if x is None else repr(x)
    if key == "minutes":
        x = C.num(s)
        return "NON_NUMERIC" if x is None else repr(x)
    return "INVALID"


def read_sheets(path, titles):
    """{case_id: kept cells} over the data sheets; (rows, n_bad_ids, duplicate ids)."""
    raws = []
    if path.lower().endswith(".xlsx"):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        for t in titles:
            if t not in wb.sheetnames:
                sys.exit(f"sheet '{t}' missing from the workbook (sheet names must not be changed)")
            it = wb[t].iter_rows(values_only=True)
            hdr = [str(h or "").split("｜")[0].strip() for h in next(it)]
            missing = [k for k in KEEP if k not in hdr]
            if missing:
                sys.exit(f"sheet '{t}': missing column(s) {missing}")
            raws += [dict(zip(hdr, r)) for r in it]
    else:                                         # a CSV export holding the rows of all sheets
        with open(path, encoding="utf-8-sig", newline="") as f:
            rd = csv.reader(f)
            hdr = [h.split("｜")[0].strip() for h in next(rd)]
            raws = [dict(zip(hdr, r)) for r in rd]
    out, bad, dup = {}, 0, []
    for r in raws:
        cid = str(r.get("case_id") or "").strip()
        if not cid:
            continue
        if not C.CASE_ID_RE.match(cid):
            bad += 1
            continue
        if cid in out:
            dup.append(cid)
            continue
        out[cid] = {k: sanitize(k, r.get(k)) for k in KEEP}
    return out, bad, dup


def collect(sheet_path, adj, refs, problems, pending, tag, dev_cases=None, comp_cases=None, applied=None):
    """Validated decisions {case_id: {"verdict", "value", "type", "after", "minutes"}} for the rows of one round."""
    need = {r["case_id"]: r for r in adj["rows"]}
    sheet, bad_ids, dups = read_sheets(sheet_path, list(adj["sheets"].values()))
    if bad_ids:
        problems.append(f"{tag}: {bad_ids} row(s) with an unexpected case_id were skipped (values not shown)")
    for cid in dups:
        problems.append(f"{tag} {cid}: appears more than once in the workbook (first row kept)")
    for cid in sorted(set(sheet) - set(need)):
        problems.append(f"{tag} {cid}: row is not in adjudication_rows.json (ignored)")
    decisions = {}
    dev_cases, comp_cases, applied = dev_cases or {}, comp_cases or {}, ({} if applied is None else applied)
    for cid, n in sorted(need.items()):
        r = sheet.get(cid)
        if r is None:
            problems.append(f"{tag} {cid}: row missing from the workbook")
            pending.add(cid)
            continue
        for k in KEEP[1:]:
            if r[k] in ("INVALID", "NON_NUMERIC"):
                problems.append(f"{tag} {cid}: {k} holds a value outside its list / not a number (value not shown)")
                r[k] = ""
        d = {"minutes": C.num(r["minutes"])}
        if n["needs_verdict"]:
            v, val = r["final_verdict"], r["final_value"]
            ref = refs[cid]["reference"]["objective"]
            x = C.num(val)
            bad = []
            if not v and dev_cases.get(cid) == "no_verdict_fall_back_to_agreement":
                per = comp_cases[cid]["reference_check"]["per_batch"]
                if val or n["ref_route"] != "ADJUDICATE" or {per["A"]["result"], per["B"]["result"]} != {"MATCH"}:
                    sys.exit(f"--deviations {cid}: no_verdict_fall_back_to_agreement needs an adjudication row with "
                             "no verdict and no value whose two batches both match the reference")
                d["fallback"] = True
                applied[cid] = "no_verdict_fall_back_to_agreement"
            elif not v:
                bad.append("final_verdict missing")
            elif v == "CORRECT" and x is not None and not C.within(x, ref):
                bad.append("CORRECT but final_value is outside the tolerance of the reference")
            elif v in C.REPLACING and val == "":
                bad.append(f"{v} needs final_value")
            elif v == "CORRECT_ROUNDED" and x is None:
                bad.append("CORRECT_ROUNDED needs a numeric final_value")
            elif v in C.REPLACING and x is not None and C.within(x, ref):
                bad.append(f"{v} but final_value is within the tolerance of the reference (that is CORRECT)")
            if bad:
                problems += [f"{tag} {cid}: {b}" for b in bad]
                pending.add(cid)
            elif d.get("fallback"):
                pass
            else:
                # AMBIGUOUS keeps the value of the most reasonable reading for the record (E13/E14 do not score it)
                keep_val = v in C.REPLACING or (v in ("CORRECT", "AMBIGUOUS") and val != "")
                d["verdict"], d["value"] = v, (val if keep_val else "")
                if v == "UNDERSPECIFIED" and val:
                    problems.append(f"{tag} {cid}: final_value given for UNDERSPECIFIED (ignored)")
        elif r["final_verdict"] or r["final_value"]:
            problems.append(f"{tag} {cid}: verdict cells filled although this row needs no verdict (ignored)")
        if n["needs_type"]:
            t, aft = r["final_type"], r["final_type_after_linearization"]
            rule = dev_cases.get(cid)
            if rule == "after_linearization_from_batches":
                ea, eb = comp_cases[cid]["A"], comp_cases[cid]["B"]
                both = {(ea.get("type"), ea.get("type_after_linearization")),
                        (eb.get("type"), eb.get("type_after_linearization"))}
                if t != "NL_LINEARIZABLE" or aft or len(both) != 1 or ea.get("type") != "NL_LINEARIZABLE" \
                        or ea.get("type_after_linearization") not in C.POST_LIN:
                    sys.exit(f"--deviations {cid}: after_linearization_from_batches needs NL_LINEARIZABLE returned "
                             "without a class and two batches that gave NL_LINEARIZABLE with the same class")
                aft = ea["type_after_linearization"]
                d["type_note"] = DEV_TEXT[rule]
                applied[cid] = rule
            elif rule == "label_cell_stands":
                if not t or t == "NL_LINEARIZABLE" or not aft:
                    sys.exit(f"--deviations {cid}: label_cell_stands needs a label other than NL_LINEARIZABLE "
                             "returned together with a class after linearisation")
                aft = ""
                d["type_note"] = DEV_TEXT[rule]
                applied[cid] = rule
            bad = []
            if not t:
                bad.append("final_type missing")
            elif t == "NL_LINEARIZABLE" and not aft:
                bad.append("NL_LINEARIZABLE needs final_type_after_linearization")
            elif t != "NL_LINEARIZABLE" and aft:
                bad.append("final_type_after_linearization given for a label other than NL_LINEARIZABLE")
            if bad:
                problems += [f"{tag} {cid}: {b}" for b in bad]
                pending.add(cid)
            else:
                d["type"], d["after"] = t, (aft if t == "NL_LINEARIZABLE" else "")
        elif r["final_type"] or r["final_type_after_linearization"]:
            problems.append(f"{tag} {cid}: type cells filled although this row needs no type (ignored)")
        decisions[cid] = d
    return decisions


def fmtv(x):
    return "" if x is None else repr(float(x))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", required=True, help="filled round-1 workbook")
    ap.add_argument("--sheet2", default=None, help="filled round-2 audit workbook (needed only after a round-1 overturn)")
    ap.add_argument("--hidden", default=C.HIDDEN_DEFAULT)
    ap.add_argument("--comparison", default=None)
    ap.add_argument("--adjudication", default=None)
    ap.add_argument("--adjudication2", default=None)
    ap.add_argument("--sample", default=os.path.join(C.STAGE1, "data", "reference_check_sample.json"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--legacy-methods", action="store_true")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any decision is missing or invalid")
    ap.add_argument("--deviations", default=None, help="JSON file of dated deviations (see the docstring)")
    a = ap.parse_args()
    comp_dir = a.comparison or os.path.join(a.hidden, "comparison")
    adj_dir = a.adjudication or os.path.join(a.hidden, "adjudication")
    adj2_dir = a.adjudication2 or os.path.join(a.hidden, "adjudication_round2")
    out = a.out or os.path.join(a.hidden, "ingest")
    auto_method = LEGACY_AUTO_METHOD if a.legacy_methods else AUTO_METHOD

    comp = C.load_json(os.path.join(comp_dir, "comparison.json"))
    comp_sha = C.sha256_file(os.path.join(comp_dir, "comparison.json"))
    adj = C.load_json(os.path.join(adj_dir, "adjudication_rows.json"))
    if adj["comparison_sha256"] != comp_sha:
        sys.exit("adjudication_rows.json was built from another comparison.json; rebuild the sheet or point to the right files")
    refs = C.load_references(a.hidden)["cases"]
    sample = C.load_json(a.sample)
    problems, pending = [], set()
    dev, dev_sha = load_deviations(a.deviations)
    applied = {}
    dec1 = collect(a.sheet, adj, refs, problems, pending, "round1", dev["cases"], comp["cases"], applied)
    if set(dev["cases"]) - set(applied):
        sys.exit("--deviations: no rule applied to " + " ".join(sorted(set(dev["cases"]) - set(applied))))

    # ---------------- audit rounds
    audit = {k: {"round1": [], "round1_overturned": [], "round2_needed": False, "round2": [],
                 "round2_overturned": []} for k in KINDS}
    for r in adj["rows"]:
        cid, d = r["case_id"], dec1.get(r["case_id"], {})
        if r["ref_route"] == "AUDIT":
            audit["reference_check"]["round1"].append(cid)
            if "verdict" in d and d["verdict"] != "CORRECT":
                audit["reference_check"]["round1_overturned"].append(cid)
        if r["type_route"] == "AUDIT":
            audit["type_label"]["round1"].append(cid)
            if "type" in d and d["type"] != r["auto_type"]:
                audit["type_label"]["round1_overturned"].append(cid)
    cands = comp["audit"]["round2_candidates"]
    r2sel = {}
    for k in KINDS:
        if audit[k]["round1_overturned"]:
            audit[k]["round2_needed"] = True
            for cid in cands[k]:
                r2sel.setdefault(cid, set()).add(k)
    dec2 = {}
    r2_skip = {k for k in KINDS if audit[k]["round2_needed"] and k in dev["round2_not_performed"]}
    if set(dev["round2_not_performed"]) - r2_skip:
        sys.exit("--deviations: round2_not_performed names an audit that needs no round 2")
    if r2_skip and (a.sheet2 or r2_skip != {k for k in KINDS if audit[k]["round2_needed"]}):
        sys.exit("--deviations: round2_not_performed must cover every round 2 that is needed, and excludes --sheet2")
    if r2sel and r2_skip:
        pass                                           # candidates keep their automatic settlement (rows below)
    elif r2sel:
        if not a.sheet2:
            problems.append("round-2 audit required (round 1 overturned a case) for "
                            + ", ".join(k for k in KINDS if audit[k]["round2_needed"]) + ": give --sheet2")
            pending |= set(r2sel)
        else:
            adj2 = C.load_json(os.path.join(adj2_dir, "adjudication_rows.json"))
            if adj2["comparison_sha256"] != comp_sha:
                sys.exit("round-2 adjudication_rows.json was built from another comparison.json")
            got = {r["case_id"]: {k for k, f in (("reference_check", r["needs_verdict"]), ("type_label", r["needs_type"]))
                                  if f} for r in adj2["rows"]}
            if got != r2sel:
                sys.exit("the round-2 sheet does not hold exactly the round-2 audits that round 1 requires")
            dec2 = collect(a.sheet2, adj2, refs, problems, pending, "round2")
    elif a.sheet2:
        problems.append("round-2 sheet given but round 1 overturned nothing: ignored")

    # ---------------- rows
    ref_rows, type_rows, scope_extra = [], [], []
    cnt = collections.defaultdict(collections.Counter)
    for cid in sorted(comp["cases"]):
        e = comp["cases"][cid]
        rt = e["routing"]
        d1, d2 = dec1.get(cid, {}), dec2.get(cid, {})
        rroute = rt["ref_route"]
        in_r2 = r2sel.get(cid, set())
        if e["needs_reference_check"] or rroute == "SCREEN_FLAG":
            ref = refs[cid]["reference"]
            per = e["reference_check"]["per_batch"]
            row = {"case_id": cid, "benchmark": e["benchmark"], "split": e["split"], "checker": "A+B",
                   "reference": fmtv(ref["objective"]) if ref["objective"] is not None else (ref.get("status") or ""),
                   "scope": rt["ref_scope"], "route": rroute,
                   "result_A": per["A"]["result"], "value_A": fmtv(e["A"].get("value")) or (e["A"].get("special") or ""),
                   "result_B": per["B"]["result"], "value_B": fmtv(e["B"].get("value")) or (e["B"].get("special") or ""),
                   "audit_outcome": "", "final_verdict": "", "final_value": "", "method": "", "adjudicator": "",
                   "deviation": ""}
            rnd = 1 if rroute == "AUDIT" else (2 if "reference_check" in in_r2 else 0)
            skipped = rnd == 2 and "reference_check" in r2_skip      # round 2 not performed: stays automatic
            rnd = 0 if skipped else rnd
            dd = d2 if rnd == 2 else d1
            if rnd == 2:
                row["route"] = "AUDIT_ROUND2"
                audit["reference_check"]["round2"].append(cid)
            if rroute == "AUTO_CORRECT" and rnd == 0:
                row.update(final_verdict="CORRECT", method=auto_method)
                if skipped:
                    row.update(audit_outcome="round2_not_performed", deviation=DEV_TEXT["round2_not_performed"])
            elif skipped:
                sys.exit(f"internal check failed: round-2 candidate {cid} is not an automatic settlement")
            elif d1.get("fallback") and rnd == 0 and cid not in pending:
                row.update(final_verdict="CORRECT", method=auto_method,
                           deviation=DEV_TEXT["no_verdict_fall_back_to_agreement"])
            elif cid in pending or "verdict" not in dd:
                pass                                                   # left blank -> pending in E14
            elif rnd and dd["verdict"] == "CORRECT":
                row.update(final_verdict="CORRECT", final_value=dd["value"], method=auto_method, checker="A+B+C",
                           audit_outcome=f"confirmed_round{rnd}")
            elif rnd:
                row.update(final_verdict=dd["verdict"], final_value=dd["value"], method="adjudication",
                           adjudicator=C.ADJUDICATOR_CODE, audit_outcome=f"overturned_round{rnd}")
                if rnd == 2:
                    audit["reference_check"]["round2_overturned"].append(cid)
            else:
                row.update(final_verdict=dd["verdict"], final_value=dd["value"], method="adjudication",
                           adjudicator=C.ADJUDICATOR_CODE)
            if rroute == "SCREEN_FLAG":
                scope_extra.append({"case_id": cid, "benchmark": e["benchmark"], "split": e["split"],
                                    "reason": SCREEN_REASON, "checker": "A+B", "rank_hash": ""})
            cnt[f"{rt['ref_scope']}_route"][row["route"]] += 1
            cnt[f"{rt['ref_scope']}_verdict"][row["final_verdict"] or "PENDING"] += 1
            cnt[f"{rt['ref_scope']}_method"][row["method"] or "PENDING"] += 1
            ref_rows.append(row)
        elif rt["ref_scope"] == "screening":
            cnt["screening_route"][rroute] += 1
        if e["needs_type_label"]:
            tl = e["type_label"]
            troute, auto = rt["type_route"], tl["auto_label"]
            row = {"case_id": cid, "split": e["split"], "final_label": "", "final_type_after_linearization": "",
                   "method": "", "adjudicator": "", "note": "", "route": troute, "audit_outcome": ""}
            rnd = 1 if troute == "AUDIT" else (2 if "type_label" in in_r2 else 0)
            skipped = rnd == 2 and "type_label" in r2_skip
            rnd = 0 if skipped else rnd
            dd = d2 if rnd == 2 else d1
            if rnd == 2:
                row["route"] = "AUDIT_ROUND2"
                audit["type_label"]["round2"].append(cid)
            if troute in ("AUTO", "AUTO_BY_REFERENCE", "UNRESOLVED") and rnd == 0:
                row.update(final_label=auto, method=auto_method)
                if skipped:
                    row.update(audit_outcome="round2_not_performed", note=DEV_TEXT["round2_not_performed"])
            elif skipped:
                sys.exit(f"internal check failed: round-2 candidate {cid} is not an automatic type label")
            elif cid in pending or "type" not in dd:
                pass
            elif rnd and dd["type"] == auto:
                row.update(final_label=auto, method=auto_method, audit_outcome=f"confirmed_round{rnd}")
            elif rnd:
                row.update(final_label=dd["type"], final_type_after_linearization=dd["after"], method="third_party",
                           adjudicator=C.ADJUDICATOR_CODE, audit_outcome=f"overturned_round{rnd}")
                if rnd == 2:
                    audit["type_label"]["round2_overturned"].append(cid)
            else:
                row.update(final_label=dd["type"], final_type_after_linearization=dd["after"], method="third_party",
                           adjudicator=C.ADJUDICATOR_CODE, note=dd.get("type_note", ""))
            cnt["type_route"][row["route"] if rnd else troute] += 1
            cnt["type_label"][row["final_label"] or "PENDING"] += 1
            cnt["type_method"][row["method"] or "PENDING"] += 1
            type_rows.append(row)

    # the E14 --sample input: the pre-registered sample, unchanged, plus the screening findings
    scope = copy.deepcopy(sample)
    scope["rows"] = sample["rows"] + scope_extra
    scope["n_rows"] = len(scope["rows"])
    scope.setdefault("addenda", []).append({
        "date": datetime.date.today().isoformat(), "added_forced": [r["case_id"] for r in scope_extra],
        "why": SCREEN_REASON, "random_sample_redrawn": False, "source_sample_sha256": C.sha256_file(a.sample)})
    sample_ids = {r["case_id"] for r in sample["rows"]}
    if not ({r["case_id"] for r in ref_rows} == sample_ids | {r["case_id"] for r in scope_extra}
            and not (sample_ids & {r["case_id"] for r in scope_extra})):
        sys.exit("internal check failed: ref_check rows != sample + screening findings")

    os.makedirs(out, exist_ok=True)
    C.write_csv(os.path.join(out, "ref_check.csv"), REF_FIELDS, ref_rows)
    C.write_csv(os.path.join(out, "type_final_labels.csv"), TYPE_FIELDS, type_rows)
    h_scope = C.dump_json(os.path.join(out, "reference_check_scope.json"), scope)
    minutes = [d["minutes"] for d in list(dec1.values()) + list(dec2.values()) if d.get("minutes") is not None]
    rate = lambda o, n: round(len(o) / len(n), 4) if n else None
    audit_out = {k: {"round1_n": len(v["round1"]), "round1_overturned": sorted(v["round1_overturned"]),
                     "round1_overturn_rate": rate(v["round1_overturned"], v["round1"]),
                     "round2_needed": v["round2_needed"], "round2_performed": bool(v["round2_needed"] and k not in r2_skip),
                     "round2_n": len(v["round2"]),
                     "round2_overturned": sorted(v["round2_overturned"]),
                     "round2_overturn_rate": (rate(v["round2_overturned"], v["round2"])
                                              if v["round2_needed"] and k not in r2_skip else None)}
                 for k, v in audit.items()}
    summary = {
        "schema": "orgene-r1/annotation_agent/adjudication_summary/v4",
        "created": datetime.date.today().isoformat(),
        "codes": {"A": "batch A agents", "B": "batch B agents", C.ADJUDICATOR_CODE: "adjudicator"},
        "auto_method": auto_method,
        "sheet_sha256": C.sha256_file(a.sheet),
        "sheet2_sha256": C.sha256_file(a.sheet2) if a.sheet2 else None,
        "comparison_sha256": comp_sha,
        "reference_check_sample": {"n": sum(r["scope"] == "sample" for r in ref_rows),
                                   "route": dict(cnt["sample_route"]), "final_verdict": dict(cnt["sample_verdict"]),
                                   "method": dict(cnt["sample_method"])},
        "screening_unsampled_industryor": {"route": dict(cnt["screening_route"]),
                                           "findings": [r["case_id"] for r in scope_extra],
                                           "final_verdict": dict(cnt["screening_verdict"])},
        "type_label": {"n": len(type_rows), "route": dict(cnt["type_route"]), "final_label": dict(cnt["type_label"]),
                       "method": dict(cnt["type_method"]),
                       "nl_not_linearizable": sorted(r["case_id"] for r in type_rows
                                                     if r["final_label"] == "NL_NOT_LINEARIZABLE"),
                       "linear_unresolved": sorted(r["case_id"] for r in type_rows
                                                   if r["final_label"] == C.LINEAR_UNRESOLVED)},
        "audit": audit_out,
        "adjudicator_minutes": {"rows_with_minutes": len(minutes), "total": round(sum(minutes), 1) if minutes else None},
        "pending": sorted(pending),
        "problems": problems,
        "deviations": {"file_sha256": dev_sha, "round2_not_performed": sorted(r2_skip),
                       "round2_candidates_kept_automatic": sorted(c for c, ks in r2sel.items() if ks & r2_skip),
                       "cases": dict(sorted(applied.items())), "rules": {k: DEV_TEXT[k] for k in sorted(
                           set(applied.values()) | ({"round2_not_performed"} if r2_skip else set()))}},
        "files": {"ref_check.csv": C.sha256_file(os.path.join(out, "ref_check.csv")),
                  "reference_check_scope.json": h_scope,
                  "type_final_labels.csv": C.sha256_file(os.path.join(out, "type_final_labels.csv"))},
    }
    C.dump_json(os.path.join(out, "adjudication_summary.json"), summary)
    C.write_manifest(out, skip_agent_outputs=False)
    s1, s2, t = summary["reference_check_sample"], summary["screening_unsampled_industryor"], summary["type_label"]
    print(f"reference check (sample): {s1['n']} rows; routes {s1['route']}; verdicts {s1['final_verdict']}; "
          f"methods {s1['method']}")
    print(f"full screening: routes {s2['route']}; findings {len(s2['findings'])} {' '.join(s2['findings'])}; "
          f"verdicts {s2['final_verdict']}")
    print(f"type labels: {t['n']} rows; routes {t['route']}; labels {t['final_label']}; methods {t['method']}")
    print(f"  NL_NOT_LINEARIZABLE: {' '.join(t['nl_not_linearizable']) or '(none)'}; "
          f"LINEAR_UNRESOLVED: {' '.join(t['linear_unresolved']) or '(none)'}")
    for k, v in audit_out.items():
        print(f"audit {k}: round 1 {v['round1_n']} (overturned {v['round1_overturned'] or 'none'}); round 2 "
              f"{'needed' if v['round2_needed'] else 'not needed'}: {v['round2_n']} "
              f"(overturned {v['round2_overturned'] or 'none'})")
    dv = summary["deviations"]
    if dv["file_sha256"]:
        print(f"deviations: round 2 not performed for {dv['round2_not_performed'] or 'none'} "
              f"({len(dv['round2_candidates_kept_automatic'])} candidates keep the automatic settlement); cases "
              + (" ".join(f"{c}={r}" for c, r in dv["cases"].items()) or "(none)"))
    print(f"pending {len(pending)}: {' '.join(sorted(pending)) or '(none)'}")
    for p in problems[:100]:
        print("  -", p)
    print(f"wrote {out}: ref_check.csv {summary['files']['ref_check.csv'][:12]}, reference_check_scope.json "
          f"{h_scope[:12]}, type_final_labels.csv {summary['files']['type_final_labels.csv'][:12]}")
    # a note that ends with "(ignored)" reports cells the export does not read; it changes no output and does not block
    blocking = [p for p in problems if not p.endswith("(ignored)")]
    return 1 if (a.strict and (pending or blocking)) else 0


if __name__ == "__main__":
    sys.exit(main())
