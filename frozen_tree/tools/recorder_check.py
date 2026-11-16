#!/usr/bin/env python3
"""Check that the solve recorder does not change what a program does (E12; dev rehearsal check 9).

  /opt/homebrew/bin/python3 tools/recorder_check.py RUN_DIR [RUN_DIR ...] [--cond C0 C2 ...] [--round 0]
                                                    [--out FILE] [--timeout 60] [--splits-root data/splits]

For every program in RUN_DIR/validated.<cond>.round<round>.jsonl the program is executed twice through
execute.run_program: without the recorder and with it. Compared: return code, timed_out, stdout, stderr (the
per-call temp directory names masked), and the parsed STATUS / FINAL_OBJECTIVE. When stdout differs, the program is
run a second time without the recorder; if the two plain runs differ as well, the program's own output is not
deterministic (for example a CBC log with timings and temp file names), and it is compared after masking those.

Dev only: a run directory whose name contains "-test-", or any record whose case_id is listed in a
<splits-root>/*/test_ids.json, stops the check before anything is executed (exit 2). The output lists case ids,
counts and flags only; no program text, output or problem text.
"""
import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene.conditions import read_jsonl  # noqa: E402
from orgene.execute import run_program  # noqa: E402
from orgene.paths import rel  # noqa: E402

_TMP_RE = re.compile(r"orgene_(exec|rec)_[A-Za-z0-9_]+")
_CBC_TMP_RE = re.compile(r"[0-9a-f]{16,}-pulp\.(mps|lp|sol|mst)")
_NUM_RE = re.compile(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?")
_TIMING_LINE = re.compile(r"(time|seconds|wallclock)", re.IGNORECASE)


def mask_tmp(s):
    return _TMP_RE.sub(r"orgene_\1_X", s or "")


def normalize(s):
    """Mask what varies between two plain runs of the same program: temp names and numbers on timing lines."""
    out = []
    for line in _CBC_TMP_RE.sub(r"X-pulp.\1", mask_tmp(s)).splitlines():
        out.append(_NUM_RE.sub("N", line) if _TIMING_LINE.search(line) else line)
    return "\n".join(out)


def refuse(msg):
    sys.stderr.write(f"[recorder_check] refused: {msg}\n")
    raise SystemExit(2)


def load_test_ids(splits_root):
    """All test case ids under splits_root. Fails closed: no test id list means test cases cannot be ruled out."""
    ids = set()
    for p in glob.glob(os.path.join(splits_root, "*", "test_ids.json")):
        with open(p, "r", encoding="utf-8") as f:
            ids.update(str(x) for x in json.load(f))
    if not ids:
        refuse(f"no test ids under {rel(splits_root)}/*/test_ids.json, so test cases cannot be ruled out")
    return ids


def collect(run_dirs, conds, rnd, test_ids):
    """(run_dir, record) pairs to check. Exits with 2 on anything that belongs to test."""
    items = []
    for d in run_dirs:
        if "-test-" in os.path.basename(os.path.normpath(d)) or "-test-" in d:
            refuse(f"{rel(d)} is a test run directory (dev only)")
        pats = [os.path.join(d, f"validated.{c}.round{rnd}.jsonl") for c in conds] if conds else \
            sorted(glob.glob(os.path.join(d, f"validated.*.round{rnd}.jsonl")))
        for p in pats:
            if not os.path.exists(p):
                continue
            for r in read_jsonl(p):
                if str(r.get("case_id")) in test_ids:
                    refuse(f"{rel(p)} holds a test case id (dev only)")
                items.append((d, r))
    return items


def compare(code, timeout):
    a = run_program(code, timeout=timeout, record_solves=False)
    b = run_program(code, timeout=timeout, record_solves=True)
    fields = ("returncode", "timed_out", "status", "objective", "exec_ok", "protocol_ok")
    same_fields = all(a.get(k) == b.get(k) for k in fields)
    same_err = mask_tmp(a["stderr_tail"]) == mask_tmp(b["stderr_tail"])
    same_out = a["stdout_tail"] == b["stdout_tail"]
    verdict = "identical" if (same_fields and same_err and same_out) else "different"
    plain_deterministic = None
    if same_fields and not (same_err and same_out):
        c = run_program(code, timeout=timeout, record_solves=False)
        plain_deterministic = (a["stdout_tail"] == c["stdout_tail"]
                               and mask_tmp(a["stderr_tail"]) == mask_tmp(c["stderr_tail"]))
        if not plain_deterministic and normalize(a["stdout_tail"]) == normalize(b["stdout_tail"]) \
                and normalize(a["stderr_tail"]) == normalize(b["stderr_tail"]):
            verdict = "identical_after_normalization"
    summ = b.get("solve_recorder") or {}
    return {"verdict": verdict, "same_fields": same_fields, "same_stdout": same_out, "same_stderr": same_err,
            "plain_deterministic": plain_deterministic, "timed_out": bool(b.get("timed_out")),
            "recorded": summ.get("recorded"), "fallback": summ.get("fallback"), "n_solves": summ.get("n_solves")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--cond", nargs="*", default=None)
    ap.add_argument("--round", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--splits-root", default=os.path.join(ROOT, "data", "splits"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    test_ids = load_test_ids(a.splits_root)
    items = collect(a.run_dirs, a.cond, a.round, test_ids)
    per, counts = [], {"identical": 0, "identical_after_normalization": 0, "different": 0, "no_program": 0}
    for d, r in items:
        code = r.get("code")
        row = {"run": os.path.basename(os.path.normpath(d)), "case_id": r.get("case_id"),
               "condition": r.get("condition"), "repeat": r.get("repeat")}
        if not code:
            counts["no_program"] += 1
            row["verdict"] = "no_program"
        else:
            row.update(compare(code, a.timeout))
            counts[row["verdict"]] += 1
        per.append(row)
    report = {"n_records": len(items), "counts": counts, "round": a.round,
              "different": [(p["run"], p["case_id"], p["condition"], p["repeat"]) for p in per
                            if p["verdict"] == "different"],
              "per_program": per}
    text = json.dumps(report, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(json.dumps({"n_records": report["n_records"], "counts": counts}, indent=1))
    return 0 if counts["different"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
