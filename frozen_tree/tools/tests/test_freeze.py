"""E21 freeze manifest: make / verify / register on throw-away repositories (self-made files only)."""
import json
import os
import subprocess
import sys

import pytest

from conftest import MINI_SPEC, ROOT, commit_all, git, write

from orgene import freeze as FZ  # noqa: E402


def _make(root, terms_file, **kw):
    return FZ.make(root, terms_file=terms_file, **kw)


def _manifest(root):
    return json.load(open(os.path.join(root, FZ.DEFAULT_MANIFEST), encoding="utf-8"))


# ------------------------------------------------------------------ make + verify (positive)


def test_make_and_verify_roundtrip(mini_repo, terms_file):
    m = _make(mini_repo, terms_file)
    assert m["complete"] is True and m["missing"] == []
    assert set(m["files"]) == {"code/a.py", "code/b.py", "conditions/t.md",
                               "data/splits/toy/dev_ids.json", "data/splits/toy/test_ids.json"}
    assert m["computed"]["git_trees"]["status"] == "ok"
    assert set(m["computed"]["git_trees"]["value"]["dirs"]) == {"code", "conditions", "tools", "configs"}
    assert m["computed"]["prov"]["value"]["salt"] == 1
    assert m["anon_scan"]["hits"] == 0 and m["anon_scan"]["identity_terms"] == 3
    assert m["content_sha256"] == FZ.content_sha256(m)
    assert m["osf"]["registration_id"] is None
    on_disk = _manifest(mini_repo)
    assert on_disk == m
    rep = FZ.verify(mini_repo)
    assert rep["ok"], rep["problems"]
    assert rep["complete"] and not rep["osf"]["id_valid"]
    # the file table has the shape the scoring override check (E13) reads: {path: {"sha256": ...}}
    assert all(len(v["sha256"]) == 64 for v in on_disk["files"].values())


def test_manifest_paths_are_relative_and_neutral(mini_repo, terms_file):
    _make(mini_repo, terms_file)
    text = open(os.path.join(mini_repo, FZ.DEFAULT_MANIFEST), encoding="utf-8").read()
    assert mini_repo not in text
    from orgene import anon as A
    sc, _ = A.build_scanner(mini_repo, terms_file)
    assert A.scan_text(sc, "m", text) == []


def test_verify_ignores_files_outside_the_freeze(mini_repo, terms_file):
    _make(mini_repo, terms_file)
    write(mini_repo, "notes.md", "edited after the freeze\n")
    commit_all(mini_repo, "notes")
    write(mini_repo, "experiments/run1/results.C0.jsonl", "{}\n")  # ignored artifact directory
    assert FZ.verify(mini_repo)["ok"]


# ------------------------------------------------------------------ verify fails after any change (negative)


@pytest.mark.parametrize("path", ["code/a.py", "conditions/t.md", "data/splits/toy/test_ids.json"])
@pytest.mark.parametrize("committed", [False, True])
def test_verify_fails_when_a_frozen_file_changes(mini_repo, terms_file, path, committed):
    _make(mini_repo, terms_file)
    with open(os.path.join(mini_repo, path), "a", encoding="utf-8") as f:
        f.write("\n")
    if committed:
        commit_all(mini_repo, "change")
    rep = FZ.verify(mini_repo)
    assert not rep["ok"]
    assert path in rep["changed"]


def test_verify_fails_when_a_file_is_added_or_removed_under_a_frozen_pattern(mini_repo, terms_file):
    _make(mini_repo, terms_file)
    write(mini_repo, "code/c.py", "z = 3\n")
    rep = FZ.verify(mini_repo)
    assert not rep["ok"] and rep["added"] == ["code/c.py"]
    os.remove(os.path.join(mini_repo, "code", "c.py"))
    os.remove(os.path.join(mini_repo, "code", "b.py"))
    rep = FZ.verify(mini_repo)
    assert not rep["ok"] and rep["missing_files"] == ["code/b.py"]


def test_verify_fails_on_uncommitted_or_untracked_files_in_frozen_dirs(mini_repo, terms_file):
    _make(mini_repo, terms_file)
    write(mini_repo, "tools/scratch.txt", "not in any glob, but inside a frozen directory\n")
    rep = FZ.verify(mini_repo)
    assert not rep["ok"] and rep["computed"]["git_trees"].startswith("error")


def test_verify_fails_when_a_computed_value_changes(mini_repo, terms_file):
    _make(mini_repo, terms_file)
    p = os.path.join(mini_repo, "tools", "prov.py")
    src = open(p).read()
    with open(p, "w") as f:
        f.write(src.replace('"salt": 1', '"salt": 2'))
    commit_all(mini_repo, "provider")
    rep = FZ.verify(mini_repo)
    assert not rep["ok"]
    assert rep["computed"]["prov"] == "changed" and rep["computed"]["git_trees"] == "changed"


def test_verify_fails_when_the_spec_changes(mini_repo, terms_file):
    _make(mini_repo, terms_file)
    spec = dict(MINI_SPEC, items=MINI_SPEC["items"][:2])
    write(mini_repo, "configs/freeze_spec.json", json.dumps(spec, indent=2))
    commit_all(mini_repo, "spec")
    rep = FZ.verify(mini_repo)
    assert not rep["ok"] and "freeze spec changed" in rep["problems"]


def test_verify_fails_when_the_manifest_is_edited(mini_repo, terms_file):
    _make(mini_repo, terms_file)
    m = _manifest(mini_repo)
    m["files"]["code/a.py"]["sha256"] = "0" * 64
    FZ.write_manifest(os.path.join(mini_repo, FZ.DEFAULT_MANIFEST), m)
    rep = FZ.verify(mini_repo)
    assert not rep["ok"]
    assert any("content_sha256" in p for p in rep["problems"])


def test_verify_without_manifest_raises(mini_repo):
    with pytest.raises(FZ.FreezeError):
        FZ.verify(mini_repo)


# ------------------------------------------------------------------ make refuses


def test_make_refuses_missing_or_pending_required_items(mini_repo, terms_file):
    spec = dict(MINI_SPEC, items=MINI_SPEC["items"] + [
        {"id": "later", "category": "text", "pending": "owner names the file"},
        {"id": "absent", "category": "config", "path": "configs/not_there.json"},
        {"id": "optional", "category": "data", "pending": "may be missing", "required": False}])
    write(mini_repo, "configs/freeze_spec.json", json.dumps(spec, indent=2))
    commit_all(mini_repo, "spec")
    with pytest.raises(FZ.FreezeError) as e:
        _make(mini_repo, terms_file)
    assert "later" in str(e.value) and "absent" in str(e.value) and "optional" not in str(e.value)
    assert not os.path.exists(os.path.join(mini_repo, FZ.DEFAULT_MANIFEST))
    m = _make(mini_repo, terms_file, allow_incomplete=True)
    assert m["complete"] is False and {x["id"] for x in m["missing"]} == {"later", "absent"}
    assert m["items"]["optional"]["status"] == "pending"
    rep = FZ.verify(mini_repo)
    assert rep["ok"] and not rep["complete"]


def test_make_refuses_a_dirty_frozen_directory(mini_repo, terms_file):
    write(mini_repo, "code/a.py", "x = 10\n")
    with pytest.raises(FZ.FreezeError) as e:
        _make(mini_repo, terms_file)
    assert "git_trees" in str(e.value)


def test_make_refuses_when_the_neutral_scan_hits(mini_repo, terms_file):
    write(mini_repo, "conditions/t.md", "Solve the problem. Prepared by " + "Alice" + " Example.\n")
    commit_all(mini_repo, "planted")
    with pytest.raises(FZ.FreezeError) as e:
        _make(mini_repo, terms_file)
    msg = str(e.value)
    assert "neutral-writing scan" in msg and "conditions/t.md:1" in msg
    assert ("Alice" + " Example") not in msg
    assert not os.path.exists(os.path.join(mini_repo, FZ.DEFAULT_MANIFEST))


def test_make_requires_an_identity_terms_file_unless_rehearsal(mini_repo, monkeypatch):
    from orgene import anon as A
    monkeypatch.delenv(A.TERMS_ENV, raising=False)
    with pytest.raises(FZ.FreezeError) as e:
        FZ.make(mini_repo)
    assert "terms" in str(e.value)
    m = FZ.make(mini_repo, allow_no_terms=True)
    assert m["anon_scan"]["identity_terms"] == 0


def test_spec_paths_must_stay_inside_the_repository(mini_repo, terms_file):
    spec = dict(MINI_SPEC, items=[{"id": "x", "category": "code", "path": "../outside.py"}])
    write(mini_repo, "configs/freeze_spec.json", json.dumps(spec))
    with pytest.raises(FZ.FreezeError):
        FZ.load_spec(mini_repo)


# ------------------------------------------------------------------ OSF registration


@pytest.mark.parametrize("raw,want", [("q7m2k", "q7m2k"), ("Q7M2K", "q7m2k"), ("https://osf.io/q7m2k/", "q7m2k"),
                                      ("osf.io/q7m2k", "q7m2k"), ("10.17605/OSF.IO/Q7M2K", "q7m2k"),
                                      ("https://doi.org/10.17605/OSF.IO/Q7M2K", "q7m2k")])
def test_osf_id_forms(raw, want):
    assert FZ.normalize_osf_id(raw) == want


@pytest.mark.parametrize("raw", ["", None, "pending", "abcde", "xxxxx", "12345", "q7m2", "q7m2k9", "osf.io/q7m", "not an id",
                                 "https://example.org/q7m2k"])
def test_osf_id_rejects_placeholders_and_malformed(raw):
    assert FZ.normalize_osf_id(raw) is None


def test_register_keeps_content_hash_and_refuses_rehearsals(mini_repo, terms_file):
    m = _make(mini_repo, terms_file)
    osf = FZ.register(mini_repo, osf_id="Q7M2K")
    assert osf["registration_id"] == "q7m2k" and osf["registered_content_sha256"] == m["content_sha256"]
    m2 = _manifest(mini_repo)
    assert m2["content_sha256"] == m["content_sha256"] == FZ.content_sha256(m2)
    rep = FZ.verify(mini_repo)
    assert rep["ok"] and rep["osf"]["matches_content"]
    FZ.register(mini_repo, osf_id="q7m2k")  # same id again is fine
    with pytest.raises(FZ.FreezeError):
        FZ.register(mini_repo, osf_id="w8n3p")
    with pytest.raises(FZ.FreezeError):
        FZ.register(mini_repo, osf_id="abcde")


def test_register_refuses_incomplete_or_changed(mini_repo, terms_file):
    spec = dict(MINI_SPEC, items=MINI_SPEC["items"] + [{"id": "later", "category": "text", "pending": "x"}])
    write(mini_repo, "configs/freeze_spec.json", json.dumps(spec, indent=2))
    commit_all(mini_repo, "spec")
    _make(mini_repo, terms_file, allow_incomplete=True)
    with pytest.raises(FZ.FreezeError):
        FZ.register(mini_repo, osf_id="q7m2k")
    write(mini_repo, "configs/freeze_spec.json", json.dumps(MINI_SPEC, indent=2))
    commit_all(mini_repo, "spec back")
    _make(mini_repo, terms_file)
    write(mini_repo, "code/a.py", "x = 11\n")
    with pytest.raises(FZ.FreezeError):
        FZ.register(mini_repo, osf_id="q7m2k")


def test_remake_of_a_registered_manifest_needs_supersede(mini_repo, terms_file):
    m1 = _make(mini_repo, terms_file)
    FZ.register(mini_repo, osf_id="q7m2k")
    with pytest.raises(FZ.FreezeError):
        _make(mini_repo, terms_file)
    write(mini_repo, "code/a.py", "x = 12\n")
    commit_all(mini_repo, "fix")
    m2 = _make(mini_repo, terms_file, supersede=True)
    assert m2["supersedes"] == [{"content_sha256": m1["content_sha256"], "created_at": m1["created_at"],
                                 "osf_registration_id": "q7m2k"}]
    assert m2["osf"]["registration_id"] is None and m2["content_sha256"] != m1["content_sha256"]


# ------------------------------------------------------------------ CLI


def test_cli_make_verify_register(tmp_path, terms_file):
    from conftest import copy_runtime_repo
    root = copy_runtime_repo(tmp_path / "r")
    cli = os.path.join(root, "tools", "freeze.py")
    run = lambda *a: subprocess.run([sys.executable, cli] + list(a), capture_output=True, text=True, timeout=300)  # noqa: E731
    p = run("verify")
    assert p.returncode == 1 and "REFUSED" in p.stderr
    p = run("make", "--anon-terms", terms_file)
    assert p.returncode == 0, p.stderr
    p = run("verify", "--require-complete")
    assert p.returncode == 0 and "VERIFY: PASS" in p.stdout
    p = run("verify", "--require-osf")
    assert p.returncode == 1
    p = run("register", "--osf", "pending")
    assert p.returncode == 1
    p = run("register", "--osf", "https://osf.io/q7m2k/")
    assert p.returncode == 0, p.stderr
    p = run("verify", "--require-complete", "--require-osf")
    assert p.returncode == 0
    assert root not in p.stdout + p.stderr


def test_real_spec_is_valid_and_lists_the_plan_categories():
    spec, rel, sha = FZ.load_spec(ROOT)
    assert rel == "configs/freeze_spec.json"
    cats = {it["category"] for it in spec["items"]}
    assert cats == set(FZ.CATEGORIES)
    ids = {it["id"] for it in spec["items"]} | {c["id"] for c in spec["computed"]}
    for must in ("gene_library", "condition_templates", "c3e_fixed_repair_template", "scoring_script", "prereg_analysis",
                 "cases", "splits_v5", "analysis_sets", "reference_overrides", "alphaopt_library", "model_registry",
                 "git_trees", "gene_anchors"):
        assert must in ids


# ------------------------------------------------------------------ gene anchors per registered configuration (A7)


def _real_gene_anchors_spec():
    spec, _, _ = FZ.load_spec(ROOT)
    return next(c for c in spec["computed"] if c["id"] == "gene_anchors")


def _ruled_library(tmp_path):
    """The working library with one problem-dependent activation rule (E04 format) added; self-made change only."""
    rows = [json.loads(line) for line in open(os.path.join(ROOT, "genes", "genes.r1.jsonl"), encoding="utf-8") if line.strip()]
    for g in rows:
        if g["geneId"] == "orgene.numeric.bigm_bounded":
            g["activation"] = {"rule": {"feature": "binary_terms", "op": "==", "value": True}, "rationale": "test only"}
    p = tmp_path / "genes.ruled.jsonl"
    p.write_text("".join(json.dumps(g, ensure_ascii=False) + "\n" for g in rows), encoding="utf-8")
    return str(p)


def test_gene_anchors_cover_every_registered_configuration():
    c = _real_gene_anchors_spec()
    assert c["call"] == "tools/anchor_hashes.py:config_anchors"
    value, _ = FZ.compute(ROOT, c)
    from orgene import configs as CF
    reg = CF.load_registry(os.path.join(ROOT, "configs", "r1_configs.json"))
    cfgs = value["configs"]
    assert set(cfgs) == set(reg["configs"])
    for cid, rec in cfgs.items():
        assert rec["gene_scope"] == reg["configs"][cid]["gene_scope"] and len(rec["scope_gene_set_digest"]) == 64, cid
    # configurations sharing a scope share its digest; the whole-scope ones record it as their activation digest
    assert cfgs["C2E"]["scope_gene_set_digest"] == cfgs["C3E"]["scope_gene_set_digest"] == cfgs["ORA"]["scope_gene_set_digest"]
    assert cfgs["C3L-ALL"]["activation_digest"] == cfgs["C3L"]["scope_gene_set_digest"]
    assert cfgs["C2E"]["activation_digest"] == cfgs["C3E"]["activation_digest"] == cfgs["C3E"]["scope_gene_set_digest"]
    assert cfgs["C3"]["activation_digest"] is None and cfgs["C3L"]["activation_digest"] is None  # per problem
    # system prompts: C3L, C3E, C3L-ALL use C0's, C2E uses C2's; the per-problem C3 prompt and ORA have none here
    assert cfgs["C3L"]["system_prompt_sha256"] == cfgs["C3E"]["system_prompt_sha256"] == cfgs["C0"]["system_prompt_sha256"]
    assert cfgs["C2E"]["system_prompt_sha256"] == cfgs["C2"]["system_prompt_sha256"]
    assert cfgs["C3"]["system_prompt_sha256"] is None and cfgs["ORA"]["system_prompt_sha256"] is None
    assert value["c3_all_active"]["n_active"] == cfgs["C3"]["n_scope_genes"]
    assert value["config_registry"] == "configs/r1_configs.json" and ROOT not in json.dumps(value)


def test_gene_anchors_survive_per_problem_rules_and_follow_the_registry(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("anchor_hashes_t", os.path.join(ROOT, "tools", "anchor_hashes.py"))
    AH = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(AH)
    cond, reg = os.path.join(ROOT, "conditions"), os.path.join(ROOT, "configs", "r1_configs.json")
    ruled = _ruled_library(tmp_path)
    # the previous anchors activated per problem without features and cannot anchor a library with rules
    with pytest.raises(ValueError, match="needs the problem features"):
        AH.gene_side(ruled, cond)
    base = AH.config_anchors(os.path.join(ROOT, "genes", "genes.r1.jsonl"), cond, reg)
    got = AH.config_anchors(ruled, cond, reg)
    # a rule changes the gene record, so the digests of the scopes holding that gene change, the others do not
    for cid in ("C3", "C3L", "C3L-ALL"):
        assert got["configs"][cid]["scope_gene_set_digest"] != base["configs"][cid]["scope_gene_set_digest"], cid
    for cid in ("C3E", "C2E"):
        assert got["configs"][cid]["scope_gene_set_digest"] == base["configs"][cid]["scope_gene_set_digest"], cid
    # remapping a configuration's scope in the registry changes the anchors (the old value did not name configurations)
    obj = json.load(open(reg, encoding="utf-8"))
    for c in obj["configs"]:
        if c["id"] == "C0":  # observe-only: records predicates of scope C3; point it at C3E instead
            c["gene_scope"] = "C3E"
    other = tmp_path / "r1_configs.json"
    other.write_text(json.dumps(obj), encoding="utf-8")
    moved = AH.config_anchors(os.path.join(ROOT, "genes", "genes.r1.jsonl"), cond, str(other))
    assert moved["configs"]["C0"]["scope_gene_set_digest"] == base["configs"]["C3E"]["scope_gene_set_digest"]
    assert moved["configs"]["C0"]["activation_digest"] != base["configs"]["C0"]["activation_digest"]
    assert moved["config_registry_sha256"] != base["config_registry_sha256"]
