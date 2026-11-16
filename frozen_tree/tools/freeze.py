#!/usr/bin/env python3
"""Freeze manifest and test gate (E21). Library: runtime/orgene/freeze.py.

  PY=/opt/homebrew/bin/python3
  $PY tools/freeze.py make [--spec configs/freeze_spec.json] [--out FREEZE_MANIFEST.json] [--anon-terms FILE]
                           [--allow-incomplete] [--allow-no-terms] [--supersede]
  $PY tools/freeze.py verify [--manifest FREEZE_MANIFEST.json] [--require-complete] [--require-osf] [--json]
  $PY tools/freeze.py register --osf <GUID | osf.io URL | OSF DOI> [--manifest ...]
  $PY tools/freeze.py gate [--stage NAME] [--record-dir DIR]      # exit 0 only if a sealed stage may run
  $PY tools/freeze.py sealed-run <run dir>                        # exit 3 if the run touches sealed cases

Order at the freeze: commit everything -> make -> commit the manifest -> upload to OSF -> register -> commit.
`make` refuses when a required item is missing (--allow-incomplete writes a rehearsal manifest with complete=false,
which the gate never accepts), when the neutral-writing scan has any hit, or when it would replace a registered
manifest (--supersede keeps the chain in `supersedes`). Output: paths, hashes and counts only.
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import freeze as FZ  # noqa: E402


def _abs(p):
    return p if p is None or os.path.isabs(p) else os.path.join(os.getcwd(), p)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="freeze", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("make")
    p.add_argument("--spec", default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--anon-terms", default=None, help="identity terms file for the neutral-writing scan (kept outside git)")
    p.add_argument("--allow-incomplete", action="store_true", help="rehearsal: write complete=false instead of refusing")
    p.add_argument("--allow-no-terms", action="store_true", help="rehearsal: scan without an identity terms file")
    p.add_argument("--supersede", action="store_true", help="replace a registered manifest (recorded in supersedes)")
    p = sub.add_parser("verify")
    p.add_argument("--manifest", default=None)
    p.add_argument("--require-complete", action="store_true")
    p.add_argument("--require-osf", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("register")
    p.add_argument("--manifest", default=None)
    p.add_argument("--osf", required=True)
    p = sub.add_parser("gate")
    p.add_argument("--manifest", default=None)
    p.add_argument("--stage", default="manual")
    p.add_argument("--record-dir", default=None, help="append the gate record to <dir>/freeze_gate.jsonl")
    p = sub.add_parser("sealed-run", help="exit 3 when a run directory touches sealed cases, 0 when it does not")
    p.add_argument("run")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "make":
            m = FZ.make(ROOT, spec_path=_abs(a.spec), out_path=_abs(a.out), allow_incomplete=a.allow_incomplete,
                        terms_file=_abs(a.anon_terms), allow_no_terms=a.allow_no_terms, supersede=a.supersede)
            print(f"[freeze] manifest written: {len(m['files'])} files, {len(m['computed'])} computed items, "
                  f"complete={m['complete']}, content_sha256 {m['content_sha256']}")
            for x in m["missing"]:
                print(f"[freeze] MISSING {x['id']}: {x['reason']}")
            return 0
        if a.cmd == "verify":
            rep = FZ.verify(ROOT, _abs(a.manifest))
            if a.json:
                print(json.dumps(rep, indent=2, sort_keys=True))
            else:
                print("\n".join(FZ.summary_lines(rep)))
            ok = rep["ok"] and (rep["complete"] or not a.require_complete) and \
                (rep["osf"]["matches_content"] or not a.require_osf)
            return 0 if ok else 1
        if a.cmd == "register":
            osf = FZ.register(ROOT, _abs(a.manifest), a.osf)
            print(f"[freeze] registered {osf['registration_id']} for content {osf['registered_content_sha256']}")
            return 0
        if a.cmd == "gate":
            rec = FZ.check_gate(ROOT, _abs(a.manifest))
            rec = dict({"stage": a.stage, "checked_at": FZ.now_iso()}, **rec)
            if a.record_dir:
                os.makedirs(a.record_dir, exist_ok=True)
                with open(os.path.join(a.record_dir, FZ.GATE_LOG), "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, sort_keys=True) + "\n")
            print(f"[freeze] gate open for {a.stage}: content {rec['content_sha256'][:16]}, OSF {rec['osf_registration_id']}")
            return 0
        if a.cmd == "sealed-run":
            # the gate's own rule: split test/eng_holdout in run_config, any sealed id in the run's request, result or
            # output files, or an earlier gate record. Only the reason and a count are printed, never ids.
            ids, split, gated = FZ.run_case_ids(_abs(a.run))
            need, reason, n = FZ.gate_reason(ROOT, split, ids, gated)
            if need:
                print(f"[freeze] run touches sealed cases ({reason}; {n} sealed id(s))")
                return 3
            print("[freeze] run touches no sealed case")
            return 0
    except (FZ.FreezeError, FZ.GateRefused) as e:
        print(f"[freeze] REFUSED: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
