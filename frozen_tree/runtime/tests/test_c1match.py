"""E11: C1 token matching (dev mean of the per-case C3 prompts), C1-api rule, rewrites, generic-entry wording check.

Fixtures are self-made: toy templates, a synthetic gene library, toy cases with toy ids in a toy split, and fake
counters (words, characters). Real case ids appear only as ids (the dev set, one test id for the refusal); the
end-to-end `c1-match` test reads the real dev cases (dev only) and prints nothing but counts.
"""
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import c1match as M  # noqa: E402
from orgene import cli  # noqa: E402
from orgene import conditions as C  # noqa: E402
from orgene import configs as CF  # noqa: E402
from orgene import env as E  # noqa: E402
from orgene import features as F  # noqa: E402
from orgene import genes as G  # noqa: E402
from orgene import split as S  # noqa: E402

GENES = os.path.join(ROOT, "genes", "genes.r1.jsonl")
R1_COND = os.path.join(ROOT, "conditions")  # the working templates; their C1 pool is the R1 pool since 2026-10-05
V5_POOL = os.path.join(HERE, "fixtures", "C1_generic_expert_pool.v5.md")


def _v5_cond():
    """conditions/ as it stood before the R1 C1 pool: the same templates, rewrites and drafts with the v5 pool. The
    tests of this module that describe the v5 pool (character rule, the bullets with gene wording, the drafted
    replacements and rewrites) run on this copy."""
    cond = os.path.join(tempfile.mkdtemp(prefix="orgene_c1_v5_"), "conditions")
    shutil.copytree(R1_COND, cond)
    shutil.copy(V5_POOL, os.path.join(cond, "C1_generic_expert_pool.md"))
    return cond


COND = _v5_cond()
RELEASE = os.path.join(ROOT, "releases", "v1.0")
SMOKE_CASES = os.path.join(ROOT, "data", "cases", "smoke.jsonl")
CANDIDATES = os.path.join(COND, "drafts", "C1_pool_candidates.draft.md")
DRAFT_POOL = os.path.join(COND, "drafts", "C1_pool_r1.draft.md")
V5_C1_SHA256 = "94c42eedc7d68ca374c204e82310dbbb728131cc7dfb0506024022cd1c853f69"
V5_CONTRACT_SHA256 = "055f9ab4a7afd87efee79959688c9568899704acab9f1a8787587e2142607102"
# the v5 bullets that hit the keyword table of the working library (replaced in C1_pool_r1.draft.md)
V5_GENE_WORDED = (2, 3, 5, 12, 13, 27, 28, 32)
LEX = F.load_lexicon()


def draft_cond(tmp_path, name="cond_r1"):
    """A copy of conditions/ whose C1 pool is the proposed R1 pool (conditions/drafts/C1_pool_r1.draft.md)."""
    cond = os.path.join(str(tmp_path), name)
    shutil.copytree(COND, cond, ignore=shutil.ignore_patterns("variants", "drafts"))
    shutil.copy(DRAFT_POOL, os.path.join(cond, "C1_generic_expert_pool.md"))
    return cond


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FakeCounter:
    """A deterministic stand-in for a tokcount counter: words or characters (/ divisor)."""

    def __init__(self, kind="words", divisor=1):
        self.kind, self.divisor = kind, divisor
        self._identity = {"backend": "fake", "kind": kind, "divisor": divisor}
        self.identity_sha256 = _sha(json.dumps(self._identity, sort_keys=True))
        self.n_calls = 0

    def identity(self):
        return dict(self._identity)

    def count(self, text):
        self.n_calls += 1
        n = len(text.split()) if self.kind == "words" else len(text)
        return n // self.divisor if self.divisor > 1 else n

    def counts(self, texts):
        return [self.count(t) for t in texts]


# ------------------------------------------------------------------ toy world: templates, library, split, cases


def write(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def toy_templates(cond, n_bullets=30, bullet_words=4, header_words=6, c3_extra="", word="step"):
    write(os.path.join(cond, "base_system.md"), "Solve the toy problem with a program.\nPrint the answer last.\n")
    write(os.path.join(cond, "spec_schema_summary.md"), '{"fields": "toy"}\n')
    write(os.path.join(cond, "C0_direct.md"), "Return only the program.\n")
    write(os.path.join(cond, "C2_schema_only.md"), "Give a spec first:\n{SPEC_SCHEMA_SUMMARY}\n")
    write(os.path.join(cond, "C3_orgene.md"), "Give a spec first:\n{SPEC_SCHEMA_SUMMARY}\n" + c3_extra + "\n{CONTRACT}\n")
    header = " ".join(["Header"] * header_words)
    bullets = [f"- {word}{i} " + " ".join([word] * (bullet_words - 1)) for i in range(1, n_bullets + 1)]
    write(os.path.join(cond, "C1_generic_expert_pool.md"),
          header + "\n\n<!-- toy pool -->\n" + "\n".join(bullets) + "\n")
    return cond


def syn_gene(i, n_words, rule=None, scope=("C3", "C3L"), token="alpha"):
    g = {"schemaVersion": G.SCHEMA_VERSION, "geneId": f"toy.rule.g{i}", "version": "1.0.0",
         "lifecycle": {"state": "active", "createdAt": "2026-09-29", "supersedes": []},
         "scope": {"task": "lp_milp_modeling", "conditions": list(scope)},
         "preference": {"statement": f"Toy preference {i}.", "rationale": "Toy rationale.", "priority": 100 - i},
         "contract": {"required": [" ".join([token] * n_words)], "forbidden": [], "checks": []},
         "targets": ["code"],
         "validation": {"mode": "executable", "predicateId": "predicate.code_present.v1", "params": {},
                        "severity": "hard", "phase": "pre_exec"},
         "repair": {"instruction": "Toy repair.", "maxApplications": 1, "safetyClass": "structural_safe"},
         "audit": {"source": "self-made test gene"}}
    if rule is not None:
        g["activation"] = {"rule": rule, "rationale": "toy"}
    return g


def syn_library(tmp_path, token="alpha"):
    genes = [syn_gene(1, 40, token=token),
             syn_gene(2, 30, rule={"feature": "binary_terms", "op": "==", "value": True}, token=token),
             syn_gene(3, 20, rule={"feature": "word_count", "op": ">=", "value": 12}, token=token),
             syn_gene(4, 5, scope=("C3", "C3L", "C3E"), token=token)]
    path = os.path.join(str(tmp_path), "genes.toy.jsonl")
    write(path, "".join(json.dumps(g) + "\n" for g in genes))
    return path, G.load_store(path)


DEV_TEXTS = {
    "toy-0001": "Make chairs and tables for profit.",
    "toy-0002": "Choose yes or no for each of four projects to maximise value within a budget.",
    "toy-0003": "Plan shipments from two plants to three shops at least cost this week, meeting every demand.",
    "toy-0004": "Pick projects, yes or no.",
    "toy-0005": "Schedule nurses over seven days so that each day is covered by enough staff members at least cost.",
}
TEST_TEXTS = {"toy-0101": "A sealed toy problem.", "toy-0102": "Another sealed toy problem."}


def toy_split(tmp_path, cases_text=None):
    """data/splits/toy/ with dev = DEV_TEXTS ids, test = TEST_TEXTS ids; a cases file whose test lines are not JSON
    (so parsing one of them would fail)."""
    root = os.path.join(str(tmp_path), "splits")
    d = os.path.join(root, "toy")
    dev, test = sorted(DEV_TEXTS), sorted(TEST_TEXTS)
    cases = os.path.join(str(tmp_path), "toy_cases.jsonl")
    lines = [json.dumps({"_header": True, "source": "toy"})]
    lines += [json.dumps({"case_id": c, "source": "toy", "text": DEV_TEXTS[c]}) for c in dev]
    lines += ['{"case_id": "%s", "source": "toy", "text": NOT JSON -- never parsed' % c for c in test]
    write(cases, cases_text if cases_text is not None else "\n".join(lines) + "\n")
    lock = {"cases_path": "toy_cases.jsonl", "n_dev": len(dev), "n_test": len(test),
            "dev_sha256": S.ids_sha256(dev), "test_sha256": S.ids_sha256(test)}
    write(os.path.join(d, "SPLIT_LOCK.json"), json.dumps(lock))
    write(os.path.join(d, "dev_ids.json"), json.dumps(dev))
    write(os.path.join(d, "test_ids.json"), json.dumps(test))
    return root, cases


def toy_dev_cases(ids=None):
    return [{"case_id": c, "source": "toy", "text": DEV_TEXTS[c]} for c in (ids or sorted(DEV_TEXTS))]


def toy_dev_info(cases):
    ids = sorted(c["case_id"] for c in cases)
    return {"name": "toy_dev", "n": len(ids), "sha256": S.ids_sha256(ids), "by_benchmark": {"toy": len(ids)}}


@pytest.fixture(scope="module")
def reg():
    return CF.load_registry()


@pytest.fixture(scope="module")
def store():
    return G.load_store(GENES)


def c3_cfg(reg):
    return CF.get_config(reg, "C3")


def feats_of(cases):
    return {c["case_id"]: F.extract_features(c["text"], LEX) for c in cases}


# ------------------------------------------------------------------ v5 regression (match_mode="chars")


def test_chars_mode_reproduces_the_v5_c1_on_the_working_library(store):
    T = C.load_templates(COND)
    text, info = M.match_c1(T, store, match_mode="chars")
    assert _sha(text) == V5_C1_SHA256
    assert info["measure"] == "chars" and info["select"] == "greedy" and info["ratio"] == 1.0101
    assert info["bullets_used"] == 47
    # the registry builder's default C1 is this one, and the v1 builder agrees
    prompts_v1, _ = C.build_system_prompts_v1(COND, GENES)
    assert prompts_v1["C1"] == text


@pytest.mark.skipif(not os.path.exists(os.path.join(RELEASE, "genes.v3.jsonl")),
                    reason="releases/v1.0 is not in the anonymous repository (v5 originals)")
def test_chars_mode_reproduces_the_v5_c1_sha_on_release_1_0():
    store_v1 = G.load_store(os.path.join(RELEASE, "genes.v3.jsonl"))
    T = C.load_templates(os.path.join(RELEASE, "conditions"))
    text, info = M.match_c1(T, store_v1, match_mode="chars")
    assert _sha(text) == V5_C1_SHA256 and info["ok"]
    # the contract with the default frame is v5's
    active, _, _ = C.activate_for(store_v1, "C3", "all")
    assert G.compile_contract(active)[1]["contract_sha256"] == V5_CONTRACT_SHA256


def test_v5_pool_constant_covers_the_working_pool():
    _, bullets = C.c1_parts(C.load_templates(COND))
    assert len(bullets) == len(M.V5_POOL_BULLETS) == 47
    assert {M.bullet_key(b) for b in bullets} == set(M.V5_POOL_BULLETS)


# ------------------------------------------------------------------ token matching on a synthetic library


def test_token_matching_on_a_synthetic_library_lands_within_tolerance(tmp_path, reg):
    cond = toy_templates(os.path.join(str(tmp_path), "cond"), n_bullets=100, bullet_words=2)
    _, store = syn_library(tmp_path)
    split_root, _ = toy_split(tmp_path)
    T = C.load_templates(cond)
    cases = toy_dev_cases()
    feats = feats_of(cases)
    m = M.TokenMeasure(FakeCounter("words"), "qwen")
    text, info = M.match_c1(T, store, "tokens", measure=m, dev_cases=cases, features_by_case=feats,
                            c3_config=c3_cfg(reg), split_root=split_root)
    # the target is the mean over the dev cases of each case's own C3 prompt (per-problem activation)
    per_case = [len(C.build_prompt(c3_cfg(reg), c, store, features=feats[c["case_id"]], templates=T)[0].split())
                for c in cases]
    assert len(set(per_case)) >= 3, "the synthetic rules must make the C3 prompts differ between cases"
    assert info["target"] == pytest.approx(sum(per_case) / len(per_case))
    assert 0.95 <= len(text.split()) / info["target"] <= 1.05 and info["ok"]
    assert info["measure"] == "tokens:qwen" and 0 < info["bullets_used"] < 100
    assert text == C.c1_text(T, info["bullets_used"])
    # of the in-band prefixes the one closest to the target (v5's greedy rule would stop near the upper edge)
    lengths = [len(C.c1_text(T, k).split()) for k in range(101)]
    band = [k for k in range(101) if 0.95 <= lengths[k] / info["target"] <= 1.05]
    assert info["select"] == "closest" and len(band) >= 3
    assert info["bullets_used"] == min(band, key=lambda k: (abs(lengths[k] / info["target"] - 1), k))
    greedy = C._prompt_c1(T, info["target"], 0.05, measure=m, select="greedy")[1]
    assert greedy["bullets_used"] == max(band) > info["bullets_used"] and greedy["ratio"] > info["ratio"]
    # the all-active C3 is at least as long as every per-case prompt and longer than most, so the two ratios differ
    all_active = len(C.c3_all_active_prompt(T, store).split())
    assert all_active == max(per_case) > min(per_case)


def test_report_gives_ratios_and_the_per_case_distribution(tmp_path, reg):
    cond = toy_templates(os.path.join(str(tmp_path), "cond"), n_bullets=60, bullet_words=4)
    gpath, store = syn_library(tmp_path)
    split_root, _ = toy_split(tmp_path)
    cases = toy_dev_cases()
    rep = M.build_report(store, gpath, reg, cases, toy_dev_info(cases), LEX,
                         {"qwen": M.TokenMeasure(FakeCounter("words"), "qwen"), "api": None},
                         cond_dir=cond, variants=[], split_root=split_root)
    assert rep["ok"] and rep["schema"] == M.REPORT_SCHEMA and list(rep["variants"]) == ["base"]
    v = rep["variants"]["base"]
    q = v["tokenizers"]["qwen"]
    assert v["c3_dev"]["n_cases"] == 5 and v["c3_dev"]["n_distinct_prompts"] >= 3
    assert 0.95 <= q["ratio_to_dev_mean"] <= 1.05 and q["ratio_all_active"] < q["ratio_to_dev_mean"]
    d = q["per_case_ratio"]
    assert d["n"] == 5 and d["min"] < d["median"] < d["max"] and set(q["per_case_ratio_by_case"]) == set(DEV_TEXTS)
    assert rep["inputs"]["gene_library"]["sha256"] == hashlib.sha256(open(gpath, "rb").read()).hexdigest()
    assert rep["inputs"]["c3_config"] == c3_cfg(reg) and rep["inputs"]["lexicon"]["sha256"] == LEX.sha256
    assert v["templates"]["C1"]["sha256"] == _sha(open(os.path.join(cond, "C1_generic_expert_pool.md")).read())
    assert rep["tokenizers"]["api"] is None and rep["gene_keyword_table"]["sha256"]
    # nothing but ids, counts, ratios and hashes: no dev problem text is written into the report
    blob = json.dumps(rep)
    assert not any(t in blob for t in DEV_TEXTS.values())


def test_report_refuses_cases_that_are_not_the_named_dev_set(tmp_path, reg):
    cond = toy_templates(os.path.join(str(tmp_path), "cond"))
    gpath, store = syn_library(tmp_path)
    split_root, _ = toy_split(tmp_path)
    cases = toy_dev_cases()
    info = toy_dev_info(cases[:3])
    with pytest.raises(M.C1MatchError, match="not the dev set"):
        M.build_report(store, gpath, reg, cases, info, LEX, {"qwen": M.TokenMeasure(FakeCounter(), "qwen"), "api": None},
                       cond_dir=cond, variants=[], split_root=split_root)


# ------------------------------------------------------------------ errors instead of warnings


def test_a_pool_that_is_too_short_raises(tmp_path, reg):
    cond = toy_templates(os.path.join(str(tmp_path), "cond"), n_bullets=2, bullet_words=4)
    gpath, store = syn_library(tmp_path)
    split_root, _ = toy_split(tmp_path)
    T = C.load_templates(cond)
    cases = toy_dev_cases()
    m = M.TokenMeasure(FakeCounter("words"), "qwen")
    with pytest.raises(C.C1MatchError, match="pool is too short"):
        M.match_c1(T, store, "tokens", measure=m, dev_cases=cases, features_by_case=feats_of(cases),
                   c3_config=c3_cfg(reg), split_root=split_root)
    # the report records the failure (so that 1C sees the shortfall) and is not ok
    rep = M.build_report(store, gpath, reg, cases, toy_dev_info(cases), LEX, {"qwen": m, "api": None},
                         cond_dir=cond, variants=[], split_root=split_root)
    q = rep["variants"]["base"]["tokenizers"]["qwen"]
    assert rep["ok"] is False and q["c1"]["ok"] is False and q["c1"]["tokens_short_of_band"] > 0
    assert "pool is too short" in rep["variants"]["base"]["errors"][0]
    # the registry builder raises too (the v5 WARNING is gone): chars against the all-active C3
    with pytest.raises(C.C1MatchError, match="pool is too short"):
        C.build_prompt(CF.get_config(CF.load_registry(), "C1"), cases[0], store, templates=T)


def test_a_header_that_alone_overshoots_raises(tmp_path):
    cond = toy_templates(os.path.join(str(tmp_path), "cond"), header_words=400)
    T = C.load_templates(cond)
    with pytest.raises(C.C1MatchError, match="header alone"):
        C._prompt_c1(T, 100, 0.05, measure=lambda t: len(t.split()))


def test_a_measure_needs_its_target(tmp_path, reg, store):
    m = M.TokenMeasure(FakeCounter(), "qwen")
    case = {"case_id": "toy-0001", "source": "toy", "text": DEV_TEXTS["toy-0001"]}
    with pytest.raises(ValueError, match="needs its target"):
        C.build_prompt(CF.get_config(reg, "C1"), case, store, cond_dir=COND, c1_measure=m)
    with pytest.raises(ValueError, match="needs its target"):
        C.build_requests([case], CF.get_config(reg, "C1"), store, "run", cond_dir=COND, c1_measure=m)


# ------------------------------------------------------------------ dev cases only


def test_test_ids_are_refused(tmp_path, reg):
    split_root, cases_path = toy_split(tmp_path)
    assert M.assert_dev_ids(sorted(DEV_TEXTS), split_root) == sorted(DEV_TEXTS)
    for bad in (["toy-0001", "toy-0101"], ["toy-0102"], ["toy-9999"], []):
        with pytest.raises(M.DevOnlyError):
            M.assert_dev_ids(bad, split_root)
    # the matching itself refuses a test case, before anything is measured
    cond = toy_templates(os.path.join(str(tmp_path), "cond"))
    _, store = syn_library(tmp_path)
    counter = FakeCounter()
    sealed = toy_dev_cases()[:2] + [{"case_id": "toy-0101", "source": "toy", "text": "made-up text"}]
    with pytest.raises(M.DevOnlyError, match="not dev ids"):
        M.match_c1(C.load_templates(cond), store, "tokens", measure=M.TokenMeasure(counter, "qwen"),
                   dev_cases=sealed, features_by_case=feats_of(sealed), c3_config=c3_cfg(reg), split_root=split_root)
    assert counter.n_calls == 0
    # loading refuses a test id before reading the cases file
    with pytest.raises(M.DevOnlyError):
        M.load_dev_cases(["toy-0001", "toy-0101"], cases_paths=[os.path.join(str(tmp_path), "no_such_file")],
                         split_root=split_root)


def test_a_real_test_id_is_refused_and_real_dev_ids_pass():
    # ids only: nothing is read from the cases files
    test_id = json.load(open(os.path.join(ROOT, "data", "splits", "mamo_complex_lp", "test_ids.json")))[0]
    dev_ids = json.load(open(os.path.join(ROOT, "data", "splits", "industryor", "dev_ids.json")))
    assert M.assert_dev_ids(dev_ids) == sorted(dev_ids)
    with pytest.raises(M.DevOnlyError, match="test or held-out"):
        M.assert_dev_ids(dev_ids[:2] + [test_id])
    ids, info = M.dev_set_ids()
    assert info["n"] == len(ids) == 55 and info["by_benchmark"] == {"industryor": 25, "mamo_complex_lp": 30}
    assert M.assert_dev_ids(ids) == ids


def test_load_dev_cases_parses_only_the_wanted_lines(tmp_path):
    split_root, cases_path = toy_split(tmp_path)
    got = M.load_dev_cases(["toy-0003", "toy-0001"], cases_paths=[cases_path], split_root=split_root)
    assert [c["case_id"] for c in got] == ["toy-0001", "toy-0003"] and got[0]["text"] == DEV_TEXTS["toy-0001"]
    # (the test lines of the toy file are not JSON: they were never parsed) a dev id missing from the files is an error
    empty = write(os.path.join(str(tmp_path), "empty.jsonl"), "")
    with pytest.raises(M.DevOnlyError, match="not found"):
        M.load_dev_cases(["toy-0001"], cases_paths=[empty], split_root=split_root)
    # a line that does not start with its case id is not parsed either: loading stops
    bad = os.path.join(str(tmp_path), "bad.jsonl")
    write(bad, '{"source": "toy", "case_id": "toy-0001", "text": "x"}\n')
    with pytest.raises(ValueError, match="no case id at the start"):
        M.load_dev_cases(["toy-0001"], cases_paths=[bad], split_root=split_root)


# ------------------------------------------------------------------ second tokenizer and C1-api


def test_c1_api_is_built_by_the_written_rule_when_the_api_ratio_is_out_of_band(tmp_path, reg):
    # C1 bullets are long words, the contract short ones: matched in words, C1 is far too long in characters
    cond = toy_templates(os.path.join(str(tmp_path), "cond"), n_bullets=80, bullet_words=3, word="extraordinarily")
    gpath, store = syn_library(tmp_path, token="a")
    split_root, _ = toy_split(tmp_path)
    cases = toy_dev_cases()
    measures = {"qwen": M.TokenMeasure(FakeCounter("words"), "qwen"),
                "api": M.TokenMeasure(FakeCounter("chars", divisor=4), "api")}
    rep = M.build_report(store, gpath, reg, cases, toy_dev_info(cases), LEX, measures, cond_dir=cond, variants=[],
                         split_root=split_root)
    q, a = rep["variants"]["base"]["tokenizers"]["qwen"], rep["variants"]["base"]["tokenizers"]["api"]
    assert q["c1"]["ok"] and a["qwen_c1"]["ratio_to_dev_mean"] > 1.05 and a["c1_api_needed"] is True
    api = a["c1_api"]
    assert api["c1"]["ok"] and 0.95 <= api["ratio_to_dev_mean"] <= 1.05
    assert api["c1"]["bullets_used"] < q["c1"]["bullets_used"]
    # same rule, same header, same pool, same order: C1-api is a prefix of the same pool
    T = C.load_templates(cond)
    assert api["c1"]["sha256"] == _sha(C.c1_text(T, api["c1"]["bullets_used"]))
    assert api["qwen_tokens"] == len(C.c1_text(T, api["c1"]["bullets_used"]).split())
    assert rep["ok"] and rep["api_rule"] == M.API_RULE


def test_no_c1_api_when_the_api_ratio_is_in_band(tmp_path, reg):
    cond = toy_templates(os.path.join(str(tmp_path), "cond"), n_bullets=60)
    gpath, store = syn_library(tmp_path)
    split_root, _ = toy_split(tmp_path)
    cases = toy_dev_cases()
    measures = {"qwen": M.TokenMeasure(FakeCounter("words"), "qwen"),
                "api": M.TokenMeasure(FakeCounter("words"), "api")}
    rep = M.build_report(store, gpath, reg, cases, toy_dev_info(cases), LEX, measures, cond_dir=cond, variants=[],
                         split_root=split_root)
    a = rep["variants"]["base"]["tokenizers"]["api"]
    assert a["c1_api_needed"] is False and a["c1_api"] is None and rep["ok"]


# ------------------------------------------------------------------ rewrites: C1-v matched to C3-v


def _toy_variant(cond, name, c3_extra_words=60, frame=None):
    vdir = os.path.join(cond, "variants", name)
    base_pool = open(os.path.join(cond, "C1_generic_expert_pool.md"), encoding="utf-8").read()
    write(os.path.join(vdir, "C1_generic_expert_pool.md"), base_pool.replace("step", "stage"))
    write(os.path.join(vdir, "C3_orgene.md"), "First the spec:\n{SPEC_SCHEMA_SUMMARY}\n"
          + " ".join(["please"] * c3_extra_words) + "\n{CONTRACT}\n")
    if frame is not None:
        write(os.path.join(vdir, "C3_contract_frame.json"), json.dumps(frame))
    write(os.path.join(vdir, "README.md"), f"# {name}\n\nstatus: draft\n")
    return vdir


def test_each_rewrite_of_c1_is_matched_to_the_same_named_rewrite_of_c3(tmp_path, reg, monkeypatch):
    cond = toy_templates(os.path.join(str(tmp_path), "cond"), n_bullets=80, bullet_words=4)
    frame = {"heading": "## Toy contract of {n} rules", "required": "Do:", "forbidden": "Do not:", "checks": "Checked:"}
    _toy_variant(cond, "rwx", c3_extra_words=60, frame=frame)
    gpath, store = syn_library(tmp_path)
    split_root, _ = toy_split(tmp_path)
    cases = toy_dev_cases()
    feats = feats_of(cases)
    rep = M.build_report(store, gpath, reg, cases, toy_dev_info(cases), LEX,
                         {"qwen": M.TokenMeasure(FakeCounter("words"), "qwen"), "api": None}, cond_dir=cond,
                         split_root=split_root)
    assert list(rep["variants"]) == ["base", "rwx"] and rep["ok"], rep["variants"]["rwx"]["errors"]
    assert rep["variants"]["rwx"]["status"] == "draft" and rep["variants"]["base"]["status"] == "working"
    Tv = C.load_templates(cond, "rwx")
    assert Tv["contract_frame"] == frame and "contract_frame" in Tv["files"]
    c3v = [C.build_prompt(c3_cfg(reg), c, store, features=feats[c["case_id"]], templates=Tv, variant="rwx")[0]
           for c in cases]
    assert all("## Toy contract of" in t and "please" in t for t in c3v)
    qb, qv = (rep["variants"][k]["tokenizers"]["qwen"] for k in ("base", "rwx"))
    assert qv["target"] == pytest.approx(sum(len(t.split()) for t in c3v) / len(c3v))
    assert qv["target"] > qb["target"] + 50
    assert 0.95 <= qv["ratio_to_dev_mean"] <= 1.05 and qv["c1"]["bullets_used"] > qb["c1"]["bullets_used"]
    assert qv["c1"]["sha256"] == _sha(C.c1_text(Tv, qv["c1"]["bullets_used"]))
    # requests: a configuration with variant rwx gets the rwx C1 (replayed with the tokenizer, checked against the report)
    rpath = os.path.join(str(tmp_path), "report.json")
    M.write_report(rep, rpath)
    monkeypatch.setattr(M, "dev_set_ids", lambda name=None, root=None: (sorted(DEV_TEXTS), toy_dev_info(cases)))
    monkeypatch.setattr(M, "load_dev_cases", lambda ids, **kw: [c for c in cases if c["case_id"] in set(ids)])
    obj = json.load(open(CF.DEFAULT_REGISTRY))
    c1 = next(c for c in obj["configs"] if c["id"] == "C1")
    obj["configs"].append(dict(c1, id="C1-RWX", variant="rwx", label="toy rewrite"))
    reg2 = CF.parse_registry(obj)
    counter = FakeCounter("words")
    rc = M.RequestsC1(reg2, [reg2["configs"]["C1-RWX"], reg2["configs"]["C1"]], store, gpath, cond, 0.05, LEX.sha256,
                      report_path=rpath, make_counter=lambda which, **kw: counter)
    for cid, entry in (("C1-RWX", qv), ("C1", qb)):
        cfg = reg2["configs"][cid]
        reqs = C.build_requests(cases[:2], cfg, store, "run", cond_dir=cond, **rc.kwargs(cfg))
        summ = C.summarize_requests(reqs)
        rc.record(cfg, reqs, summ)
        assert reqs[0]["meta"]["system_prompt_sha256"] == entry["c1"]["sha256"]
        assert summ["system_prompt_tokens_local"]["mean"] == entry["c1"]["tokens"]
    assert set(rc.run_info()["by_config"]) == {"C1", "C1-RWX"}
    # the dev C3 prompts are rebuilt and compared by digest: other problem features (here other texts under the same
    # ids) activate other genes, so the target is stale although no recorded input file changed
    other = [dict(c, text="Pick yes or no for each project within a budget, twelve words or more here.") for c in cases]
    monkeypatch.setattr(M, "load_dev_cases", lambda ids, **kw: other)
    with pytest.raises(M.C1MatchError, match="C3 dev system prompts of variant 'rwx'"):
        M.RequestsC1(reg2, [reg2["configs"]["C1-RWX"]], store, gpath, cond, 0.05, LEX.sha256, report_path=rpath,
                     make_counter=lambda which, **kw: counter)


def test_a_rewrite_that_does_not_paraphrase_one_to_one_is_not_ok(tmp_path, reg):
    cond = toy_templates(os.path.join(str(tmp_path), "cond"), n_bullets=60)
    vdir = _toy_variant(cond, "rwy")
    pool = open(os.path.join(vdir, "C1_generic_expert_pool.md")).read()
    write(os.path.join(vdir, "C1_generic_expert_pool.md"), pool + "- stage extra entry\n")
    gpath, store = syn_library(tmp_path)
    split_root, _ = toy_split(tmp_path)
    cases = toy_dev_cases()
    rep = M.build_report(store, gpath, reg, cases, toy_dev_info(cases), LEX,
                         {"qwen": M.TokenMeasure(FakeCounter(), "qwen"), "api": None}, cond_dir=cond, split_root=split_root)
    assert rep["ok"] is False and any("one to one" in e for e in rep["variants"]["rwy"]["errors"])


# ------------------------------------------------------------------ generic entries only (gene wording)


def test_the_keyword_table_catches_gene_wording(store):
    table = M.gene_keyword_table(store, M.base_texts(COND))
    assert {"LpVariable.dicts", "lpSum", "cat="} <= set(table["code"]) and "big-m" in table["hyphen"]
    assert "tuple key indexing" in table["rule_names"]
    # nothing the shared base prompt already says is in the table
    assert "pulp.LpProblem" not in table["code"] and "FINAL_OBJECTIVE" not in table["code"]
    for g in store:
        assert M.wording_hits(g["preference"]["statement"], table), g["geneId"]
    for text in ("- Derive big-M constants from the data.", "- Use lpSum for every total.",
                 "- Read a tuple key indexing mapping carefully.", "- Never hard-code the result."):
        assert M.wording_hits(text, table), text
    assert M.wording_hits("- Read the statement twice before you start.", table) == []


def test_the_v5_bullets_with_gene_wording_are_refused_too(store):
    # C1 is generic expert guidance without gene content: the v5 bullets are not exempt
    table = M.gene_keyword_table(store, M.base_texts(COND))
    w = M.pool_wording(C.load_templates(COND), table)
    assert w["n_v5_bullets"] == 47
    assert [b["bullet"] for b in w["bullets_with_hits"]] == list(V5_GENE_WORDED)
    assert all(b["v5"] for b in w["bullets_with_hits"]) and len(w["errors"]) == len(V5_GENE_WORDED)
    assert "pool bullet 2 carries gene wording" in w["errors"][0]


def test_added_pool_entries_with_gene_wording_are_refused(tmp_path, store):
    cond = draft_cond(tmp_path)
    pool = os.path.join(cond, "C1_generic_expert_pool.md")
    table = M.gene_keyword_table(store, M.base_texts(cond))
    w = M.pool_wording(C.load_templates(cond), table)
    assert w["errors"] == [] and w["bullets_with_hits"] == [] and w["n_v5_bullets"] == 47 - len(V5_GENE_WORDED)
    with open(pool, "a", encoding="utf-8") as f:
        f.write("- Keep assumptions few and explicit.\n")
    assert M.pool_wording(C.load_templates(cond), table)["errors"] == []
    with open(pool, "a", encoding="utf-8") as f:
        f.write("- Derive big-M constants from the data (capacities, total demand) instead of arbitrary numbers.\n")
    errs = M.pool_wording(C.load_templates(cond), table)["errors"]
    assert len(errs) == 1 and "pool bullet 49" in errs[0] and "big-m" in errs[0]
    # a header line with gene wording is refused as well
    text = open(pool, encoding="utf-8").read().replace("Return the program.", "Return the program; never hard-code it.")
    with open(pool, "w", encoding="utf-8") as f:
        f.write(text)
    assert any("header" in e for e in M.pool_wording(C.load_templates(cond), table)["errors"])


def _libraries(store):
    libs = [store]
    if os.path.exists(os.path.join(RELEASE, "genes.v3.jsonl")):
        libs.append(G.load_store(os.path.join(RELEASE, "genes.v3.jsonl")))
    return libs


def _with_pool(T, text):
    return dict(T, texts=dict(T["texts"], C1=text))


def test_the_proposed_r1_pool_replaces_exactly_the_gene_worded_v5_bullets(store):
    text = open(DRAFT_POOL, encoding="utf-8").read()
    assert "status: draft" in text.splitlines()[0]
    T = C.load_templates(COND)
    D = _with_pool(T, text)
    (h0, b0), (h1, b1) = C.c1_parts(T), C.c1_parts(D)
    assert h1 == h0 and len(b1) == len(b0) == 47
    changed = [i for i, (x, y) in enumerate(zip(b0, b1), 1) if x != y]
    assert changed == list(V5_GENE_WORDED)
    for i in changed:  # each replacement carries its record: the v5 text it replaces
        assert f"<!-- replaces v5 bullet {i}: '{b0[i - 1][2:]}'" in text
    for lib in _libraries(store):
        assert M.pool_wording(D, M.gene_keyword_table(lib, M.base_texts(COND)))["errors"] == []
    # the rewrites of the proposed pool: one to one, the same headers as the drafted rewrites, no gene wording
    for v in ("rw1", "rw2"):
        path = os.path.join(COND, "drafts", f"C1_pool_r1.{v}.draft.md")
        vt = open(path, encoding="utf-8").read()
        assert "status: draft" in vt.splitlines()[0]
        Tv = C.load_templates(COND, v)
        Dv = _with_pool(Tv, vt)
        (hv0, bv0), (hv1, bv1) = C.c1_parts(Tv), C.c1_parts(Dv)
        assert hv1 == hv0 and len(bv1) == 47
        assert [i for i, (x, y) in enumerate(zip(bv0, bv1), 1) if x != y] == list(V5_GENE_WORDED)
        for lib in _libraries(store):
            assert M.pool_wording(Dv, M.gene_keyword_table(lib, M.base_texts(COND)), D)["errors"] == [], v


def _real_qwen():
    from orgene import tokcount as TC
    try:
        m = TC.resolve_ollama_model("qwen3:8b")
    except TC.TokenizerError:
        return None
    binary = os.environ.get(TC.ENV_LLAMA_TOKENIZE) or TC.DEFAULT_LLAMA_TOKENIZE
    if not os.access(binary, os.X_OK) or m["weights_sha256"] != TC.QWEN3_WEIGHTS_SHA256:
        return None
    return TC.OllamaCounter("qwen3:8b", expect_weights_sha256=TC.QWEN3_WEIGHTS_SHA256)


def test_the_replaced_bullets_keep_their_length_in_qwen_tokens():
    counter = _real_qwen()
    if counter is None:
        pytest.skip("llama-tokenize or the qwen3:8b blob is not on this machine")
    b0 = C.c1_parts(C.load_templates(COND))[1]
    b1 = C.c1_parts(_with_pool(C.load_templates(COND), open(DRAFT_POOL, encoding="utf-8").read()))[1]
    for i in V5_GENE_WORDED:
        n0, n1 = counter.count(b0[i - 1]), counter.count(b1[i - 1])
        assert abs(n1 / n0 - 1) <= 0.10, (i, n0, n1)


def test_candidate_entries_are_generic_and_marked_draft(store):
    lines = open(CANDIDATES, encoding="utf-8").read().splitlines()
    assert "status: draft" in lines[0]
    entries = M.candidate_entries(CANDIDATES)
    assert len(entries) >= 25 and len(set(entries)) == len(entries)
    assert not {M.bullet_key(e) for e in entries} & M.V5_POOL_BULLETS
    for lib in _libraries(store):
        table = M.gene_keyword_table(lib, M.base_texts(COND))
        hits = {i: M.wording_hits(e, table) for i, e in enumerate(entries, 1)}
        assert {i: h for i, h in hits.items() if h} == {}
    # appended to the proposed R1 pool they pass the pool check
    pool = open(DRAFT_POOL, encoding="utf-8").read()
    T2 = _with_pool(C.load_templates(COND), pool.rstrip("\n") + "\n" + "\n".join(entries) + "\n")
    w = M.pool_wording(T2, M.gene_keyword_table(store, M.base_texts(COND)))
    assert w["errors"] == [] and w["n_bullets"] == 47 + len(entries)
    # no candidate says anything about the benchmark instances
    assert not any("instances" in e for e in entries)


# ------------------------------------------------------------------ the drafted rewrites rw1, rw2


PROTOCOL = ("```python", "`pulp`", "`pulp.LpProblem`", "`prob.solve(pulp.PULP_CBC_CMD(msg=0))`",
            "STATUS: <pulp.LpStatus[prob.status]>\nFINAL_OBJECTIVE: <pulp.value(prob.objective) as a plain number>")


@pytest.mark.parametrize("v", ["rw1", "rw2"])
def test_drafted_rewrites_keep_the_protocol_and_add_no_gene_wording(v, reg, store):
    assert v in M.variant_names(COND) and M.variant_status(COND, v) == "draft"
    base = C.load_templates(COND)  # the v5 pool, which the rewrites paraphrase one to one
    T = C.load_templates(R1_COND, v)  # the rewrite files themselves (paths inside the repository)
    assert set(T["files"]) == set(base["files"]) | {"contract_frame"}
    for k in ("base", "C0", "C1", "C3"):
        assert T["files"][k]["path"].startswith(f"conditions/variants/{v}/") and T["texts"][k] != base["texts"][k], k
    for k in ("schema_summary", "C2"):
        assert T["texts"][k] == base["texts"][k], k
    for lit in PROTOCOL:
        assert lit in T["texts"]["base"], lit
    lines = T["texts"]["base"].splitlines()
    i = lines.index("STATUS: <pulp.LpStatus[prob.status]>")
    assert lines[i + 1] == "FINAL_OBJECTIVE: <pulp.value(prob.objective) as a plain number>"
    assert "```json" in T["texts"]["C3"] and T["texts"]["C3"].count("{CONTRACT}") == 1
    # one-to-one paraphrase of the working pool; gene wording only where the working pool has it (the v5 bullets
    # that C1_pool_r1.draft.md replaces, with their rewrites in C1_pool_r1.<v>.draft.md)
    table = M.gene_keyword_table(store, M.base_texts(COND))
    w = M.pool_wording(T, table, base)
    assert w["n_bullets"] == 47 and w["n_v5_bullets"] == 0 and w["header_hits"] == []
    assert {b["bullet"] for b in w["bullets_with_hits"]} <= set(V5_GENE_WORDED)
    assert len(w["errors"]) == len(w["bullets_with_hits"]) and not any("one to one" in e for e in w["errors"])
    # the gene lines of the contract are untouched; only the four framing lines differ
    active, _, _ = C.activate_for(store, "C3", "all")
    c_base, c_v = G.compile_contract(active)[0].splitlines(), G.compile_contract(active, T["contract_frame"])[0].splitlines()
    frame_lines = {G.DEFAULT_CONTRACT_FRAME[k] for k in ("required", "forbidden", "checks")}
    frame_lines.add(G.DEFAULT_CONTRACT_FRAME["heading"].replace("{n}", str(len(active))))
    diff = [(a, b) for a, b in zip(c_base, c_v) if a != b]
    assert len(c_base) == len(c_v) and len(diff) == 4 and {a for a, _ in diff} == frame_lines
    # prompts build per configuration with no identifier in them
    obj = json.load(open(CF.DEFAULT_REGISTRY))
    for cid in ("C0", "C1", "C3"):
        c = next(x for x in obj["configs"] if x["id"] == cid)
        obj["configs"].append(dict(c, id=f"{cid}-{v.upper()}", variant=v, label="draft rewrite"))
    reg2 = CF.parse_registry(obj)
    case = {"case_id": "toy-0001", "source": "toy", "text": DEV_TEXTS["toy-0001"]}
    for cid in ("C0", "C3"):
        req = C.build_request(reg2["configs"][f"{cid}-{v.upper()}"], case, store, "run", registry_ids=CF.all_ids(reg2))
        assert req["meta"]["variant"] == v
        assert req["messages"][0]["content"] != C.build_request(reg2["configs"][cid], case, store, "run")["messages"][0]["content"]


# ------------------------------------------------------------------ contract frame


def test_contract_frame_default_is_v5_and_bad_frames_are_refused(store, tmp_path):
    active, _, _ = C.activate_for(store, "C3", "all")
    text, info = G.compile_contract(active)
    assert info["contract_sha256"] == V5_CONTRACT_SHA256 == G.compile_contract(active, dict(G.DEFAULT_CONTRACT_FRAME))[1]["contract_sha256"]
    assert "contract_frame" not in C.load_templates(COND)["files"] and C.load_templates(COND)["contract_frame"] is None
    good = dict(G.DEFAULT_CONTRACT_FRAME)
    for bad in ({k: v for k, v in good.items() if k != "checks"}, dict(good, extra="x"), dict(good, heading="no count"),
                dict(good, heading="{n} and {n}"), dict(good, required="Required {n}:"), dict(good, forbidden="a\nb"),
                dict(good, checks=" padded "), dict(good, checks="")):
        with pytest.raises(ValueError):
            G.compile_contract(active, bad)
    cond = toy_templates(os.path.join(str(tmp_path), "cond"))
    vdir = _toy_variant(cond, "rwz")
    write(os.path.join(vdir, "C3_contract_frame.json"), '{"heading": "x"}')
    with pytest.raises(ValueError, match="C3_contract_frame.json"):
        C.load_templates(cond, "rwz")


# ------------------------------------------------------------------ command line


def _have_python():
    return os.path.exists(E.orgene_python())


def _real_dev_report(tmp_path, reg, store, counter, cond, genes_path=GENES):
    """A report over the real dev ids with self-made texts (ids only), matched with a fake counter (characters) on the
    templates in `cond` (conditions/ with the proposed R1 pool: the working pool carries gene wording and is refused).
    Returns (report, path, sha256 of the matched C1 prompt)."""
    ids, info = M.dev_set_ids()
    cases = [{"case_id": c, "source": "toy", "text": f"Toy statement {i} with yes or no choices."}
             for i, c in enumerate(ids)]
    rep = M.build_report(store, genes_path, reg, cases, info, LEX, {"qwen": M.TokenMeasure(counter, "qwen"), "api": None},
                         cond_dir=cond, variants=[])
    path = os.path.join(str(tmp_path), "c1_report.json")
    M.write_report(rep, path)
    q = rep["variants"]["base"]["tokenizers"]["qwen"]["c1"]
    return rep, path, (_sha(C.c1_text(C.load_templates(cond), q["bullets_used"])) if q["ok"] else None)


def _run_cli(argv):
    try:
        cli.main(argv)
    except SystemExit as e:
        return e.code
    return 0


@pytest.mark.skipif(not _have_python(), reason="generation interpreter not present on this host")
def test_requests_builds_the_token_matched_c1_from_the_report(tmp_path, reg, store, monkeypatch, capsys):
    counter = FakeCounter("chars")
    cond = draft_cond(tmp_path)
    rep, rpath, c1_sha = _real_dev_report(tmp_path, reg, store, counter, cond)
    assert rep["ok"] and rep["variants"]["base"]["tokenizers"]["qwen"]["c1"]["sha256"] == c1_sha
    monkeypatch.setattr(M, "MAKE_COUNTER", lambda which, **kw: counter)
    run = os.path.join(str(tmp_path), "run")
    code = _run_cli(["requests", "--run", run, "--cases", SMOKE_CASES, "--cond", "C0", "C1", "--limit", "2",
                     "--c1-report", rpath, "--cond-dir", cond])
    assert code == 0, capsys.readouterr().err
    reqs = C.read_jsonl(os.path.join(run, "requests.C1.jsonl"))
    assert {r["meta"]["system_prompt_sha256"] for r in reqs} == {c1_sha}
    assert reqs[0]["meta"]["c1_match"]["measure"] == "tokens:qwen"
    cfg = json.load(open(os.path.join(run, "run_config.json")))
    cm = cfg["prompts"]["c1_matching"]
    assert cm["match_mode"] == "tokens" and cm["report_sha256"] == hashlib.sha256(open(rpath, "rb").read()).hexdigest()
    assert cm["by_config"]["C1"]["sha256"] == c1_sha
    for cid in ("C0", "C1"):  # local counts of the system prompts are recorded, not None
        t = cfg["prompts"]["by_config"][cid]["system_prompt_tokens_local"]
        assert t["tokenizer_sha256"] == counter.identity_sha256 and t["min"] == t["max"] > 0
    # the same run directory refuses another matching
    code = _run_cli(["requests", "--run", run, "--cases", SMOKE_CASES, "--cond", "C1", "--limit", "2",
                     "--c1-match-mode", "chars", "--cond-dir", cond])
    assert code != 0 and "another C1 matching" in str(code)


@pytest.mark.skipif(not _have_python(), reason="generation interpreter not present on this host")
def test_requests_refuses_a_missing_stale_or_failed_report(tmp_path, reg, store, monkeypatch):
    counter = FakeCounter("chars")
    monkeypatch.setattr(M, "MAKE_COUNTER", lambda which, **kw: counter)
    cond = draft_cond(tmp_path)
    base = ["requests", "--cases", SMOKE_CASES, "--cond", "C1", "--limit", "1", "--cond-dir", cond]

    def run(name, *extra):
        return str(_run_cli(base[:1] + ["--run", os.path.join(str(tmp_path), name)] + base[1:] + list(extra)))

    assert "no C1 matching report" in run("r1", "--c1-report", os.path.join(str(tmp_path), "none.json"))
    rep, rpath, _ = _real_dev_report(tmp_path, reg, store, counter, cond)
    # stale: another gene library (same genes, one more blank line)
    g2 = os.path.join(str(tmp_path), "genes.copy.jsonl")
    write(g2, open(GENES, encoding="utf-8").read() + "\n")
    assert "stale (gene library" in run("r2", "--c1-report", rpath, "--genes", g2)
    # stale: another tokenizer
    monkeypatch.setattr(M, "MAKE_COUNTER", lambda which, **kw: FakeCounter("words"))
    assert "not the one the C1 matching report was made with" in run("r3", "--c1-report", rpath)
    monkeypatch.setattr(M, "MAKE_COUNTER", lambda which, **kw: counter)
    # a report that is not ok
    bad = dict(rep, ok=False)
    bpath = os.path.join(str(tmp_path), "bad.json")
    M.write_report(bad, bpath)
    assert "is not ok" in run("r4", "--c1-report", bpath)
    # the tokenizer switched off, the API C1 asked of a report without API numbers
    assert "needs the local tokenizer" in run("r5", "--c1-report", rpath, "--local-tokens", "off")
    assert "no API tokenizer numbers" in run("r6", "--c1-report", rpath, "--c1-tokenizer", "api")
    # stale templates: a copy of the templates with one more pool bullet
    cond2 = os.path.join(str(tmp_path), "cond2")
    shutil.copytree(cond, cond2)
    with open(os.path.join(cond2, "C1_generic_expert_pool.md"), "a", encoding="utf-8") as f:
        f.write("- Keep assumptions few and explicit.\n")
    assert "templates of variant 'base' changed" in run("r7", "--c1-report", rpath, "--cond-dir", cond2)
    # the replayed matching must give the prompt the report records
    t = json.load(open(rpath, encoding="utf-8"))
    t["variants"]["base"]["tokenizers"]["qwen"]["c1"]["sha256"] = "0" * 64
    tpath = os.path.join(str(tmp_path), "tampered.json")
    M.write_report(t, tpath)
    assert "replayed C1 prompt is not the one in the matching report" in run("r8", "--c1-report", tpath)
    # stale dev C3 prompts although every recorded input file is the same (a change in the code that builds them)
    orig = G.compile_contract
    monkeypatch.setattr(G, "compile_contract",
                        lambda active, frame=None: (lambda t_, i_: (t_ + "One more line.\n", i_))(*orig(active, frame)))
    assert "C3 dev system prompts of variant 'base'" in run("r9", "--c1-report", rpath)
    monkeypatch.setattr(G, "compile_contract", orig)
    assert run("r10", "--c1-report", rpath) == "0"
    for name in ("r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9"):
        assert not os.path.exists(os.path.join(str(tmp_path), name, "requests.C1.jsonl")), name
    assert os.path.exists(os.path.join(str(tmp_path), "r10", "requests.C1.jsonl"))


@pytest.mark.skipif(not _have_python(), reason="generation interpreter not present on this host")
def test_requests_chars_mode_and_the_pool_error(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "MAKE_COUNTER", lambda which, **kw: (_ for _ in ()).throw(AssertionError("no counter")))
    run = os.path.join(str(tmp_path), "run")
    assert _run_cli(["requests", "--run", run, "--cases", SMOKE_CASES, "--cond", "C1", "--limit", "1",
                     "--c1-match-mode", "chars", "--cond-dir", COND]) == 0
    reqs = C.read_jsonl(os.path.join(run, "requests.C1.jsonl"))
    assert reqs[0]["meta"]["system_prompt_sha256"] == V5_C1_SHA256
    cfg = json.load(open(os.path.join(run, "run_config.json")))
    assert cfg["prompts"]["c1_matching"]["match_mode"] == "chars"
    assert cfg["prompts"]["by_config"]["C1"]["system_prompt_tokens_local"] is None
    assert "not computed" in cfg["prompts"]["by_config"]["C1"]["system_prompt_tokens_note"]
    # a pool that cannot reach the target is an error (it was a warning), and nothing is written
    cond2 = os.path.join(str(tmp_path), "cond2")
    shutil.copytree(COND, cond2, ignore=shutil.ignore_patterns("variants", "drafts"))
    pool = open(os.path.join(cond2, "C1_generic_expert_pool.md"), encoding="utf-8").read().splitlines()
    write(os.path.join(cond2, "C1_generic_expert_pool.md"), "\n".join(pool[:10]) + "\n")
    run2 = os.path.join(str(tmp_path), "run2")
    code = _run_cli(["requests", "--run", run2, "--cases", SMOKE_CASES, "--cond", "C0", "C1", "--limit", "1",
                     "--c1-match-mode", "chars", "--cond-dir", cond2])
    assert "cannot be length-matched" in str(code) and "pool is too short" in str(code)
    assert not os.path.exists(os.path.join(run2, "requests.C0.jsonl"))


def test_c1_match_command_on_the_dev_cases(tmp_path, monkeypatch, capsys):
    # reads the dev cases of dev_signal55 (dev only) and prints counts, ratios and hashes
    counter = FakeCounter("chars")
    monkeypatch.setattr(M, "MAKE_COUNTER", lambda which, **kw: counter)
    cond = draft_cond(tmp_path)
    out = os.path.join(str(tmp_path), "report.json")
    code = _run_cli(["c1-match", "--out", out, "--no-api", "--variants", "--cond-dir", cond])
    printed = capsys.readouterr()
    assert code == 0, printed.err
    rep = json.load(open(out))
    assert rep["dev_set"]["name"] == "dev_signal55" and rep["dev_set"]["n"] == rep["dev_set"]["n_loaded"] == 55
    v = rep["variants"]["base"]
    q = v["tokenizers"]["qwen"]
    assert v["ok"] and v["c3_dev"]["n_cases"] == 55 and v["c3_dev"]["prompts_sha256"]
    assert q["c1"]["sha256"] == _sha(C.c1_text(C.load_templates(cond), q["c1"]["bullets_used"]))
    assert set(q["per_case_ratio_by_case"]) == set(M.dev_set_ids()[0])
    assert "[c1-match] OK" in printed.out
    # the v5 pool: its bullets with gene wording make the report not ok
    code = _run_cli(["c1-match", "--out", out, "--no-api", "--variants", "--cond-dir", COND])
    assert code == 1 and "carries gene wording" in capsys.readouterr().err


# ------------------------------------------------------------------ the R1 pool (working templates since 2026-10-05)


def test_r1_pool_is_the_drafted_pool_followed_by_the_candidates():
    T = C.load_templates(R1_COND)
    header, bullets = C.c1_parts(T)
    draft = C.c1_parts(_with_pool(T, open(os.path.join(R1_COND, "drafts", "C1_pool_r1.draft.md"), encoding="utf-8").read()))[1]
    cand = [line for line in open(os.path.join(R1_COND, "drafts", "C1_pool_candidates.draft.md"), encoding="utf-8").read().splitlines()
            if line.startswith("- ")]
    assert bullets == draft + cand and len(bullets) == 77 and len(set(bullets)) == 77
    v5_header = C.c1_parts(C.load_templates(COND))[0]
    assert [h.replace("Return only the program.", "Return the program.") for h in header] == list(v5_header)
    closing = open(os.path.join(R1_COND, "C0_direct.md"), encoding="utf-8").read().strip()
    assert header[0].endswith(closing)  # the closing sentence of C0


def test_r1_pool_has_no_gene_wording_for_the_libraries():
    T = C.load_templates(R1_COND)
    libs = [(os.path.join(ROOT, "genes", "genes.r1.jsonl"), None),
            (os.path.join(ROOT, "genes", "genes.it1.jsonl"), os.path.join(ROOT, "genes", "activation_lexicon.v2.json"))]
    for lib, lex in libs:
        w = M.pool_wording(T, M.gene_keyword_table(G.load_store(lib, lexicon=lex), M.base_texts(R1_COND)))
        assert w["errors"] == [] and w["header_hits"] == [] and w["n_bullets"] == 77, lib


def test_committed_c1_report_is_ok_for_the_registered_library():
    path = os.path.join(R1_COND, "c1_matching_report.json")
    if not os.path.exists(path):
        pytest.skip("no C1 matching report yet")
    rep = json.load(open(path, encoding="utf-8"))
    v = rep["variants"]["base"]
    assert rep["ok"] and v["ok"] and list(rep["variants"]) == ["base"]
    assert "genes.it1.jsonl" in json.dumps(rep["inputs"])

