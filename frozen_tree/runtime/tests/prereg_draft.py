"""Test support: the pre-registration file with the 1D decisions set back to pending.

configs/prereg_analysis.json fixed most of its items on 2026-10-03. The tests of the pending-item rules (a test
analysis refuses a pending item, a dev analysis runs on its proposal and records it) still need a document with
pending items; this builds one from the real file, so every other item stays the real one."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REAL = os.path.join(ROOT, "configs", "prereg_analysis.json")
DRAFT_ITEMS = ("alpha", "bootstrap", "holm_families", "tost", "shared_round0_mde", "forest_settings", "gated_tests")
NO_PROPOSAL = ("tost_margin",)


def draft_doc():
    doc = json.load(open(REAL, encoding="utf-8"))
    for name in DRAFT_ITEMS + NO_PROPOSAL:
        it = doc["items"][name]
        if it["status"] == "fixed":
            it["proposal"] = None if name in NO_PROPOSAL else it["value"]
            it.update(status="pending", value=None)
    return doc


def draft_file(tmp_path):
    p = os.path.join(str(tmp_path), "prereg_draft.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(draft_doc(), f)
    return p
