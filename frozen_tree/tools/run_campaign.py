#!/usr/bin/env python3
"""Run a campaign unattended: preflight, then for every stage of a campaign spec build the unit matrix, write the
seeded plan (E07) and execute it, audit the stage, and finally hash every output file.

  /opt/homebrew/bin/python3 tools/run_campaign.py --spec configs/campaigns/<name>.json --campaign <basename>
  /opt/homebrew/bin/python3 tools/run_campaign.py --spec ... --campaign ... --dry-run     # matrices and plans only
  /opt/homebrew/bin/python3 tools/run_campaign.py --spec ... --campaign ... --resume      # after an interruption

The campaign directory is experiments/<basename>/. A stage is one cases file with one split (the scheduler pins
one cases file per run): its units come from id lists (ids only, no case record is read here) crossed with the
configurations and repeats of each model registry entry. Dev rehearsal and the formal test use this same driver;
only the spec differs. A test or eng_holdout stage runs only when the freeze gate of the scheduler accepts it; the
driver adds no override.

What it guarantees
  - nothing starts unless the preflight passes: clean committed tree, interpreter check, selftest, model registry
    check against the live host, test-isolation check, and (for a spec with sealed stages) `freeze.py verify`;
  - a stage that ends incomplete is executed again with the same plan (completed units are skipped) up to
    --retries times; a stage that still fails is recorded and the next stage runs, so one bad stage does not waste
    the window; a model identity drift (exit 3) stops the campaign;
  - every stage is audited from its unit records: all planned units complete, local token counts complete, every
    reused round 0 taken from the planned source unit of the same case and repeat;
  - status.json always says where the campaign is; the driver prints and writes counts, ids and hashes only;
  - it never scores: scoring is a separate step (sealed for test until the preregistered order allows it).

Spec (JSON)
  {"schema": "orgene.r1.campaign.v1", "seed": 20261005, "genes": "...", "lexicon": "...",
   "env": {"ORGENE_TOOLS_PY": "<path relative to the repository>", ...},   # optional; exported to every command
   "stages": [{"label": "...", "cases": "data/cases/<b>.jsonl", "split_dir": "data/splits_r1/<set>",
               "split": "dev" | "test" | "eng_holdout",
               "blocks": [{"registry_entry": "...", "configs": ["C0", ...], "repeats": 1,
                           "ids": {"split": "dev"}                      # every id of that side of split_dir
                                | {"subset": "determinism"}             # data/subsets_r1/..., this stage's benchmark
                                | {"split": "dev", "minus_subset": "determinism"}
                                | {"split": "test", "minus_split_dir": "data/splits_r1/<other set>"}  # this side
                                                                      # without the ids of another lock's same side
                                | {"split": "test", "split_dir": "data/splits_r1/<other set>"}   # another lock's side,
                                                                      # which must lie inside this stage's side
               "matrix": "configs/run_matrix/<label>.json",          # optional: the committed matrix the stage must equal
               "plan": "configs/run_plans/<label>.plan.json"}]}       # optional: the committed plan (a sealed stage
                                                                      # may only read frozen inputs, the plan included)

  --write-matrices   write every stage's matrix and plan to their committed paths (before the freeze) instead of running
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from orgene.paths import neutral_home  # noqa: E402

SCHEMA = "orgene.r1.campaign.v1"
SUBSETS = "data/subsets_r1/variance_determinism_ids.json"
SEALED = ("test", "eng_holdout")
PY = sys.executable


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def benchmark_of(stage):
    return Path(stage["cases"]).stem


def stage_ids(stage, spec_ids, subsets):
    """The case ids one block selects (ids only)."""
    side_ids = lambda side, d=None: json.loads((ROOT / (d or stage["split_dir"]) / f"{side}_ids.json").read_text())  # noqa: E731
    sub_ids = lambda name: subsets["subsets"][name]["strata"][benchmark_of(stage)]["ids"]  # noqa: E731
    if set(spec_ids) == {"split"}:
        ids = side_ids(spec_ids["split"])
    elif set(spec_ids) == {"split", "split_dir"}:
        if spec_ids["split"] != stage["split"]:
            raise ValueError(f"{stage['label']}: a split_dir selector must use the stage's side")
        ids = side_ids(spec_ids["split"], spec_ids["split_dir"])
    elif set(spec_ids) == {"subset"}:
        ids = sub_ids(spec_ids["subset"])
    elif set(spec_ids) == {"split", "minus_subset"}:
        drop = set(sub_ids(spec_ids["minus_subset"]))
        ids = [c for c in side_ids(spec_ids["split"]) if c not in drop]
    elif set(spec_ids) == {"split", "minus_split_dir"}:
        if spec_ids["split"] != stage["split"]:
            raise ValueError(f"{stage['label']}: a minus_split_dir selector must use the stage's side")
        drop = set(side_ids(spec_ids["split"], spec_ids["minus_split_dir"]))
        ids = [c for c in side_ids(spec_ids["split"]) if c not in drop]
    else:
        raise ValueError(f"unknown ids selector {spec_ids}")
    allowed = set(side_ids(stage["split"] if stage["split"] != "eng_holdout" else "eng_holdout"))
    outside = [c for c in ids if c not in allowed]
    if outside:
        raise ValueError(f"{stage['label']}: {len(outside)} selected id(s) are not in the {stage['split']} side")
    if len(set(ids)) != len(ids) or not ids:
        raise ValueError(f"{stage['label']}: empty or duplicate id selection")
    return sorted(ids)


def build_matrix(stage, subsets):
    units, seen = [], set()
    for block in stage["blocks"]:
        ids = stage_ids(stage, block["ids"], subsets)
        for case_id in ids:
            for k in range(int(block.get("repeats", 1))):
                for cfg in block["configs"]:
                    key = (block["registry_entry"], case_id, cfg, k)
                    if key in seen:
                        continue  # two blocks of one stage may name the same unit
                    seen.add(key)
                    units.append({"case_id": case_id, "config_id": cfg, "repeat": k,
                                  "registry_entry": block["registry_entry"]})
    return {"schema_version": 1, "units": units}


def run(cmd, log_path=None, env=None, check=False):
    """Run one command; output to log_path (append) or captured. Returns (code, text)."""
    if log_path is None:
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr)
    with open(log_path, "a") as log:
        log.write(f"\n===== {now()} {' '.join(cmd)}\n")
        log.flush()
        p = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    if check and p.returncode:
        raise RuntimeError(f"command failed ({p.returncode}): {cmd[1:4]}")
    return p.returncode, ""


def preflight(spec, env, allow_dirty):
    """List of (name, ok, detail). Read-only checks; no model call."""
    out = []

    def add(name, cmd, ok_if):
        code, text = run(cmd, env=env)
        ok = ok_if(code, text)
        last = text.strip().splitlines()[-1] if text.strip() else f"exit {code}"
        out.append((name, ok, re.sub(r"/\S+", "<path>", neutral_home(last))[:200]))  # no local paths in the record

    code, text = run(["git", "status", "--porcelain", "--untracked-files=no"], env=env)
    out.append(("tracked files committed", allow_dirty or (code == 0 and not text.strip()),
                "clean" if not text.strip() else f"{len(text.strip().splitlines())} modified"))
    add("interpreter and solver", [PY, "runtime/orgene_cli.py", "env"], lambda c, t: c == 0 and '"ok": true' in t)
    add("selftest", [PY, "runtime/orgene_cli.py", "selftest"], lambda c, t: c == 0 and "[selftest] PASS" in t)
    add("model registry vs host", [PY, "tools/model_registry.py", "check"], lambda c, t: c == 0)
    add("test isolation", [PY, "analysis/check_test_isolation.py"], lambda c, t: c == 0 and "RESULT: PASS" in t)
    add("seeded subsets", [PY, "tools/draw_subsets_r1.py", "--check"], lambda c, t: c == 0)
    if any(s["split"] in SEALED for s in spec["stages"]):
        add("freeze manifest", [PY, "tools/freeze.py", "verify"], lambda c, t: c == 0)
    for s in spec["stages"]:
        for rel in (s["cases"], s["split_dir"]):
            out.append((f"{s['label']}: {rel}", (ROOT / rel).exists(), "present" if (ROOT / rel).exists() else "missing"))
    for rel in (spec["genes"], spec["lexicon"]):
        out.append((rel, (ROOT / rel).exists(), "present" if (ROOT / rel).exists() else "missing"))
    free_gb = os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize / 1e9
    out.append(("free disk", free_gb > 5, f"{free_gb:.0f} GB"))
    return out


def audit_stage(run_dir, matrix, configs):
    """Counts from the unit records of one executed stage; raises on any planned unit that is not sound."""
    planned = {(u["registry_entry"], u["case_id"], u["config_id"], u["repeat"]) for u in matrix["units"]}
    source_of = {c["id"]: (c["round0"][6:] if c["round0"].startswith("reuse:") else None) for c in configs}
    found, by_key, problems = set(), {}, []
    for model_dir in sorted((run_dir / "by-model").iterdir()):
        for p in sorted((model_dir / "units").glob("*.json")):
            if p.name == "setup.json":
                continue
            r = json.loads(p.read_text())
            key = (model_dir.name, r["case_id"], r["config_id"], r["repeat"])
            found.add(key)
            by_key[key] = r
    missing = planned - found
    if missing:
        problems.append(f"{len(missing)} planned unit(s) have no record")
    stops = {}
    for key in sorted(planned & found):
        r = by_key[key]
        if r["status"] != "complete":
            problems.append(f"{r['unit_id']}: status {r['status']}")
            continue
        stops[r["stop_reason"]] = stops.get(r["stop_reason"], 0) + 1
        if r["tokens"]["local"]["n_calls_missing"]:
            problems.append(f"{r['unit_id']}: local token counts missing")
        if r.get("error") is not None or r.get("context_exceeded") is not None:
            problems.append(f"{r['unit_id']}: error or context limit recorded")
        src = source_of.get(key[2])
        if src is not None:
            s = by_key.get((key[0], key[1], src, key[3]))
            got = ((r.get("round0") or {}).get("reused_from") or {}).get("unit_id")
            if s is None or got != s["unit_id"]:
                problems.append(f"{r['unit_id']}: round 0 not reused from the planned source")
    return {"planned": len(planned), "complete": sum(stops.values()), "stop_reasons": stops,
            "problems": problems[:20], "n_problems": len(problems)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--campaign", required=True, help="basename of experiments/<campaign>")
    ap.add_argument("--resume", action="store_true", help="continue an existing campaign with its recorded plans")
    ap.add_argument("--dry-run", action="store_true", help="preflight, matrices and plans; no model call")
    ap.add_argument("--retries", type=int, default=2, help="re-executions of a stage that ends incomplete")
    ap.add_argument("--allow-dirty", action="store_true", help="dev only: skip the committed-tree check")
    ap.add_argument("--write-matrices", action="store_true",
                    help="write each stage's matrix to its committed path (before the freeze); no model call")
    a = ap.parse_args()
    if Path(a.campaign).name != a.campaign:
        ap.error("campaign must be a basename")
    os.chdir(ROOT)
    env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
               PATH="/opt/homebrew/bin:" + os.environ.get("PATH", ""))
    spec = json.loads((ROOT / a.spec).read_text())
    if spec.get("schema") != SCHEMA:
        raise SystemExit(f"[campaign] unsupported spec schema {spec.get('schema')!r}")
    for name, rel_path in (spec.get("env") or {}).items():  # tool locations a worktree does not have (ORGENE_* only)
        if not name.startswith("ORGENE_") or not (ROOT / rel_path).exists():
            raise SystemExit(f"[campaign] spec env {name}: not an ORGENE_ variable or path missing")
        env[name] = os.path.normpath(str(ROOT / rel_path))  # not resolve(): a venv interpreter is a symlink
    sealed = any(s["split"] in SEALED for s in spec["stages"])
    if sealed and ("dev" in a.campaign or a.allow_dirty):
        raise SystemExit("[campaign] a spec with sealed stages needs a clean tree and a campaign name without 'dev'")
    if not sealed and "test" in a.campaign:
        raise SystemExit("[campaign] a dev campaign must not be named like a test run")
    subsets = json.loads((ROOT / SUBSETS).read_text())
    configs = json.loads((ROOT / "configs/r1_configs.json").read_text())
    configs = configs if isinstance(configs, list) else configs["configs"]
    if a.write_matrices:
        for stage in spec["stages"]:
            if "matrix" not in stage:
                raise SystemExit(f"[campaign] {stage['label']}: no matrix path in the spec")
            body = json.dumps(build_matrix(stage, subsets), indent=1) + "\n"
            target = ROOT / stage["matrix"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
            n = len(json.loads(body)["units"])
            print(f"[campaign] {stage['label']}: wrote {stage['matrix']} ({n} units, sha256 {hashlib.sha256(body.encode()).hexdigest()[:12]})")
            if "plan" in stage:
                plan_target = ROOT / stage["plan"]
                if plan_target.exists():
                    plan_target.unlink()
                    (ROOT / (stage["plan"] + ".sha256")).unlink(missing_ok=True)
                code, text = run([PY, "runtime/orgene_cli.py", "plan", "--matrix", str(target), "--out",
                                  str(plan_target), "--seed", str(spec["seed"]), "--order", "random"], env=env)
                if code:
                    raise SystemExit(f"[campaign] {stage['label']}: plan refused: {neutral_home(text.strip())[-300:]}")
                print(f"[campaign] {stage['label']}: wrote {stage['plan']} (sha256 {sha256_file(plan_target)[:12]})")
        return 0
    campaign = ROOT / "experiments" / a.campaign
    if campaign.exists() and not (a.resume or a.dry_run):
        raise SystemExit(f"[campaign] experiments/{a.campaign} exists; use --resume or another name")
    campaign.mkdir(parents=True, exist_ok=True)
    status_path = campaign / "status.json"
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    state = json.loads(status_path.read_text()) if (a.resume and status_path.exists()) else {
        "schema": SCHEMA, "campaign": a.campaign, "spec": a.spec, "spec_sha256": sha256_file(ROOT / a.spec),
        "git_head": head, "started_at": now(), "stages": {}, "runs": []}
    if state.get("git_head") != head or state.get("spec_sha256") != sha256_file(ROOT / a.spec):
        raise SystemExit("[campaign] code or spec changed since this campaign started; use a new campaign")
    state["runs"].append({"at": now(), "pid": os.getpid(), "resume": a.resume, "dry_run": a.dry_run})

    def save(**kw):
        state.update(kw)
        tmp = campaign / "status.tmp"
        tmp.write_text(json.dumps(state, indent=2) + "\n")
        tmp.replace(status_path)

    save(state="preflight")
    checks = preflight(spec, env, a.allow_dirty and not sealed)
    for name, ok, detail in checks:
        print(f"[preflight] {'ok  ' if ok else 'FAIL'} {name}: {detail}", flush=True)
    save(preflight=[{"check": n, "ok": ok, "detail": d} for n, ok, d in checks])
    if not all(ok for _, ok, _ in checks):
        save(state="failed", error="preflight")
        raise SystemExit("[campaign] preflight failed; nothing was run")

    failed = []
    for stage in spec["stages"]:
        label = stage["label"]
        run_dir = campaign / label
        st = state["stages"].setdefault(label, {"state": "planned"})
        if st.get("state") == "complete":
            print(f"[campaign] {label}: already complete", flush=True)
            continue
        matrix_path, plan_path = campaign / f"{label}.matrix.json", campaign / f"{label}.plan.json"
        matrix = build_matrix(stage, subsets)
        body = json.dumps(matrix, indent=1) + "\n"
        if matrix_path.exists() and matrix_path.read_text() != body:
            raise SystemExit(f"[campaign] {label}: the matrix differs from the recorded one; use a new campaign")
        if "matrix" in stage:  # the committed, frozen matrix must be exactly what the spec builds
            pinned = ROOT / stage["matrix"]
            if not pinned.exists() or pinned.read_text() != body:
                raise SystemExit(f"[campaign] {label}: the matrix built from the spec differs from {stage['matrix']}")
        matrix_path.write_text(body)
        if not plan_path.exists():
            code, text = run([PY, "runtime/orgene_cli.py", "plan", "--matrix", str(matrix_path), "--out",
                              str(plan_path), "--seed", str(spec["seed"]), "--order", "random"], env=env)
            if code:
                raise SystemExit(f"[campaign] {label}: plan refused: {neutral_home(text.strip())[-400:]}")
        plan_sha = sha256_file(plan_path)
        if "plan" in stage:  # the committed, frozen plan must be exactly what the spec builds; execute reads that file
            pinned = ROOT / stage["plan"]
            if not pinned.exists() or pinned.read_bytes() != plan_path.read_bytes():
                raise SystemExit(f"[campaign] {label}: the plan built from the spec differs from {stage['plan']}")
            plan_path = pinned
        by_model = {}
        for u in matrix["units"]:
            by_model[u["registry_entry"]] = by_model.get(u["registry_entry"], 0) + 1
        st.update(units=len(matrix["units"]), units_by_model=by_model, plan_sha256=plan_sha,
                  matrix_sha256=sha256_file(matrix_path))
        save()
        print(f"[campaign] {label}: {len(matrix['units'])} units {by_model}, plan {plan_sha[:12]}", flush=True)
        if a.dry_run:
            continue
        cmd = [PY, "runtime/orgene_cli.py", "execute", "--run", str(run_dir.relative_to(ROOT)),
               "--cases", stage["cases"], "--split-dir", stage["split_dir"], "--split", stage["split"],
               "--genes", spec["genes"], "--lexicon", spec["lexicon"], "--local-tokens", "on", "--export-validated",
               "--plan", str(plan_path.relative_to(ROOT)), "--plan-sha256", plan_sha]
        cmd += [str(x) for x in stage.get("extra_args", [])]
        st.update(state="running", started_at=st.get("started_at") or now(), command=cmd)
        save(state="running", current_stage=label)
        code = None
        for attempt in range(a.retries + 1):
            code, _ = run(cmd, log_path=campaign / f"{label}.log", env=env)
            st.setdefault("attempts", []).append({"at": now(), "exit": code})
            save()
            print(f"[campaign] {label}: execute attempt {attempt + 1} exit {code}", flush=True)
            if code in (0, 3):
                break
            time.sleep(30)
        if code == 3:
            st.update(state="failed", error="model identity changed during the run")
            save(state="failed", error=f"{label}: model identity drift")
            raise SystemExit(f"[campaign] {label}: model identity drift; campaign stopped")
        try:
            audit = audit_stage(run_dir, matrix, configs)
        except Exception as exc:  # the stage wrote nothing usable
            audit = {"planned": len(matrix["units"]), "complete": 0, "n_problems": 1,
                     "problems": [f"{type(exc).__name__}: {neutral_home(str(exc))[:200]}"]}
        ok = code == 0 and audit["n_problems"] == 0 and audit["complete"] == audit["planned"]
        st.update(state="complete" if ok else "failed", finished_at=now(), audit=audit)
        save()
        print(f"[campaign] {label}: {'verified' if ok else 'FAILED'} {audit['complete']}/{audit['planned']} "
              f"complete, problems {audit['n_problems']}", flush=True)
        if not ok:
            failed.append(label)

    if a.dry_run:
        save(state="dry_run_done")
        print("[campaign] dry run done: matrices and plans written, no model call", flush=True)
        return 0
    lines = []
    for p in sorted(campaign.rglob("*")):
        if p.is_file() and p.name not in ("OUTPUT_SHA256.txt", "status.json", "status.tmp", ".lock", ".schedule.lock"):
            lines.append(f"{sha256_file(p)}  {p.relative_to(campaign)}")
    (campaign / "OUTPUT_SHA256.txt").write_text("\n".join(lines) + "\n")
    save(state="failed" if failed else "complete", finished_at=now(), failed_stages=failed,
         output_files=len(lines), output_manifest_sha256=sha256_file(campaign / "OUTPUT_SHA256.txt"))
    print(f"[campaign] {'FAILED stages: ' + ', '.join(failed) if failed else 'complete'}; "
          f"{len(lines)} output files hashed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[campaign] failed: {type(exc).__name__}: {neutral_home(str(exc))}", file=sys.stderr)
        sys.exit(1)
