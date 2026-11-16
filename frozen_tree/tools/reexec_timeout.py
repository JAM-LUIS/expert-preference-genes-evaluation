#!/usr/bin/env python3
"""Re-validate a finished run's model outputs under another execution timeout (E22). No model call.

  $ORGENE_PY tools/reexec_timeout.py --run experiments/<run> --cases data/cases/eng.jsonl --cond C3L \
      [--timeout 600] [--out experiments/<run>.t600] [--configs configs/r1_configs.json] [--genes genes/genes.r1.jsonl]

Default timeout: execution.timeout_s_engineering_cases of configs/model_registry.json (600). Default output
directory: <run>.t<timeout>. The replay rule is in runtime/orgene/reexec.py. A run on sealed cases (test,
eng_holdout) passes the E21 test gate first, exactly like `orgene_cli.py validate`.
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import configs as CF  # noqa: E402
from orgene import data as D  # noqa: E402
from orgene import env as E  # noqa: E402
from orgene import reexec as RX  # noqa: E402
from orgene.paths import rel  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--cond", required=True)
    ap.add_argument("--timeout", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--configs", default=CF.DEFAULT_REGISTRY)
    ap.add_argument("--genes", default=os.path.join(ROOT, "genes", "genes.r1.jsonl"))
    ap.add_argument("--python", default=None)
    a = ap.parse_args(argv)
    timeout = a.timeout or RX.execution_timeouts()["timeout_s_engineering_cases"]
    if not timeout:
        sys.exit("[reexec] no timeout given and the registry has no execution.timeout_s_engineering_cases")
    out = a.out or os.path.normpath(a.run) + f".t{timeout}"
    reg = CF.load_registry(a.configs)
    try:
        c = CF.get_config(reg, a.cond)
    except CF.RegistryError as e:
        sys.exit(f"[reexec] {e}")
    if c.get("pipeline", "standard") != "standard":
        sys.exit(f"[reexec] {c['id']} does not run through the batch path")
    kw = {"gene_scope": c["gene_scope"], "repair": c["repair"], "closing": c["closing"]} if c["validator"] == "gene" else {}
    cases = {x["case_id"]: x for x in D.load_cases(a.cases)}
    from orgene import freeze as FZ
    try:
        FZ.gate_stage("validate", run_dir=a.run, case_ids=None)
    except FZ.GateRefused as e:
        sys.exit(f"[reexec] refused by the test gate: {e}")
    python = a.python or E.orgene_python()
    E.require_env(python)
    s = RX.reexecute(a.run, out, a.cond, cases, a.genes, timeout, act=c["repair"] != "none",
                     max_rounds=c["max_rounds"], python=python, validate_kw=kw)
    print(json.dumps({"out": rel(out), **{k: s[k] for k in ("timeout_s", "n_units", "n_timed_out_final", "n_provisional", "n_diverged")}}, indent=2))


if __name__ == "__main__":
    main()
