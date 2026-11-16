"""E03: configuration registry and per-(configuration, case) prompts and requests.

Fixtures are self-made toy cases and the author-written smoke cases only; no benchmark case is read.
"""
import copy
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from orgene import conditions as C  # noqa: E402
from orgene import configs as CF  # noqa: E402
from orgene import env as E  # noqa: E402
from orgene import genes as G  # noqa: E402
from orgene import paths as PA  # noqa: E402
from orgene.selftest import GOOD_CODE  # noqa: E402

REG_PATH = os.path.join(ROOT, "configs", "r1_configs.json")
GENES = os.path.join(ROOT, "genes", "genes.r1.jsonl")
COND = os.path.join(ROOT, "conditions")
RELEASE = os.path.join(ROOT, "releases", "v1.0")
CLI = os.path.join(RUNTIME, "orgene_cli.py")
SMOKE_CASES = os.path.join(ROOT, "data", "cases", "smoke.jsonl")

CASE_A = {"case_id": "toy-0001", "source": "toy",
          "text": "A shop makes chairs and tables. Maximise profit 5x + 4y subject to 2x + y <= 10 and x + y <= 7."}
CASE_B = {"case_id": "toy-0002", "source": "toy",
          "text": "Choose at most 2 of 4 projects (yes or no) to maximise total value within a budget of 100."}
STANDARD = ("C0", "C1", "C2", "C3", "C3L", "C3E", "C2E", "C3L-ALL")


@pytest.fixture(scope="module")
def reg():
    return CF.load_registry(REG_PATH)


@pytest.fixture(scope="module")
def store():
    return G.load_store(GENES)


def _raw():
    with open(REG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _cfg(obj, cid):
    return next(c for c in obj["configs"] if c["id"] == cid)


def _expect_error(obj, *fragments):
    with pytest.raises(CF.RegistryError) as ei:
        CF.parse_registry(obj)
    msg = str(ei.value)
    for f in fragments:
        assert f in msg, msg
    return msg


def _prompt(reg, store, cid, case=CASE_A, **kw):
    kw.setdefault("cond_dir", COND)
    return C.build_prompt(CF.get_config(reg, cid), case, store, **kw)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ============================================================ registry: positive


def test_registry_lists_the_planned_configurations(reg):
    assert list(reg["configs"]) == ["C0", "C1", "C2", "C3", "C3L", "C3E", "C2E", "C3L-ALL", "C3T", "C3A",
                                    "C0R-E", "ORA"]
    assert sorted(reg["adapters"]) == ["AOPT", "LLMOPT", "ORLM"]
    assert reg["path"] == "configs/r1_configs.json"
    assert reg["sha256"] == hashlib.sha256(open(REG_PATH, "rb").read()).hexdigest()
    assert {a["adapter"] for a in reg["adapters"].values()} == {"alphaopt", "orlm", "llmopt"}


# id: (prompt, round0, validator, gene_scope, activation, repair, closing, max_rounds)
DESIGN = {
    "C0": ("C0", "own", "observe", "C3", "all", "none", "program", 0),
    "C1": ("C1", "own", "observe", "C3", "all", "none", "program", 0),
    "C2": ("C2", "own", "observe", "C3", "all", "none", "spec_and_program", 0),
    "C3": ("C3", "own", "gene", "C3", "per_problem", "gene", "spec_and_program", 2),
    "C3L": ("C0", "reuse:C0", "gene", "C3L", "per_problem", "gene", "program", 2),
    "C3E": ("C0", "reuse:C0", "gene", "C3E", "all", "generic", "program", 2),
    "C2E": ("C2", "reuse:C2", "gene", "C3E", "all", "generic", "spec_and_program", 2),
    "C3L-ALL": ("C0", "reuse:C0", "gene", "C3L", "all", "gene", "program", 2),
    "C3T": ("C0", "reuse:C0", "gene", "C3L", "per_problem", "gene_generic", "program", 2),
    "C3A": ("C0", "reuse:C0", "gene", "C3L", "per_problem", "gene_generic", "program", 2),
    "C0R-E": ("C0R", "own", "gene", "C3E", "all", "generic", "program", 2),
    "ORA": ("C0", "own", "gene", "C3E", "all", "generic", "program", 2),
}
DESIGN_KEYS = ("prompt", "round0", "validator", "gene_scope", "activation", "repair", "closing", "max_rounds")


def test_registry_fields_match_the_design(reg):
    for cid, want in DESIGN.items():
        c = reg["configs"][cid]
        assert tuple(c[k] for k in DESIGN_KEYS) == want, cid
        assert (c["num_predict"], c["num_ctx"], c["variant"], c["token_cap"]) == (6000, 32768, None, None), cid
        assert c["pipeline"] == ("ora" if cid == "ORA" else "standard"), cid
        assert c["label"], cid


def test_main_comparison_differs_only_in_the_repair_mechanism(reg):
    """C3L vs C3E: same prompt, same round 0, same rounds and limits; only gene scope, activation and repair differ."""
    a, b = reg["configs"]["C3L"], reg["configs"]["C3E"]
    differing = {k for k in a if a[k] != b[k]}
    assert differing == {"id", "label", "notes", "gene_scope", "activation", "repair"}, differing


def test_helpers(reg):
    assert CF.reuse_source(reg["configs"]["C3L"]) == "C0" and CF.reuse_source(reg["configs"]["C2E"]) == "C2"
    assert CF.reuse_source(reg["configs"]["C3"]) is None
    assert [c for c in reg["configs"] if CF.asks_for_spec(reg["configs"][c])] == ["C2", "C3", "C2E"]
    assert set(CF.all_ids(reg)) == set(DESIGN) | {"AOPT", "ORLM", "LLMOPT"}


# ============================================================ registry: negative


def test_unknown_field_is_rejected():
    obj = _raw()
    _cfg(obj, "C0")["temperature"] = 0
    _expect_error(obj, "config 'C0'", "unknown field(s) ['temperature']")


def test_missing_field_is_rejected():
    obj = _raw()
    del _cfg(obj, "C3")["closing"]
    _expect_error(obj, "config 'C3'", "missing field(s) ['closing']")


def test_unknown_prompt_is_rejected():
    obj = _raw()
    _cfg(obj, "C1")["prompt"] = "C4"
    _expect_error(obj, "config 'C1'", "prompt='C4'")


def test_reuse_of_an_unregistered_configuration_is_rejected():
    obj = _raw()
    _cfg(obj, "C3L")["round0"] = "reuse:C9"
    _expect_error(obj, "config 'C3L'", "'C9', which is not a registered configuration")


@pytest.mark.parametrize("cid, changes, fragment", [
    ("C3L", {"round0": "reuse:C3E"}, "no chains"),
    ("C3L", {"round0": "reuse:C3L"}, "reuses itself"),
    ("C3L", {"round0": "reuse:AOPT"}, "reuses adapter 'AOPT'"),
    ("C3L", {"round0": "reuse:ORA"}, "whose pipeline is 'ora'"),
    ("C3L", {"round0": "copy:C0"}, "must be 'own' or 'reuse:<config id>'"),
    ("C3L", {"prompt": "C1"}, "but prompt differs"),
    ("C2E", {"num_ctx": 16384}, "but num_ctx differs"),
    ("C3E", {"num_predict": 4000}, "but num_predict differs"),
    ("C3L", {"variant": "r1"}, "but variant differs"),
])
def test_reuse_must_be_one_step_and_request_identical(cid, changes, fragment):
    obj = _raw()
    _cfg(obj, cid).update(changes)
    _expect_error(obj, f"config {cid!r}", fragment)


@pytest.mark.parametrize("cid, changes, fragment", [
    ("C0", {"repair": "gene", "max_rounds": 2}, "repair 'gene' needs validator 'gene'"),
    ("C3L", {"repair": "none", "max_rounds": 0}, "validator 'gene' without repair"),
    ("C3", {"max_rounds": 0}, "max_rounds must be 0 exactly when repair is 'none'"),
    ("C0", {"max_rounds": 1}, "max_rounds must be 0 exactly when repair is 'none'"),
    ("C0", {"max_rounds": True}, "max_rounds must be an integer"),
    ("C3", {"max_rounds": 9}, "max_rounds must be an integer in 0..5"),
    ("C3L", {"closing": "spec_and_program"}, "closing 'spec_and_program' does not match prompt 'C0'"),
    ("C2E", {"closing": "program"}, "closing 'program' does not match prompt 'C2'"),
    ("C3L", {"gene_scope": "C2E"}, "gene_scope='C2E' is not one of"),
    ("C3", {"gene_scope": "C3L"}, "compiles its contract from gene scope C3"),
    ("C3", {"activation": "none"}, "need a gene_scope and an activation"),
    ("C3L", {"gene_scope": None}, "need a gene_scope and an activation"),
    ("C0", {"validator": "none"}, "gene_scope must be null and activation 'none'"),
    ("C3L", {"repair": "generic"}, "gene_scope must be 'C3E'"),
    ("C0", {"num_ctx": 6000}, "num_ctx (6000) must exceed num_predict (6000)"),
    ("C0", {"num_predict": 0}, "num_predict must be a positive integer"),
    ("C0", {"variant": "Bad Name"}, "variant must be null or match"),
    ("C0", {"token_cap": 0}, "token_cap must be null or a positive integer"),
    ("C0", {"id": "C0.x"}, "id must match"),
    ("C0", {"validator": "strict"}, "validator='strict'"),
    ("C3", {"activation": "sometimes"}, "activation='sometimes'"),
    ("C3", {"repair": "gene_and_generic"}, "repair='gene_and_generic'"),
    ("C3", {"closing": "spec"}, "closing='spec'"),
    ("ORA", {"pipeline": "agent"}, "pipeline='agent'"),
    ("ORA", {"round0": "reuse:C0"}, "the ora pipeline generates its own round 0"),
    # scope C3 carries the spec predicates: repairing with it on a prompt that never asked for a spec is inconsistent
    ("C3L", {"gene_scope": "C3"}, "gene scope C3 includes the spec predicates"),
    ("C3L-ALL", {"gene_scope": "C3"}, "gene scope C3 includes the spec predicates"),
    # a trailing newline must not slip through the name patterns ('$' matches before it, '\Z' does not)
    ("C0", {"id": "C0\n"}, "id must match"),
    ("C0", {"variant": "r1\n"}, "variant must be null or match"),
    ("C3L", {"round0": "reuse:C0\n"}, "must be 'own' or 'reuse:<config id>'"),
])
def test_inconsistent_or_invalid_fields_are_rejected(cid, changes, fragment):
    obj = _raw()
    _cfg(obj, cid).update(changes)
    _expect_error(obj, fragment)


def test_duplicate_ids_are_rejected():
    obj = _raw()
    obj["configs"].append(copy.deepcopy(_cfg(obj, "C0")))
    _expect_error(obj, "duplicate id 'C0'")
    obj = _raw()
    obj["adapters"][0]["id"] = "C3"
    _expect_error(obj, "duplicate id 'C3' (config and adapter)")


def test_top_level_and_adapters_are_checked():
    obj = _raw()
    obj["defaults"] = {}
    _expect_error(obj, "unknown top-level field(s) ['defaults']")
    obj = _raw()
    obj["schema"] = "orgene.configs.v0"
    _expect_error(obj, "schema must be 'orgene.configs.v1'")
    obj = _raw()
    del obj["configs"]
    _expect_error(obj, "missing top-level field(s) ['configs']")
    obj = _raw()
    obj["adapters"][0]["prompt"] = "C0"
    _expect_error(obj, "adapter 'AOPT'", "unknown field(s) ['prompt']")
    obj = _raw()
    obj["adapters"][1]["adapter"] = "orlm2"
    _expect_error(obj, "adapter='orlm2'")


def test_every_error_is_reported_at_once():
    obj = _raw()
    _cfg(obj, "C0")["temperature"] = 0
    _cfg(obj, "C1")["prompt"] = "C4"
    _cfg(obj, "C3L")["round0"] = "reuse:C9"
    msg = _expect_error(obj, "temperature", "prompt='C4'", "'C9'")
    assert msg.count("\n  - ") == 3


def test_invalid_json_is_rejected(tmp_path):
    p = tmp_path / "r.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(CF.RegistryError, match="not valid JSON"):
        CF.load_registry(str(p))


def test_get_config_refuses_unknown_and_adapter_ids(reg):
    with pytest.raises(CF.RegistryError, match="unknown configuration 'C9'"):
        CF.get_config(reg, "C9")
    with pytest.raises(CF.RegistryError, match="adapter baseline"):
        CF.get_config(reg, "AOPT")


# ============================================================ gene scopes


def test_gene_records_may_only_name_the_three_scopes(reg, store):
    CF.check_store_scopes(store)
    CF.check_registry_against_store(reg, store)
    bad = copy.deepcopy(store)
    bad[0]["scope"]["conditions"] = ["C3", "C2E"]
    with pytest.raises(CF.RegistryError, match="C2E"):
        CF.check_store_scopes(bad)
    with pytest.raises(CF.RegistryError, match="C2E"):
        _prompt(reg, bad, "C0")


def test_every_scope_in_use_has_active_genes(reg, store):
    no_c3e = copy.deepcopy(store)
    for g in no_c3e:
        g["scope"]["conditions"] = [c for c in g["scope"]["conditions"] if c != "C3E"]
    with pytest.raises(CF.RegistryError, match="gene scope 'C3E' has no active gene"):
        CF.check_registry_against_store(reg, no_c3e)


def test_new_configurations_reuse_the_scope_gene_sets(reg, store):
    """C3L-ALL, C2E and ORA point at existing scopes: same gene sets and digests, no change to the library."""
    digest = {s: G.store_digest(G.activate(store, condition=s)[0]) for s in CF.GENE_SCOPES}
    for cid in STANDARD:
        meta = _prompt(reg, store, cid)[1]
        assert meta["gene_set_digest"] == digest[reg["configs"][cid]["gene_scope"]], cid
    assert len(_prompt(reg, store, "C3L-ALL")[1]["active_genes"]) == 13
    assert len(_prompt(reg, store, "C2E")[1]["active_genes"]) == 5


# ============================================================ prompts


def test_registry_builder_reproduces_the_v1_builder_on_the_working_library(reg, store):
    prompts_v1, info = C.build_system_prompts_v1(COND, GENES)
    for cid in STANDARD:
        for case in (CASE_A, CASE_B):
            text, meta = _prompt(reg, store, cid, case)
            assert text == prompts_v1[reg["configs"][cid]["prompt"]], cid
            assert meta["system_prompt_sha256"] == _sha(text)
    c1 = _prompt(reg, store, "C1")[1]["c1_match"]
    assert c1["ratio"] == info["c1_c3_char_ratio"] and c1["bullets_used"] == info["c1_bullets_used"]
    assert c1["ok"] is True and c1["measure"] == "chars"
    assert _prompt(reg, store, "C3")[1]["contract_sha256"] == info["contract_sha256"]


@pytest.mark.skipif(not os.path.exists(os.path.join(RELEASE, "genes.v3.jsonl")),
                    reason="releases/v1.0 is not in the anonymous repository (v5 originals)")
def test_v1_release_hashes_are_reproduced_by_the_registry_builder(reg):
    from anchor_hashes import EXPECTED_V1
    store_v1 = G.load_store(os.path.join(RELEASE, "genes.v3.jsonl"))
    cond_v1 = os.path.join(RELEASE, "conditions")
    got = {cid: _prompt(reg, store_v1, cid, cond_dir=cond_v1) for cid in STANDARD}
    for cid, want in EXPECTED_V1["system_prompt_sha256"].items():
        assert got[cid][1]["system_prompt_sha256"].startswith(want), cid
    for cid in ("C3L", "C3E", "C3L-ALL"):
        assert got[cid][0] == got["C0"][0], cid
    assert got["C2E"][0] == got["C2"][0]
    assert got["C3"][1]["contract_sha256"] == EXPECTED_V1["contract_sha256"]
    assert got["C3"][1]["contract_chars"] == EXPECTED_V1["contract_chars"]
    for cid in ("C3", "C3L", "C3E"):
        assert got[cid][1]["gene_set_digest"].startswith(EXPECTED_V1["activation_digest"][cid]), cid
        assert len(got[cid][1]["active_genes"]) == EXPECTED_V1["n_active"][cid], cid


def test_messages_are_exactly_system_and_user_without_ids(reg, store):
    ids = CF.all_ids(reg)
    run_id = "20260101-toy-model-toy-dev-X"
    for cid in STANDARD:
        for case in (CASE_A, CASE_B):
            req = C.build_request(CF.get_config(reg, cid), case, store, run_id, registry_ids=ids, cond_dir=COND)
            msgs = req["messages"]
            assert [m["role"] for m in msgs] == ["system", "user"]
            assert all(set(m) == {"role", "content"} for m in msgs)
            assert msgs[1]["content"] == "Problem:\n" + case["text"].strip() + "\n"
            blob = json.dumps(msgs)
            for s in (req["request_id"], case["case_id"], run_id):
                assert s not in blob, (cid, s)
            for other in ids:
                assert not C._id_pattern(other).search(msgs[0]["content"]), (cid, other)
            assert req["request_id"] == f"{case['case_id']}.{cid}" and req["config_id"] == cid == req["condition"]
            meta = req["meta"]
            for k in ("config_id", "activation_trace", "active_genes", "system_prompt_sha256", "contract_sha256",
                      "features_sha256", "gene_scope", "activation", "round0", "run_id"):
                assert k in meta, (cid, k)
            assert meta["config_id"] == cid and meta["round"] == 0
            assert meta["system_prompt_sha256"] == _sha(msgs[0]["content"])
            assert (meta["contract_sha256"] is not None) == (reg["configs"][cid]["prompt"] == "C3")
            assert len(meta["activation_trace"]) == len(store)


def test_ids_leaking_into_messages_are_refused(reg, store, tmp_path):
    leaky = dict(CASE_A, case_id="toy-0003", text="Case toy-0003: maximise x subject to x <= 1.")
    with pytest.raises(ValueError, match="identifier 'toy-0003'"):
        C.build_request(CF.get_config(reg, "C0"), leaky, store, "run", cond_dir=COND)
    cond = tmp_path / "conditions"
    shutil.copytree(COND, cond)
    with open(cond / "base_system.md", "a", encoding="utf-8") as f:
        f.write("\nThis is configuration C3L.\n")
    with pytest.raises(ValueError, match="configuration id 'C3L'"):
        C.build_request(CF.get_config(reg, "C0"), CASE_A, store, "run", registry_ids=CF.all_ids(reg), cond_dir=str(cond))
    sysm = {"role": "system", "content": "s"}
    usr = {"role": "user", "content": "u"}
    with pytest.raises(ValueError, match="exactly"):
        C.check_messages([sysm, usr, {"role": "assistant", "content": "a"}])
    with pytest.raises(ValueError, match="exactly"):
        C.check_messages([usr, sysm])
    with pytest.raises(ValueError, match="only role and"):
        C.check_messages([sysm, dict(usr, name="C0")])


def test_c2_differs_from_c0_exactly_by_the_spec_section(reg, store):
    c0 = _prompt(reg, store, "C0")[0]
    c2 = _prompt(reg, store, "C2")[0]
    assert c0 != c2
    T = C.load_templates(COND)
    base = C._base(T)
    assert c0.startswith(base) and c2.startswith(base)
    diff = [line for line in difflib.ndiff(c0.splitlines(), c2.splitlines()) if line[:2] in ("- ", "+ ")]
    removed = [line[2:] for line in diff if line.startswith("- ")]
    added = [line[2:] for line in diff if line.startswith("+ ")]
    assert removed == [T["texts"]["C0"].strip()]
    spec_section = (T["texts"]["C2"].replace("{SPEC_SCHEMA_SUMMARY}", T["texts"]["schema_summary"].rstrip())
                    .strip().splitlines())
    assert added == spec_section
    assert any("JSON specification" in line for line in added)
    assert any('"decision_variables"' in line for line in added)
    assert "JSON specification" not in c0 and "decision_variables" not in c0


def test_reuse_configurations_send_byte_identical_round0_requests(reg, store):
    for cid, c in reg["configs"].items():
        src = CF.reuse_source(c)
        if not src:
            continue
        for case in (CASE_A, CASE_B):
            a = C.build_request(c, case, store, "run", cond_dir=COND)
            b = C.build_request(CF.get_config(reg, src), case, store, "run", cond_dir=COND)
            assert a["messages"] == b["messages"], (cid, src)
            assert a["meta"]["round0"] == f"reuse:{src}"


def _fake_per_problem_activate(real):
    """Stand-in for the E04 activate(): drops the big-M gene unless the case has a big-M cue."""
    def activate(genes, condition="C3", task="lp_milp_modeling", features=None, mode="per_problem"):
        active, trace = real(genes, condition=condition, task=task)
        if mode == "per_problem":
            drop = set() if (features or {}).get("big_m_cue") else {"orgene.numeric.bigm_bounded"}
            active = [g for g in active if g["geneId"] not in drop]
            trace = [dict(t, included=t["included"] and t["geneId"] not in drop,
                          activation_value=t["geneId"] not in drop) for t in trace]
        return active, trace
    return activate


def test_c3_contract_is_compiled_per_case(monkeypatch, reg, store):
    monkeypatch.setattr(G, "activate", _fake_per_problem_activate(G.activate))
    fa, fb = {"big_m_cue": True, "n_numbers": 4}, {"big_m_cue": False, "n_numbers": 3}
    a = _prompt(reg, store, "C3", CASE_A, features=fa)
    b = _prompt(reg, store, "C3", CASE_B, features=fb)
    assert a[1]["activation_impl"] == b[1]["activation_impl"] == "per_problem"
    assert len(a[1]["active_genes"]) == 17 and len(b[1]["active_genes"]) == 16
    assert a[1]["contract_sha256"] != b[1]["contract_sha256"]
    assert a[1]["system_prompt_sha256"] != b[1]["system_prompt_sha256"]
    assert a[1]["features_sha256"] == C.features_digest(fa) != b[1]["features_sha256"]
    assert _prompt(reg, store, "C3", CASE_A, features=dict(fa))[0] == a[0], "deterministic"
    # C3L activates per problem too; the ablation and the fixed-template configuration do not
    assert len(_prompt(reg, store, "C3L", CASE_B, features=fb)[1]["active_genes"]) == 12
    assert len(_prompt(reg, store, "C3L-ALL", CASE_B, features=fb)[1]["active_genes"]) == 13
    assert len(_prompt(reg, store, "C3E", CASE_B, features=fb)[1]["active_genes"]) == 5
    # prompts without a contract do not depend on the case (C1 is matched against the all-active C3 prompt)
    for cid in ("C0", "C1", "C2", "C3L", "C3E", "C2E", "C3L-ALL"):
        assert _prompt(reg, store, cid, CASE_A, features=fa)[0] == _prompt(reg, store, cid, CASE_B, features=fb)[0], cid


def test_per_problem_rules_are_refused_until_activation_can_evaluate_them(monkeypatch, reg, store):
    def scope_only_activate(genes, condition="C3", task="lp_milp_modeling"):
        active = [g for g in genes if g["lifecycle"].get("state") == "active" and condition in g["scope"]["conditions"]]
        active.sort(key=lambda g: (-int(g["preference"].get("priority", 0)), g["geneId"]))
        return active, [{"geneId": g["geneId"], "included": g in active} for g in genes]
    monkeypatch.setattr(G, "activate", scope_only_activate)
    assert _prompt(reg, store, "C3")[1]["activation_impl"] == "scope_only"
    ruled = copy.deepcopy(store)
    ruled[-1]["activation"] = {"rule": {"feature": "n_numbers", "op": ">=", "value": 3}}
    with pytest.raises(NotImplementedError, match="activation rules"):
        _prompt(reg, ruled, "C3")
    with pytest.raises(NotImplementedError, match="activation rules"):
        _prompt(reg, ruled, "C3L")
    assert len(_prompt(reg, ruled, "C3L-ALL")[1]["active_genes"]) == 13, "'all' ignores activation rules"
    # only problem-dependent rules of the configuration's own scope count; the rule "always" does not
    gid = ruled[-1]["geneId"]
    assert C.problem_rule_genes(ruled) == C.problem_rule_genes(ruled, "C3L") == [gid]
    assert C.problem_rule_genes(ruled, "C3E") == [] and C.problem_rule_genes(store) == []
    always = copy.deepcopy(store)
    always[-1]["activation"] = {"rule": "always", "rationale": "applies to every problem"}
    assert C.problem_rule_genes(always) == []
    assert _prompt(reg, always, "C3")[1]["activation_impl"] == "scope_only"


def test_c1_prompt_is_static_and_length_matched(reg, store):
    a = _prompt(reg, store, "C1", CASE_A)
    b = _prompt(reg, store, "C1", CASE_B)
    assert a[0] == b[0]
    target = C.c1_default_target(C.load_templates(COND), store)  # the C3 prompt with every C3 gene active
    assert a[1]["c1_match"]["target"] == target == len(_prompt(reg, store, "C3")[0])
    assert a[1]["contract_sha256"] is None and a[1]["contract_in_prompt"] is False
    assert a[1]["c1_match"]["ok"]


def test_ora_and_adapters_have_no_single_system_prompt(reg, store):
    with pytest.raises(ValueError, match="pipeline 'ora'"):
        _prompt(reg, store, "ORA")
    with pytest.raises(ValueError, match="pipeline 'ora'"):
        C.build_requests([CASE_A], CF.get_config(reg, "ORA"), store, "run", cond_dir=COND)


def _variant_setup(tmp_path, files):
    cond = tmp_path / "conditions"
    shutil.copytree(COND, cond)
    vdir = cond / "variants" / "r1"
    vdir.mkdir(parents=True)
    for name, text in files.items():
        (vdir / name).write_text(text, encoding="utf-8")
    obj = _raw()
    v = dict(_cfg(obj, "C0"), id="C0-R1", variant="r1", label="C0 rewrite r1")
    obj["configs"].append(v)
    obj["configs"].append(dict(_cfg(obj, "C3L"), id="C3L-R1", variant="r1", round0="reuse:C0-R1"))
    return str(cond), CF.parse_registry(obj)


def test_prompt_variants(tmp_path, store):
    cond, reg2 = _variant_setup(tmp_path, {"C0_direct.md": "Return only the complete program.\n"})
    text, meta = C.build_prompt(reg2["configs"]["C0-R1"], CASE_A, store, cond_dir=cond)
    base_text, base_meta = C.build_prompt(reg2["configs"]["C0"], CASE_A, store, cond_dir=cond)
    assert text.endswith("\nReturn only the complete program.\n") and text != base_text
    assert meta["variant"] == "r1" and base_meta["variant"] is None
    assert meta["template_sha256"]["C0"] != base_meta["template_sha256"]["C0"]
    assert meta["template_sha256"]["base"] == base_meta["template_sha256"]["base"]
    # a rewrite of one template leaves the others as they are
    c2v = C.build_prompt(reg2["configs"]["C2"], CASE_A, store, cond_dir=cond, variant="r1")[0]
    assert c2v == C.build_prompt(reg2["configs"]["C2"], CASE_A, store, cond_dir=cond)[0]
    # the reusing configuration follows its source's variant
    assert C.build_prompt(reg2["configs"]["C3L-R1"], CASE_A, store, cond_dir=cond)[0] == text
    with pytest.raises(ValueError, match="registered with variant 'r1'"):
        C.build_prompt(reg2["configs"]["C0-R1"], CASE_A, store, cond_dir=cond, variant="r2")
    with pytest.raises(ValueError, match="not found"):
        C.build_prompt(reg2["configs"]["C0"], CASE_A, store, cond_dir=cond, variant="zz")


def test_misspelt_variant_file_is_refused(tmp_path, store):
    cond, reg2 = _variant_setup(tmp_path, {"C0_direkt.md": "Return only the complete program.\n"})
    with pytest.raises(ValueError, match="not template names"):
        C.build_prompt(reg2["configs"]["C0-R1"], CASE_A, store, cond_dir=cond)


def test_template_without_contract_placeholder_is_refused(tmp_path, reg, store):
    cond = tmp_path / "conditions"
    shutil.copytree(COND, cond)
    p = cond / "C3_orgene.md"
    p.write_text(p.read_text(encoding="utf-8").replace("{CONTRACT}", ""), encoding="utf-8")
    with pytest.raises(ValueError, match="CONTRACT"):
        _prompt(reg, store, "C0", cond_dir=str(cond))


# ============================================================ CLI


def _need_generation_python():
    py = E.orgene_python()
    if not os.path.exists(py):
        pytest.skip(f"generation interpreter {py} not present on this host")


def _cli(*args, timeout=300):
    return subprocess.run([sys.executable, CLI, *args], capture_output=True, text=True, timeout=timeout)


def _jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.mark.skipif(not os.path.exists(SMOKE_CASES), reason="data/cases/smoke.jsonl missing")
def test_cli_requests_builds_registry_requests(tmp_path):
    _need_generation_python()
    run = tmp_path / "20260101-toy-smoke-dev-E03"
    p = _cli("requests", "--run", str(run), "--cases", SMOKE_CASES, "--cond", "C0", "C2", "C3", "C3L", "C2E", "--limit", "2")
    assert p.returncode == 0, p.stderr
    req = {cid: _jsonl(run / f"requests.{cid}.jsonl") for cid in ("C0", "C2", "C3", "C3L", "C2E")}
    assert all(len(v) == 2 for v in req.values())
    for i in range(2):
        assert req["C3L"][i]["messages"] == req["C0"][i]["messages"]
        assert req["C2E"][i]["messages"] == req["C2"][i]["messages"]
    cfg = json.load(open(run / "run_config.json"))
    assert cfg["config_registry"] == {"path": "configs/r1_configs.json",
                                      "sha256": hashlib.sha256(open(REG_PATH, "rb").read()).hexdigest()}
    assert set(cfg["configs"]) == {"C0", "C2", "C3", "C3L", "C2E"}
    assert cfg["prompts"]["gene_store_path"] == "genes/genes.r1.jsonl"
    c3 = cfg["prompts"]["by_config"]["C3"]
    assert c3["n_requests"] == 2 and c3["activation"] == "per_problem" and len(c3["contract_sha256"]) == 1
    assert c3["gene_activation_rate"] and set(c3["gene_activation_rate"].values()) == {1.0}
    sp = json.load(open(run / "system_prompts.json"))
    for rows in req.values():
        for r in rows:
            assert sp["texts"][r["meta"]["system_prompt_sha256"]] == r["messages"][0]["content"]
    # a second call adds configurations to the same run
    p = _cli("requests", "--run", str(run), "--cases", SMOKE_CASES, "--cond", "C3E", "--limit", "2")
    assert p.returncode == 0, p.stderr
    cfg = json.load(open(run / "run_config.json"))
    assert set(cfg["configs"]) == {"C0", "C2", "C3", "C3L", "C2E", "C3E"}
    assert set(cfg["prompts"]["by_config"]) == set(cfg["configs"])
    assert set(json.load(open(run / "system_prompts.json"))["by_config"]) == set(cfg["configs"])
    # ... but not with another registry
    other = tmp_path / "other_configs.json"
    obj = _raw()
    obj["note"] = "changed"
    other.write_text(json.dumps(obj), encoding="utf-8")
    p = _cli("requests", "--run", str(run), "--cases", SMOKE_CASES, "--cond", "C3E", "--configs", str(other))
    assert p.returncode != 0 and "another configuration registry" in p.stderr
    # ... nor with another template directory, other template texts or another C1 tolerance
    cond2 = tmp_path / "conditions"
    shutil.copytree(COND, cond2)
    p = _cli("requests", "--run", str(run), "--cases", SMOKE_CASES, "--cond", "C3E", "--cond-dir", str(cond2))
    assert p.returncode != 0 and "another prompt template directory" in p.stderr, p.stderr
    p = _cli("requests", "--run", str(run), "--cases", SMOKE_CASES, "--cond", "C3E", "--tolerance", "0.1")
    assert p.returncode != 0 and "another C1 length tolerance" in p.stderr, p.stderr
    run2 = tmp_path / "20260101-toy-smoke-dev-E03b"
    p = _cli("requests", "--run", str(run2), "--cases", SMOKE_CASES, "--cond", "C0", "--limit", "1", "--cond-dir", str(cond2))
    assert p.returncode == 0, p.stderr
    with open(cond2 / "C0_direct.md", "a", encoding="utf-8") as f:
        f.write("\nReturn nothing else.\n")
    p = _cli("requests", "--run", str(run2), "--cases", SMOKE_CASES, "--cond", "C3L", "--limit", "1", "--cond-dir", str(cond2))
    assert p.returncode != 0 and "another set of prompt templates" in p.stderr, p.stderr
    assert not (run2 / "requests.C3L.jsonl").exists()
    hits = []
    for dirpath, _, files in os.walk(run):
        for fn in files:
            text = open(os.path.join(dirpath, fn), encoding="utf-8").read()
            hits += PA.find_absolute_paths(text)
            assert str(tmp_path) not in text, fn
    assert not hits, hits


@pytest.mark.skipif(not os.path.exists(SMOKE_CASES), reason="data/cases/smoke.jsonl missing")
def test_cli_requests_rejects_unknown_adapter_and_ora_configs(tmp_path):
    for cid, fragment in (("C9", "unknown configuration"), ("AOPT", "adapter baseline"), ("ORA", "stage prompts")):
        run = tmp_path / f"run-{cid}"
        p = _cli("requests", "--run", str(run), "--cases", SMOKE_CASES, "--cond", "C0", cid)
        assert p.returncode != 0 and fragment in p.stderr, (cid, p.stderr)
        assert not run.exists(), cid


@pytest.mark.skipif(not os.path.exists(SMOKE_CASES), reason="data/cases/smoke.jsonl missing")
def test_cli_validate_refuses_configs_outside_the_batch_path(tmp_path):
    for cid, fragment in (("ORA", "unit executor"), ("AOPT", "adapter baseline")):
        p = _cli("validate", "--run", str(tmp_path), "--cases", SMOKE_CASES, "--cond", cid)
        assert p.returncode != 0 and fragment in p.stderr, (cid, p.stderr)


def _fake_validate_round(monkeypatch, extra=None):
    """Replace pipeline.validate_round (E05 signature: gene_scope, repair, closing; E06 adds activation and
    inapplicable) by a recorder. `extra` (a list) receives (cond, activation, inapplicable) per call."""
    from orgene import pipeline as P
    calls = []

    def fake(run, cond, rnd, gen_dir, cases, genes, timeout=60, act=True, max_rounds=2, python=None,
             gene_scope=None, repair=None, closing=None, activation=None, inapplicable=()):
        calls.append((cond, act, max_rounds, gene_scope, repair, closing))
        if extra is not None:
            extra.append((cond, activation, list(inapplicable)))
        return {}
    monkeypatch.setattr(P, "validate_round", fake)
    monkeypatch.setattr(E, "require_env", lambda python=None: {})
    return calls


def _validate(tmp_path, cid, *extra):
    from orgene import cli as CLI_MOD
    CLI_MOD.main(["validate", "--run", str(tmp_path), "--cases", SMOKE_CASES, "--cond", cid, *extra])


@pytest.mark.skipif(not os.path.exists(SMOKE_CASES), reason="data/cases/smoke.jsonl missing")
def test_cli_validate_takes_repair_and_rounds_from_the_registry(monkeypatch, tmp_path, capsys):
    """validate: whether to repair and the default max_rounds come from the registry, not from the configuration name."""
    from orgene import cli as CLI_MOD
    calls = _fake_validate_round(monkeypatch)
    for cid, extra, want in (("C3", [], (True, 2)), ("C3L", [], (True, 2)), ("C3E", [], (True, 2)),
                             ("C0", [], (False, 0)), ("C1", [], (False, 0)), ("C2", [], (False, 0)),
                             ("C3", ["--max-rounds", "1"], (True, 1)), ("C3L", ["--no-repair"], (False, 2))):
        calls.clear()
        CLI_MOD.main(["validate", "--run", str(tmp_path), "--cases", SMOKE_CASES, "--cond", cid, *extra])
        assert [x[:3] for x in calls] == [(cid, *want)], (cid, extra, calls)
    # the values follow the registry file: change max_rounds there and validate follows
    obj = _raw()
    _cfg(obj, "C3")["max_rounds"] = 1
    _cfg(obj, "C3E")["max_rounds"] = 3
    other = tmp_path / "rounds.json"
    other.write_text(json.dumps(obj), encoding="utf-8")
    for cid, want in (("C3", (True, 1)), ("C3E", (True, 3)), ("C3L", (True, 2))):
        calls.clear()
        CLI_MOD.main(["validate", "--run", str(tmp_path), "--cases", SMOKE_CASES, "--cond", cid, "--configs", str(other)])
        assert [x[:3] for x in calls] == [(cid, *want)], (cid, calls)
    capsys.readouterr()


@pytest.mark.skipif(not os.path.exists(SMOKE_CASES), reason="data/cases/smoke.jsonl missing")
def test_cli_validate_scope_repair_and_closing_come_from_the_registry(monkeypatch, tmp_path, capsys):
    """validate passes the registry's gene_scope, repair and closing to validate_round (E05), so configurations whose
    scope has another name (C2E, C3L-ALL) are served by the batch path like the others."""
    extra = []
    new = _fake_validate_round(monkeypatch, extra)
    for cid, want in (("C3", ("C3", "gene", "spec_and_program")), ("C3L", ("C3L", "gene", "program")),
                      ("C3E", ("C3E", "generic", "program")), ("C2E", ("C3E", "generic", "spec_and_program")),
                      ("C3L-ALL", ("C3L", "gene", "program"))):
        new.clear()
        _validate(tmp_path, cid)
        assert new == [(cid, True, 2, *want)], (cid, new)
    # observe-only (E06): every gene of scope C3 is run and recorded, never repaired; for an answer that was not asked
    # for a spec (C0, C1) the four spec genes are recorded as not applicable, for C2 every gene applies
    spec_genes = ["orgene.artifact.spec_present", "orgene.constraints.implemented", "orgene.objective.sense_consistent",
                  "orgene.variables.domain_consistent"]
    for cid, na in (("C0", spec_genes), ("C1", spec_genes), ("C2", [])):
        new.clear()
        extra.clear()
        _validate(tmp_path, cid)
        assert new == [(cid, False, 0, "C3", None, None)], (cid, new)
        assert extra == [(cid, "all", na)], (cid, extra)
    with pytest.raises(SystemExit, match="unit executor"):
        _validate(tmp_path, "ORA")
    # genes whose activation depends on the problem: refused on the batch path, for their own scope only;
    # an explicit rule "always" does not depend on the problem
    real_load = G.load_store

    def with_rule(rule):
        def load(path):
            s = real_load(path)
            for g in s:
                if g["geneId"] == "orgene.numeric.bigm_bounded":  # scopes C3, C3L
                    g["activation"] = {"rule": rule}
            return s
        return load
    monkeypatch.setattr(G, "load_store", with_rule({"feature": "numeric_literal_count", "op": ">=", "value": 3}))
    for cid in ("C3", "C3L"):
        with pytest.raises(SystemExit, match="per-problem activation rules"):
            _validate(tmp_path, cid)
    # activation "all" ignores the rules (C3L-ALL is the all-active ablation; C0 observes the whole C3 scope), and
    # C3E's scope has no ruled gene
    for cid in ("C3E", "C3L-ALL", "C0"):
        new.clear()
        _validate(tmp_path, cid)
        assert [c[0] for c in new] == [cid]
    monkeypatch.setattr(G, "load_store", with_rule("always"))
    new.clear()
    _validate(tmp_path, "C3L")
    assert [c[0] for c in new] == ["C3L"]
    capsys.readouterr()


@pytest.mark.skipif(not os.path.exists(SMOKE_CASES), reason="data/cases/smoke.jsonl missing")
def test_cli_validate_does_not_guess_from_the_pipeline_signature(monkeypatch, tmp_path, capsys):
    """The registry values reach validate_round whatever its signature looks like: a wrapped validate_round (a
    decorator or profiler exposing only *args/**kwargs) still serves C2E and C3L-ALL; the earlier signature probe
    refused them as 'activating by configuration id'."""
    from orgene import pipeline as P
    calls = []

    class Wrapped:
        def __call__(self, *args, **kwargs):
            calls.append((args[1], kwargs.get("gene_scope"), kwargs.get("repair"), kwargs.get("closing")))
            return {}
    monkeypatch.setattr(P, "validate_round", Wrapped())
    monkeypatch.setattr(E, "require_env", lambda python=None: {})
    for cid, want in (("C2E", ("C3E", "generic", "spec_and_program")), ("C3L-ALL", ("C3L", "gene", "program")),
                      ("C3E", ("C3E", "generic", "program"))):
        calls.clear()
        _validate(tmp_path, cid)
        assert calls == [(cid, *want)], (cid, calls)
    capsys.readouterr()


def test_build_requests_needs_features_for_every_case(reg, store):
    with pytest.raises(KeyError, match="toy-0002"):
        C.build_requests([CASE_A, CASE_B], CF.get_config(reg, "C3"), store, "run",
                         features_by_case={CASE_A["case_id"]: {"n_numbers": 4}}, cond_dir=COND)


def test_cli_configs_lists_and_checks_the_registry(tmp_path):
    p = _cli("configs")
    assert p.returncode == 0, p.stderr
    assert "| C3L-ALL | C0 | reuse:C0 |" in p.stdout and "adapter AOPT" in p.stdout
    assert hashlib.sha256(open(REG_PATH, "rb").read()).hexdigest() in p.stdout
    obj = _raw()
    _cfg(obj, "C2E")["round0"] = "reuse:C9"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(obj), encoding="utf-8")
    p = _cli("configs", "--configs", str(bad))
    assert p.returncode == 1 and "INVALID" in p.stderr and "'C9'" in p.stderr


class _CapturingOpenAI(BaseHTTPRequestHandler):
    bodies = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        type(self).bodies.append(body)
        out = {"id": "mock-1", "model": body["model"],
               "choices": [{"message": {"content": "```python\n" + GOOD_CODE + "```"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 20}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.mark.skipif(not os.path.exists(SMOKE_CASES), reason="data/cases/smoke.jsonl missing")
def test_model_receives_only_the_two_messages(tmp_path):
    """What reaches the model endpoint: the request's [system, user] messages and nothing from meta or the ids."""
    _need_generation_python()
    run = tmp_path / "20260101-toy-smoke-dev-payload"
    p = _cli("requests", "--run", str(run), "--cases", SMOKE_CASES, "--cond", "C3", "C3L", "--limit", "1")
    assert p.returncode == 0, p.stderr
    _CapturingOpenAI.bodies = []
    srv = HTTPServer(("127.0.0.1", 0), _CapturingOpenAI)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        for cid in ("C3", "C3L"):
            g = subprocess.run([sys.executable, os.path.join(RUNTIME, "api_runner.py"), "--backend", "compat",
                                "--base-url", f"http://127.0.0.1:{srv.server_address[1]}/v1", "--api-key-env", "MOCK_KEY",
                                "--model", "mock-model", "--requests", str(run / f"requests.{cid}.jsonl"),
                                "--out", str(run / f"gen.{cid}.r0")],
                               capture_output=True, text=True, env=dict(os.environ, MOCK_KEY="x"), timeout=120)
            assert g.returncode == 0, g.stderr
    finally:
        srv.shutdown()
    bodies = _CapturingOpenAI.bodies
    assert len(bodies) == 2
    for body, cid in zip(bodies, ("C3", "C3L")):
        r = _jsonl(run / f"requests.{cid}.jsonl")[0]
        assert body["messages"] == r["messages"]
        assert "meta" not in body and "request_id" not in body and "case_id" not in body
        blob = json.dumps(body)
        for s in (r["request_id"], r["case_id"], r["meta"]["run_id"], r["meta"]["system_prompt_sha256"]):
            assert s not in blob, s
