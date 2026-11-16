#!/usr/bin/env python3
"""Engineering-source case set (E22): PGLib-UC and MIPLIB-NL instances -> data/cases/eng.jsonl + eng_holdout split.

  $ORGENE_PY data/ingest_eng.py select                  # print the seeded candidate orders (no network, no files)
  $ORGENE_PY data/ingest_eng.py fetch [--case ID ...]   # download the selected source files at the pinned commits
  $ORGENE_PY data/ingest_eng.py solve --case ID         # CBC reference solve (<= 1800 s) -> data/raw/eng/solve_logs/
  $ORGENE_PY data/ingest_eng.py collect                 # solve records -> data/eng/reference_values.json
  $ORGENE_PY data/ingest_eng.py build                   # data/cases/eng.jsonl and data/eng/eng_hashes.json
  $ORGENE_PY data/ingest_eng.py split                   # data/splits/eng/ (all cases eng_holdout)
  $ORGENE_PY data/ingest_eng.py check                   # re-derive and compare everything; exit 1 on a difference

Before the freeze only (refused once FREEZE_MANIFEST.json exists), for the time-limited references (cbc_time_limited):
  $ORGENE_PY data/ingest_eng.py long-solve --case ID    # one longer CBC solve (default 14400 s, one thread), run when
                                                        # the machine is otherwise idle; -> <case>.long.json in the logs
  $ORGENE_PY data/ingest_eng.py upgrade                 # a long solve that proved optimality (and passes the schedule
                                                        # check, inside the earlier interval) turns the reference into
                                                        # cbc_optimal; before/after go to data/eng/reference_upgrades.json,
                                                        # then collect + build + split are redone
Scoring of a cbc_time_limited reference (runtime/orgene/score.py in_reference_interval): the printed objective
agrees when it lies in reference.interval = [CBC bound, CBC best value], each end widened by the tolerance.

Isolation (data/cases/README_ISOLATION.md): gene-writing sessions do not open data/cases/, data/eng/ or data/raw/.
This script prints ids, counts and hashes only, never problem text. It holds no problem wording: the PGLib-UC
wording is in data/eng/pglib_uc_render.py, the MIPLIB-NL glue lines in data/eng/miplib_nl_convert.py.

The selection (which instances, why) is recorded in data/eng/selection.json; `check` re-derives the seeded orders
from the pinned tree listings in data/eng/sources/ and verifies that each chosen instance is the first eligible one.
"""
import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from eng import miplib_nl_convert as MC  # noqa: E402
from eng import pglib_uc_render as UR  # noqa: E402

SCHEMA_CASES = "orgene.r1.eng_cases.v1"
CASES_PATH = "data/cases/eng.jsonl"
SPLIT_DIR = "data/splits/eng"
SELECTION_PATH = "data/eng/selection.json"
REFERENCE_PATH = "data/eng/reference_values.json"
HASHES_PATH = "data/eng/eng_hashes.json"
UPGRADES_PATH = "data/eng/reference_upgrades.json"
SOLVE_LOGS = "data/raw/eng/solve_logs"
FREEZE_MANIFEST = "FREEZE_MANIFEST.json"
SEED = "20260928"
LONG_TIME_LIMIT_S = 14400  # 4 h, one thread (main session 2026-09-29, option c)

SOURCES = {
    "pglib_uc": {
        "repo": "https://github.com/power-grid-lib/pglib-uc",
        "commit": "39a7f38cf4703de92f0291f0c873c2e98c789301",
        "raw_url": "https://raw.githubusercontent.com/power-grid-lib/pglib-uc/{commit}/{path}",
        "raw_dir": "data/raw/eng/pglib_uc/{commit}",
        "tree": "data/eng/sources/pglib_uc_tree.json",
        "license": "CC-BY-4.0 (case data; LICENSE: 'Data License: Creative Commons Attribution 4.0'); software MIT",
        "license_files": ["LICENSE"],
        "changes": "problem text rendered from the instance data by template pglib_uc.v1 (data/eng/pglib_uc_render.py); "
                   "renewable availability aggregated per hour; units numbered instead of named",
    },
    "miplib_nl": {
        "repo": "https://github.com/optsuite/MIPLIB-NL",
        "commit": "9f14ad1782eaa547f7dad982d1edb186321ffd88",
        "raw_url": "https://raw.githubusercontent.com/optsuite/MIPLIB-NL/{commit}/{path}",
        "raw_dir": "data/raw/eng/miplib_nl/{commit}",
        "tree": "data/eng/sources/miplib_nl_tree.json",
        "license": "CC-BY-SA-4.0 (README.md, section License; the repository has no LICENSE file)",
        "license_files": ["README.md"],
        "changes": "abstract_problem, parameters and file descriptions kept verbatim; data file contents appended "
                   "inline with fixed glue lines (converter miplib_nl.v1, data/eng/miplib_nl_convert.py)",
    },
}

# ------------------------------------------------------------------ selection rule (fixed 2026-09-28, see selection.json)
NUM_CTX = 32768
NUM_PREDICT = 6000
PGLIB_FAMILIES_THAT_FIT = ("rts_gmlc",)  # ca (>= 110 KB of tables) and ferc (larger) cannot fit in NUM_CTX
MIPLIB_STRATA = (("T", 0, 3000), ("S", 3000, 8000), ("L", 8000, 22001))  # bytes of instance.json + data files
MIPLIB_PER_STRATUM = 2
PGLIB_N = 2


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rp(path):
    return os.path.join(ROOT, path)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


def git_blob_sha1(path):
    with open(path, "rb") as f:
        b = f.read()
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


def load_json(path):
    with open(rp(path) if not os.path.isabs(path) else path, encoding="utf-8") as f:
        return json.load(f)


def raw_dir(source):
    s = SOURCES[source]
    return s["raw_dir"].format(commit=s["commit"])


def miplib_sizes(tree):
    out = {}
    for name, files in tree["instances"].items():
        out[name] = sum(v["bytes"] for p, v in files.items() if p == "instance.json" or p.startswith("data/"))
    return out


def miplib_orders(tree):
    """{stratum: [instance names in seeded order]} under the v2 rule."""
    sizes = miplib_sizes(tree)
    orders = {}
    for st, lo, hi in MIPLIB_STRATA:
        names = sorted(n for n, s in sizes.items() if lo <= s < hi)
        rnd = random.Random(f"{SEED}:miplib_nl:v2:{st}")
        rnd.shuffle(names)
        orders[st] = names
    return orders


def pglib_draw(tree):
    days = sorted(p.split("/")[1][:-5] for p in tree["files"] if p.startswith("rts_gmlc/") and p.endswith(".json"))
    return random.Random(f"{SEED}:pglib_uc:v2:rts_gmlc").sample(days, PGLIB_N)


# ------------------------------------------------------------------ cases


def case_sources(sel):
    """[(case_id, source, source_id, files {relpath: tree entry})] of the selected cases, in id order."""
    out = []
    for c in sel["cases"]:
        out.append((c["case_id"], c["source"], c["source_id"], c["source_files"]))
    return sorted(out)


def instance_path(source, source_id):
    if source == "pglib_uc":
        return os.path.join(raw_dir(source), source_id + ".json")
    return os.path.join(raw_dir(source), "dataset", source_id)


def render_case(source, source_id):
    p = rp(instance_path(source, source_id))
    if source == "pglib_uc":
        return UR.render_file(p)
    return MC.convert(p)


# ------------------------------------------------------------------ commands


def cmd_select(a):
    mt = load_json(SOURCES["miplib_nl"]["tree"])
    pt = load_json(SOURCES["pglib_uc"]["tree"])
    sizes = miplib_sizes(mt)
    print(f"pglib_uc rts_gmlc draw: {pglib_draw(pt)}")
    for st, order in miplib_orders(mt).items():
        print(f"miplib_nl stratum {st} ({len(order)} instances): " + ", ".join(f"{n} ({sizes[n]} B)" for n in order[:a.show]))


def _fetch_one(url, dest, want_blob):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    subprocess.run(["curl", "-sS", "-f", "-m", "600", "-o", tmp, url], check=True)
    if git_blob_sha1(tmp) != want_blob:
        os.remove(tmp)
        raise SystemExit(f"[fetch] content of {os.path.basename(dest)} does not match the pinned git blob")
    os.replace(tmp, dest)


def cmd_fetch(a):
    sel = load_json(SELECTION_PATH)
    todo = []
    for src, s in SOURCES.items():
        tree = load_json(s["tree"])
        top = tree["files"] if src == "pglib_uc" else tree["top_level_files"]
        for lf in s["license_files"]:
            todo.append((src, lf, top[lf]["git_blob"]))
    for cid, src, sid, files in case_sources(sel):
        if a.case and cid not in a.case:
            continue
        for rel_path, ent in files.items():
            todo.append((src, rel_path, ent["git_blob"]))
    n_new = 0
    for src, rel_path, blob in todo:
        dest = rp(os.path.join(raw_dir(src), rel_path))
        if os.path.exists(dest) and git_blob_sha1(dest) == blob:
            continue
        s = SOURCES[src]
        _fetch_one(s["raw_url"].format(commit=s["commit"], path=rel_path), dest, blob)
        n_new += 1
    print(f"[fetch] {len(todo)} file(s) pinned, {n_new} downloaded, all match their git blobs")


def cmd_solve(a):
    sel = load_json(SELECTION_PATH)
    by_id = {c["case_id"]: c for c in sel["cases"]}
    for cid in a.case:
        c = by_id.get(cid)
        if c is None:
            raise SystemExit(f"[solve] unknown case {cid}")
        out = rp(os.path.join(SOLVE_LOGS, f"{cid}.json"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cmd = [sys.executable, rp("data/eng/reference/solve.py"), c["source"], rp(instance_path(c["source"], c["source_id"])),
               out, "--time-limit", str(a.time_limit)]
        subprocess.run(cmd, check=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))


def refuse_after_freeze(what):
    if os.path.exists(rp(FREEZE_MANIFEST)):
        raise SystemExit(f"[{what}] {FREEZE_MANIFEST} exists: the engineering references are frozen")


def long_record_path(cid):
    return rp(os.path.join(SOLVE_LOGS, f"{cid}.long.json"))


def cmd_long_solve(a):
    """One longer CBC solve of a time-limited reference (one thread, reference/cbc.py); the record goes next to the
    30-minute one as <case>.long.json and is used only through `upgrade`."""
    refuse_after_freeze("long-solve")
    sel = load_json(SELECTION_PATH)
    by_id = {c["case_id"]: c for c in sel["cases"]}
    refs = load_json(REFERENCE_PATH)["cases"]
    for cid in a.case:
        c = by_id.get(cid)
        if c is None:
            raise SystemExit(f"[long-solve] unknown case {cid}")
        if refs[cid]["reference_kind"] != "cbc_time_limited":
            raise SystemExit(f"[long-solve] {cid} is {refs[cid]['reference_kind']}, not cbc_time_limited")
        out = long_record_path(cid)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cmd = [sys.executable, rp("data/eng/reference/solve.py"), c["source"], rp(instance_path(c["source"], c["source_id"])),
               out, "--time-limit", str(a.time_limit)]
        subprocess.run(cmd, check=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))


def normalize_record(rec, log_path=None):
    """A solve record in the current form: the bound CBC proved (lower for a minimisation, upper for a maximisation;
    re-read from the kept CBC log when an older record lacks it) and the relative gap recomputed from incumbent and
    bound (CBC prints the gap rounded to two decimals; that value stays as gap_printed)."""
    from eng.reference import cbc as CBC
    rec = dict(rec)
    parsed = CBC.parse_log(open(log_path, encoding="utf-8", errors="replace").read()) if log_path and os.path.exists(log_path) else {}
    if rec.get("status") == "other" and parsed.get("status") not in (None, "other"):  # parse_log learned the case later
        rec["status"], rec["result"] = parsed["status"], parsed["result"]
    if "bound" not in rec:
        rec["bound"] = parsed.get("bound", rec.get("lower_bound"))
        rec["gap_printed"] = rec.get("gap")
    rec.pop("lower_bound", None)
    rec.pop("upper_bound", None)
    ob, bd = rec.get("objective"), rec.get("bound")
    rec["gap"] = None if ob is None or bd is None else abs(ob - bd) / max(abs(ob), 1e-10)
    return rec


REF_KEYS = ("status", "result", "objective", "bound", "gap", "gap_printed", "gap_at_most", "nodes", "cpu_seconds", "wall_seconds",
            "cbc_version", "pulp_version", "n_variables", "n_constraints", "options", "started_at", "finished_at", "check")


def reference_decision(source, rec, official):
    """(reference objective, kind, problems) under the E22 rule.

    kind: "cbc_optimal" (CBC reached ratioGap 1e-7 within the limit; for MIPLIB-NL it must also equal the published
    optimal_value within 1e-6 relative); "cbc_attains_published_optimum" (MIPLIB-NL: stopped at the limit with an
    incumbent equal to optimal_value and a bound that does not contradict it; scored like cbc_optimal); or
    "cbc_time_limited" (best value CBC found within the limit, no published optimum reached; scored separately).
    """
    problems = []
    obj = rec.get("objective")
    if rec.get("status") == "optimal" and obj is not None:
        kind = "cbc_optimal"
    elif rec.get("status") == "time_limit_feasible" and obj is not None:
        kind = "cbc_time_limited"
    else:
        return None, "no_reference", [f"CBC status {rec.get('status')}"]
    if source == "pglib_uc":
        chk = rec.get("check") or {}
        if chk.get("n_violations") != 0 or chk.get("rel_diff", 1) > 1e-9:
            problems.append("independent schedule check failed")
    if official is not None:
        tol = 1e-6 * max(1.0, abs(official))
        if kind == "cbc_optimal" and abs(obj - official) > tol:
            problems.append("CBC optimum differs from the published optimal_value")
        if kind == "cbc_time_limited":
            lb = rec.get("bound")
            lo, hi = sorted((lb if lb is not None else obj, obj))
            if not (lo - tol <= official <= hi + tol):
                problems.append("published optimal_value outside CBC's [bound, incumbent] interval")
            elif abs(obj - official) <= tol:
                # CBC reached the published optimum but did not prove it within the limit: the value is attained by
                # a solution of the reference script, and its optimality rests on the published (MIPLIB) value
                kind = "cbc_attains_published_optimum"
    return obj, kind, problems


def load_upgrades():
    return load_json(UPGRADES_PATH) if os.path.exists(rp(UPGRADES_PATH)) else {"cases": {}}


def upgraded(upgrades, cid):
    u = upgrades["cases"].get(cid)
    return bool(u and u.get("upgraded"))


def collect_doc(sel=None, upgrades=None):
    """(reference_values document, problems) from the solve records; an upgraded case uses its long record."""
    sel = sel or load_json(SELECTION_PATH)
    upgrades = upgrades if upgrades is not None else load_upgrades()
    out = {"schema": "orgene.r1.eng_reference_values.v1", "note": (
        "CBC reference values of the engineering-source cases (E22). Model: data/eng/reference/ (PGLib-UC: MODEL.tex of "
        "the benchmark; MIPLIB-NL: PuLP translation of the instance's solve.py). Limit 1800 s wall clock, ratioGap 1e-7, "
        "one thread. kind cbc_optimal: CBC closed the gap within the limit; cbc_attains_published_optimum: CBC stopped at "
        "the limit with an incumbent equal to the published optimal_value (optimality from the published value); "
        "cbc_time_limited: best value found within the limit, reported with its gap and scored separately. "
        "official_value: MIPLIB-NL instance.json optimal_value."),
        "cases": {}}
    bad = []
    for cid, src, sid, _ in case_sources(sel):
        up = upgraded(upgrades, cid)
        path = long_record_path(cid) if up else rp(os.path.join(SOLVE_LOGS, f"{cid}.json"))
        if not os.path.exists(path):
            raise SystemExit(f"[collect] no solve record for {cid}; run `solve --case {cid}` first")
        if up and sha256_file(path) != upgrades["cases"][cid]["long_solve"]["record_sha256"]:
            raise SystemExit(f"[collect] the long solve record of {cid} changed since the upgrade was recorded")
        rec = normalize_record(load_json(path), path + ".cbc.log")
        official = MC.official_value(rp(instance_path(src, sid))) if src == "miplib_nl" else None
        ref, kind, problems = reference_decision(src, rec, official)
        if up and kind != "cbc_optimal":
            problems.append("an upgraded reference must be cbc_optimal")
        bad += [f"{cid}: {p}" for p in problems]
        out["cases"][cid] = {"source": src, "source_id": sid, "reference_objective": ref, "reference_kind": kind,
                             "official_value": official, "problems": problems,
                             "cbc": {k: rec.get(k) for k in REF_KEYS if k in rec},
                             "solve_record_sha256": sha256_file(path)}
        if up:
            out["cases"][cid]["upgraded_from"] = upgrades["cases"][cid]["before"]
    return out, bad


def write_reference_values(doc):
    with open(rp(REFERENCE_PATH), "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def cmd_collect(a):
    out, bad = collect_doc()
    write_reference_values(out)
    print(f"[collect] {len(out['cases'])} case(s) -> {REFERENCE_PATH}" + ("" if not bad else "; PROBLEMS: " + "; ".join(bad)))
    return 1 if bad else 0


UPGRADE_RULE = ("a cbc_time_limited reference becomes cbc_optimal before the freeze when one longer CBC solve (one thread, "
                "default 14400 s, same model and options) ends with 'Optimal solution found' (ratioGap 1e-7), its schedule "
                "passes the independent check (0 violations, recomputed cost within 1e-9 relative) and its optimum lies in "
                "the earlier interval [bound, best value] widened by 1e-6 relative at each end; otherwise the time-limited "
                "reference and its interval stay and the attempt is recorded")


def upgrade_decision(before, long_rec):
    """(upgraded, reason) for a time-limited reference `before` (a reference_values entry) and a normalized long
    solve record."""
    if before["reference_kind"] != "cbc_time_limited":
        return False, f"reference is {before['reference_kind']}, not cbc_time_limited"
    if long_rec.get("status") != "optimal" or long_rec.get("objective") is None:
        return False, f"long solve ended {long_rec.get('status')}, no optimality proof"
    chk = long_rec.get("check") or {}
    if chk.get("n_violations") != 0 or chk.get("rel_diff", 1) > 1e-9:
        return False, "the long solve's schedule fails the independent check"
    lo, hi = sorted((before["cbc"]["bound"], before["reference_objective"]))
    x = long_rec["objective"]
    if not (lo - 1e-6 * max(1.0, abs(lo)) <= x <= hi + 1e-6 * max(1.0, abs(hi))):
        return False, "the long solve's optimum lies outside the earlier interval (the two solves disagree)"
    return True, "optimality proved by the long solve"


def cmd_upgrade(a):
    refuse_after_freeze("upgrade")
    refs = load_json(REFERENCE_PATH)["cases"]
    ups = load_upgrades()
    ups.update({"schema": "orgene.r1.eng_reference_upgrades.v1", "rule": UPGRADE_RULE})
    changed = False
    for cid, before in sorted(refs.items()):
        path = long_record_path(cid)
        if (a.case and cid not in a.case) or not os.path.exists(path) or upgraded(ups, cid):
            continue
        rec = normalize_record(load_json(path), path + ".cbc.log")
        ok, why = upgrade_decision(before, rec)
        cbc = before["cbc"]
        ups["cases"][cid] = {
            "decided_utc": now_iso(), "upgraded": ok, "reason": why,
            "before": {"reference_kind": before["reference_kind"], "reference_objective": before["reference_objective"],
                       "bound": cbc.get("bound"), "gap": cbc.get("gap"), "status": cbc.get("status"),
                       "wall_seconds": cbc.get("wall_seconds"), "time_limit_s": (cbc.get("options") or {}).get("time_limit_s"),
                       "solve_record_sha256": before["solve_record_sha256"]},
            "long_solve": {"status": rec.get("status"), "objective": rec.get("objective"), "bound": rec.get("bound"),
                           "gap": rec.get("gap"), "wall_seconds": rec.get("wall_seconds"),
                           "options": rec.get("options"), "cbc_version": rec.get("cbc_version"),
                           "check": {k: (rec.get("check") or {}).get(k) for k in ("n_violations", "rel_diff")},
                           "started_at": rec.get("started_at"), "finished_at": rec.get("finished_at"),
                           "record_sha256": sha256_file(path)},
            "after": ({"reference_kind": "cbc_optimal", "reference_objective": rec["objective"]} if ok else None),
        }
        changed = changed or ok
        print(f"[upgrade] {cid}: {'upgraded to cbc_optimal' if ok else 'kept as cbc_time_limited'} ({why})")
    with open(rp(UPGRADES_PATH), "w", encoding="utf-8") as f:
        f.write(json.dumps(ups, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    if not changed:
        print(f"[upgrade] no reference changed; {UPGRADES_PATH} records the attempt(s)")
        return 0
    if cmd_collect(a):
        return 1
    a.force = True
    cmd_build(a)
    cmd_split(a)
    print("[upgrade] references, case file and split rebuilt; record the new hashes (eng_hashes.json) before the freeze")
    return 0


def build_records():
    """(header, rows, hashes) of data/cases/eng.jsonl from the raw files, the selection and the reference values."""
    sel = load_json(SELECTION_PATH)
    refs = load_json(REFERENCE_PATH)["cases"]
    rows, hashes = [], {}
    for cid, src, sid, files in case_sources(sel):
        for rel_path, ent in files.items():
            p = rp(os.path.join(raw_dir(src), rel_path))
            if not os.path.exists(p) or git_blob_sha1(p) != ent["git_blob"]:
                raise SystemExit(f"[build] source file of {cid} missing or changed; run `fetch`")
        text, info = render_case(src, sid)
        r = refs[cid]
        if r["reference_objective"] is None or r["problems"]:
            raise SystemExit(f"[build] {cid} has no usable reference value ({r['reference_kind']}, {r['problems']})")
        cbc = r["cbc"]
        extra = {
            "reference_kind": r["reference_kind"],
            "reference_solver": {"solver": "CBC", "cbc_version": cbc.get("cbc_version"), "status": cbc.get("status"),
                                 "bound": cbc.get("bound"), "gap": cbc.get("gap"),
                                 "gap_at_most": cbc.get("gap_at_most"), "wall_seconds": cbc.get("wall_seconds"),
                                 "time_limit_s": (cbc.get("options") or {}).get("time_limit_s")},
            # the optimum lies in this interval (CBC bound and incumbent) when the reference is time-limited
            "reference_interval": (sorted([cbc["bound"], cbc["objective"]])
                                   if r["reference_kind"] == "cbc_time_limited" and cbc.get("bound") is not None else None),
            "official_value": r["official_value"],
            "stratum": next(c.get("stratum") for c in sel["cases"] if c["case_id"] == cid),
            # defects of the benchmark's own wording, kept verbatim (selection.json; E22 verification)
            "source_text_issues": next(c.get("source_text_issues", []) for c in sel["cases"] if c["case_id"] == cid),
            "source_repo": SOURCES[src]["repo"], "source_commit": SOURCES[src]["commit"],
            "source_files": {k: {"git_blob": v["git_blob"], "bytes": v["bytes"]} for k, v in sorted(files.items())},
            "text_builder": {k: info[k] for k in ("template_version", "template_sha256", "converter_version", "glue_sha256") if k in info},
            "changes": SOURCES[src]["changes"],
        }
        ref = r["reference_objective"]
        # kind and interval travel with the reference: score.is_correct judges a cbc_time_limited case by the interval
        row = {"case_id": cid, "source": src, "source_id": sid, "text": text,
               "reference": {"objective": ref, "raw": repr(ref), "status": None, "kind": r["reference_kind"],
                             "interval": extra["reference_interval"]},
               "extra": extra, "license": SOURCES[src]["license"]}
        rows.append(row)
        hashes[cid] = {"text_sha256": sha256_bytes(text.encode("utf-8")),
                       "reference_objective": ref, "reference_kind": r["reference_kind"],
                       "record_sha256": sha256_bytes((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))}
    header = {"_header": True, "source": "eng", "schema": SCHEMA_CASES, "n": len(rows),
              "built_by": "data/ingest_eng.py", "selection_sha256": sha256_file(rp(SELECTION_PATH)),
              "reference_values_sha256": sha256_file(rp(REFERENCE_PATH)),
              "renderer_sha256": sha256_file(os.path.join(HERE, "eng", "pglib_uc_render.py")),
              "converter_sha256": sha256_file(os.path.join(HERE, "eng", "miplib_nl_convert.py")),
              "isolation": "data/cases/README_ISOLATION.md"}
    return header, rows, hashes


def cases_bytes(header, rows):
    lines = [json.dumps(header, ensure_ascii=False)] + [json.dumps(r, ensure_ascii=False) for r in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def hashes_doc(header, rows, hashes, data):
    ids = [r["case_id"] for r in rows]
    return {"schema": "orgene.r1.eng_hashes.v1",
            "note": "SHA-256 of the engineering-source case ids, problem texts and reference values (E22), for the "
                    "freeze manifest and the OSF upload. ids_sha256 = sha256(json.dumps(sorted ids)), as split.py hashes id lists.",
            "cases_path": CASES_PATH, "cases_sha256": sha256_bytes(data),
            "ids": ids, "ids_sha256": sha256_bytes(json.dumps(sorted(ids)).encode()),
            "reference_values_sha256": header["reference_values_sha256"], "cases": hashes}


def cmd_build(a):
    header, rows, hashes = build_records()
    data = cases_bytes(header, rows)
    path = rp(CASES_PATH)
    if os.path.exists(path) and open(path, "rb").read() != data and not a.force:
        raise SystemExit(f"[build] {CASES_PATH} exists with other content; it is frozen once the split exists (use --force "
                         "only before any eng_holdout run and record why)")
    with open(path, "wb") as f:
        f.write(data)
    with open(rp(HASHES_PATH), "w", encoding="utf-8") as f:
        f.write(json.dumps(hashes_doc(header, rows, hashes, data), indent=2, sort_keys=True) + "\n")
    print(f"[build] {len(rows)} case(s) -> {CASES_PATH} sha256 {sha256_bytes(data)[:16]}")


def cmd_split(a):
    from orgene import split as S
    info = S.freeze_eng_holdout(rp(CASES_PATH), rp(SPLIT_DIR),
                                existing_split_dirs=[os.path.join(rp("data/splits"), d) for d in sorted(os.listdir(rp("data/splits")))
                                                     if d != "eng" and os.path.isdir(os.path.join(rp("data/splits"), d))],
                                force=a.force)
    print(json.dumps({k: info[k] for k in ("n_eng_holdout", "eng_holdout_sha256", "cases_sha256")}, indent=2))


def screening_eligible(stratum, out):
    """(eligible, reasons) of one screened MIPLIB-NL instance, re-derived from the evidence its screening entry records
    (E1-E4 of selection.json; reference_decision as for the case set), not from its recorded `eligible` flag."""
    why = []
    if not out.get("E1_files_complete"):
        why.append("E1")
    if not out.get("E2_official_numeric"):
        why.append("E2")
    tok = out.get("tokens") or {}
    fits = isinstance(tok.get("max_prompt"), int) and tok["max_prompt"] + NUM_PREDICT <= NUM_CTX
    if not (fits and tok.get("round0_fits") is True):
        why.append("E3")
    cbc = out.get("cbc")
    if not cbc:
        return False, why + ["E4: no solve outcome"]
    if (out.get("model_variant") or {}).get("carries_over") is False:
        why.append("E4: the solved relaxation does not carry over")
    _, kind, probs = reference_decision("miplib_nl", cbc, out.get("official_value"))
    why += [f"E4: {p}" for p in probs]
    if kind == "no_reference":
        why.append("E4: no reference")
    elif stratum in ("T", "S") and kind not in ("cbc_optimal", "cbc_attains_published_optimum"):
        why.append(f"E4: {kind} in stratum {stratum}")
    return not why, why


def check_selection(sel):
    """Problems (list of str) between selection.json and the seeded orders / eligibility outcomes it records.
    Eligibility is re-derived from each screening entry's evidence (screening_eligible)."""
    problems = []
    mt = load_json(SOURCES["miplib_nl"]["tree"])
    pt = load_json(SOURCES["pglib_uc"]["tree"])
    for src in SOURCES:
        if sha256_file(rp(SOURCES[src]["tree"])) != sel["sources"][src]["tree_sha256"]:
            problems.append(f"{src}: tree listing changed since the selection")
    draw = pglib_draw(pt)
    chosen = [c["source_id"].split("/")[1] for c in sorted(sel["cases"], key=lambda c: c["case_id"]) if c["source"] == "pglib_uc"]
    if chosen != draw:
        problems.append(f"pglib_uc: chosen {chosen} but the seeded draw is {draw}")
    orders = miplib_orders(mt)
    screened = sel["miplib_nl_screening"]
    for st, _, _ in MIPLIB_STRATA:
        picked = []
        for name in orders[st]:
            if len(picked) == MIPLIB_PER_STRATUM:
                break
            out = screened.get(name)
            if out is None:
                problems.append(f"miplib_nl {st}: {name} comes before the picks in the seeded order but has no screening outcome")
                break
            if screening_eligible(st, out)[0]:
                picked.append(name)
        got = [c["source_id"] for c in sorted(sel["cases"], key=lambda c: c["case_id"]) if c["source"] == "miplib_nl" and c["stratum"] == st]
        if got != picked:
            problems.append(f"miplib_nl {st}: chosen {got} but the first eligible in the seeded order are {picked}")
    for name, out in sorted(screened.items()):
        ok, why = screening_eligible(out.get("stratum"), out)
        if ok != bool(out.get("eligible")):
            problems.append(f"miplib_nl {name}: recorded eligible={out.get('eligible')} but its evidence gives {ok} ({'; '.join(why)})")
        raw = rp(os.path.join(SOLVE_LOGS, f"miplib_nl.{name}.json"))
        if out.get("cbc") and os.path.exists(raw):  # the screening solve record, where data/raw/eng is present
            rec = normalize_record(load_json(raw), raw + ".cbc.log")
            if any(rec.get(k) != out["cbc"].get(k) for k in ("status", "objective", "bound")):
                problems.append(f"miplib_nl {name}: screening outcome differs from its solve record")
    for c in sel["cases"]:
        if c["source"] == "miplib_nl" and c.get("tokens") != (screened.get(c["source_id"]) or {}).get("tokens"):
            problems.append(f"{c['case_id']}: token counts differ from the screening record")
    for c in sel["cases"]:
        tree_files = (pt["files"] if c["source"] == "pglib_uc" else
                      {f"dataset/{c['source_id']}/{k}": v for k, v in mt["instances"][c["source_id"]].items()})
        for k, v in c["source_files"].items():
            if tree_files.get(k) != v:
                problems.append(f"{c['case_id']}: source file {k} does not match the tree listing")
    return problems


def cmd_check(a):
    problems = []
    sel = load_json(SELECTION_PATH)
    problems += check_selection(sel)
    ups = load_upgrades()
    for cid, u in sorted(ups["cases"].items()):
        kind = load_json(REFERENCE_PATH)["cases"].get(cid, {}).get("reference_kind")
        if u.get("upgraded") != (kind == "cbc_optimal" and u.get("before", {}).get("reference_kind") == "cbc_time_limited"):
            problems.append(f"{cid}: {UPGRADES_PATH} and {REFERENCE_PATH} disagree on the upgrade")
    if all(os.path.exists(rp(os.path.join(SOLVE_LOGS, f"{c['case_id']}.json"))) for c in sel["cases"]):
        try:  # the reference values re-derived from the solve records (data/raw/eng present)
            doc, _ = collect_doc(sel, ups)
            if json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n" != open(rp(REFERENCE_PATH), encoding="utf-8").read():
                problems.append(f"{REFERENCE_PATH} differs from the values re-derived from the solve records")
        except SystemExit as e:
            problems.append(str(e))
    else:
        print(f"  --  solve records not present; {REFERENCE_PATH} not re-derived")
    try:
        header, rows, hashes = build_records()
        data = cases_bytes(header, rows)
        if not os.path.exists(rp(CASES_PATH)) or open(rp(CASES_PATH), "rb").read() != data:
            problems.append(f"{CASES_PATH} differs from a fresh build (renderer, converter, raw files or references changed)")
        want = json.dumps(hashes_doc(header, rows, hashes, data), indent=2, sort_keys=True) + "\n"
        if not os.path.exists(rp(HASHES_PATH)) or open(rp(HASHES_PATH), encoding="utf-8").read() != want:
            problems.append(f"{HASHES_PATH} differs from a fresh build")
        again = cases_bytes(*build_records()[:2])
        if again != data:
            problems.append("two builds in a row differ (rendering is not deterministic)")
    except SystemExit as e:
        problems.append(str(e))
    from orgene import split as S
    probs = S.verify_eng_holdout(rp(SPLIT_DIR), rp(CASES_PATH)) if os.path.isdir(rp(SPLIT_DIR)) else [f"{SPLIT_DIR} missing"]
    problems += probs
    for p in problems:
        print(f"  BAD {p}")
    print("RESULT:", "PASS" if not problems else "FAIL")
    return 0 if not problems else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("select")
    p.add_argument("--show", type=int, default=8)
    p.set_defaults(fn=cmd_select)
    p = sub.add_parser("fetch")
    p.add_argument("--case", nargs="*", default=None)
    p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("solve")
    p.add_argument("--case", nargs="+", required=True)
    p.add_argument("--time-limit", type=int, default=1800)
    p.set_defaults(fn=cmd_solve)
    p = sub.add_parser("collect")
    p.set_defaults(fn=cmd_collect)
    p = sub.add_parser("build")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("split")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_split)
    p = sub.add_parser("check")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("long-solve")
    p.add_argument("--case", nargs="+", required=True)
    p.add_argument("--time-limit", type=int, default=LONG_TIME_LIMIT_S)
    p.set_defaults(fn=cmd_long_solve)
    p = sub.add_parser("upgrade")
    p.add_argument("--case", nargs="*", default=None)
    p.set_defaults(fn=cmd_upgrade)
    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
