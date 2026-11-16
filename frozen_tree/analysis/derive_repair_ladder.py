#!/usr/bin/env python3
"""Cut the repair ladder from one finished run of a repairing configuration, with no model calls and no re-execution.

  $ORGENE_PY analysis/derive_repair_ladder.py --run <run-dir> --cases <cases.jsonl> --cond C3L [--points 0 1]

Every repairing configuration (C3, C3L, C3E, C2E) runs to at most 2 repair rounds (D8). For each k in --points this
writes <run>-r<k>/ with final.<cond>.jsonl cut at k repair rounds (runtime/orgene/ladder.py), a manifest
ladder.<cond>.json, and the scored results.<cond>.jsonl / metrics.<cond>.json / report.md. The source run keeps the
full two-round result and gets conflicts.<cond>.json (gene pairs fixed -> newly failing, units that did not converge).

Replaces v5's derive_repair_ladder.sh, which copied the run and re-executed every program with a lower --max-rounds:
the cut reads the validated records the run already holds, so every ladder point comes from exactly the same model
outputs and the same executions.
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import data as D  # noqa: E402
from orgene import ladder as L  # noqa: E402
from orgene import pipeline as P  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--cond", required=True)
    ap.add_argument("--points", type=int, nargs="+", default=[0, 1], help="ladder points k (at most k repair rounds)")
    ap.add_argument("--rel-tol", type=float, default=1e-4)
    ap.add_argument("--abs-tol", type=float, default=1e-4)
    a = ap.parse_args(argv)

    run = a.run.rstrip("/")
    cases = {c["case_id"]: c for c in D.load_cases(a.cases)}
    final = L.read_final(run, a.cond)
    summary = L.conflict_summary(final)
    with open(os.path.join(run, f"conflicts.{a.cond}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"[ladder] {a.cond}: {summary['n_conflict_events']} conflict events, "
          f"{summary['n_not_converged']} of {summary['n_units']} units not converged")
    for k in sorted(set(a.points)):
        dst = f"{run}-r{k}"
        man = L.derive_run(run, a.cond, k, dst)
        m = P.score_condition(dst, a.cond, cases, rel_tol=a.rel_tol, abs_tol=a.abs_tol)
        P.report(dst)
        print(f"[ladder] {os.path.basename(dst)}: at most {k} repair rounds, {man['n_cut_at_k']} of {man['n_units']} "
              f"units cut, mean calls {m.get('mean_calls')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
