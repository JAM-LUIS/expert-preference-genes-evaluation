#!/usr/bin/env python3
"""Final analysis of the measurement check under SET_RULE_20261013.md, in one step. Outside the frozen tree.

  final_measurement.py --export DIR --rater R3=W.xlsx@2026-10-16T16:13:05Z --rater R4=W.xlsx@<return time>
                       [--coauthor W.xlsx] --out report.json

Every --rater is a reviewer who confirmed all seven independence statements; the time is the mail-server time of
the returned workbook (rule 4: among independent reviewers, order of return). Per set (rule 3) a reviewer is
eligible when every program of the set is judged. Per set the first two eligible reviewers are taken (rule 4; no
two of the known reviewers belong to one research group, rule 5); the lower number gives the first judgment.
A set with one eligible reviewer takes that reviewer's labels and is left out of kappa (rule 8); a set with none
takes the co-author's blind workbook (rule 8) or, without one, stays unlabelled (worst-case bounds).
No discussion (rule 7): a program whose overall judgments differ is 'unresolved' (no label); both 'incorrect'
with different categories stays incorrect with the category 'not agreed'.
Rates, corrected accuracies and bounds come from the frozen analyze(); kappa is recomputed on the programs that
have two judgments, which is what rule 9 asks for.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "20261013_sets"))
import sets as S  # noqa: E402
B = S.B


def judged(rows, pid):
    raw = rows[pid]["raw"]
    import measurement_check as MC
    j = {k: MC._code(raw[k]) for k in MC.ASPECTS + ("overall", "error_category")}
    j["notes"] = raw["notes"].strip() if isinstance(raw.get("notes"), str) else ""
    return j


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True)
    ap.add_argument("--rater", action="append", required=True, help="R3=path@ISO-time")
    ap.add_argument("--coauthor")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=10000)
    a = ap.parse_args(argv)
    MC = B.load_mc()
    man, items = B.load_items(a.export)
    key = json.load(open(os.path.join(a.export, "key.json"), encoding="utf-8"))
    sets = S.plan(items)

    raters = []
    for x in a.rater:
        rid, rest = x.split("=", 1)
        path, t = rest.rsplit("@", 1)
        rows, meta = B.read_rows(MC, path)
        if meta.get("rater_id") != rid:
            raise SystemExit(f"{path}: workbook says rater {meta.get('rater_id')}, not {rid}")
        raters.append({"id": rid, "path": path, "time": t, "rows": rows, "sha256": B.sha256_file(path)})
    raters.sort(key=lambda r: r["time"])                       # rule 4: all independent -> order of return

    assign, j1, j2, src = {}, {}, {}, {}
    for name, unit in sets.items():
        elig = [r for r in raters if not B.block_state(r["rows"], unit)[1]]
        take = sorted(elig[:2], key=lambda r: int(r["id"][1:]))
        extra = [r["id"] for r in elig[2:]]
        partial = [r["id"] for r in raters if r not in elig and B.block_state(r["rows"], unit)[0]]
        if take:
            a1, a2 = take[0], take[-1]
            kind = "two" if len(take) == 2 else "one"
            for pid in unit["programs"]:
                j1[pid], j2[pid] = judged(a1["rows"], pid), judged(a2["rows"], pid)
        else:
            kind = "none"
            if a.coauthor:
                rows, _ = B.read_rows(MC, a.coauthor)
                if B.block_state(rows, unit)[1]:
                    raise SystemExit(f"co-author workbook does not complete set {name}")
                kind = "coauthor"
                for pid in unit["programs"]:
                    j1[pid] = j2[pid] = judged(rows, pid)
            else:
                for pid in unit["programs"]:
                    j1[pid] = j2[pid] = {**{k: "cannot_judge" for k in MC.ASPECTS}, "overall": "cannot_judge",
                                         "error_category": None, "notes": "no eligible reviewer"}
        assign[name] = {"kind": kind, "reviewers": [r["id"] for r in take], "additional": extra + partial,
                        "programs": len(unit["programs"])}
        for pid in unit["programs"]:
            src[pid] = name

    two = [pid for pid in j1 if assign[src[pid]]["kind"] == "two"]
    cons, cat_not_agreed = {}, []
    for pid, why in MC.disagreements({p: j1[p] for p in two}, {p: j2[p] for p in two}):
        if why == "overall_differs":
            cons[pid] = ("unresolved", None)
        else:
            cons[pid] = ("incorrect", "other")
            cat_not_agreed.append(pid)
    doc = MC.analyze(key, j1, j2, cons, a.n_boot)

    pairs = [(j1[p]["overall"], j2[p]["overall"]) for p in two]
    kappa = MC.cohen_kappa(pairs, MC.JUDGMENTS) if pairs else None
    doc["agreement"] = {"rule": "SET_RULE_20261013 rule 9: programs with two judgments only",
                        "n_programs": len(two), "kappa": kappa,
                        "percent_agreement": (sum(x == y for x, y in pairs) / len(pairs)) if pairs else None,
                        "unresolved": sorted(p for p, v in cons.items() if v[0] == "unresolved"),
                        "category_not_agreed": sorted(cat_not_agreed), "reference_value": 0.60}
    doc["assignment"] = assign
    doc["counts"] = {k: sum(1 for v in assign.values() if v["kind"] == k) for k in ("two", "one", "none", "coauthor")}
    doc["counts_programs"] = {k: sum(v["programs"] for v in assign.values() if v["kind"] == k)
                              for k in ("two", "one", "none", "coauthor")}
    doc["inputs"] = {"export_id": man["export_id"], "raters": [{k: r[k] for k in ("id", "path", "time", "sha256")}
                                                               for r in raters],
                     "coauthor": B.sha256_file(a.coauthor) if a.coauthor else None}
    json.dump(doc, open(a.out, "w", encoding="utf-8"), indent=1, default=str)

    pc = lambda x: "--" if x is None else f"{100 * x:.1f}%"
    print("sets:", " ".join(f"{k}:{v['kind']}({'+'.join(v['reviewers'])})" for k, v in assign.items()))
    print("sets by kind:", doc["counts"], "programs:", doc["counts_programs"])
    ag = doc["agreement"]
    print(f"two judgments: {ag['n_programs']} programs, kappa {ag['kappa']}, agreement {pc(ag['percent_agreement'])},"
          f" unresolved {len(ag['unresolved'])}, category not agreed {len(cat_not_agreed)}")
    print("labels NA:", doc["resolution"]["NA"])
    o = doc["rates"]["overall"]["weighted"]
    for k in ("FP", "FN", "FN_executed"):
        x = o[k]
        print(f"overall {k}: {pc(x['rate'])} (n {x['n']}, 95% {pc(x['ci'][0])}-{pc(x['ci'][1])})")
    for c in MC.CONDS:
        w = doc["rates"]["by_condition"][c]["weighted"]
        print(f"  {c}: FP {pc(w['FP']['rate'])} (n {w['FP']['n']}), FN {pc(w['FN']['rate'])} (n {w['FN']['n']})")
    m = doc["main_effect_bounds"]
    print(f"main effect: delta {100 * m['delta']:.1f}, corrected {100 * m['point']:.1f}, "
          f"[L, U] = [{100 * m['L']:.1f}, {100 * m['U']:.1f}], worst case NA [{100 * m['worst_case_NA']['L']:.1f}, "
          f"{100 * m['worst_case_NA']['U']:.1f}] ({m['design']}, n_D {m['n_D']}, NA {m['n_NA']})")
    print("corrected accuracy:", {c: round(100 * v, 1) for c, v in doc["corrected_accuracy"].items()})
    print("error categories:", {c: {k: v["n"] for k, v in t.items() if v["n"]} for c, t in doc["error_categories"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
