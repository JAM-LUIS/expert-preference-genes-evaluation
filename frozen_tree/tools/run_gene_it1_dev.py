#!/usr/bin/env python3
"""Run iteration 1 (author-approved clause review): one-case rehearsal, then dev55, sequentially.

Conditions C0, C3L and C3 only; C3E repair messages are unchanged under it1 (offline replay).

Development only. Each stage uses the ordinary registry, token and freeze gates.
An incomplete stage or missing local token count stops the campaign.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from orgene.paths import neutral_home

CONDS = ("C0", "C3L", "C3")


def check_stage(run, n_cases, predicate_sha):
    rows = []
    for p in (run / "units").glob("*.json"):
        row = json.loads(p.read_text())
        if p.name == "setup.json" and row.get("schema_version") == "orgene.r1.unit_setup.v1":
            continue
        if row.get("schema_version") != "orgene.r1.unit.v1":
            raise RuntimeError(f"unexpected unit artifact: {p.name}")
        rows.append(row)
    if len(rows) != n_cases * len(CONDS):
        raise RuntimeError(f"{run.name}: expected {n_cases * len(CONDS)} units, got {len(rows)}")
    by_key = {(r["case_id"], r["config_id"]): r for r in rows}
    case_ids = {r["case_id"] for r in rows}
    if len(case_ids) != n_cases or set(by_key) != {(c, cfg) for c in case_ids for cfg in CONDS}:
        raise RuntimeError(f"{run.name}: incomplete condition pairing")
    for r in rows:
        if r["status"] != "complete" or r["tokens"]["local"]["n_calls_missing"] != 0:
            raise RuntimeError(f"{r['unit_id']}: incomplete execution or missing local tokens")
        if len(r["rounds"]) > 3 or not r["local_tokenizer"]:
            raise RuntimeError(f"{r['unit_id']}: invalid rounds/tokenizer")
        if predicate_sha not in r["code_sha256"].values():
            raise RuntimeError(f"{r['unit_id']}: approved predicate code not recorded")
        if r["config_id"] == "C3L":
            src = by_key[(r["case_id"], "C0")]
            if r["round0"]["reused_from"]["unit_id"] != src["unit_id"]:
                raise RuntimeError(f"{r['unit_id']}: mismatched round-0 source")
    return {"units": len(rows), "cases": n_cases, "local_token_counts_complete": True,
            "shared_round0_verified": True, "approved_predicate_hash_verified": True}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", required=True, help="new basename for experiments/<campaign>")
    a = ap.parse_args()
    if Path(a.campaign).name != a.campaign or "dev" not in a.campaign or "test" in a.campaign:
        ap.error("campaign must be a dev basename, without 'test'")
    os.chdir(ROOT)
    env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    manifest = json.loads((ROOT / "configs/gene_iteration.it1.json").read_text())
    for name, sha in manifest["runtime_sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha:
            raise RuntimeError(f"approved artifact changed: {name}")
    campaign = ROOT / "experiments" / a.campaign
    campaign.mkdir(parents=True, exist_ok=False)
    state = {"state": "starting", "pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat(),
             "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], env=env, text=True).strip(),
             "model_registry_entry": "qwen3-8b.main", "iteration": manifest, "stages": []}

    def save():
        tmp = campaign / "status.tmp"
        tmp.write_text(json.dumps(state, indent=2) + "\n")
        tmp.replace(campaign / "status.json")

    save()
    stages = [("smoke-mamo1", "mamo_complex_lp", "mamo_main_clean111_excl0905", 1, True),
              ("mamo30", "mamo_complex_lp", "mamo_main_clean111_excl0905", 30, False),
              ("industry25", "industryor", "industryor_main_rev2026_100_excl0905", 25, False)]
    try:
        for label, benchmark, split_dir, count, smoke in stages:
            run = campaign / label
            cmd = [sys.executable, "runtime/unit_runner.py", "--run", str(run.relative_to(ROOT)),
                   "--cases", f"data/cases/{benchmark}.jsonl", "--split-dir", f"data/splits_r1/{split_dir}",
                   "--split", "dev", "--cond", *CONDS, "--genes", manifest["genes"],
                   "--lexicon", manifest["lexicon"], "--registry-entry", "qwen3-8b.main",
                   "--local-tokens", "on", "--export-validated"]
            if smoke:
                cmd += ["--limit", "1"]
            stage = {"label": label, "state": "running", "command": cmd}
            state["stages"].append(stage)
            state["state"] = "running"
            save()
            print(f"[campaign] start {label}", flush=True)
            with (campaign / f"{label}.log").open("w") as log:
                subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            stage["audit"] = check_stage(run, count, manifest["runtime_sha256"]["runtime/orgene/predicates_it0.py"])
            stage["state"] = "complete"
            save()
            print(f"[campaign] verified {label}: {stage['audit']}", flush=True)
        state["state"] = "complete"
        state["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
    except Exception as exc:
        state["state"] = "failed"
        state["error"] = neutral_home(str(exc))
        save()
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[campaign] failed: {type(exc).__name__}: {neutral_home(str(exc))}", file=sys.stderr)
        sys.exit(1)
