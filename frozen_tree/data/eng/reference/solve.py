"""CBC reference solves for the engineering-source cases (E22).

  $ORGENE_PY data/eng/reference/solve.py pglib_uc <instance.json> <out.json> [--time-limit 1800]
  $ORGENE_PY data/eng/reference/solve.py miplib_nl <instance dir> <out.json> [--time-limit 1800]

Writes one reference record (JSON). The CBC log goes next to it as <out>.cbc.log; keep both out of git (they are
raw material; data/ingest_eng.py copies the record into data/eng/reference_values.json).
Isolation: gold material (data/cases/README_ISOLATION.md).
"""
import argparse
import importlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # data/

from eng.reference import cbc  # noqa: E402

REFERENCE_GAP_REL = 1e-7
REFERENCE_TIME_LIMIT_S = 1800  # the 30-minute stop rule of the E22 brief


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def solve_pglib_uc(path, time_limit_s=REFERENCE_TIME_LIMIT_S, log_copy=None):
    from eng.reference import pglib_uc as M
    from eng.reference import pglib_uc_check as K
    inst = json.load(open(path, encoding="utf-8"))
    prob, index = M.build(inst)
    rec, values = cbc.solve(prob, time_limit_s, gap_rel=REFERENCE_GAP_REL, log_copy=log_copy)
    if rec["objective"] is not None:
        sched = M.schedule_from(index, values)
        bad, cost = K.check(inst, sched)
        rec["check"] = {"n_violations": len(bad), "violations_head": bad[:10], "recomputed_objective": cost,
                        "abs_diff": abs(cost - rec["objective"]),
                        "rel_diff": abs(cost - rec["objective"]) / max(1.0, abs(rec["objective"]))}
    return rec


def solve_miplib_nl(inst_dir, time_limit_s=REFERENCE_TIME_LIMIT_S, log_copy=None):
    name = os.path.basename(os.path.normpath(inst_dir))
    mod = importlib.import_module("eng.reference.miplib_nl." + name.replace("-", "_"))
    # a module may solve a stated relaxation instead (build_for_reference), when its optimum provably carries over
    prob = getattr(mod, "build_for_reference", mod.build)(inst_dir)
    rec, _ = cbc.solve(prob, time_limit_s, gap_rel=REFERENCE_GAP_REL, log_copy=log_copy)
    if hasattr(mod, "build_for_reference"):
        rec["model_variant"] = {"note": mod.REFERENCE_NOTE, "carries_over": bool(mod.reference_holds(rec))}
        if not rec["model_variant"]["carries_over"]:
            rec["status"] = "relaxation_not_conclusive"
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["pglib_uc", "miplib_nl"])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--time-limit", type=int, default=REFERENCE_TIME_LIMIT_S)
    a = ap.parse_args(argv)
    started = now_iso()
    fn = solve_pglib_uc if a.kind == "pglib_uc" else solve_miplib_nl
    rec = fn(a.src, a.time_limit, log_copy=a.out + ".cbc.log")
    rec.update({"started_at": started, "finished_at": now_iso(), "solver": "CBC via PuLP PULP_CBC_CMD"})
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2, sort_keys=True)
    print(json.dumps({k: rec.get(k) for k in ("status", "objective", "bound", "gap", "wall_seconds", "cbc_version")}))


if __name__ == "__main__":
    main()
