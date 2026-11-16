#!/usr/bin/env python3
"""Wrapper around tools/server_refused.py for a stage the driver retried (written 2026-10-10, after unsealing began).

The frozen tool reads every dependency_blocked event of schedule_events.jsonl. The driver ran each stage up to three
times and appends to the same event file, so an event of an earlier attempt can name a unit that a later attempt
completed (the source unit was refused twice and answered on the third attempt). The frozen check then stops with
"blocked by a unit that was not refused by the server". This wrapper changes one thing: a dependency_blocked event is
ignored when the blocked unit AND its source unit both have a complete unit record now. Everything else, including
the derivation and the scoring, is the frozen code. Run from the repository root:
  python3 <this file> derive --run <stage>/by-model/gptoss-20b.main --cases data/cases/<source>.jsonl --freeze-manifest FREEZE_MANIFEST.json
Prints the resolved events (case ids and conditions only).
"""
import glob
import json
import os
import sys

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "tools"))
import server_refused as SR  # noqa: E402


def classify(run_dir, stage_dir=None):
    entry = os.path.basename(os.path.normpath(run_dir))
    stage_dir = stage_dir or os.path.dirname(os.path.dirname(os.path.normpath(run_dir)))
    refused, complete, problems = set(), set(), []
    for p in sorted(glob.glob(os.path.join(run_dir, "units", "*.json"))):
        if os.path.basename(p) == "setup.json":
            continue
        u = json.load(open(p, encoding="utf-8"))
        if u.get("status") == "complete":
            complete.add(SR._key(u))
            continue
        err = u.get("error") or {}
        if err.get("kind") == "call_failed" and SR.REFUSAL_TEXT in str(err.get("message", "")):
            refused.add(SR._key(u))
        else:
            problems.append(f"{os.path.basename(p)}: incomplete but not a server refusal (status {u.get('status')}, "
                            f"error kind {err.get('kind')})")
    blocked, resolved = set(), set()
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
            if SR._key(src) in refused:
                blocked.add(SR._key(unit))
            elif SR._key(unit) in complete and SR._key(src) in complete:
                resolved.add((SR._key(unit), SR._key(src)))       # an earlier attempt; both units completed later
            else:
                problems.append(f"{unit.get('case_id')}.{unit.get('config_id')}: blocked by a unit that was not "
                                "refused by the server")
    for u, s in sorted(resolved):
        print(f"[resolved_blocks] {u[0]}.{u[1]}: blocked in an earlier attempt by {s[0]}.{s[1]}, both complete now")
    if blocked & complete:
        problems.append("a unit is both blocked by a refused unit and complete: " + str(sorted(blocked & complete)[:3]))
    return {"entry": entry, "refused": sorted(refused), "blocked": sorted(blocked - refused), "problems": problems}


SR.classify = classify
if __name__ == "__main__":
    sys.exit(SR.main())
