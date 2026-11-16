#!/usr/bin/env python3
"""Server-refused units of the second model (preregistration, Section 3: rule fixed 2026-10-06).

The inference server sometimes rejects a gpt-oss response with HTTP 500 "error parsing tool call"; the same request
fails again deterministically. The registered rule: such a unit is recorded as server_refused, counted as not executed
(wrong) in every gpt-oss analysis, and any repair unit that depends on its round 0 is recorded the same way; the number
and problem ids are reported per condition, and every gpt-oss result is also reported excluding the refused problems
(complete case) next to the main rule. The unit executor leaves such units without a final row and never creates the
dependent units, so `score` drops them and paired.py refuses the label. This tool implements the registered rule
without touching the raw outputs.

  $PY tools/server_refused.py derive --run <stage>/by-model/gptoss-20b.main --cases data/cases/<source>.jsonl
                                     [--freeze-manifest FREEZE_MANIFEST.json] [--out <run>.server_refused]
  $PY tools/server_refused.py paired-cc --a C3L@2 --b C3E@2 --refused <dir>/refused.json [...] [--registry ...]
                                     [--set main] [--models gpt-oss:20b] --out paired.cc.json

derive    checks that every incomplete unit of the model entry is a server refusal (error kind call_failed with the
          server's "error parsing tool call" message) and that every unit the schedule blocked depends on a refused
          unit; anything else stops the tool and nothing is written. It then writes <out>/final.<C>.jsonl (the original
          final rows plus one row per refused or blocked unit: no program, done_reason server_refused) and scores them
          with the unchanged scoring code (pipeline.score_condition), so the added rows have the schema of every other
          result row and count as wrong; their `reason` is set to server_refused. <out>/refused.json lists the units
          and problem ids per condition. Register <out> instead of the run directory for the gpt-oss labels.
paired-cc the complete-case comparison: paired.py on the same analysis set without the problems listed in the given
          refused.json files (all conditions, both benchmarks); the output names the set <set>-complete_case.
Prints counts and case ids only.
"""
import argparse
import copy
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime"))
sys.path.insert(0, ROOT)

from orgene import freeze as FZ  # noqa: E402
from orgene import pipeline as P  # noqa: E402
from orgene import refs as R  # noqa: E402
from orgene.conditions import read_jsonl  # noqa: E402

REFUSAL_TEXT = "error parsing tool call"
SCHEMA = "orgene.r1.server_refused.v1"


class RefusalError(RuntimeError):
    pass


def _key(u):
    return (u["case_id"], u["config_id"], int(u.get("repeat", 0)))


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def classify(run_dir, stage_dir=None):
    """{refused: [(case, cond, repeat)], blocked: [...], problems: [...]} for one model entry."""
    entry = os.path.basename(os.path.normpath(run_dir))
    stage_dir = stage_dir or os.path.dirname(os.path.dirname(os.path.normpath(run_dir)))
    refused, problems = set(), []
    for p in sorted(glob.glob(os.path.join(run_dir, "units", "*.json"))):
        if os.path.basename(p) == "setup.json":
            continue
        u = json.load(open(p, encoding="utf-8"))
        if u.get("status") == "complete":
            continue
        err = u.get("error") or {}
        if err.get("kind") == "call_failed" and REFUSAL_TEXT in str(err.get("message", "")):
            refused.add(_key(u))
        else:
            problems.append(f"{os.path.basename(p)}: incomplete but not a server refusal (status {u.get('status')}, "
                            f"error kind {err.get('kind')})")
    blocked = set()
    ev_path = os.path.join(stage_dir, "schedule_events.jsonl")
    if os.path.exists(ev_path):
        for line in open(ev_path, encoding="utf-8"):
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("event") != "dependency_blocked":
                continue
            unit, src = e.get("unit") or {}, e.get("source") or {}
            if unit.get("registry_entry") != entry:
                continue
            if _key(src) in refused:
                blocked.add(_key(unit))
            else:
                problems.append(f"{unit.get('case_id')}.{unit.get('config_id')}: blocked by a unit that was not "
                                "refused by the server")
    return {"entry": entry, "refused": sorted(refused), "blocked": sorted(blocked - refused), "problems": problems}


def derive(run_dir, cases_path, out_dir=None, freeze_manifest=None, overrides="auto", conds=None):
    out_dir = out_dir or os.path.normpath(run_dir) + ".server_refused"
    if os.path.exists(out_dir):
        raise RefusalError(f"{out_dir} exists; nothing is overwritten")
    finals = {os.path.basename(p)[len("final."):-len(".jsonl")]: p
              for p in glob.glob(os.path.join(run_dir, "final.*.jsonl"))}
    conds = conds or sorted(finals)
    case_ids = sorted({r["case_id"] for c in conds for r in read_jsonl(finals[c])})
    cfg = json.load(open(os.path.join(run_dir, "run_config.json"), encoding="utf-8"))
    cls = classify(run_dir)
    if cls["problems"]:
        raise RefusalError("; ".join(cls["problems"][:10]))
    missing = {k for k in cls["refused"] + cls["blocked"]}
    case_ids = sorted(set(case_ids) | {k[0] for k in missing})
    FZ.gate_stage("score", run_dir=out_dir, case_ids=case_ids, split=cfg.get("split"))
    cases = {c["case_id"]: c for c in R.load_scoring_cases(cases_path, overrides=overrides,
                                                            freeze_manifest=freeze_manifest)}
    os.makedirs(out_dir, exist_ok=True)
    added = {}
    for c in conds:
        rows = read_jsonl(finals[c])
        have = {(r["case_id"], int(r.get("repeat", 0))) for r in rows}
        extra = sorted((k[0], k[2]) for k in missing if k[1] == c)
        clash = [x for x in extra if x in have]
        if clash:
            raise RefusalError(f"{c}: refused or blocked unit(s) already have a final row: {clash[:3]}")
        for cid, rep in extra:
            rows.append({"case_id": cid, "repeat": rep, "condition": c, "code": "", "has_code": False,
                         "gen_ok": False, "done_reason": "server_refused", "exec": {}, "rounds": [],
                         "provisional": False, "hard_failed_genes": [], "soft_failed_genes": []})
        _write_jsonl(os.path.join(out_dir, f"final.{c}.jsonl"), sorted(rows, key=lambda r: (r["case_id"], r["repeat"])))
        P.score_condition(out_dir, c, cases)
        res_path = os.path.join(out_dir, f"results.{c}.jsonl")
        res = read_jsonl(res_path)
        mark = set(extra)
        for r in res:
            if (r["case_id"], int(r.get("repeat", 0))) in mark:
                if r["correct"]:
                    raise RefusalError(f"{c}: a refused unit scored correct")
                r["reason"] = "server_refused"
        _write_jsonl(res_path, res)
        added[c] = [{"case_id": cid, "repeat": rep,
                     "kind": "refused" if (cid, c, rep) in set(cls["refused"]) else "blocked"} for cid, rep in extra]
    # unit records of the complete units only (links): the registry reads each record's round-0 call for the shared
    # round-0 hash, and a refused unit has no round-0 call; its added row carries no hash
    src_units = os.path.join(run_dir, "units")
    if os.path.isdir(src_units):
        dst_units = os.path.join(out_dir, "units")
        os.makedirs(dst_units)
        refused_names = {f"{cid}.{c}.r{rep}.json" for cid, c, rep in cls["refused"]}
        for p in sorted(glob.glob(os.path.join(src_units, "*.json"))):
            if os.path.basename(p) in refused_names:
                continue
            os.symlink(os.path.relpath(p, dst_units), os.path.join(dst_units, os.path.basename(p)))
    for name in ("run_config.json",):
        src = os.path.join(run_dir, name)
        if os.path.exists(src):
            with open(src, "rb") as f, open(os.path.join(out_dir, name), "wb") as g:
                g.write(f.read())
    problems_ids = sorted({k[0] for k in missing})
    doc = {"schema": SCHEMA, "entry": cls["entry"], "source_run": os.path.relpath(run_dir, ROOT),
           "rule": "preregistration Section 3 (2026-10-06): server_refused units and their dependent repair units "
                   "count as wrong; complete-case results exclude these problems",
           "refused": [list(k) for k in cls["refused"]], "blocked": [list(k) for k in cls["blocked"]],
           "added_rows": added, "problem_ids": problems_ids,
           "counts": {"refused": len(cls["refused"]), "blocked": len(cls["blocked"]), "problems": len(problems_ids)}}
    with open(os.path.join(out_dir, "refused.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, indent=1) + "\n")
    print(f"[server_refused] {cls['entry']}: refused {len(cls['refused'])}, blocked {len(cls['blocked'])}, "
          f"problems {len(problems_ids)}: {' '.join(problems_ids)}")
    for c in conds:
        m = json.load(open(os.path.join(out_dir, f"metrics.{c}.json"), encoding="utf-8"))
        print(f"  {c}: n={m['n']} added={len(added[c])} accuracy={m['accuracy']} ({m['n_correct']}/{m['n']})")
    print(f"  -> {os.path.relpath(out_dir, ROOT)}")
    return doc


def paired_cc(argv_paired, refused_files, set_name, out):
    sys.path.insert(0, os.path.join(ROOT, "analysis", "r1"))
    import paired as PA  # noqa: E402
    import registry as RG  # noqa: E402
    from common import write_json, labelled_path  # noqa: E402
    drop = set()
    for p in refused_files:
        drop |= set(json.load(open(p, encoding="utf-8"))["problem_ids"])
    args = PA.parser().parse_args(argv_paired + ["--set", set_name, "--out", out])
    reg = RG.load_registry(args.registry, superseded_path=args.superseded)
    matrix = RG.build_matrix(reg, labels=[args.a, args.b], models=args.models)
    dev = matrix.label == "DEV"
    aset = copy.deepcopy(RG.resolve_set(RG.set_name_for(matrix.label, args.set, args.incl_0905),
                                        allow_pending=args.allow_pending and dev))
    aset["ids"] = [c for c in aset["ids"] if c not in drop]
    aset["by_benchmark"] = {b: [c for c in ids if c not in drop] for b, ids in aset["by_benchmark"].items()}
    aset["name"] = aset["name"] + "-complete_case"
    aset["dropped_server_refused"] = sorted(drop)
    doc = PA.run(args, matrix=matrix, aset=aset)
    doc["analysis_set"]["name"] = aset["name"]
    doc["analysis_set"]["n"] = len(aset["ids"])
    doc["analysis_set"]["dropped_server_refused"] = sorted(drop)
    doc["generated_by"] = "tools/server_refused.py paired-cc (paired.py on the complete-case set)"
    path = write_json(labelled_path(out, doc["data"]), doc)
    print(f"[server_refused] complete case: set {aset['name']} n={len(aset['ids'])} (dropped {len(drop)}) -> {path}")
    for r in doc["results"]:
        print(f"  {r['model']} {r['a']} vs {r['b']} {r['scope']}: n={r['n']} diff={r['diff']} ci={r['ci']} "
              f"W/T/L={r['wins']}/{r['ties']}/{r['losses']} p={r['mcnemar_exact_p']}")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("derive")
    d.add_argument("--run", required=True)
    d.add_argument("--cases", required=True)
    d.add_argument("--cond", nargs="*")
    d.add_argument("--out")
    d.add_argument("--freeze-manifest")
    d.add_argument("--overrides", default="auto")
    c = sub.add_parser("paired-cc")
    c.add_argument("--refused", nargs="+", required=True)
    c.add_argument("--set", default="main")
    c.add_argument("--out", required=True)
    a, rest = ap.parse_known_args(argv)
    try:
        if a.cmd == "derive":
            if rest:
                ap.error(f"unknown arguments {rest}")
            derive(a.run, a.cases, a.out, a.freeze_manifest, a.overrides, a.cond)
        else:
            paired_cc(rest, a.refused, a.set, a.out)
    except (RefusalError, FZ.GateRefused, R.OverrideError) as x:
        print(f"[server_refused] REFUSED: {x}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
