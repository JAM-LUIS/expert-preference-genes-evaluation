#!/usr/bin/env python3
"""Model and decoding-parameter registry (E19): snapshot, update, validate, check, hash, verify-run, api-observed.

  PY=${ORGENE_PY:-/opt/homebrew/bin/python3}
  $PY tools/model_registry.py snapshot [--out configs/snapshots/model_env.<UTC>.json]   # read-only, see below
  $PY tools/model_registry.py update --snapshot configs/snapshots/model_env.<UTC>.json    # write observed facts
  $PY tools/model_registry.py validate                                                     # static checks
  $PY tools/model_registry.py check [--snapshot FILE | --quick] [--entry ID] [--strict]    # registry == host?
  $PY tools/model_registry.py hash ID                                                      # entry sha256 for a run
  $PY tools/model_registry.py verify-run experiments/<run>/gen.C0.r0 ...                   # run config == entry?
  $PY tools/model_registry.py api-observed experiments/<run>/gen.C0.r0 ... [--update]      # API ids/fingerprints
                                                                     # (--update: per run directory, idempotent)

snapshot / check (live) only read: Ollama GET /api/version, GET /api/tags, POST /api/show; the model store's
manifests and small blobs; the launchd job file, the running server's environment and the server log (fixed fields);
package metadata of the baselines interpreter; `--version` of llama.cpp tools and glpsol; the generation
interpreter's one-LP start-up check. They never call a generation endpoint, never restart or reconfigure the server,
and never record a path, host or user name (the output is refused if it would contain one).

Exit status: 0 ok; 1 problems found (validate, check, verify-run); 2 usage or refused output.
"""
import argparse
import glob
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import model_registry as MR  # noqa: E402
from orgene import model_snapshot as MS  # noqa: E402
from orgene.paths import OUTSIDE, find_absolute_paths, rel  # noqa: E402


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _neutral_or_die(text, what):
    """Refuse to write or print output that would carry a path, the home directory or the user name."""
    bad = [h[:12] + "..." for h in find_absolute_paths(text)]
    home = os.path.expanduser("~")
    if home and home not in ("/", "~") and home in text:
        bad.append("home directory")
    user = os.environ.get("USER") or os.environ.get("LOGNAME")
    if user and len(user) >= 3 and user in text:
        bad.append("user name")
    if bad:
        raise SystemExit(f"[registry] refused: the {what} would contain {sorted(set(bad))}")


def _live_snapshot(a, reg, quick=False):
    log = None
    if not (quick or a.no_log):
        log = a.server_log or MS.default_log_path(a.launchd_plist)
    parts = ("ollama", "execution") if quick else None
    return MS.snapshot(reg, host=a.host, models_dir=a.models_dir, plist_path=a.launchd_plist, log_path=log,
                       baselines_python=a.baselines_python, bin_dir=a.bin_dir, verify_weights=getattr(a, "verify_weights", False),
                       scan_log=not (quick or a.no_log), parts=parts)


def cmd_snapshot(a):
    reg = MR.read(a.registry)
    snap = _live_snapshot(a, reg)
    text = json.dumps(snap, ensure_ascii=False, indent=2) + "\n"
    _neutral_or_die(text, "snapshot")
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[registry] snapshot -> {rel(a.out)} (sha256 {MR.file_sha256(a.out)[:16]})", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def cmd_update(a):
    reg = MR.read(a.registry)
    with open(a.snapshot, "r", encoding="utf-8") as f:
        snap = json.load(f)
    try:
        new, notes = MR.apply_snapshot(reg, snap, snapshot_path=a.snapshot, accept_identity_change=a.accept_identity_change)
    except MR.IdentityChange as e:
        print(f"[registry] refused: {e}. Re-run with --accept-identity-change after recording why in DECISIONS.md.",
              file=sys.stderr)
        return 1
    text = json.dumps(new, ensure_ascii=False, indent=2) + "\n"
    _neutral_or_die(text, "registry")
    problems = MR.validate(new)
    if problems and not a.allow_invalid:
        print("[registry] refused: the updated registry would not validate:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        return 1
    MR.dump(new, a.registry)
    for n in notes:
        print(f"[registry] note: {n}", file=sys.stderr)
    print(f"[registry] updated {rel(a.registry or MR.DEFAULT_PATH)} from {rel(a.snapshot)}", file=sys.stderr)
    return 0


def cmd_validate(a):
    reg = MR.read(a.registry)
    problems = MR.validate(reg)
    for p in problems:
        print(f"[registry] {p}")
    print(f"[registry] {'OK' if not problems else 'INVALID'}: {len(reg.get('entries') or {})} entries, "
          f"{len(problems)} problem(s)")
    return 1 if problems else 0


def _entry_scope(mismatch, entry_id, reg):
    """Mismatches that matter for one entry's run: the entry itself, its model, the server and execution."""
    if mismatch.startswith("snapshot: model "):
        return mismatch.startswith(f"snapshot: model {MR.get_entry(reg, entry_id).get('model')}:")
    if mismatch.startswith("snapshot:"):
        return True
    path = mismatch.split(":", 1)[0]
    return path.startswith((f"entries.{entry_id}.", "server.", "execution."))


def cmd_check(a):
    reg = MR.read(a.registry)
    problems = MR.validate(reg)
    if a.entry:
        MR.get_entry(reg, a.entry)
    if a.snapshot:
        with open(a.snapshot, "r", encoding="utf-8") as f:
            snap = json.load(f)
        source = rel(a.snapshot)
    else:
        snap = _live_snapshot(a, reg, quick=a.quick)
        source = "live (read-only)" + (" quick" if a.quick else "")
    mism, notes = MR.compare_snapshot(reg, snap)
    if a.entry:
        mism = [m for m in mism if _entry_scope(m, a.entry, reg)]
    if a.quick:
        notes = [n for n in notes if not n.startswith(("snapshot: baselines", "snapshot: tools"))]
    for p in problems:
        print(f"[registry] INVALID {p}")
    for m in mism:
        print(f"[registry] MISMATCH {m}")
    for n in notes:
        print(f"[registry] note {n}")
    failed = bool(problems or mism or (a.strict and notes))
    print(f"[registry] check against {source}: {'FAIL' if failed else 'OK'} "
          f"({len(problems)} invalid, {len(mism)} mismatch, {len(notes)} notes)")
    return 1 if failed else 0


def cmd_hash(a):
    reg = MR.read(a.registry)
    e = MR.get_entry(reg, a.entry_id)
    _print({"path": rel(a.registry or MR.DEFAULT_PATH), "entry_id": a.entry_id, "entry_sha256": MR.entry_sha256(e)})
    return 0


def _config_of(d):
    p = os.path.join(d, "config.json") if os.path.isdir(d) else d
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_verify_run(a):
    reg = MR.read(a.registry)
    bad = 0
    for d in a.run_dirs:
        problems = MR.verify_run_config(reg, _config_of(d))
        status = "OK" if not problems else "FAIL"
        print(f"[registry] {status} {rel(d)}")
        for p in problems:
            print(f"[registry]   {p}")
        bad += bool(problems)
    return 1 if bad else 0


def cmd_api_observed(a):
    # one observation per run directory, keyed by its path relative to the repository: --update replaces a run's
    # earlier observation instead of adding its calls again
    per_run = {}
    for d in a.run_dirs:
        recs = []
        for p in sorted(glob.glob(os.path.join(d, "outputs", "*.json"))):
            with open(p, "r", encoding="utf-8") as f:
                recs.append(json.load(f))
        src = rel(d)
        if src in per_run:
            print(f"[registry] refused: run directory {src} given twice", file=sys.stderr)
            return 2
        per_run[src] = MR.api_observed(recs, a.model)
    models = sorted({m for obs in per_run.values() for m in obs})
    _print({m: MR.combine_api_observed([obs[m] for obs in per_run.values() if m in obs]) for m in models})
    if a.update:
        outside = [s for s in per_run if s.startswith(OUTSIDE) or s == "."]
        if outside:
            print(f"[registry] refused: --update takes run directories inside the repository, not {outside}",
                  file=sys.stderr)
            return 2
        reg = MR.read(a.registry)
        new = reg
        for src, obs in per_run.items():
            new = MR.merge_api_observed(new, obs, source=src)
        text = json.dumps(new, ensure_ascii=False, indent=2) + "\n"
        _neutral_or_die(text, "registry")
        MR.dump(new, a.registry)
        print(f"[registry] merged observations for {models} from {len(per_run)} run(s) into "
              f"{rel(a.registry or MR.DEFAULT_PATH)}", file=sys.stderr)
    return 0


def _live_args(p):
    p.add_argument("--host", default=MS.DEFAULT_HOST)
    p.add_argument("--models-dir", default=None, help="Ollama models directory (default $OLLAMA_MODELS or ~/.ollama/models)")
    p.add_argument("--launchd-plist", default=None, help="launchd job file of the server (default: the Homebrew one)")
    p.add_argument("--server-log", default=None, help="server log (default: the launchd job's StandardErrorPath)")
    p.add_argument("--no-log", action="store_true", help="do not scan the server log")
    p.add_argument("--baselines-python", default=None, help="baselines interpreter (default $ORGENE_BASELINES_PY or ~/venvs/baselines)")
    p.add_argument("--bin-dir", default=MS.DEFAULT_BIN_DIR)


def build_parser():
    ap = argparse.ArgumentParser(description="Model and decoding-parameter registry (E19)")
    ap.add_argument("--registry", default=None, help="registry file (default configs/model_registry.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("snapshot", help="read-only snapshot of the model environment")
    _live_args(p)
    p.add_argument("--verify-weights", action="store_true", help="also re-hash the weight blobs (GBs; read-only)")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_snapshot)
    p = sub.add_parser("update", help="write a snapshot's observed facts into the registry")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--accept-identity-change", action="store_true")
    p.add_argument("--allow-invalid", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_update)
    p = sub.add_parser("validate", help="static checks of the registry file")
    p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("check", help="compare the registry with a snapshot (default: a live read-only one)")
    _live_args(p)
    p.add_argument("--snapshot", default=None)
    p.add_argument("--quick", action="store_true", help="live: Ollama identity, launchd/process settings and the "
                                                         "interpreter only (no log scan, no baselines)")
    p.add_argument("--entry", default=None, help="only report what matters for this entry")
    p.add_argument("--strict", action="store_true", help="unobserved parts fail too")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("hash", help="print an entry's sha256 (what a run records)")
    p.add_argument("entry_id")
    p.set_defaults(fn=cmd_hash)
    p = sub.add_parser("verify-run", help="check runner config.json files against the registry")
    p.add_argument("run_dirs", nargs="+")
    p.set_defaults(fn=cmd_verify_run)
    p = sub.add_parser("api-observed", help="aggregate returned model ids / fingerprints / dates of API runs")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--model", default=None)
    p.add_argument("--update", action="store_true")
    p.set_defaults(fn=cmd_api_observed)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except MR.RegistryError as e:
        print(f"[registry] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
