#!/usr/bin/env python3
"""Pre-registered analysis settings (configs/prereg_analysis.json): load, validate, read values (E20a).

  $PY analysis/r1/prereg.py check [--file configs/prereg_analysis.json] [--final]

Every item is {status: fixed | pending, value, basis[, proposal][, note]}:
  fixed    decided; `value` is not null and `basis` names the decision
  pending  decided in 1D; `value` is null; `proposal` (optional) is what a dev analysis may run on
Prereg.get(name, allow_pending) returns the value of a fixed item. For a pending item it raises PendingItem unless
allow_pending is true (dev analyses only) and a proposal exists; the item is then listed in `pending_used`, which
every output copies. `check --final` fails while any item is pending (for the freeze step in 1D).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common import ROOT, AnalysisError, rel, resolve, sha256_file  # noqa: E402

SCHEMA = "orgene.r1.prereg_analysis.v1"
DEFAULT_PATH = "configs/prereg_analysis.json"
STATUSES = ("fixed", "pending")
ITEM_KEYS = {"status", "value", "basis", "proposal", "note"}
ITEMS = (
    "primary_comparison", "outcome_primary", "tolerance_tiers", "tolerance_primary", "analysis_set_main",
    "analysis_sets_sensitivity", "analysis_set_dev_signal", "repeats", "paired_test", "alpha", "bootstrap",
    "holm_families", "tost_margin", "tost", "length_model", "strata_scale_feature", "strata_scale_cutpoints",
    "strata_industryor_difficulty", "strata_type_labels", "shared_round0_mde", "forest_settings",
    "gated_tests", "mechanism",
)
MECHANISM_LABELS = ("l", "e", "t", "a", "round0")
COMPARISON_KEYS = {"id", "a", "b", "model", "outcome", "analysis_set", "scope"}


class PendingItem(AnalysisError):
    """A pre-registered value is still pending (decided in 1D)."""


def _check_comparison(c, where):
    p = []
    if not isinstance(c, dict):
        return [f"{where}: a comparison must be an object"]
    missing = COMPARISON_KEYS - set(c)
    extra = set(c) - COMPARISON_KEYS
    if missing:
        p.append(f"{where}: missing {sorted(missing)}")
    if extra:
        p.append(f"{where}: unknown keys {sorted(extra)}")
    for k in COMPARISON_KEYS & set(c):
        if not isinstance(c[k], str) or not c[k]:
            p.append(f"{where}.{k} must be a non-empty string")
    if c.get("a") == c.get("b"):
        p.append(f"{where}: a and b are the same label")
    return p


def check_families(fams, where="holm_families"):
    p = []
    if not isinstance(fams, list) or not fams:
        return [f"{where}: a non-empty list of families is required"]
    fam_ids, comp_ids = set(), set()
    for i, f in enumerate(fams):
        w = f"{where}[{i}]"
        if not isinstance(f, dict) or set(f) - {"id", "alpha", "comparisons", "note"}:
            p.append(f"{w}: a family is {{id, alpha, comparisons[, note]}}")
            continue
        if f.get("id") in fam_ids or not f.get("id"):
            p.append(f"{w}: missing or repeated family id")
        fam_ids.add(f.get("id"))
        a = f.get("alpha")
        if not isinstance(a, (int, float)) or not 0 < a < 1:
            p.append(f"{w}.alpha must lie in (0, 1)")
        comps = f.get("comparisons")
        if not isinstance(comps, list) or not comps:
            p.append(f"{w}: comparisons must be a non-empty list")
            continue
        for j, c in enumerate(comps):
            p += _check_comparison(c, f"{w}.comparisons[{j}]")
            cid = c.get("id") if isinstance(c, dict) else None
            if cid in comp_ids:
                p.append(f"{w}.comparisons[{j}]: comparison id {cid!r} is used twice (a comparison belongs to one family)")
            comp_ids.add(cid)
    return p


def check_gated(gated, families, where="gated_tests"):
    """A gated test {id, gate, alpha, comparison} is tested only when the comparison `gate` (the id of a comparison in
    a one-member Holm family, so its rejection needs no further correction) is rejected: a fixed sequence."""
    p = []
    if not isinstance(gated, list):
        return [f"{where}: a list of gated tests is required"]
    single = {f["comparisons"][0]["id"] for f in (families or [])
              if isinstance(f, dict) and isinstance(f.get("comparisons"), list) and len(f["comparisons"]) == 1}
    member = {c.get("id") for f in (families or []) if isinstance(f, dict) for c in (f.get("comparisons") or [])
              if isinstance(c, dict)}
    seen = set()
    for i, g in enumerate(gated):
        w = f"{where}[{i}]"
        if not isinstance(g, dict) or set(g) != {"id", "gate", "alpha", "comparison"}:
            p.append(f"{w}: a gated test is {{id, gate, alpha, comparison}}")
            continue
        if not g["id"] or g["id"] in seen:
            p.append(f"{w}: missing or repeated id")
        seen.add(g["id"])
        if not isinstance(g["alpha"], (int, float)) or not 0 < g["alpha"] < 1:
            p.append(f"{w}.alpha must lie in (0, 1)")
        if g["gate"] not in single:
            p.append(f"{w}: gate {g['gate']!r} is not the single comparison of a Holm family")
        p += _check_comparison(g["comparison"], f"{w}.comparison")
        if isinstance(g["comparison"], dict) and g["comparison"].get("id") in member:
            p.append(f"{w}: the gated comparison also belongs to a Holm family")
    return p


def validate(doc):
    """Problems of a prereg document (empty list = valid)."""
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return [f"schema must be {SCHEMA!r}"]
    p = []
    items = doc.get("items")
    if not isinstance(items, dict):
        return ["items must be an object"]
    for name in ITEMS:
        if name not in items:
            p.append(f"item {name} is missing")
    for name, it in items.items():
        if name not in ITEMS:
            p.append(f"unknown item {name!r}")
            continue
        if not isinstance(it, dict) or set(it) - ITEM_KEYS or "status" not in it or "value" not in it:
            p.append(f"{name}: an item is {{status, value, basis[, proposal][, note]}}")
            continue
        st = it["status"]
        if st not in STATUSES:
            p.append(f"{name}.status must be one of {STATUSES}")
        elif st == "fixed":
            if it["value"] is None:
                p.append(f"{name}: a fixed item needs a value")
            if not it.get("basis"):
                p.append(f"{name}: a fixed item needs a basis (the decision it rests on)")
        elif it["value"] is not None:
            p.append(f"{name}: a pending item has value null (put a suggestion in proposal)")
    # structure of the values (or proposals) that the scripts read
    pc = items.get("primary_comparison") or {}
    if pc.get("value") is not None:
        p += _check_comparison(pc["value"], "primary_comparison.value")
    for key in ("value", "proposal"):
        fams = (items.get("holm_families") or {}).get(key)
        if fams is not None:
            p += check_families(fams, f"holm_families.{key}")
        tost = (items.get("tost") or {}).get(key)
        if tost is not None:
            if not isinstance(tost, dict) or not isinstance(tost.get("comparisons"), list):
                p.append(f"tost.{key} must be an object with comparisons")
            else:
                for j, c in enumerate(tost["comparisons"]):
                    p += _check_comparison(c, f"tost.{key}.comparisons[{j}]")
        gated = (items.get("gated_tests") or {}).get(key)
        if gated is not None:
            fams_ref = (items.get("holm_families") or {}).get("value") or (items.get("holm_families") or {}).get("proposal")
            p += check_gated(gated, fams_ref, f"gated_tests.{key}")
        mech = (items.get("mechanism") or {}).get(key)
        if mech is not None:
            lab = mech.get("labels") if isinstance(mech, dict) else None
            if not isinstance(lab, dict) or set(lab) != set(MECHANISM_LABELS) or not all(
                    isinstance(v, str) and v for v in lab.values()):
                p.append(f"mechanism.{key}.labels must name {list(MECHANISM_LABELS)}")
        m = (items.get("tost_margin") or {}).get(key)
        if m is not None and (not isinstance(m, (int, float)) or not 0 < m < 1):
            p.append(f"tost_margin.{key} must be a proportion in (0, 1)")
    tiers = (items.get("tolerance_tiers") or {}).get("value")
    try:
        from orgene.score import TOLERANCES, tol_key
        if tiers is not None and list(tiers) != [tol_key(t) for t in TOLERANCES]:
            p.append(f"tolerance_tiers {tiers} differ from runtime/orgene/score.py {[tol_key(t) for t in TOLERANCES]}")
        prim = (items.get("tolerance_primary") or {}).get("value")
        if prim is not None and tiers is not None and prim not in tiers:
            p.append("tolerance_primary is not one of tolerance_tiers")
    except ImportError:  # pragma: no cover - the runtime is part of the repository
        p.append("runtime/orgene/score.py not importable")
    return p


class Prereg:
    def __init__(self, doc, path):
        self.doc = doc
        self.path = path
        self.sha256 = sha256_file(path) if path and os.path.exists(path) else None
        self.pending_used = {}

    @property
    def items(self):
        return self.doc["items"]

    def status(self, name):
        return self.items[name]["status"]

    def pending(self):
        return sorted(n for n, it in self.items.items() if it["status"] == "pending")

    def get(self, name, allow_pending=False, override=None):
        """Value of an item. `override` (a dev-only command-line value) is used only for a pending item."""
        it = self.items.get(name)
        if it is None:
            raise AnalysisError(f"no pre-registered item {name!r}")
        if it["status"] == "fixed":
            if override is not None and override != it["value"]:
                raise AnalysisError(f"{name} is fixed ({it['value']!r}); it cannot be overridden")
            return it["value"]
        if not allow_pending:
            raise PendingItem(f"pre-registered item {name} is pending (decided in 1D); a test analysis cannot run on it")
        val = override if override is not None else it.get("proposal")
        if val is None:
            raise PendingItem(f"pre-registered item {name} is pending and has no proposal; give the value explicitly "
                              "(dev analyses only)")
        self.pending_used[name] = val
        return val

    def provenance(self):
        return {"file": rel(self.path) if self.path else None, "sha256": self.sha256, "status": self.doc.get("status"),
                "pending_used": dict(sorted(self.pending_used.items()))}


def load(path=None, root=None):
    p = resolve(path or DEFAULT_PATH, root or ROOT)
    with open(p, encoding="utf-8") as f:
        doc = json.load(f)
    probs = validate(doc)
    if probs:
        raise AnalysisError(f"{rel(p)}: " + "; ".join(probs))
    return Prereg(doc, p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check"])
    ap.add_argument("--file", default=DEFAULT_PATH)
    ap.add_argument("--final", action="store_true", help="fail while any item is pending")
    a = ap.parse_args(argv)
    pr = load(a.file)
    pend = pr.pending()
    print(f"[prereg] {rel(pr.path)} sha256 {pr.sha256[:16]}  status {pr.doc.get('status')}  items {len(pr.items)}  "
          f"pending {len(pend)}: {', '.join(pend) or '(none)'}")
    if a.final and pend:
        print("[prereg] FAIL: pending items remain")
        return 1
    print("[prereg] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
