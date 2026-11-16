#!/usr/bin/env python3
"""Run registry and per-case matrix of the R1 analysis (E20a).

  $PY analysis/r1/registry.py check      [--registry experiments/run_registry.json]
  $PY analysis/r1/registry.py add        --run <run dir> --results results.<C>.jsonl --config <C> --model <m>
                                         --benchmark <b> --split dev|test|eng_holdout [--max-repair-rounds k]
                                         [--label L] [--round0 own|reuse:<C>] [--round0-gen-dir <dir>] [--note ...]
  $PY analysis/r1/registry.py matrix     [--set dev_signal55 | --set main [--incl-0905]] [--allow-pending] --out m.jsonl
  $PY analysis/r1/registry.py superseded

Registry (JSON, schema orgene.r1.run_registry.v1; default experiments/run_registry.json, outside the frozen
directories because it grows while stage 2 runs). One entry per (model, label, benchmark):
  label              analysis label, unique per model; default <config>@<k> for a repairing configuration at ladder
                     point "at most k repair rounds", else the configuration id (C0, C1, C2)
  config, model, benchmark, split (dev | test | eng_holdout), max_repair_rounds (int or null)
  path               run directory, relative to the repository root; results = file name inside it
  results_sha256     sha256 of the results file when registered; a changed file is refused
  optional: final, final_sha256, run_config_sha256, round0 (own | reuse:<C>), round0_gen_dir (directory holding the
            runner outputs of round 0, gen.<C>.r0, for the round-0 content sha256; a run of the unit executor needs
            none, its unit records carry the hash), note
Superseded runs (configs/superseded_runs.json, frozen): condition, model, benchmark, split, number of cases and times
only. They carry no path, and an entry that names a directory or a file is refused, so nothing can read them.

Reading: an entry whose split is test or eng_holdout is read only after the freeze gate passes
(runtime/orgene/freeze.check_gate; nothing is written into the run directory, the gate record goes into the
output). Before any row is used, every case id must belong to the entry's benchmark and split (data/splits/<b>/),
the row's condition must be the entry's configuration, and the results file must hash to results_sha256.

Per-case matrix: one row per (model, label, case, repeat) with the fields in MATRIX_FIELDS. Core fields come from
the result rows (pipeline.score_condition). The fields in RESERVED stay null here; the later analysis modules (census,
misreport, truncation, cost, token_audit, order_effects, determinism, measurement_check, equivamap_diag) fill them
through enrichers, which may set reserved fields only. round0_content_sha256 is filled from the runner outputs of
round 0 when round0_gen_dir is registered, else from the unit executor's records in <run>/units/ (for a ladder point,
in the units/ of its source run).

Analysis sets (runtime/orgene/analysis_sets.py): a matrix is restricted to one named set. Test analyses use `main`
(built from the *_excl0905 id sets); --incl-0905 switches to the sensitivity set that adds the 2026-09-05-viewed
cases back. Dev analyses default to dev_signal55. Every output is labelled DEV, TEST or ENG_HOLDOUT.
"""
import argparse
import glob
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common import (ROOT, SEALED, AnalysisError, check_relative, data_label, dumps, labelled_path,  # noqa: E402
                    read_jsonl, rel, resolve, sha256_file, write_text)

REGISTRY_SCHEMA = "orgene.r1.run_registry.v1"
SUPERSEDED_SCHEMA = "orgene.r1.superseded_runs.v1"
MATRIX_SCHEMA = "orgene.r1.case_matrix.v1"
DEFAULT_REGISTRY = "experiments/run_registry.json"
DEFAULT_SUPERSEDED = "configs/superseded_runs.json"
SPLITS = ("dev", "test", "eng_holdout")
SPLIT_ID_FILES = {"dev": "dev_ids.json", "test": "test_ids.json", "eng_holdout": "eng_holdout_ids.json"}

RUN_REQUIRED = ("label", "config", "model", "benchmark", "split", "path", "results", "results_sha256")
RUN_OPTIONAL = ("max_repair_rounds", "final", "final_sha256", "run_config_sha256", "round0", "round0_gen_dir", "note")
SUPERSEDED_REQUIRED = ("config", "model", "benchmark", "split", "n_cases", "started_utc", "finished_utc")
SUPERSEDED_OPTIONAL = ("started_local", "finished_local", "note")

# per-case matrix fields; the order is the column order of every written matrix
IDENTITY_FIELDS = ("model", "label", "config", "max_repair_rounds", "benchmark", "split", "run", "case_id", "repeat")
CORE_FIELDS = (
    "correct", "correct_tol", "correct_original_ref", "correct_tol_original_ref", "verified_correct",
    "exec_ok", "protocol_ok", "status", "objective", "reason", "provisional",
    "reference_version", "reference_main_eligible",
    "n_calls", "repair_rounds_used", "hard_issue_count_round0", "hard_failed_genes_final", "soft_failed_genes_final",
    "out_tokens", "in_tokens", "exec_seconds", "misreport",
)
RESERVED = {  # field -> module that fills it (all null until then)
    "round0_content_sha256": "registry (runner outputs of round 0) / unit executor records (E06)",
    "round0_source": "registry (round0 of the entry) / unit executor records (E06)",
    "round0_predicates": "census.py",
    "round0_hard_failed_genes": "census.py",
    "done_reasons": "truncation.py",
    "truncated": "truncation.py",
    "gen_seconds": "cost.py",
    "wall_seconds": "cost.py",
    "local_in_tokens": "token_audit.py",
    "local_out_tokens": "token_audit.py",
    "token_gap_prompt": "token_audit.py",
    "token_gap_completion": "token_audit.py",
    "planned_index": "order_effects.py",
    "started_at": "order_effects.py",
    "finished_at": "order_effects.py",
    "queue_wait_seconds": "order_effects.py",
    "content_sha256_by_round": "determinism.py",
    "in_measurement_sample": "measurement_check.py",
    "equivamap_verdict": "equivamap_diag.py",
    "unit_record": "unit executor records (E06): path of the unit record, relative to the repository root",
}
MATRIX_FIELDS = IDENTITY_FIELDS + CORE_FIELDS + tuple(RESERVED)
OUTCOMES = ("correct", "correct_original_ref", "verified_correct", "exec_ok", "protocol_ok")


class RegistryError(AnalysisError):
    """The registry or a registered run breaks a rule."""


def label_of(config, max_repair_rounds):
    return config if max_repair_rounds is None else f"{config}@{int(max_repair_rounds)}"


# ------------------------------------------------------------------ registry files


def validate_run(e, i=None):
    w = f"runs[{i}]" if i is not None else "run"
    p = []
    if not isinstance(e, dict):
        return [f"{w}: an entry is an object"]
    for k in RUN_REQUIRED:
        if k not in e:
            p.append(f"{w}: missing {k}")
    extra = set(e) - set(RUN_REQUIRED) - set(RUN_OPTIONAL)
    if extra:
        p.append(f"{w}: unknown keys {sorted(extra)}")
    if e.get("split") not in SPLITS:
        p.append(f"{w}.split must be one of {SPLITS}")
    for k in ("path", "round0_gen_dir"):
        if e.get(k) is not None:
            try:
                check_relative(e[k], f"{w}.{k}")
            except AnalysisError as x:
                p.append(str(x))
    for k in ("results", "final"):
        v = e.get(k)
        if v is not None and (not isinstance(v, str) or "/" in v or "\\" in v or not v.endswith(".jsonl")):
            p.append(f"{w}.{k} must be a .jsonl file name inside the run directory")
    for k in ("results_sha256", "final_sha256", "run_config_sha256"):
        v = e.get(k)
        if v is not None and (not isinstance(v, str) or len(v) != 64 or any(c not in "0123456789abcdef" for c in v)):
            p.append(f"{w}.{k} must be a sha256 hex digest")
    k = e.get("max_repair_rounds")
    if k is not None and (not isinstance(k, int) or isinstance(k, bool) or k < 0):
        p.append(f"{w}.max_repair_rounds must be a non-negative integer or null")
    r0 = e.get("round0")
    if r0 is not None and not (r0 == "own" or (isinstance(r0, str) and r0.startswith("reuse:") and len(r0) > 6)):
        p.append(f"{w}.round0 must be 'own' or 'reuse:<config>'")
    for k in ("label", "config", "model", "benchmark"):
        if k in e and (not isinstance(e[k], str) or not e[k]):
            p.append(f"{w}.{k} must be a non-empty string")
    return p


def validate_superseded(e, i=None):
    w = f"superseded[{i}]" if i is not None else "superseded"
    if not isinstance(e, dict):
        return [f"{w}: an entry is an object"]
    p = [f"{w}: missing {k}" for k in SUPERSEDED_REQUIRED if k not in e]
    extra = set(e) - set(SUPERSEDED_REQUIRED) - set(SUPERSEDED_OPTIONAL)
    if extra:
        p.append(f"{w}: keys {sorted(extra)} are not allowed; a superseded run is registered by condition, number of "
                 "cases and times only and never names a directory or a file")
    if e.get("split") not in SPLITS:
        p.append(f"{w}.split must be one of {SPLITS}")
    n = e.get("n_cases")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        p.append(f"{w}.n_cases must be a positive integer")
    for k in ("started_utc", "finished_utc"):
        v = e.get(k)
        if not isinstance(v, str) or not v.endswith("Z") or "T" not in v:
            p.append(f"{w}.{k} must be an ISO time in UTC (…Z)")
    if isinstance(e.get("started_utc"), str) and isinstance(e.get("finished_utc"), str) \
            and e["finished_utc"] < e["started_utc"]:
        p.append(f"{w}: finished before it started")
    return p


def load_superseded(path=None, root=None):
    p = resolve(path or DEFAULT_SUPERSEDED, root or ROOT)
    if not os.path.exists(p):
        return {"path": rel(p, root), "sha256": None, "entries": [], "common": {}}
    doc = json.load(open(p, encoding="utf-8"))
    probs = [] if doc.get("schema") == SUPERSEDED_SCHEMA else [f"schema must be {SUPERSEDED_SCHEMA!r}"]
    ents = doc.get("superseded") or []
    for i, e in enumerate(ents):
        probs += validate_superseded(e, i)
    if probs:
        raise RegistryError(f"{rel(p, root)}: " + "; ".join(probs))
    return {"path": rel(p, root), "sha256": sha256_file(p), "entries": ents, "common": doc.get("common") or {}}


class Registry:
    def __init__(self, runs, path=None, sha256=None, superseded=None):
        self.runs = runs
        self.path = path
        self.sha256 = sha256
        self.superseded = superseded or {"entries": [], "common": {}}

    def groups(self):
        """{(model, label): [entries]}."""
        out = {}
        for e in self.runs:
            out.setdefault((e["model"], e["label"]), []).append(e)
        return out


def check_registry_doc(doc):
    if not isinstance(doc, dict) or doc.get("schema") != REGISTRY_SCHEMA:
        return [f"schema must be {REGISTRY_SCHEMA!r}"]
    p = []
    runs = doc.get("runs")
    if not isinstance(runs, list):
        return ["runs must be a list"]
    if "superseded" in doc:
        p.append("superseded runs live in configs/superseded_runs.json, not in the run registry")
    seen, labels = set(), {}
    for i, e in enumerate(runs):
        p += validate_run(e, i)
        if not isinstance(e, dict):
            continue
        key = (e.get("model"), e.get("label"), e.get("benchmark"))
        if key in seen:
            p.append(f"runs[{i}]: (model, label, benchmark) {key} registered twice")
        seen.add(key)
        # a label means one configuration at one ladder point for one split
        sig = (e.get("config"), e.get("max_repair_rounds"), e.get("split"))
        prev = labels.setdefault((e.get("model"), e.get("label")), sig)
        if prev != sig:
            p.append(f"runs[{i}]: label {e.get('label')!r} of model {e.get('model')!r} names both {prev} and {sig}")
    return p


def load_registry(path=None, root=None, superseded_path=None):
    root = root or ROOT
    p = resolve(path or DEFAULT_REGISTRY, root)
    doc = json.load(open(p, encoding="utf-8"))
    probs = check_registry_doc(doc)
    if probs:
        raise RegistryError(f"{rel(p, root)}: " + "; ".join(probs))
    return Registry(doc["runs"], rel(p, root), sha256_file(p), load_superseded(superseded_path, root))


def empty_registry_doc():
    return {"schema": REGISTRY_SCHEMA,
            "about": "R1 run registry (analysis/r1/registry.py). Superseded runs: configs/superseded_runs.json.",
            "runs": []}


# ------------------------------------------------------------------ reading one registered run


def split_ids(root, benchmark):
    """{split: set of ids} from data/splits/<benchmark>/ (ids only)."""
    d = os.path.join(root, "data", "splits", benchmark)
    if not os.path.isdir(d):
        raise RegistryError(f"no frozen split for benchmark {benchmark!r} (data/splits/{benchmark}/)")
    out = {}
    for s, fn in SPLIT_ID_FILES.items():
        f = os.path.join(d, fn)
        out[s] = set(json.load(open(f, encoding="utf-8"))) if os.path.exists(f) else set()
    return out


# Files every analysis reads besides the run results (DECISIONS R1-D17: a gated stage reads frozen files only).
# Globs relative to the repository root; the ones that exist must be covered by the freeze (listed in the manifest,
# or tracked inside a directory whose git tree hash it records). The run registry itself grows during stage 2 and
# the results are produced after the freeze, so neither is among them.
ANALYSIS_INPUTS = (
    "analysis/r1/*.py", "runtime/orgene/__init__.py", "runtime/orgene/analysis_sets.py", "runtime/orgene/split.py",
    "runtime/orgene/paths.py", "runtime/orgene/score.py", "runtime/orgene/freeze.py",
    "configs/prereg_analysis.json", "configs/superseded_runs.json", "configs/analysis_set_defs*.json",
    "data/analysis_sets/*.json", "data/exclusions_r1.json", "data/mamo_underspecified_ids.json",
    "data/reference_overrides/*.json", "data/labels/**/*.json", "data/features/**/*.json",
    "data/splits/**/*.json", "data/splits_r1/**/*.json", "data/cases/*.jsonl",
)


def analysis_inputs(root):
    out = []
    for pat in ANALYSIS_INPUTS:
        out += sorted(glob.glob(os.path.join(root, pat), recursive=True))
    return [p for p in out if os.path.isfile(p)]


def gate_entry(e, root):
    """None for a dev entry; for a sealed split the freeze gate record (raises RegistryError when refused): the
    manifest must be complete, verify, be registered, and cover every analysis input (analysis_inputs)."""
    if e["split"] not in SEALED:
        return None
    from orgene import freeze as FZ
    try:
        rec = FZ.check_gate(root, inputs=analysis_inputs(root))
    except FZ.GateRefused as x:
        raise RegistryError(f"{e['label']} / {e['benchmark']} is a {e['split']} run: {x}") from None
    return dict(rec, stage="analysis", split=e["split"])


def entry_files(e, root):
    run = resolve(e["path"], root)
    return run, os.path.join(run, e["results"])


def load_entry_rows(e, root, ids=None):
    """Result rows of one entry, after the gate, hash and membership checks. Returns (rows, gate record)."""
    run, res = entry_files(e, root)
    gate = gate_entry(e, root)
    if not os.path.isfile(res):
        raise RegistryError(f"{e['label']} / {e['benchmark']}: results file {rel(res, root)} missing")
    got = sha256_file(res)
    if got != e["results_sha256"]:
        raise RegistryError(f"{e['label']} / {e['benchmark']}: {rel(res, root)} has sha256 {got[:16]}…, the registry "
                            f"records {e['results_sha256'][:16]}…; the file changed after registration")
    ids = ids or split_ids(root, e["benchmark"])
    rows = read_jsonl(res)
    own = ids[e["split"]]
    foreign = [r for r in rows if r.get("case_id") not in own]
    if foreign:
        other = {s for s, v in ids.items() if s != e["split"] for r in foreign if r.get("case_id") in v}
        raise RegistryError(f"{e['label']} / {e['benchmark']}: {len(foreign)} row(s) are not {e['split']} cases of "
                            f"{e['benchmark']}" + (f" (they belong to {sorted(other)})" if other else ""))
    bad_cond = sum(1 for r in rows if r.get("condition") not in (None, e["config"]))
    bad_src = sum(1 for r in rows if r.get("source") not in (None, e["benchmark"]))
    if bad_cond or bad_src:
        raise RegistryError(f"{e['label']} / {e['benchmark']}: {bad_cond} row(s) of another condition, {bad_src} of "
                            "another benchmark; wrong results file for this entry")
    seen = set()
    for r in rows:
        k = (r["case_id"], int(r.get("repeat", 0)))
        if k in seen:
            raise RegistryError(f"{e['label']} / {e['benchmark']}: case {k[0]} repeat {k[1]} appears twice")
        seen.add(k)
        if not isinstance(r.get("correct"), bool) or not isinstance(r.get("exec_ok"), bool):
            raise RegistryError(f"{e['label']} / {e['benchmark']}: a row lacks boolean correct / exec_ok")
    return rows, gate


def round0_shas_from_gen_dir(gen_dir):
    """{(case_id, repeat): sha256 of the round-0 answer text} from runner outputs (<gen dir>/outputs/*.json)."""
    out = {}
    for p in sorted(glob.glob(os.path.join(gen_dir, "outputs", "*.json"))):
        rec = json.load(open(p, encoding="utf-8"))
        meta = rec.get("meta") or {}
        k = (rec["case_id"], int(meta.get("orig_repeat", rec.get("repeat", 0))))
        if int(meta.get("round", 0) or 0) != 0:
            raise RegistryError(f"{os.path.basename(gen_dir)}: output {os.path.basename(p)} is not a round-0 answer")
        out[k] = hashlib.sha256((rec.get("content") or "").encode("utf-8")).hexdigest()
    if not out:
        raise RegistryError(f"no runner outputs in {os.path.basename(gen_dir)}/outputs")
    return out


UNIT_SCHEMA = "orgene.r1.unit.v1"
LADDER_SCHEMA = "orgene.r1.ladder.v1"


def units_dir_of(run_dir, config):
    """The units/ directory holding this run's unit records, or None. A ladder point (<run>-r<k>, cut by
    analysis/derive_repair_ladder.py) has no unit records of its own: its ladder.<config>.json names the source run,
    a sibling directory, whose records are the ones its rows were cut from."""
    d = os.path.join(run_dir, "units")
    if os.path.isdir(d):
        return d
    lp = os.path.join(run_dir, f"ladder.{config}.json")
    if os.path.isfile(lp):
        lad = json.load(open(lp, encoding="utf-8"))
        src = lad.get("source_run")
        if lad.get("schema_version") != LADDER_SCHEMA or not isinstance(src, str) or os.path.basename(src) != src:
            raise RegistryError(f"{os.path.basename(run_dir)}: ladder.{config}.json does not name a sibling source run")
        d = os.path.join(os.path.dirname(os.path.abspath(run_dir)), src, "units")
        if os.path.isdir(d):
            return d
    return None


def round0_shas_from_units(units_dir, config):
    """{(case_id, repeat): sha256 of the round-0 answer text} from the unit executor's records of one configuration
    (<units dir>/*.json with config_id == config). The recorded content_sha256 must be the hash of the recorded
    answer, and a shared round 0 (round0.reused_from) must record the same hash; otherwise the run is refused."""
    out = {}
    for p in sorted(glob.glob(os.path.join(units_dir, "*.json"))):
        u = json.load(open(p, encoding="utf-8"))
        if u.get("schema_version") != UNIT_SCHEMA or u.get("config_id") != config:
            continue
        name = os.path.basename(p)
        try:
            call = u["rounds"][0]["calls"][0]["call"]
            sha, content = call["content_sha256"], call.get("content") or ""
        except (KeyError, IndexError, TypeError):
            raise RegistryError(f"unit record {name} has no round-0 call") from None
        if u["rounds"][0].get("round") != 0:
            raise RegistryError(f"unit record {name}: its first round is not round 0")
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != sha:
            raise RegistryError(f"unit record {name}: content_sha256 is not the hash of the recorded round-0 answer")
        src = (u.get("round0") or {}).get("reused_from")
        if src and src.get("content_sha256") != sha:
            raise RegistryError(f"unit record {name}: the shared round 0 it names has another content sha256")
        k = (u["case_id"], int(u.get("repeat", 0)))
        if k in out:
            raise RegistryError(f"two unit records for case {k[0]} repeat {k[1]} of {config}")
        out[k] = sha
    return out


def enrich_round0(e, rows, root):
    """Default enricher: round0_source from the entry; round0_content_sha256 from its round-0 runner outputs
    (round0_gen_dir, the batch path) or, without one, from the unit executor's records of the run (or of the source
    run of a ladder point). A run with neither keeps None."""
    for r in rows:
        r["round0_source"] = e.get("round0")
    if e.get("round0_gen_dir"):
        shas = round0_shas_from_gen_dir(resolve(e["round0_gen_dir"], root))
    else:
        d = units_dir_of(resolve(e["path"], root), e["config"])
        shas = round0_shas_from_units(d, e["config"]) if d else {}
    for r in rows:
        r["round0_content_sha256"] = shas.get((r["case_id"], r["repeat"]))


def matrix_row(e, r):
    row = {k: None for k in MATRIX_FIELDS}
    row.update({"model": e["model"], "label": e["label"], "config": e["config"],
                "max_repair_rounds": e.get("max_repair_rounds"), "benchmark": e["benchmark"], "split": e["split"],
                "run": os.path.basename(e["path"].rstrip("/")), "case_id": r["case_id"], "repeat": int(r.get("repeat", 0))})
    for k in CORE_FIELDS:
        if k in r:
            row[k] = r[k]
    return row


class Matrix:
    """Per-case matrix rows plus the provenance header every output copies."""

    def __init__(self, rows, header):
        self.rows = rows
        self.header = header

    @property
    def label(self):
        return self.header["data"]

    def groups(self):
        out = {}
        for r in self.rows:
            out.setdefault((r["model"], r["label"]), []).append(r)
        return out

    def models(self):
        return sorted({r["model"] for r in self.rows})

    def select(self, model, label):
        rows = [r for r in self.rows if r["model"] == model and r["label"] == label]
        if not rows:
            raise AnalysisError(f"no rows for label {label!r} of model {model!r} (registered: "
                                f"{sorted({l for m, l in self.groups() if m == model})})")
        return rows


def build_matrix(reg, root=None, labels=None, models=None, enrichers=()):
    """Matrix of every registered run (or of the given labels / models)."""
    root = root or ROOT
    rows, gates, used = [], [], []
    ids_cache = {}
    for e in reg.runs:
        if labels is not None and e["label"] not in labels:
            continue
        if models is not None and e["model"] not in models:
            continue
        ids = ids_cache.setdefault(e["benchmark"], split_ids(root, e["benchmark"]))
        res_rows, gate = load_entry_rows(e, root, ids)
        if gate:
            gates.append(gate)
        mrows = [matrix_row(e, r) for r in res_rows]
        for fn in (enrich_round0,) + tuple(enrichers):
            before = [{k: r[k] for k in IDENTITY_FIELDS + CORE_FIELDS} for r in mrows]
            fn(e, mrows, root)
            for b, r in zip(before, mrows):
                if set(r) != set(MATRIX_FIELDS):
                    raise RegistryError(f"enricher {getattr(fn, '__name__', fn)} added fields "
                                        f"{sorted(set(r) - set(MATRIX_FIELDS))}; only reserved fields may be set")
                if any(r[k] != b[k] for k in b):
                    raise RegistryError(f"enricher {getattr(fn, '__name__', fn)} changed core fields; only reserved "
                                        "fields may be set")
        rows += mrows
        used.append({"label": e["label"], "model": e["model"], "config": e["config"], "benchmark": e["benchmark"],
                     "split": e["split"], "max_repair_rounds": e.get("max_repair_rounds"), "path": e["path"],
                     "results": e["results"], "results_sha256": e["results_sha256"], "n_rows": len(mrows)})
    if not rows:
        raise RegistryError("no registered run matches")
    seen = set()
    for r in rows:
        k = (r["model"], r["label"], r["case_id"], r["repeat"])
        if k in seen:
            raise RegistryError(f"{k[1]} of {k[0]}: case {k[2]} repeat {k[3]} comes from two runs")
        seen.add(k)
    header = {"_header": True, "schema": MATRIX_SCHEMA, "data": data_label(r["split"] for r in rows),
              "registry": {"path": reg.path, "sha256": reg.sha256},
              "superseded": {"path": reg.superseded.get("path"), "sha256": reg.superseded.get("sha256"),
                             "n": len(reg.superseded.get("entries") or []), "read": False},
              "runs": used, "freeze_gate": gates or None, "fields": list(MATRIX_FIELDS), "reserved": RESERVED,
              "analysis_set": None}
    return Matrix(rows, header)


# ------------------------------------------------------------------ analysis sets


INCL0905 = {"main": "sens_incl0905", "sens_full211": "sens_full211_incl0905"}
DEFAULT_SET = {"DEV": "dev_signal55", "TEST": "main"}


def resolve_set(name, root=None, allow_pending=False):
    """The resolved analysis set (runtime/orgene/analysis_sets.py). Pending lists raise unless allow_pending."""
    from orgene import analysis_sets as AS
    try:
        return AS.analysis_set(name, root=root, strict=not allow_pending)
    except AS.PendingError as x:
        raise AnalysisError(f"analysis set {name}: {x}") from None


def set_name_for(label, name=None, incl_0905=False):
    name = name or DEFAULT_SET.get(label)
    if name is None:
        raise AnalysisError(f"no default analysis set for {label} data; give --set")
    if incl_0905:
        if name not in INCL0905:
            raise AnalysisError(f"--incl-0905 applies to {sorted(INCL0905)}, not to {name}")
        name = INCL0905[name]
    return name


def restrict(matrix, aset):
    """Rows of the matrix inside the analysis set; the set's split must be the matrix's split."""
    want = {"DEV": "dev", "TEST": "test"}.get(matrix.label)
    if aset["split"] != want:
        raise AnalysisError(f"analysis set {aset['name']} is a {aset['split']} set; the matrix holds {matrix.label} data")
    ids = set(aset["ids"])
    rows = [r for r in matrix.rows if r["case_id"] in ids]
    header = dict(matrix.header, analysis_set={
        "name": aset["name"], "split": aset["split"], "reference": aset["reference"], "n": aset["n"],
        "sha256": aset["sha256"], "by_benchmark": {b: len(v) for b, v in aset["by_benchmark"].items()},
        "pending": aset["pending"]})
    return Matrix(rows, header)


def bench_map(aset):
    return {c: b for b, ids in aset["by_benchmark"].items() for c in ids}


# ------------------------------------------------------------------ CLI


def cmd_check(a):
    reg = load_registry(a.registry, superseded_path=a.superseded)
    bad = 0
    for e in reg.runs:
        run, res = entry_files(e, ROOT)
        state = "ok"
        if not os.path.isfile(res):
            state, bad = "MISSING", bad + 1
        elif sha256_file(res) != e["results_sha256"]:
            state, bad = "CHANGED", bad + 1
        print(f"  {e['model']:>12}  {e['label']:<14} {e['benchmark']:<16} {e['split']:<5} {state}  {e['path']}")
    s = reg.superseded
    print(f"[registry] {reg.path}: {len(reg.runs)} run(s); superseded runs registered (never read): "
          f"{len(s['entries'])} in {s['path']}")
    print("[registry] " + ("OK" if not bad else f"FAIL: {bad} run(s) missing or changed"))
    return 1 if bad else 0


def cmd_add(a):
    reg_path = resolve(a.registry, ROOT)
    doc = json.load(open(reg_path, encoding="utf-8")) if os.path.exists(reg_path) else empty_registry_doc()
    run = os.path.abspath(a.run)
    path = rel(run)
    if path.startswith("<outside-root>"):
        raise SystemExit("[registry] the run directory must be inside the repository")
    res = os.path.join(run, a.results)
    if not os.path.isfile(res):
        raise SystemExit(f"[registry] no {a.results} in {path}")
    e = {"label": a.label or label_of(a.config, a.max_repair_rounds), "config": a.config, "model": a.model,
         "benchmark": a.benchmark, "split": a.split, "max_repair_rounds": a.max_repair_rounds, "path": path,
         "results": a.results, "results_sha256": sha256_file(res)}
    fin = os.path.join(run, f"final.{a.config}.jsonl")
    if os.path.isfile(fin):
        e.update(final=os.path.basename(fin), final_sha256=sha256_file(fin))
    cfg = os.path.join(run, "run_config.json")
    if os.path.isfile(cfg):
        e["run_config_sha256"] = sha256_file(cfg)
        rc_split = (json.load(open(cfg, encoding="utf-8")) or {}).get("split")
        if rc_split and rc_split != a.split:
            raise SystemExit(f"[registry] run_config.json records split {rc_split}, not {a.split}")
    if a.round0:
        e["round0"] = a.round0
    if a.round0_gen_dir:
        e["round0_gen_dir"] = rel(os.path.abspath(a.round0_gen_dir))
    if a.note:
        e["note"] = a.note
    doc["runs"].append(e)
    probs = check_registry_doc(doc)
    if probs:
        raise SystemExit("[registry] refused: " + "; ".join(probs))
    write_text(reg_path, dumps(doc))
    print(f"[registry] added {e['label']} / {e['benchmark']} ({e['split']}) -> {rel(reg_path)}")
    return 0


def cmd_matrix(a):
    reg = load_registry(a.registry, superseded_path=a.superseded)
    m = build_matrix(reg, labels=a.labels, models=a.models)
    name = set_name_for(m.label, a.set, a.incl_0905)
    # pending set lists resolve as empty for dev data only; a test matrix needs the final set
    m = restrict(m, resolve_set(name, allow_pending=a.allow_pending and m.label == "DEV"))
    out = labelled_path(a.out, m.label)
    text = json.dumps(m.header, ensure_ascii=False) + "\n" + "".join(
        json.dumps(r, ensure_ascii=False) + "\n" for r in sorted(
            m.rows, key=lambda r: (r["model"], r["label"], r["case_id"], r["repeat"])))
    write_text(out, text)
    print(f"[registry] {m.label}: {len(m.rows)} rows, set {name}, -> {rel(out)}")
    return 0


def cmd_superseded(a):
    s = load_superseded(a.superseded)
    print(f"superseded runs ({s['path']}; registered by condition, cases and times only; contents not opened):")
    for e in s["entries"]:
        print(f"  {e['config']:<4} {e['model']:<9} {e['benchmark']:<16} {e['split']:<5} n={e['n_cases']:<4} "
              f"{e['started_utc']} -> {e['finished_utc']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "add", "matrix", "superseded"):
        s = sub.add_parser(name)
        s.add_argument("--registry", default=DEFAULT_REGISTRY)
        s.add_argument("--superseded", default=DEFAULT_SUPERSEDED)
        if name == "add":
            s.add_argument("--run", required=True)
            s.add_argument("--results", required=True)
            s.add_argument("--config", required=True)
            s.add_argument("--model", required=True)
            s.add_argument("--benchmark", required=True)
            s.add_argument("--split", required=True, choices=SPLITS)
            s.add_argument("--max-repair-rounds", type=int, default=None)
            s.add_argument("--label", default=None)
            s.add_argument("--round0", default=None)
            s.add_argument("--round0-gen-dir", default=None)
            s.add_argument("--note", default=None)
        if name == "matrix":
            s.add_argument("--set", default=None)
            s.add_argument("--incl-0905", action="store_true")
            s.add_argument("--allow-pending", action="store_true")
            s.add_argument("--labels", nargs="*", default=None)
            s.add_argument("--models", nargs="*", default=None)
            s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        return {"check": cmd_check, "add": cmd_add, "matrix": cmd_matrix, "superseded": cmd_superseded}[a.cmd](a)
    except AnalysisError as x:
        print(f"[registry] REFUSED: {x}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
