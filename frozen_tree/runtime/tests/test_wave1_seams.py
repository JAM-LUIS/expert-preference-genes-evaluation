"""Seams between branches merged in wave1 that no single branch could test (wave1 merge verification).

Each branch was written against the v5 code base, so a test on one branch had to stub the others. These tests run
the merged pieces together: the configuration registry builder (E03) with the real per-problem activation and
features (E04), the test gate (E21) with the reference-override check (E13), the run script (E05) with the registries
(E03, E19), and every `orgene` name that runtime, analysis and tool code refers to. Fixtures are self-made toy cases;
no benchmark text is read and no model is called.
"""
import argparse
import ast
import copy
import importlib
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)

from orgene import cli  # noqa: E402
from orgene import conditions as C  # noqa: E402
from orgene import configs as CF  # noqa: E402
from orgene import features as F  # noqa: E402
from orgene import freeze as FZ  # noqa: E402
from orgene import genes as G  # noqa: E402

REG_PATH = os.path.join(ROOT, "configs", "r1_configs.json")
MODEL_REG_PATH = os.path.join(ROOT, "configs", "model_registry.json")
GENES = os.path.join(ROOT, "genes", "genes.r1.jsonl")
COND = os.path.join(ROOT, "conditions")
SMOKE_CASES = os.path.join(ROOT, "data", "cases", "smoke.jsonl")

# self-made; B mentions a yes/no choice (lexicon feature binary_terms), A does not
CASE_A = {"case_id": "seam-0001", "source": "toy",
          "text": "A shop makes chairs and tables. Maximise profit 5x + 4y subject to 2x + y <= 10 and x + y <= 7."}
CASE_B = {"case_id": "seam-0002", "source": "toy",
          "text": "Choose at most 2 of 4 projects (yes or no) to maximise total value within a budget of 100."}
RULED_GENE = "orgene.numeric.bigm_bounded"
RULE = {"rule": {"feature": "binary_terms", "op": "==", "value": True},
        "rationale": "test only: big-M bounds matter when the problem has yes/no decisions"}


# ------------------------------------------------------------------ every orgene name referred to exists


def _code_files():
    out = []
    for top in ("runtime", "analysis", "tools", "data"):
        for d, dirs, files in os.walk(os.path.join(ROOT, top)):
            rel_d = os.path.relpath(d, ROOT).replace(os.sep, "/")
            dirs[:] = [x for x in dirs if x not in ("__pycache__", "tests", "raw", "cases")]
            if rel_d.startswith("data/raw"):
                continue
            out += [os.path.join(d, f) for f in files if f.endswith(".py")]
    return sorted(out)


def _module_aliases(tree, path):
    """{local name: module name} for `from orgene[.backends] import m [as x]` and `from . import m` in orgene."""
    in_pkg = f"{os.sep}orgene{os.sep}" in path
    pkg = "orgene.backends" if f"{os.sep}backends{os.sep}" in path else "orgene"
    names, imported = {}, []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level == 0 and node.module in ("orgene", "orgene.backends"):
            base = node.module
        elif node.level == 1 and node.module is None and in_pkg:
            base = pkg
        else:
            if node.level == 0 and (node.module or "").startswith("orgene."):
                imported.append((node.module, [a.name for a in node.names], node.lineno))
            continue
        for a in node.names:
            names[a.asname or a.name] = f"{base}.{a.name}"
    return names, imported


def test_every_orgene_name_used_by_runtime_analysis_and_tools_exists():
    """A branch renamed or removed a name (E03: build_system_prompts -> build_system_prompts_v1) that another branch
    still used outside the tests; nothing ran that file, so the merge kept it. Checked statically here."""
    missing, checked = [], 0
    for path in _code_files():
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        aliases, imported = _module_aliases(tree, path)
        mods = {}
        for alias, name in aliases.items():
            try:
                mods[alias] = importlib.import_module(name)
            except ImportError:
                pass  # `from orgene import some_function`: not a module
        where = os.path.relpath(path, ROOT)
        for module, names, line in imported:
            m = importlib.import_module(module)
            for n in names:
                checked += 1
                if n != "*" and not hasattr(m, n):
                    missing.append(f"{where}:{line} {module}.{n}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in mods:
                checked += 1
                if not hasattr(mods[node.value.id], node.attr):
                    missing.append(f"{where}:{node.lineno} {aliases[node.value.id]}.{node.attr}")
    assert checked > 200
    assert not missing, missing


# ------------------------------------------------------------------ E03 builder x E04 activation


@pytest.fixture(scope="module")
def reg():
    return CF.load_registry(REG_PATH)


@pytest.fixture(scope="module")
def ruled_store(tmp_path_factory):
    """The working library with one problem-dependent rule added, written out and read back through genes.load_store."""
    store = G.load_store(GENES)
    assert RULED_GENE in {g["geneId"] for g in store}
    ruled = copy.deepcopy(store)
    for g in ruled:
        if g["geneId"] == RULED_GENE:
            g["activation"] = copy.deepcopy(RULE)
    F.check_activation(RULE, F.feature_types(F.load_lexicon(None)))
    p = tmp_path_factory.mktemp("genes") / "genes.ruled.jsonl"
    p.write_text("".join(json.dumps(g, ensure_ascii=False) + "\n" for g in ruled), encoding="utf-8")
    return G.load_store(str(p))


def _features(cases):
    a = argparse.Namespace(lexicon=None)
    feats, lex_info = cli._features_by_case(a, cases)  # the path `orgene_cli.py requests` takes
    assert lex_info["sha256"] and set(feats) == {c["case_id"] for c in cases}
    return feats


def test_registry_builder_activates_per_problem_with_the_real_activation(reg, ruled_store):
    assert C._activate_takes_features(), "genes.activate must take problem features once E04 is merged"
    feats = _features([CASE_A, CASE_B])
    assert feats[CASE_A["case_id"]]["binary_terms"] is False and feats[CASE_B["case_id"]]["binary_terms"] is True
    by = {}
    for cid in ("C0", "C1", "C2", "C3", "C3L", "C3E", "C2E", "C3L-ALL"):
        reqs = C.build_requests([CASE_A, CASE_B], CF.get_config(reg, cid), ruled_store, "seam", features_by_case=feats,
                                cond_dir=COND)
        by[cid] = {r["case_id"]: r for r in reqs}
        for r in reqs:
            assert r["meta"]["features_sha256"] == F.features_sha256(feats[r["case_id"]]), cid
    a, b = CASE_A["case_id"], CASE_B["case_id"]

    def genes_of(cid, case):
        return {g["geneId"] for g in by[cid][case]["meta"]["active_genes"]}

    # C3: the rule drops the gene for A only, so the contract (and the prompt) differ between the two cases
    assert by["C3"][a]["meta"]["activation_impl"] == "per_problem"
    assert RULED_GENE not in genes_of("C3", a) and RULED_GENE in genes_of("C3", b)
    assert genes_of("C3", b) - genes_of("C3", a) == {RULED_GENE}
    assert by["C3"][a]["meta"]["contract_sha256"] != by["C3"][b]["meta"]["contract_sha256"]
    assert by["C3"][a]["messages"][0] != by["C3"][b]["messages"][0]
    trace = {t["geneId"]: t for t in by["C3"][a]["meta"]["activation_trace"]}
    assert trace[RULED_GENE]["activation_value"] is False and trace[RULED_GENE]["features_used"] == ["binary_terms"]
    # C3L validates per problem too, but its prompt is C0's for every case
    if RULED_GENE in {g["geneId"] for g in G.activate(ruled_store, condition="C3L", mode="all")[0]}:
        assert RULED_GENE not in genes_of("C3L", a) and RULED_GENE in genes_of("C3L", b)
    # the all-active ablation and the fixed-template configurations ignore the rule
    for cid in ("C3L-ALL", "C3E", "C2E"):
        assert by[cid][a]["meta"]["activation_impl"] == "all" and genes_of(cid, a) == genes_of(cid, b), cid
    # no configuration without a contract depends on the case
    for cid in ("C0", "C1", "C2", "C3L", "C3E", "C2E", "C3L-ALL"):
        assert by[cid][a]["messages"][0] == by[cid][b]["messages"][0], cid
    assert by["C3L"][a]["messages"][0] == by["C0"][a]["messages"][0]
    assert by["C2E"][a]["messages"][0] == by["C2"][a]["messages"][0]


def test_per_problem_rules_without_features_are_refused_not_ignored(reg, ruled_store):
    with pytest.raises(ValueError, match="needs the problem features"):
        C.build_requests([CASE_A], CF.get_config(reg, "C3"), ruled_store, "seam", cond_dir=COND)
    # the batch validate path recognises the E04 rule format and sends such libraries to the unit executor (E06)
    assert C.problem_rule_genes(ruled_store, "C3") == [RULED_GENE]
    assert C.problem_rule_genes(G.load_store(GENES), "C3") == []


# ------------------------------------------------------------------ E21 test gate x E13 reference overrides


def test_gated_score_hands_the_manifest_to_the_override_check(monkeypatch, tmp_path):
    """E21's gate sets --freeze-manifest for a gated score only when the E13 option exists and was not given."""
    seen = []
    monkeypatch.setattr(cli, "cmd_score", lambda a: seen.append(a))
    run = str(tmp_path / "run")
    argv = ["score", "--run", run, "--cases", SMOKE_CASES, "--cond", "C0"]

    monkeypatch.setattr(FZ, "gate_stage", lambda stage, **kw: {"stage": stage, "manifest": "FREEZE_MANIFEST.json"})
    cli.main(argv)
    assert seen[-1].freeze_manifest == os.path.join(ROOT, "FREEZE_MANIFEST.json")
    cli.main(argv + ["--freeze-manifest", str(tmp_path / "given.json")])
    assert seen[-1].freeze_manifest == str(tmp_path / "given.json"), "an explicit manifest is kept"

    monkeypatch.setattr(FZ, "gate_stage", lambda stage, **kw: None)  # a dev run: no gate record
    cli.main(argv)
    assert seen[-1].freeze_manifest is None


# ------------------------------------------------------------------ E05 run script x E03/E19 registries


def test_run_condition_defaults_are_the_registered_settings():
    sh = open(os.path.join(RUNTIME, "run_condition.sh"), encoding="utf-8").read()
    num_predict = int(re.search(r'NUM_PREDICT="\$\{5:-(\d+)\}"', sh).group(1))
    num_ctx = int(re.search(r'NUM_CTX="\$\{NUM_CTX:-(\d+)\}"', sh).group(1))
    temp = float(re.search(r'TEMP="\$\{7:-([0-9.]+)\}"', sh).group(1))
    model = re.search(r'MODEL="\$\{4:-([^}]+)\}"', sh).group(1)
    main = json.load(open(MODEL_REG_PATH, encoding="utf-8"))["entries"]["qwen3-8b.main"]
    assert (num_predict, num_ctx, temp) == (main["opts"]["num_predict"], main["opts"]["num_ctx"], main["opts"]["temperature"])
    assert model == main["model"]
    reg = CF.load_registry(REG_PATH)
    for cid in ("C0", "C1", "C2", "C3", "C3L", "C3E", "C2E"):
        c = CF.get_config(reg, cid)
        assert (c["num_predict"], c["num_ctx"]) == (num_predict, num_ctx), cid
