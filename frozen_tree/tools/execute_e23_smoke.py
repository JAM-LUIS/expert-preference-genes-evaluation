#!/usr/bin/env python3
"""Execute the authorized one-case author smoke, once; preserve every failure.

Run only in the coordinator's approved single-model window. No dev20 or test
execution is implemented. Uses existing registry/settings/dependencies verbatim.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

from run_e23_dev_acceptance import ROOT, ENTRY_ID, MODEL, verify_approval, prepare_smoke, audit_run, sha_file


def now():
    return datetime.now(timezone.utc).isoformat()


def claim_recovery(root, campaign, prior_campaign):
    """Claim one zero-generation recovery, without changing the original evidence.

    A claim survives a crash. Subsequent launches must stop for review rather
    than claim the same failed preflight again. Existing recovery journals also
    block launches, including journals created before this guard was added.
    """
    root = Path(root)
    if Path(campaign).name != campaign or "dev" not in campaign or "test" in campaign:
        raise RuntimeError("recovery campaign must be a new development basename")
    if Path(prior_campaign).name != prior_campaign or "dev" not in prior_campaign or "test" in prior_campaign:
        raise RuntimeError("prior campaign must be a development basename")
    experiments = root / "experiments"
    if (experiments / campaign).exists():
        raise RuntimeError("recovery campaign already exists")
    previous = experiments / prior_campaign / "status.json"
    prior = json.loads(previous.read_text())
    stages = prior.get("stages") if isinstance(prior, dict) else None
    if not isinstance(stages, list) or any(not isinstance(s, dict) for s in stages):
        raise RuntimeError("prior campaign has no valid stage journal")
    if prior.get("state") != "failed" or any(
        s.get("label") in ("generation", "server-token-comparison") for s in stages
    ):
        raise RuntimeError("only a stopped preflight without a generation stage can be recovered")
    for status in experiments.glob("*/status.json"):
        journal = json.loads(status.read_text())
        if (journal.get("recovery_of") or {}).get("campaign") == prior_campaign:
            raise RuntimeError("an existing recovery campaign already consumed this preflight")
    recovery = {"campaign": prior_campaign, "status_sha256": sha_file(previous), "reason": prior.get("error"),
                "generation_stages_in_prior": 0}
    claim = dict(recovery, recovery_campaign=campaign, claimed_at=now())
    try:
        with (previous.parent / "recovery.claim.json").open("x") as handle:
            json.dump(claim, handle, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise RuntimeError("this preflight already has a recovery claim") from exc
    return recovery


def resource_snapshot():
    with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=30) as response:
        ps = json.load(response)
    if not isinstance(ps, dict) or not isinstance(ps.get("models"), list):
        raise RuntimeError("malformed model-occupancy response; no model operation permitted")
    processes = []
    own_helpers = []
    me = os.getpid()
    listing = subprocess.check_output(["ps", "ax", "-o", "pid=,ppid=,command="], text=True)
    for line in listing.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit():
            continue
        pid, ppid, command = int(fields[0]), int(fields[1]), fields[2]
        markers = [m for m in ("llama-server", "runtime/unit_runner.py", "runtime/ollama_runner.py",
                               "run_gene_it0_dev.py", "alphaopt/run", "tools/gptoss_tokenizer_check.py",
                               "tools/execute_e23_smoke.py") if m in command]
        # On this host caffeinate execs the driver and forks a helper child.
        # Accept only this driver's related helper (or the parent on a fork-style host),
        # with both executable name and this script name verified. Other runners remain occupied.
        own_caffeinate = Path(command.split()[0]).name == "caffeinate" and Path(__file__).name in command and \
            (pid == os.getppid() or ppid == me)
        if own_caffeinate:
            own_helpers.append({"pid": pid, "ppid": ppid, "relation": "parent" if pid == os.getppid() else "child"})
        if pid != me and not own_caffeinate and markers:
            processes.append({"pid": pid, "ppid": ppid, "markers": markers})
    result = {"at": now(), "models": ps["models"], "competing_processes": processes,
              "own_caffeinate_helpers": own_helpers}
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--recovery-of", help="previous failed campaign with zero generation stages; never a model resample")
    args = ap.parse_args()
    os.chdir(ROOT)
    env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    recovery = None
    if args.recovery_of:
        recovery = claim_recovery(ROOT, args.campaign, args.recovery_of)
    plan = prepare_smoke(args.campaign)  # refuses existing directories: cannot accidentally rerun/resample
    campaign = ROOT / "experiments" / args.campaign
    state = {"state": "starting", "pid": os.getpid(), "started_at": now(), "mode": "author_smoke_only",
             "source_main": "74b6c0b", "source_e23": "d4e5f28", "registry_entry": ENTRY_ID, "stages": [], "plan": plan,
             "recovery_of": recovery}

    def save():
        tmp = campaign / "status.tmp"
        tmp.write_text(json.dumps(state, indent=2) + "\n")
        tmp.replace(campaign / "status.json")

    def stage(label, command):
        row = {"label": label, "state": "running", "started_at": now(), "command": command}
        state["stages"].append(row)
        state["state"] = "running"
        save()
        with (campaign / f"{label}.log").open("x") as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        row.update(state="passed" if result.returncode == 0 else "failed", returncode=result.returncode, finished_at=now())
        save()
        if result.returncode:
            raise RuntimeError(f"{label} failed with exit {result.returncode}; original log preserved")

    def idle(label):
        snapshot = resource_snapshot()
        (campaign / f"resources.{label}.json").write_text(json.dumps(snapshot, indent=2) + "\n")
        if snapshot["models"] or snapshot["competing_processes"]:
            raise RuntimeError(f"resource window occupied before {label}; no model called or unloaded")

    save()
    try:
        verify_approval()
        py = sys.executable
        stage("registry-validate", [py, "tools/model_registry.py", "validate"])
        stage("venv-tools", [py, "tools/venv_tools_check.py"])
        stage("registry-live-quick", [py, "tools/model_registry.py", "check", "--quick", "--entry", ENTRY_ID])
        idle("generation")
        stage("generation", plan["command"])
        request = campaign / "requests.C0.jsonl"
        audit = audit_run(campaign / "smoke", campaign / "roster.json", request)
        (campaign / "audit.units.json").write_text(json.dumps(audit, indent=2) + "\n")
        unit_path = next((campaign / "smoke/units").glob("smoke-0001.C0.r0.json"))
        unit = json.loads(unit_path.read_text())
        ex = unit["final_row"].get("exec") or {}
        # A failed author smoke is retained. This does not create a CP1 gate for development datasets.
        passed_smoke = ex.get("exec_ok") is True and ex.get("protocol_ok") is True and ex.get("status") == "Optimal" and \
            isinstance(ex.get("objective"), (int, float)) and abs(ex["objective"] - 2600) <= 1e-4
        state["smoke_execution"] = {"exec_ok": ex.get("exec_ok"), "protocol_ok": ex.get("protocol_ok"),
                                    "status": ex.get("status"), "objective": ex.get("objective"),
                                    "expected_objective": 2600, "passed": passed_smoke}
        save()
        if not passed_smoke:
            raise RuntimeError("author smoke execution/protocol/objective failed; no retry or resampling")
        idle("server-token-comparison")
        stage("server-token-comparison", [".venv-tools/bin/python", "tools/gptoss_tokenizer_check.py", "server",
              "--model", MODEL, "--requests", str(request.relative_to(ROOT)), "--think", "low", "--keep-alive", "0",
              "--out", str((campaign / "audit.server_tokens.json").relative_to(ROOT))])
        comparison = json.loads((campaign / "audit.server_tokens.json").read_text())
        if comparison.get("ok") is not True or comparison.get("n_prompts") != 1:
            raise RuntimeError("one-prompt live server token comparison did not pass")
        state.update(state="complete", finished_at=now(), engineering_audit=audit,
                     dev20="not_started; final gene, current o200k C1 report, fixed dev roster prerequisites")
        save()
        print(json.dumps({k: state[k] for k in ("state", "finished_at", "smoke_execution", "dev20")}), flush=True)
        return 0
    except Exception as exc:
        state.update(state="failed", error=f"{type(exc).__name__}: {exc}", finished_at=now())
        save()
        print(json.dumps({k: state[k] for k in ("state", "error", "finished_at")}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
