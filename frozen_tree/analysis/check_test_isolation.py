#!/usr/bin/env python3
"""Verify the frozen splits and the R1 analysis sets, and prove that no held-out case reached anything tuned on dev.

  $ORGENE_PY analysis/check_test_isolation.py [--experiments experiments] [--splits data/splits] [...]

Every default path is relative to the repository root (not the working directory), and every path printed is
relative to it. Held-out ids = the frozen test ids, plus the ids of any `eng_holdout_ids.json` next to a SPLIT_LOCK
(engineering case set, E22).

  1. frozen splits (data/splits/*): cases/dev/test hashes recomputed as split.py wrote them, counts, disjointness
  2. R1 subset locks (data/splits_r1/*): parent lock unchanged, no case changed side, hashes (E14)
  3. id sets (data/analysis_sets/analysis_sets.v2.json) on their frozen sides, *_excl0905 sets without the
     2026-09-05-viewed cases; every analysis-set definition (configs/analysis_set_defs.r1.json) meets its
     must_exclude / expect / relations. A definition waiting for an annotation list is reported PENDING, not FAIL.
  4. non-test runs under experiments/ (every text file: requests, units, outputs, configs) and --scan dirs:
     no held-out id. Runs whose top-level directory name contains "-test-" or "-eng_holdout-" (E22) are skipped by
     design and never opened.
  5. baseline training inputs (files under baselines/ named *manifest* / *train* / *library* / *experience*,
     outside "-test-" directories, plus every --train-manifest): no held-out id
  6. gene devCaseIds and activation.devEvidence (genes/*.jsonl): every id is a frozen dev id
  7. text of conditions/ and genes/: no held-out id, in the canonical form (industryor-0014) or a short form
     (IndustryOR 0014, mamo 0022)
Only ids, counts and hashes are printed; no case text is read (case files are only hashed). Exit code 1 on failure.
"""
import argparse
import fnmatch
import glob
import hashlib
import json
import os
import re
import sys

CODE_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(CODE_ROOT, "runtime"))

from orgene import analysis_sets as A  # noqa: E402
from orgene import split as S  # noqa: E402

# canonical ids and the short forms used in notes ("mamo 0022", "IndustryOR-0014"); normalised to canonical ids
ID_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(mamo(?:[_ -]?complex[_ -]?lp)?|industry[_ -]?or)[\s_#-]*(\d{4})(?!\d)")
TRAIN_PATTERNS = ("*manifest*", "*train*", "*library*", "*experience*")
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv-tools"}
SEALED_RUN_TAGS = ("-test-", "-eng_holdout-")  # run directory names of sealed runs (never opened here)


def sealed_run(name):
    return any(tag in name for tag in SEALED_RUN_TAGS)


def canonical(m):
    src = "mamo_complex_lp" if m.group(1).lower().startswith("mamo") else "industryor"
    return f"{src}-{m.group(2)}"


class Scanner:
    """Finds held-out ids in text: benchmark ids via ID_RE, any other held-out id (E22) literally."""

    def __init__(self, held_out):
        self.held_out = set(held_out)
        other = sorted(h for h in self.held_out if not ID_RE.fullmatch(h))
        self.literal = (re.compile(r"(?<![\w-])(" + "|".join(re.escape(h) for h in other) + r")(?![\w])")
                        if other else None)

    def ids_in(self, text):
        found = {canonical(m) for m in ID_RE.finditer(text)} & self.held_out
        if self.literal:
            found |= set(self.literal.findall(text))
        return found

    def scan_file(self, path):
        with open(path, "rb") as f:
            data = f.read()
        if b"\0" in data[:8192]:
            return set()
        return self.ids_in(data.decode("utf-8", errors="ignore"))


def walk_files(top, skip_test_dirs=True):
    for d, dirs, files in os.walk(top):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not (skip_test_dirs and sealed_run(x)))
        for fn in sorted(files):
            yield os.path.join(d, fn)


class Report:
    def __init__(self, root):
        self.root, self.ok, self.pending = root, True, 0

    def rel(self, p):
        return os.path.relpath(p, self.root).replace(os.sep, "/")

    def line(self, good, msg):
        self.ok = self.ok and good
        print(f"  {'OK ' if good else 'BAD'} {msg}")


def check_frozen_splits(rep, splits_dir):
    dev_ids, test_ids, holdout = {}, {}, {}
    for lock_path in sorted(glob.glob(os.path.join(splits_dir, "*", "SPLIT_LOCK.json"))):
        d = os.path.dirname(lock_path)
        name = os.path.basename(d)
        lock = json.load(open(lock_path, encoding="utf-8"))
        dev = json.load(open(os.path.join(d, "dev_ids.json"), encoding="utf-8"))
        test = json.load(open(os.path.join(d, "test_ids.json"), encoding="utf-8"))
        dev_ids[name], test_ids[name] = set(dev), set(test)
        eh = os.path.join(d, "eng_holdout_ids.json")
        if os.path.exists(eh):
            holdout[name] = set(json.load(open(eh, encoding="utf-8")))
        cases_path = lock["cases_path"] if os.path.isabs(lock["cases_path"]) else os.path.join(rep.root, lock["cases_path"])
        cases_sha = hashlib.sha256(open(cases_path, "rb").read()).hexdigest() if os.path.exists(cases_path) else "missing"
        print(f"[{rep.rel(d)}]")
        for label, got, want in (("cases_sha256", cases_sha, lock["cases_sha256"]),
                                 ("dev_sha256", S.ids_sha256(dev), lock["dev_sha256"]),
                                 ("test_sha256", S.ids_sha256(test), lock["test_sha256"]),
                                 ("n_dev", len(dev), lock["n_dev"]), ("n_test", len(test), lock["n_test"])):
            rep.line(str(got) == str(want), f"{label}: {got}" + ("" if str(got) == str(want) else f"  != lock {want}"))
        shared = dev_ids[name] & test_ids[name]
        rep.line(not shared, f"dev/test disjoint ({len(shared)} shared)")
        if lock.get("kind") == "eng_holdout" or "eng_holdout_sha256" in lock:  # E22 split: its id file is locked too
            eh_ids = sorted(holdout.get(name, set()))
            good = (os.path.exists(eh) and S.ids_sha256(eh_ids) == lock.get("eng_holdout_sha256")
                    and len(eh_ids) == lock.get("n_eng_holdout"))
            rep.line(good, f"eng_holdout_sha256: {S.ids_sha256(eh_ids)}" + ("" if good else "  != lock"))
            both = holdout.get(name, set()) & (dev_ids[name] | test_ids[name])
            rep.line(not both, f"eng_holdout disjoint from dev/test ({len(both)} shared)")
    return dev_ids, test_ids, holdout


def check_subset_locks(rep, splits_r1_dir):
    dirs = sorted(os.path.dirname(p) for p in glob.glob(os.path.join(splits_r1_dir, "*", "SPLIT_LOCK.json")))
    print(f"\n[{rep.rel(splits_r1_dir)}] {len(dirs)} subset lock(s)")
    for d in dirs:
        problems = S.verify_subset_lock(d, rep.root)
        lock = json.load(open(os.path.join(d, "SPLIT_LOCK.json"), encoding="utf-8"))
        rep.line(not problems, f"{os.path.basename(d)}: dev {lock.get('n_dev')} / test {lock.get('n_test')}, "
                               f"parent {lock.get('parent_lock')}" + ("" if not problems else " -- " + "; ".join(problems)))


def check_analysis_sets(rep, id_sets_path, defs_path):
    print("\n[analysis sets]")
    if not os.path.exists(id_sets_path):
        print(f"  --  {rep.rel(id_sets_path)} not present; skipped")
        return
    try:
        doc = A.load_id_sets(id_sets_path, rep.root)
        rep.line(True, f"{rep.rel(id_sets_path)}: {len(doc['sets'])} id sets on their frozen sides; "
                       f"*_excl0905 sets hold none of the {len(doc['exclusions'][A.SEEN]['ids'])} viewed cases")
    except (A.DefinitionError, OSError, KeyError) as e:
        rep.line(False, str(e))
        return
    if not os.path.exists(defs_path):
        print(f"  --  {rep.rel(defs_path)} not present; skipped")
        return
    try:
        defs = A.load_set_defs(defs_path, rep.root, id_sets_path=id_sets_path)
        lists = A.load_named_lists(doc, rep.root)
        res = A.resolve_sets(defs, doc, lists, strict=False)
    except (A.DefinitionError, OSError, KeyError) as e:
        rep.line(False, f"{rep.rel(defs_path)}: {e}")
        return
    for name, r in res.items():
        counts = ", ".join(f"{b} {len(v)}" for b, v in sorted(r["by_benchmark"].items())) or "no case"
        if r["pending"]:
            rep.pending += 1
            print(f"  PEND {name} ({r['split']}): {counts} so far; waiting for {', '.join(r['pending'])}")
        else:
            rep.line(True, f"{name} ({r['split']}): {r['n']} cases ({counts})")


def check_runs(rep, experiments, extra_scan, scanner):
    print(f"\nscanning every text file of the non-test runs under {rep.rel(experiments)} "
          "(runs named *-test-* or *-eng_holdout-* skipped)")
    leaks, n_files, skipped, skipped_eng = [], 0, 0, 0
    if os.path.isdir(experiments):
        for run in sorted(os.listdir(experiments)):
            p = os.path.join(experiments, run)
            if sealed_run(run):
                skipped += 1
                skipped_eng += "-test-" not in run
                continue
            for f in (walk_files(p) if os.path.isdir(p) else [p]):
                n_files += 1
                leaks += [(rep.rel(f), c) for c in sorted(scanner.scan_file(f))]
    for top in extra_scan:
        if os.path.isdir(top):
            for f in walk_files(top):
                n_files += 1
                leaks += [(rep.rel(f), c) for c in sorted(scanner.scan_file(f))]
    print(f"  scanned {n_files} file(s) ({skipped - skipped_eng} test run(s) skipped by design"
          + (f", {skipped_eng} eng_holdout run(s) skipped by design" if skipped_eng else "") + ")")
    report_leaks(rep, leaks, "no held-out case id appears in any dev/smoke run or unit file")


def check_train_inputs(rep, baselines, manifests, scanner):
    files = []
    if os.path.isdir(baselines):
        files = [f for f in walk_files(baselines)
                 if any(fnmatch.fnmatch(os.path.basename(f).lower(), pat) for pat in TRAIN_PATTERNS)]
    files += [m for m in manifests if os.path.exists(m)]
    missing = [m for m in manifests if not os.path.exists(m)]
    print(f"\nscanning {len(files)} baseline training input file(s)")
    for m in missing:
        rep.line(False, f"--train-manifest {rep.rel(m)} does not exist")
    leaks = [(rep.rel(f), c) for f in files for c in sorted(scanner.scan_file(f))]
    report_leaks(rep, leaks, "no held-out case id in any baseline training input")


def check_genes(rep, genes_dir, conditions_dir, all_dev, scanner):
    print(f"\nchecking devCaseIds in {rep.rel(genes_dir)}/*.jsonl and the text of "
          f"{rep.rel(conditions_dir)}/, {rep.rel(genes_dir)}/")
    bad, n_ids = [], 0
    for path in sorted(glob.glob(os.path.join(genes_dir, "*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                if not line.strip():
                    continue
                g = json.loads(line)
                refs = [("devCaseIds", c) for c in (g.get("audit") or {}).get("devCaseIds") or []]
                ev = (g.get("activation") or {}).get("devEvidence") if isinstance(g.get("activation"), dict) else None
                refs += [("activation.devEvidence", c) for c in (ev if isinstance(ev, list) else [])]  # E04 field (E22)
                for field, c in refs:
                    n_ids += 1
                    if c not in all_dev:
                        why = "held-out" if c in scanner.held_out else "not a frozen dev id"
                        bad.append(f"{rep.rel(path)}:{ln} {g.get('geneId')} {field}: {c} ({why})")
    for b in bad:
        rep.line(False, b)
    if not bad:
        rep.line(True, f"all {n_ids} devCaseIds / activation.devEvidence ids are frozen dev ids")
    leaks = []
    for top in (conditions_dir, genes_dir):
        if os.path.isdir(top):
            leaks += [(rep.rel(f), c) for f in walk_files(top, skip_test_dirs=False) for c in sorted(scanner.scan_file(f))]
    report_leaks(rep, leaks, "no held-out case id in the conditions/ or genes/ text")


def report_leaks(rep, leaks, ok_msg):
    if leaks:
        rep.line(False, f"{len(leaks)} held-out id occurrence(s):")
        for f, c in leaks[:40]:
            print(f"      {f}: {c}")
    else:
        rep.line(True, ok_msg)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=CODE_ROOT, help="repository root that the other paths are relative to")
    ap.add_argument("--experiments", default="experiments")
    ap.add_argument("--splits", default="data/splits")
    ap.add_argument("--splits-r1", default="data/splits_r1")
    ap.add_argument("--id-sets", default=A.ID_SETS_PATH)
    ap.add_argument("--set-defs", default=A.SET_DEFS_PATH)
    ap.add_argument("--genes", default="genes")
    ap.add_argument("--conditions", default="conditions")
    ap.add_argument("--baselines", default="baselines")
    ap.add_argument("--scan", action="append", default=[], help="extra non-test directory to scan (default: units/ if present)")
    ap.add_argument("--train-manifest", action="append", default=[], help="baseline training-input file (must exist)")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)

    def p(x):
        return x if os.path.isabs(x) else os.path.join(root, x)

    rep = Report(root)
    dev_ids, test_ids, holdout = check_frozen_splits(rep, p(a.splits))
    all_dev = set().union(*dev_ids.values())
    held_out = set().union(*test_ids.values(), *holdout.values())
    print(f"\nheld-out ids total: {len(held_out)} (" + ", ".join(f"{k}={len(v)}" for k, v in sorted(test_ids.items()))
          + ("; eng_holdout " + ", ".join(f"{k}={len(v)}" for k, v in sorted(holdout.items())) if holdout else "") + ")")
    if not test_ids:
        rep.line(False, f"no frozen split found under {rep.rel(p(a.splits))}")
    if all_dev & held_out:
        rep.line(False, f"{len(all_dev & held_out)} id(s) are dev in one split and held out in another")
    scanner = Scanner(held_out)

    if os.path.isdir(p(a.splits_r1)):
        check_subset_locks(rep, p(a.splits_r1))
    check_analysis_sets(rep, p(a.id_sets), p(a.set_defs))
    extra = [p(x) for x in a.scan] or ([p("units")] if os.path.isdir(p("units")) else [])
    check_runs(rep, p(a.experiments), extra, scanner)
    check_train_inputs(rep, p(a.baselines), [p(x) for x in a.train_manifest], scanner)
    check_genes(rep, p(a.genes), p(a.conditions), all_dev, scanner)

    tail = f" ({rep.pending} analysis set(s) pending annotation)" if rep.pending else ""
    print("\nRESULT:", ("PASS" if rep.ok else "FAIL") + tail)
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
