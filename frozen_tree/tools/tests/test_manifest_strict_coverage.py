"""Spec coverage regressions; all files/providers are invented in temporary roots.

Can run with unittest (stdlib only) or pytest. No model, real cases or OSF access.
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
from orgene import freeze as FZ


class StrictCoverage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="invented-freeze-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "configs").mkdir()
        (self.root / "payload").mkdir()
        (self.root / "payload/a.txt").write_text("invented a\n")
        (self.root / "payload/b.txt").write_text("invented b\n")
        (self.root / "provider.py").write_text("def compute():\n    return {'invented': 1}\n")
        self.spec = {"schema": FZ.SPEC_SCHEMA, "items": [
            {"id": "one", "category": "gene", "path": "payload/a.txt"},
            {"id": "all", "category": "code", "glob": "payload/*.txt"},
            {"id": "empty", "category": "text", "glob": "nothing/*.txt", "min_count": 0},
            {"id": "optional", "category": "config", "pending": "invented", "required": False},
        ], "computed": [
            {"id": "calc", "kind": "call", "call": "provider.py:compute"},
            {"id": "optional_calc", "kind": "call", "call": "provider.py:compute", "required": False},
        ]}
        self.build()

    def build(self):
        sp = self.root / FZ.DEFAULT_SPEC
        sp.write_text(json.dumps(self.spec))
        items, files, missing = FZ.collect(str(self.root), self.spec)
        computed = {}
        for definition in self.spec["computed"]:
            value, info = FZ.compute(str(self.root), definition)
            computed[definition["id"]] = {"status": "ok", "kind": definition["kind"],
                "required": bool(definition.get("required", True)), "value": value, "info": info}
        self.manifest = {"schema": FZ.MANIFEST_SCHEMA,
            "spec": {"path": FZ.DEFAULT_SPEC, "sha256": FZ.sha_file(sp)},
            "complete": not missing, "missing": missing, "items": items, "files": files,
            "computed": computed, "anon_scan": {"identity_terms": 0, "hits": 0}}

    def report(self, mutation=None):
        manifest = copy.deepcopy(self.manifest)
        if mutation:
            mutation(manifest)
        # Rehash deliberately: each test must detect a contract violation,
        # rather than merely a stale checksum. The OSF ID is invented metadata.
        manifest["content_sha256"] = FZ.content_sha256(manifest)
        manifest["osf"] = {"registration_id": "q7m2k",
                           "registered_content_sha256": manifest["content_sha256"]}
        FZ.write_manifest(str(self.root / FZ.DEFAULT_MANIFEST), manifest)
        return FZ.verify(str(self.root))

    def refuse(self, mutation):
        try:
            rep = self.report(mutation)
        except FZ.FreezeError:
            pass  # Malformed structural records fail closed before verification.
        else:
            self.assertFalse(rep["ok"], rep)
        with self.assertRaises(FZ.GateRefused):
            FZ.check_gate(str(self.root))

    def test_intact_roundtrip_shared_files_zero_minimum_optional_pending(self):
        rep = self.report()
        self.assertTrue(rep["ok"], rep["problems"])
        self.assertTrue(rep["complete"])
        FZ.check_gate(str(self.root))

    def test_required_item_deleted(self):
        self.refuse(lambda m: m["items"].pop("one"))

    def test_required_file_deleted(self):
        self.refuse(lambda m: m["files"].pop("payload/a.txt"))

    def test_both_glob_path_and_file_deleted(self):
        def edit(m):
            m["items"]["all"]["paths"].remove("payload/b.txt")
            m["files"].pop("payload/b.txt")
        self.refuse(edit)

    def test_required_item_demoted(self):
        self.refuse(lambda m: m["items"]["one"].update(required=False))

    def test_required_selector_changed(self):
        self.refuse(lambda m: m["items"]["all"].update(glob="payload/a.txt", paths=["payload/a.txt"]))

    def test_required_file_ownership_removed(self):
        self.refuse(lambda m: m["files"]["payload/a.txt"]["items"].remove("one"))

    def test_required_computed_deleted(self):
        self.refuse(lambda m: m["computed"].pop("calc"))

    def test_required_computed_demoted(self):
        self.refuse(lambda m: m["computed"]["calc"].update(required=False))

    def test_required_computed_kind_changed(self):
        self.refuse(lambda m: m["computed"]["calc"].update(kind="git_trees"))

    def test_required_pending_spec_with_forged_complete(self):
        self.spec["items"].append({"id": "later", "category": "text", "pending": "invented"})
        self.build()
        self.refuse(lambda m: m.update(complete=True, missing=[]))

    def test_required_missing_spec_with_forged_complete(self):
        self.spec["items"].append({"id": "absent", "category": "text", "path": "payload/absent.txt"})
        self.build()
        self.refuse(lambda m: m.update(complete=True, missing=[]))

    def test_intact_missing_pending_rehearsal(self):
        self.spec["items"] += [
            {"id": "later", "category": "text", "pending": "invented"},
            {"id": "absent", "category": "text", "path": "payload/absent.txt"}]
        self.build()
        rep = self.report()
        self.assertTrue(rep["ok"], rep["problems"])
        self.assertFalse(rep["complete"])
        with self.assertRaises(FZ.GateRefused):
            FZ.check_gate(str(self.root))

    def test_required_computed_error_rehearsal(self):
        def edit(m):
            m["computed"]["calc"] = {"status": "error", "kind": "call", "required": True, "error": "invented"}
            m.update(complete=False, missing=[{"id": "calc", "reason": "invented"}])
        rep = self.report(edit)
        self.assertTrue(rep["ok"], rep["problems"])
        self.assertFalse(rep["complete"])
        self.assertEqual(rep["computed"]["calc"], "not frozen")

    def test_optional_computed_error_complete(self):
        rep = self.report(lambda m: m["computed"]["optional_calc"].update(status="error"))
        self.assertTrue(rep["ok"], rep["problems"])
        self.assertTrue(rep["complete"])

    def test_optional_item_deleted(self):
        self.refuse(lambda m: m["items"].pop("optional"))

    def test_optional_computed_deleted(self):
        self.refuse(lambda m: m["computed"].pop("optional_calc"))

    def test_extra_item(self):
        self.refuse(lambda m: m["items"].update(extra=copy.deepcopy(m["items"]["one"])))

    def test_extra_computed(self):
        self.refuse(lambda m: m["computed"].update(extra=copy.deepcopy(m["computed"]["calc"])))

    def test_extra_file(self):
        path = self.root / "outside.txt"
        path.write_text("invented outside file\n")
        self.refuse(lambda m: m["files"].update({"outside.txt": {
            "sha256": FZ.sha_file(path), "bytes": path.stat().st_size, "items": []}}))

    def test_optional_missing_with_required_satisfied_is_complete(self):
        self.spec["items"].append({"id": "optional_absent", "category": "text",
                                   "path": "absent.txt", "required": False})
        self.build()
        rep = self.report()
        self.assertTrue(rep["ok"], rep["problems"])
        self.assertTrue(rep["complete"])

    def test_nonempty_missing_with_claimed_complete(self):
        self.refuse(lambda m: m.update(missing=[{"id": "invented", "reason": "invented"}]))


def invalid_missing(value):
    def test(self):
        self.refuse(lambda m: m.update(missing=value))
    return test


for i, value in enumerate((None, "", {}, False, 0)):
    setattr(StrictCoverage, "test_non_list_missing_%d" % i, invalid_missing(value))


def invalid_file_field(field, value):
    def test(self):
        self.refuse(lambda m: m["files"]["payload/a.txt"].update({field: value}))
    return test


for i, value in enumerate((True, False, -1, "11", 1.5, 999)):
    setattr(StrictCoverage, "test_invalid_byte_count_%d" % i, invalid_file_field("bytes", value))
for i, value in enumerate(("", "a" * 63, "A" * 64, "z" * 64, 1, int("1" * 64))):
    setattr(StrictCoverage, "test_invalid_file_hash_%d" % i, invalid_file_field("sha256", value))


def invalid_complete(value):
    def test(self):
        self.refuse(lambda m: m.update(complete=value))
        self.assertFalse(FZ.verify(str(self.root))["complete"])
    return test


for i, value in enumerate((1, 0, "true", "false", None, [], {})):
    setattr(StrictCoverage, "test_non_boolean_complete_%d" % i, invalid_complete(value))


def failed_computed(status):
    def test(self):
        self.refuse(lambda m: m["computed"]["calc"].update(status=status))
    return test


for status in ("error", "pending"):
    setattr(StrictCoverage, "test_required_computed_" + status + "_claimed_complete", failed_computed(status))


if __name__ == "__main__":
    unittest.main(verbosity=2)
