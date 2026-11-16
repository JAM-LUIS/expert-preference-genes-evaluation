"""R1 analysis sets (E14): which cases each analysis uses. No case id is written in this code.

Two layers:
  id sets      data/analysis_sets/analysis_sets.v2.json   stage-1 output, copied byte for byte (case ids and their
                                                           dev/test side only; hash kept in the set definitions)
  definitions  configs/analysis_set_defs.r1.json           named analysis sets (main, sensitivity sets, dev sets)
                                                           composed from id-set names and named exclusion lists
Named lists a definition can subtract or intersect:
  seen_20260905_test     the 9 test cases whose statements were viewed on 2026-09-05 (from the id sets)
  nl_not_linearizable    IndustryOR cases labelled NL_NOT_LINEARIZABLE        } data/exclusions_r1.json, written by
  q3_removed             reference check AMBIGUOUS / UNDERSPECIFIED (rule Q3)  } data/ingest_annotations.py; "pending"
                                                                                 until the annotations are ingested;
                         must equal the AMBIGUOUS / UNDERSPECIFIED entries of data/reference_overrides/ (E13 files)
  underspecified_screen  keyword screen data/mamo_underspecified_ids.json (as analysis/paired_bootstrap.py --subset)

Every set keeps the frozen split: an id-set's dev (test) list must lie inside the frozen dev (test) ids of its
benchmark (no case changes side). A definition lists the lists it must not contain (`must_exclude`), counts it must
reproduce (`expect`) and relations to other definitions (`relations`); any violation raises DefinitionError.
A definition that depends on a pending list resolves with that list taken as empty and reports it in `pending`;
with strict=True (the default for analysis code) it raises PendingError instead.
"""
import hashlib
import json
import os

from .paths import rel, resolve
from .split import ids_sha256, read_lock_dir, split_subset

ID_SETS_PATH = "data/analysis_sets/analysis_sets.v2.json"
SET_DEFS_PATH = "configs/analysis_set_defs.r1.json"
EXCLUSIONS_PATH = "data/exclusions_r1.json"
UNDERSPEC_PATH = "data/mamo_underspecified_ids.json"
OVERRIDES_DIR = "data/reference_overrides"
SPLITS_DIR = "data/splits"
REMOVING_VERDICTS = ("AMBIGUOUS", "UNDERSPECIFIED")

ID_SETS_SCHEMA = "orgene-eaai-r1/analysis_sets/v2"
SET_DEFS_SCHEMA = "orgene-r1/analysis_set_defs/v1"
EXCLUSIONS_SCHEMA = "orgene-r1/exclusions/v1"

SIDES = ("dev", "test")
SEEN = "seen_20260905_test"
NL = "nl_not_linearizable"
Q3 = "q3_removed"
UNDERSPEC = "underspecified_screen"
EXCLUSION_LISTS = (NL, Q3)          # the lists that come from data/exclusions_r1.json
REFERENCE_KINDS = ("r1", "original", "not_a_signal")
EXCL_SUFFIX = "_excl0905"


class DefinitionError(ValueError):
    """An analysis set violates its definition (wrong side, forbidden case, count or relation)."""


class PendingError(RuntimeError):
    """An analysis set depends on a list that has not been produced yet (annotation not ingested)."""


def sha256_path(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ------------------------------------------------------------------ id sets (stage-1 file)


def load_id_sets(path=None, root=None, check_splits=True):
    """Load and validate the id-set file; raises DefinitionError listing every problem."""
    path = resolve(path or ID_SETS_PATH, root)
    doc = json.load(open(path, encoding="utf-8"))
    problems = validate_id_sets(doc, root=root, check_splits=check_splits)
    if problems:
        raise DefinitionError(f"{rel(path, root)}: " + "; ".join(problems))
    return doc


def validate_id_sets(doc, root=None, check_splits=True):
    """Problems in an id-set document (empty list = valid). Checks only ids, sides, counts and hashes."""
    p = []
    if doc.get("schema") != ID_SETS_SCHEMA:
        return [f"schema is {doc.get('schema')!r}, expected {ID_SETS_SCHEMA!r}"]
    sets = doc.get("sets") or {}
    for name, s in sets.items():
        b = s.get("benchmark")
        for side in SIDES:
            ids = s.get(side)
            if not isinstance(ids, list) or ids != sorted(set(ids)):
                p.append(f"{name}.{side} is not a sorted list of distinct ids")
                continue
            if any(not str(c).startswith(f"{b}-") for c in ids):
                p.append(f"{name}.{side} holds ids of another benchmark than {b}")
            if len(ids) != s.get(f"n_{side}"):
                p.append(f"{name}: n_{side} = {s.get(f'n_{side}')} but {len(ids)} ids")
            if ids_sha256(ids) != s.get(f"{side}_ids_sha256"):
                p.append(f"{name}: {side}_ids_sha256 does not match its ids")
        if isinstance(s.get("dev"), list) and isinstance(s.get("test"), list):
            if set(s["dev"]) & set(s["test"]):
                p.append(f"{name}: dev and test share cases")
            if s.get("n") != len(s["dev"]) + len(s["test"]):
                p.append(f"{name}: n = {s.get('n')} but dev + test = {len(s['dev']) + len(s['test'])}")
    for bench, name in (doc.get("primary_sets") or {}).items():
        if name not in sets or sets[name].get("benchmark") != bench:
            p.append(f"primary_sets.{bench} names {name!r}, which is not a set of that benchmark")
    seen = (doc.get("exclusions", {}).get(SEEN) or {}).get("ids")
    if not isinstance(seen, list) or len(seen) != len(set(seen)):
        p.append(f"exclusions.{SEEN}.ids is missing or has duplicates")
        seen = []
    seen = set(seen)
    for name, s in sets.items():
        if not name.endswith(EXCL_SUFFIX):
            continue
        hit = sorted(seen & (set(s.get("dev", [])) | set(s.get("test", []))))
        if hit:
            p.append(f"{name} still contains {len(hit)} case(s) of {SEEN}: {hit}")
        base = sets.get(name[: -len(EXCL_SUFFIX)])
        if base is not None and (s.get("dev") != base.get("dev") or
                                 s.get("test") != sorted(set(base.get("test", [])) - seen)):
            p.append(f"{name} is not {name[: -len(EXCL_SUFFIX)]} minus {SEEN} (test side only)")
    if check_splits:
        p += _check_against_splits(doc, seen, root)
    return p


def _check_against_splits(doc, seen, root):
    p, all_test = [], set()
    by_bench = {}
    for name, s in (doc.get("sets") or {}).items():
        by_bench.setdefault(s.get("benchmark"), []).append(name)
    for bench, names in sorted(by_bench.items()):
        split_dir = resolve(os.path.join(SPLITS_DIR, bench), root)
        try:
            lock, dev, test = read_lock_dir(split_dir)
        except (OSError, ValueError, KeyError) as e:
            p.append(f"frozen split of {bench}: {e}")
            continue
        all_test |= set(test)
        origin = (doc.get("split_origin") or {}).get(f"{bench}_split_lock") or {}
        for k in ("dev_sha256", "test_sha256", "n_dev", "n_test", "seed"):
            if origin.get(k) != lock.get(k):
                p.append(f"split_origin.{bench}_split_lock.{k} differs from {SPLITS_DIR}/{bench}/SPLIT_LOCK.json")
        for name in names:
            s = doc["sets"][name]
            try:
                split_subset(dev, test, {"dev": s.get("dev", []), "test": s.get("test", [])})
            except ValueError as e:
                p.append(f"{name}: {e}")
    outside = sorted(seen - all_test)
    if outside:
        p.append(f"{SEEN} has {len(outside)} id(s) outside the frozen test splits: {outside}")
    return p


def benchmark_of(id_sets):
    """case id -> benchmark, from the id sets."""
    out = {}
    for s in id_sets["sets"].values():
        for side in SIDES:
            for c in s[side]:
                out[c] = s["benchmark"]
    return out


# ------------------------------------------------------------------ named lists


def load_named_lists(id_sets, root=None, exclusions_path=None, underspec_path=None):
    """{name: {"status": "final" | "pending", "ids": set, "source": relative path, "pending_ids": [...]}}."""
    out = {SEEN: {"status": "final", "ids": set(id_sets["exclusions"][SEEN]["ids"]), "source": ID_SETS_PATH,
                  "pending_ids": []}}
    ex_path = resolve(exclusions_path or EXCLUSIONS_PATH, root)
    if os.path.exists(ex_path):
        ex = json.load(open(ex_path, encoding="utf-8"))
        if ex.get("schema") != EXCLUSIONS_SCHEMA:
            raise DefinitionError(f"{rel(ex_path, root)}: schema {ex.get('schema')!r}, expected {EXCLUSIONS_SCHEMA!r}")
        for name in EXCLUSION_LISTS:
            e = ex.get(name) or {}
            status = e.get("status")
            if status not in ("final", "pending"):
                raise DefinitionError(f"{rel(ex_path, root)}: {name}.status must be 'final' or 'pending'")
            ids = e.get("ids", [])
            if not isinstance(ids, list) or ids != sorted(set(ids)):
                raise DefinitionError(f"{rel(ex_path, root)}: {name}.ids is not a sorted list of distinct ids")
            out[name] = {"status": status, "ids": set(ids), "source": rel(ex_path, root),
                         "pending_ids": list(e.get("pending_ids", []))}
    for name in EXCLUSION_LISTS:
        out.setdefault(name, {"status": "pending", "ids": set(), "source": EXCLUSIONS_PATH, "pending_ids": [],
                              "reason": "annotation not ingested yet"})
    # the reference-override files (E13 format) carry the same verdicts; both come from one ingest and must agree
    ov_ids = override_removed_ids(root)
    if ov_ids is not None:
        if out[Q3]["status"] != "final":
            raise DefinitionError(f"{OVERRIDES_DIR}/ has override files but {EXCLUSIONS_PATH} has no final {Q3} "
                                  "list; re-run data/ingest_annotations.py")
        if ov_ids != out[Q3]["ids"]:
            raise DefinitionError(f"{Q3} in {EXCLUSIONS_PATH} differs from the AMBIGUOUS / UNDERSPECIFIED entries "
                                  f"of {OVERRIDES_DIR}/ ({len(out[Q3]['ids'])} vs {len(ov_ids)} cases)")
    us_path = resolve(underspec_path or UNDERSPEC_PATH, root)
    if os.path.exists(us_path):
        doc = json.load(open(us_path, encoding="utf-8"))
        ids = {hit["case_id"] for src in doc.get("sources", {}).values() for hit in src.get("flagged", [])}
        out[UNDERSPEC] = {"status": "final", "ids": ids, "source": rel(us_path, root), "pending_ids": [],
                          "rule_version": doc.get("rule_version")}
    else:
        out[UNDERSPEC] = {"status": "pending", "ids": set(), "source": UNDERSPEC_PATH, "pending_ids": [],
                          "reason": "screen file missing"}
    return out


def override_removed_ids(root=None):
    """Case ids with verdict AMBIGUOUS / UNDERSPECIFIED in data/reference_overrides/*.json, or None without files.

    Reads only the entries' case_id / verdict fields (the format and its validation belong to E13, refs.py)."""
    d = resolve(OVERRIDES_DIR, root)
    files = sorted(f for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []
    if not files:
        return None
    ids = set()
    for fn in files:
        doc = json.load(open(os.path.join(d, fn), encoding="utf-8"))
        ids |= {e["case_id"] for e in doc.get("entries", []) if e.get("verdict") in REMOVING_VERDICTS}
    return ids


# ------------------------------------------------------------------ definitions


def load_set_defs(path=None, root=None, id_sets_path=None):
    """Load the definitions; the id-set file they name must have the recorded sha256."""
    path = resolve(path or SET_DEFS_PATH, root)
    defs = json.load(open(path, encoding="utf-8"))
    if defs.get("schema") != SET_DEFS_SCHEMA:
        raise DefinitionError(f"{rel(path, root)}: schema {defs.get('schema')!r}, expected {SET_DEFS_SCHEMA!r}")
    src = defs.get("id_sets") or {}
    ids_path = resolve(id_sets_path or src.get("path", ID_SETS_PATH), root)
    got = sha256_path(ids_path)
    if got != src.get("sha256"):
        raise DefinitionError(f"{rel(ids_path, root)} has sha256 {got[:16]}…, the definitions record "
                              f"{str(src.get('sha256'))[:16]}…; refusing to use a different id-set file")
    return defs


def _names_ids(names, split, id_sets, lists, pending):
    ids = set()
    for n in names:
        if n in lists:
            if lists[n]["status"] != "final":
                pending.add(n)
            ids |= lists[n]["ids"]
        elif n in id_sets["sets"]:
            ids |= set(id_sets["sets"][n][split])
        else:
            raise DefinitionError(f"unknown list or id set {n!r}")
    return ids


def resolve_sets(defs, id_sets, lists, strict=False, names=None):
    """Resolve every definition (or only `names` and what they depend on). Returns {name: result}.

    result = {"name", "split", "reference", "role", "ids" (sorted), "by_benchmark" {b: sorted ids}, "n",
              "sha256" (ids_sha256 of ids), "pending" (sorted list names)}.
    """
    table = defs.get("sets") or {}
    bench = benchmark_of(id_sets)
    done, active = {}, set()

    def one(name):
        if name in done:
            return done[name]
        if name not in table:
            raise DefinitionError(f"unknown analysis set {name!r}")
        if name in active:
            raise DefinitionError(f"analysis set {name!r} refers to itself")
        active.add(name)
        d = table[name]
        split = d.get("split")
        if split not in SIDES:
            raise DefinitionError(f"{name}: split must be 'dev' or 'test'")
        if d.get("reference") not in REFERENCE_KINDS:
            raise DefinitionError(f"{name}: reference must be one of {REFERENCE_KINDS}")
        pending, ids = set(), set()
        for t in d.get("terms") or []:
            if ("set" in t) == ("def" in t):
                raise DefinitionError(f"{name}: each term names exactly one of 'set' / 'def'")
            if "set" in t:
                if t["set"] not in id_sets["sets"]:
                    raise DefinitionError(f"{name}: unknown id set {t['set']!r}")
                part = set(id_sets["sets"][t["set"]][split])
            else:
                sub = one(t["def"])
                if sub["split"] != split:
                    raise DefinitionError(f"{name}: term {t['def']!r} is a {sub['split']} set")
                part = set(sub["ids"])
                pending |= set(sub["pending"])
            if t.get("benchmark"):
                part = {c for c in part if bench.get(c) == t["benchmark"]}
            if t.get("only"):
                part &= _names_ids(t["only"], split, id_sets, lists, pending)
            if t.get("minus"):
                part -= _names_ids(t["minus"], split, id_sets, lists, pending)
            ids |= part
        if not ids and not pending and not d.get("allow_empty"):
            raise DefinitionError(f"{name}: resolves to an empty set")
        for n in d.get("must_exclude") or []:
            hit = sorted(ids & _names_ids([n], split, id_sets, lists, pending))
            if hit:
                raise DefinitionError(f"{name} contains {len(hit)} case(s) of {n}, which it must exclude: {hit[:5]}")
        by_b = {}
        for c in sorted(ids):
            by_b.setdefault(bench.get(c, "?"), []).append(c)
        if "?" in by_b:
            raise DefinitionError(f"{name}: {len(by_b['?'])} id(s) are in no id set")
        res = {"name": name, "split": split, "reference": d["reference"], "role": d.get("role", ""),
               "ids": sorted(ids), "by_benchmark": by_b, "n": len(ids), "sha256": ids_sha256(sorted(ids)),
               "pending": sorted(pending)}
        exp = d.get("expect") or {}
        if exp and not pending:
            if "n" in exp and exp["n"] != res["n"]:
                raise DefinitionError(f"{name}: {res['n']} cases, expected {exp['n']}")
            for b, k in (exp.get("by_benchmark") or {}).items():
                if len(by_b.get(b, [])) != k:
                    raise DefinitionError(f"{name}: {len(by_b.get(b, []))} {b} cases, expected {k}")
        for r in d.get("relations") or []:
            other = one(r["def"])
            if r.get("same_ids") and other["ids"] != res["ids"]:
                raise DefinitionError(f"{name} must have the same cases as {r['def']}")
            if r.get("superset") and not set(other["ids"]) <= ids:
                raise DefinitionError(f"{name} must contain every case of {r['def']}")
            if r.get("disjoint") and set(other["ids"]) & ids:
                raise DefinitionError(f"{name} must share no case with {r['def']}")
            if "difference_within" in r:
                extra = ids - set(other["ids"])
                allowed = _names_ids(r["difference_within"], split, id_sets, lists, pending) if r["difference_within"] else set()
                bad = sorted(extra - allowed)
                if bad:
                    raise DefinitionError(f"{name} minus {r['def']} must lie in {r['difference_within']}; "
                                          f"{len(bad)} case(s) do not: {bad[:5]}")
            res["pending"] = sorted(set(res["pending"]) | set(other["pending"]))
        if strict and res["pending"]:
            raise PendingError(f"{name} depends on {res['pending']}, which are not final yet "
                               "(ingest the annotations with data/ingest_annotations.py)")
        active.discard(name)
        done[name] = res
        return res

    for n in (names or list(table)):
        one(n)
    return done if names is None else {n: done[n] for n in names}


def resolve_all(root=None, strict=False, defs_path=None):
    """Load id sets (checked against the frozen splits), named lists and definitions from the tree; resolve all."""
    defs = load_set_defs(defs_path, root)
    id_sets = load_id_sets(defs["id_sets"]["path"], root)
    lists = load_named_lists(id_sets, root)
    return resolve_sets(defs, id_sets, lists, strict=strict), lists


def analysis_set(name, root=None, strict=True):
    """The resolved analysis set `name` (strict by default: raises PendingError while a list is pending)."""
    defs = load_set_defs(None, root)
    id_sets = load_id_sets(defs["id_sets"]["path"], root)
    lists = load_named_lists(id_sets, root)
    return resolve_sets(defs, id_sets, lists, strict=strict, names=[name])[name]
