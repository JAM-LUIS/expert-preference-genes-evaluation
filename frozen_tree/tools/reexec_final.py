#!/usr/bin/env python3
"""Re-execute the final programs of a unit-executor run under a longer time limit and score them (engineering-source
set: preregistration "scored at the 60-second limit ... and again after re-executing the same programs with a
600-second limit"). No model call.

  $PY tools/reexec_final.py --run <stage>/by-model/<entry> --cases data/cases/eng.jsonl [--cond C0 C3E C3L]
                            [--timeout 600] [--jobs 2] [--freeze-manifest FREEZE_MANIFEST.json] [--out <run>.final_t600]

tools/reexec_timeout.py replays a runner directory (requests.<C>.jsonl, gen.<C>.*); the scheduler's unit executor
writes final.<C>.jsonl and unit records instead, so that tool cannot read a campaign stage. This tool takes the final
program of every unit (final.<C>.jsonl, field `code`), runs it with the unchanged executor (execute.run_program) under
--timeout, and writes <out>/final.<C>.jsonl with the new execution record (the original one is kept under
`exec_original`) and <out>/results.<C>.jsonl scored by the unchanged scoring code (pipeline.score_condition), with the
same references as the 60-second scoring. Repairs are not replayed: a program that timed out at 60 s and would have
triggered a repair is re-executed as it stands; such units are counted in reexec.json. A run on sealed cases passes the
test gate first. Prints counts and case ids only.
"""
import argparse
import concurrent.futures as cf
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import freeze as FZ  # noqa: E402
from orgene import pipeline as P  # noqa: E402
from orgene import refs as R  # noqa: E402
from orgene.conditions import read_jsonl  # noqa: E402
from orgene.execute import run_program  # noqa: E402


SCHEMA = "orgene.r1.reexec_final.v1"


def default_timeout():
    try:
        reg = json.load(open(os.path.join(ROOT, "configs", "model_registry.json"), encoding="utf-8"))
        return int(reg["execution"]["timeout_s_engineering_cases"])
    except Exception:  # noqa: BLE001
        return 600


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def reexec(run_dir, cases_path, conds=None, timeout=None, jobs=2, out_dir=None, freeze_manifest=None,
           overrides="auto", python=None):
    timeout = timeout or default_timeout()
    out_dir = out_dir or os.path.normpath(run_dir) + f".final_t{timeout}"
    if os.path.exists(out_dir):
        raise FileExistsError(f"{out_dir} exists; nothing is overwritten")
    finals = {os.path.basename(p)[len("final."):-len(".jsonl")]: p
              for p in glob.glob(os.path.join(run_dir, "final.*.jsonl"))}
    conds = conds or sorted(finals)
    missing = [c for c in conds if c not in finals]
    if missing:
        raise FileNotFoundError(f"no final.<C>.jsonl for {missing} in {run_dir}")
    rows_by = {c: read_jsonl(finals[c]) for c in conds}
    cfg_path = os.path.join(run_dir, "run_config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {}
    case_ids = sorted({r["case_id"] for rows in rows_by.values() for r in rows})
    FZ.gate_stage("validate", run_dir=out_dir, case_ids=case_ids, split=cfg.get("split"))
    cases = {c["case_id"]: c for c in R.load_scoring_cases(cases_path, overrides=overrides,
                                                            freeze_manifest=freeze_manifest)}
    os.makedirs(out_dir, exist_ok=True)
    jobs_list = [(c, i, r) for c in conds for i, r in enumerate(rows_by[c]) if r.get("code")]

    def work(item):
        c, i, r = item
        return c, i, run_program(r["code"], timeout=timeout, python=python)

    started = P.now_iso()
    with cf.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for c, i, res in ex.map(work, jobs_list):
            r = rows_by[c][i]
            r["exec_original"] = r.get("exec")
            r["exec"] = res
            r["exec_timeout_s"] = timeout
    summary = {"schema": SCHEMA, "source_run": os.path.relpath(run_dir, ROOT), "timeout_s": timeout, "jobs": jobs,
               "started_at": started, "finished_at": P.now_iso(),
               "rule": "final program of every unit re-executed as it stands; repairs not replayed", "conditions": {}}
    for c in conds:
        rows = rows_by[c]
        _write_jsonl(os.path.join(out_dir, f"final.{c}.jsonl"), rows)
        m = P.score_condition(out_dir, c, cases)
        before = {(r["case_id"], r["repeat"]): r for r in read_jsonl(os.path.join(run_dir, f"results.{c}.jsonl"))} \
            if os.path.exists(os.path.join(run_dir, f"results.{c}.jsonl")) else {}
        after = {(r["case_id"], r["repeat"]): r for r in read_jsonl(os.path.join(out_dir, f"results.{c}.jsonl"))}
        timed0 = sorted(f"{r['case_id']}#{r['repeat']}" for r in rows if (r.get("exec_original") or {}).get("timed_out"))
        timed1 = sorted(f"{r['case_id']}#{r['repeat']}" for r in rows if (r.get("exec") or {}).get("timed_out"))
        changed = sorted(f"{k[0]}#{k[1]}" for k in after if k in before and before[k]["correct"] != after[k]["correct"])
        no_code = sorted(f"{r['case_id']}#{r['repeat']}" for r in rows if not r.get("code"))
        summary["conditions"][c] = {"n": m["n"], "n_correct": m["n_correct"], "accuracy": m["accuracy"],
                                    "timed_out_at_original_limit": timed0, "timed_out_now": timed1,
                                    "correct_changed": changed, "no_program": no_code}
        print(f"[reexec_final] {c}: n={m['n']} correct {m['n_correct']} (timed out: {len(timed0)} -> {len(timed1)}; "
              f"verdict changed: {' '.join(changed) or 'none'})")
    with open(os.path.join(out_dir, "reexec.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(summary, indent=1) + "\n")
    print(f"  -> {os.path.relpath(out_dir, ROOT)}")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--cond", nargs="*")
    ap.add_argument("--timeout", type=int)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--out")
    ap.add_argument("--freeze-manifest")
    ap.add_argument("--overrides", default="auto")
    ap.add_argument("--python")
    a = ap.parse_args(argv)
    try:
        reexec(a.run, a.cases, a.cond, a.timeout, a.jobs, a.out, a.freeze_manifest, a.overrides, a.python)
    except (FileExistsError, FileNotFoundError, FZ.GateRefused, R.OverrideError) as x:
        print(f"[reexec_final] REFUSED: {x}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
