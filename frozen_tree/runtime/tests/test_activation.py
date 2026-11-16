"""Per-problem activation (E04): problem-text features, activation rules, activate(), load-time checks, version rule.

Every text below is a short self-written sentence; none is taken from a benchmark.
"""
import copy
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RUNTIME, ".."))
sys.path.insert(0, RUNTIME)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from orgene import features as F  # noqa: E402
from orgene import genes as G  # noqa: E402
from orgene.versioning import compare_stores, parse_version  # noqa: E402

R1_GENES = os.path.join(ROOT, "genes", "genes.r1.jsonl")
V1_GENES = os.path.join(ROOT, "releases", "v1.0", "genes.v3.jsonl")
LEX = F.load_lexicon()


def feats(text):
    return F.extract_features(text, LEX)


def base_features(**over):
    """Every feature at its 'absent' value (False / 0), with overrides."""
    d = {n: (False if t == "bool" else 0) for n, t in LEX.types.items()}
    d.update(over)
    return d


def write_store(path, genes):
    with open(path, "w", encoding="utf-8") as f:
        for g in genes:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    return str(path)


def gene_with(gid, activation=None, **changes):
    g = copy.deepcopy({x["geneId"]: x for x in G.load_store(R1_GENES)}[gid])
    if activation is not None:
        g["activation"] = activation
    g.update(changes)
    return g


# ----------------------------------------------------------------------------- features: 3 positive / 3 negative each

FEATURE_CASES = {
    "integer_terms": (
        ["The number of buses sent must be an integer.",
         "Chairs are sold in whole units only.",
         "Crates cannot be split between two trucks."],
        ["Production quantities may be fractional.",
         "Blend the two oils in any proportion.",
         "Each acre can be divided freely between wheat and corn."]),
    "binary_terms": (
        ["The firm must decide whether to build a new plant.",
         "Each project is either funded in full or not at all.",
         "Select three of the five candidate sites."],
        ["Produce chairs and tables to maximize profit.",
         "The machine runs for 8 hours per day.",
         "Send the goods from the port to the city."]),
    "fixed_cost_terms": (
        ["Each plant has a fixed cost of 500 per month if it operates.",
         "A set-up cost of 200 is paid for every production run.",
         "Opening a depot incurs a one-time fee of 3,000."],
        ["Each unit costs 5 to produce.",
         "The variable cost per ton is 12.",
         "Prices are fixed by contract for the whole year."]),
    "multi_period_terms": (
        ["Plan production for the next three months.",
         "Demand in month 1 is 40 units and in month 2 it is 55 units.",
         "Over a planning horizon of four quarters, the firm hires staff."],
        ["The factory can produce at most 100 units per week.",
         "A day has 24 hours of machine time.",
         "Last year the company earned a profit of 2 million."]),
    "inventory_terms": (
        ["Unsold units can be kept in inventory at a cost of 2 per unit per month.",
         "The holding cost is 1 per unit per week.",
         "Excess production is carried over to the next month."],
        ["The investor buys stocks and bonds.",
         "All units produced are sold immediately.",
         "The warehouse has 500 square meters of floor space."]),
    "network_flow_terms": (
        ["Goods are shipped from two factories to three stores.",
         "Water flows through a network of pipes.",
         "Find the cheapest route from the depot to each customer."],
        ["A bakery makes bread and cakes.",
         "The diet must supply at least 60 grams of protein.",
         "Workers are assigned to morning and evening shifts."]),
    "ratio_percent_terms": (
        ["At least 30% of the budget goes to advertising.",
         "The ratio of fat to protein must not exceed 2 to 1.",
         "No more than half of the workers may be part-time."],
        ["Each worker earns 20 dollars per hour.",
         "The truck carries 10 tons.",
         "Maximize total output."]),
    "logical_terms": (
        ["If product A is made, then at least 10 units of it must be made.",
         "Plant B may operate only if plant A operates.",
         "At most two of the four projects can be funded."],
        ["Each product needs 2 hours of labor.",
         "Minimize the total delivery cost.",
         "Demand must be met in full."]),
    "count_terms": (
        ["How many trucks should be sent?",
         "Decide how many machines to buy and the number of shifts.",
         "Report the number of workers hired."],
        ["Maximize profit from blending.",
         "What is the minimum cost?",
         "Allocate the budget across three campaigns."]),
}


def test_every_lexicon_feature_has_cases():
    assert set(FEATURE_CASES) == set(LEX.features), "each lexicon feature needs 3 positive and 3 negative texts"
    for name, (pos, neg) in FEATURE_CASES.items():
        assert len(pos) >= 3 and len(neg) >= 3, name


@pytest.mark.parametrize("name,text", [(n, t) for n, (pos, _) in FEATURE_CASES.items() for t in pos])
def test_feature_positive(name, text):
    v = feats(text)[name]
    assert (v is True) if LEX.types[name] == "bool" else (v >= 1), (name, text)


@pytest.mark.parametrize("name,text", [(n, t) for n, (_, neg) in FEATURE_CASES.items() for t in neg])
def test_feature_negative(name, text):
    v = feats(text)[name]
    assert (v is False) if LEX.types[name] == "bool" else (v == 0), (name, text)


NUMERIC_CASES = [  # built-in count feature: >= 3 texts with literals and >= 3 without
    ("A costs $1,200 and B costs 3.5 per unit; 10% tax applies.", 3),
    ("Buy 4 trucks, 12 vans and 7 bikes.", 3),
    ("Shifts last 8 hours; overtime is limited to 20 hours in weeks 3-4.", 4),
    ("Machines M1 and M2 run on the 2nd shift.", 0),
    ("There is no number here.", 0),
    ("Maximize the total profit of the three farms.", 0),
]


@pytest.mark.parametrize("text,n", NUMERIC_CASES)
def test_numeric_literal_count(text, n):
    assert feats(text)["numeric_literal_count"] == n


WORD_CASES = [  # built-in count feature: exact counts after whitespace normalisation
    ("Maximize profit.", 2),
    ("  Plan   the\nnext three\tmonths. ", 5),
    ("A set-up cost of 200 applies.", 6),
    ("", 0),
]


@pytest.mark.parametrize("text,n", WORD_CASES)
def test_word_count(text, n):
    assert feats(text)["word_count"] == n


def test_builtin_features_have_positive_and_negative_cases():
    assert sum(1 for _, n in NUMERIC_CASES if n) >= 3 and sum(1 for _, n in NUMERIC_CASES if not n) >= 3
    assert set(F.BUILTIN_TYPES) == {"numeric_literal_count", "word_count"}, "add cases for every built-in feature"


def test_count_feature_counts_matches():
    assert feats("How many trucks and how many vans? Also the number of drivers.")["count_terms"] == 3


def test_features_are_deterministic_typed_and_sorted():
    text = "Plan the next three months; at most 20% overtime; whether to open a second shift."
    a, b = feats(text), feats(text)
    assert a == b and F.features_sha256(a) == F.features_sha256(b)
    assert list(a) == sorted(a)
    assert set(a) == set(LEX.types)
    for k, v in a.items():
        assert isinstance(v, bool) if LEX.types[k] == "bool" else (isinstance(v, int) and not isinstance(v, bool)), k


def test_features_ignore_case_whitespace_and_unicode_dashes():
    a = feats("A set-up cost applies.\n\nPlan the  next THREE months.")
    b = feats("a set‑up cost applies. plan the next three months.")
    assert a == b and a["fixed_cost_terms"] and a["multi_period_terms"]


def test_extract_features_takes_the_statement_only():
    with pytest.raises(TypeError):
        F.extract_features({"text": "x", "spec": {}, "code": "print(1)"}, LEX)


# ----------------------------------------------------------------------------- lexicon validation (negative)


def _lex(features):
    return {"schemaVersion": F.LEXICON_SCHEMA, "features": features}


@pytest.mark.parametrize("doc,msg", [
    ({"schemaVersion": "other", "features": {"a_terms": {"kind": "any", "patterns": ["a"]}}}, "schemaVersion"),
    (_lex({}), "non-empty"),
    (_lex({"a_terms": {"kind": "sometimes", "patterns": ["a"]}}), "kind"),
    (_lex({"a_terms": {"kind": "any", "patterns": []}}), "patterns"),
    (_lex({"a_terms": {"kind": "any", "patterns": ["(unclosed"]}}), "bad pattern"),
    (_lex({"a_terms": {"kind": "any", "patterns": ["a"], "weight": 2}}), "unknown keys"),
    (_lex({"word_count": {"kind": "count", "patterns": ["a"]}}), "built-in"),
    (_lex({"spec_terms": {"kind": "any", "patterns": ["a"]}}), "problem-text features only"),
    (_lex({"Bad-Name": {"kind": "any", "patterns": ["a"]}}), "must match"),
])
def test_lexicon_rejects(doc, msg):
    with pytest.raises(ValueError, match=msg):
        F.compile_lexicon(doc)


def test_repository_lexicon_is_valid_and_hashed():
    with open(F.DEFAULT_LEXICON, "rb") as f:
        raw = f.read()
    import hashlib
    assert LEX.sha256 == hashlib.sha256(raw).hexdigest()
    assert LEX.path == "genes/activation_lexicon.v1.json"


# ----------------------------------------------------------------------------- rules: truth table

R_INT = {"feature": "integer_terms", "op": "==", "value": True}
R_FIX = {"feature": "fixed_cost_terms", "op": "==", "value": True}
R_NUM = {"feature": "numeric_literal_count", "op": ">=", "value": 5}

TRUTH = [
    # (rule, features, expected)
    ("always", base_features(), True),
    (R_INT, base_features(integer_terms=True), True),
    (R_INT, base_features(), False),
    ({"feature": "integer_terms", "op": "!=", "value": True}, base_features(), True),
    (R_NUM, base_features(numeric_literal_count=5), True),
    (R_NUM, base_features(numeric_literal_count=4), False),
    ({"feature": "count_terms", "op": ">", "value": 0}, base_features(count_terms=2), True),
    ({"feature": "count_terms", "op": "<", "value": 1}, base_features(count_terms=2), False),
    ({"feature": "word_count", "op": "<=", "value": 40}, base_features(word_count=40), True),
    ({"all": [R_INT, R_FIX]}, base_features(integer_terms=True, fixed_cost_terms=True), True),
    ({"all": [R_INT, R_FIX]}, base_features(integer_terms=True), False),
    ({"any": [R_INT, R_FIX]}, base_features(fixed_cost_terms=True), True),
    ({"any": [R_INT, R_FIX]}, base_features(), False),
    ({"not": R_INT}, base_features(), True),
    ({"not": R_INT}, base_features(integer_terms=True), False),
    ({"all": ["always", {"not": {"any": [R_INT, R_NUM]}}]}, base_features(numeric_literal_count=2), True),
    ({"all": ["always", {"not": {"any": [R_INT, R_NUM]}}]}, base_features(numeric_literal_count=9), False),
]


@pytest.mark.parametrize("rule,fs,want", TRUTH)
def test_rule_truth_table(rule, fs, want):
    F.check_rule(rule, LEX.types)
    assert F.eval_rule(rule, fs) is want


def test_truth_table_has_enough_positive_and_negative_rows():
    assert sum(1 for *_, w in TRUTH if w) >= 3 and sum(1 for *_, w in TRUTH if not w) >= 3


def test_eval_evaluates_every_branch_so_missing_features_raise():
    fs = base_features(integer_terms=True)
    del fs["fixed_cost_terms"]
    with pytest.raises(ValueError, match="missing"):
        F.eval_rule({"any": [R_INT, R_FIX]}, fs)


def test_eval_rejects_wrongly_typed_feature_values():
    with pytest.raises(ValueError, match="not a bool"):
        F.eval_rule(R_INT, base_features(integer_terms=1))
    with pytest.raises(ValueError, match="not a number"):
        F.eval_rule(R_NUM, base_features(numeric_literal_count=True))


@pytest.mark.parametrize("rule,msg", [
    ("sometimes", "only string rule"),
    (["always"], "a rule is"),
    ({"feature": "no_such_feature", "op": "==", "value": True}, "unknown feature"),
    ({"feature": "integer_terms", "op": "~", "value": True}, "op"),
    ({"feature": "integer_terms", "op": ">", "value": True}, "bool feature"),
    ({"feature": "integer_terms", "op": "==", "value": 1}, "bool feature"),
    ({"feature": "count_terms", "op": ">", "value": True}, "count feature"),
    ({"feature": "count_terms", "op": ">", "value": "2"}, "bool or a number"),
    ({"feature": "integer_terms", "op": "=="}, "exactly the keys"),
    ({"feature": "integer_terms", "op": "==", "value": True, "weight": 1}, "exactly the keys"),
    ({"all": []}, "non-empty list"),
    ({"any": R_INT}, "non-empty list"),
    ({"all": [R_INT], "any": [R_FIX]}, "unknown rule form"),
    ({"xor": [R_INT, R_FIX]}, "unknown rule form"),
    # activation may only read problem-text features: nothing from the spec, the program or its execution
    ({"feature": "spec_objective_sense", "op": "==", "value": True}, "problem-text features only"),
    ({"feature": "code_line_count", "op": ">", "value": 3}, "problem-text features only"),
    ({"feature": "exec_status", "op": "==", "value": True}, "problem-text features only"),
    ({"feature": "spec.objective.sense", "op": "==", "value": True}, "must match"),
    ({"field": "code", "contains": "pulp"}, "unknown rule form"),
])
def test_rule_check_rejects(rule, msg):
    with pytest.raises(ValueError, match=msg):
        F.check_rule(rule, LEX.types)


# ----------------------------------------------------------------------------- load-time checks on gene records


def test_store_with_rules_loads_and_reports_features(tmp_path):
    act = {"rule": {"any": [R_INT, R_FIX]}, "rationale": "integrality or fixed charges", "devEvidence": []}
    p = write_store(tmp_path / "g.jsonl", [gene_with("orgene.numeric.bigm_bounded", act, version="1.1.0")])
    (g,) = G.load_store(p)
    assert F.check_activation(g["activation"], LEX.types) == ["fixed_cost_terms", "integer_terms"]


@pytest.mark.parametrize("act,msg", [
    ({"rule": {"feature": "spec_has_integers", "op": "==", "value": True}}, "problem-text features only"),
    ({"rule": {"feature": "program_uses_bigm", "op": "==", "value": True}}, "problem-text features only"),
    ({"rule": {"feature": "unknown_terms", "op": "==", "value": True}}, "unknown feature"),
    ({"rule": {"feature": "integer_terms", "op": ">=", "value": 1}}, "bool feature"),
    ({"rationale": "no rule"}, "'rule' is required"),
    ({"rule": "always", "scopeHint": "C3"}, "unknown keys"),
    ({"rule": "always", "devEvidence": "mamo-1"}, "devEvidence"),
    ("always", "must be an object"),
])
def test_store_rejects_bad_activation(tmp_path, act, msg):
    p = write_store(tmp_path / "g.jsonl", [gene_with("orgene.numeric.bigm_bounded", act, version="1.1.0")])
    with pytest.raises(ValueError, match=msg):
        G.load_store(p)


def test_lexicon_is_read_only_when_a_rule_names_a_feature(tmp_path):
    missing = str(tmp_path / "no_lexicon.json")
    p = write_store(tmp_path / "a.jsonl", [gene_with("orgene.numeric.bigm_bounded", {"rule": "always"}, version="1.1.0")])
    assert len(G.load_store(p, lexicon=missing)) == 1
    plain = write_store(tmp_path / "plain.jsonl", _plain_store())
    assert len(G.load_store(plain, lexicon=missing)) == len(_plain_store())
    q = write_store(tmp_path / "b.jsonl", [gene_with("orgene.numeric.bigm_bounded", {"rule": R_INT}, version="1.1.0")])
    with pytest.raises(FileNotFoundError):
        G.load_store(q, lexicon=missing)


# ----------------------------------------------------------------------------- activate()


def _plain_store():
    """The working library with every activation field removed (as before E04: all genes always active)."""
    out = []
    for g in G.load_store(R1_GENES):
        g = copy.deepcopy(g)
        g.pop("activation", None)
        out.append(g)
    return out


def _mixed_store():
    """Rule-free working library plus one C3L gene gated on integrality or fixed costs and one on yes/no wording."""
    out = []
    for g in _plain_store():
        if g["geneId"] == "orgene.numeric.bigm_bounded":
            g["activation"] = {"rule": {"any": [R_INT, R_FIX]}}
        if g["geneId"] == "orgene.model.binary_cardinality_linked":
            g["activation"] = {"rule": {"feature": "binary_terms", "op": "==", "value": True}}
        out.append(g)
    return out


GATED = {"orgene.numeric.bigm_bounded", "orgene.model.binary_cardinality_linked"}


def test_per_problem_drops_genes_whose_rule_is_false():
    store = _mixed_store()
    all_c3l, _ = G.activate(store, "C3L", mode="all")
    act, trace = G.activate(store, "C3L", features=feats("Blend two oils; quantities may be fractional."))
    ids = {g["geneId"] for g in act}
    assert ids == {g["geneId"] for g in all_c3l} - GATED
    t = {x["geneId"]: x for x in trace}
    assert t["orgene.numeric.bigm_bounded"]["reasons"] == ["activation rule false"]
    assert t["orgene.numeric.bigm_bounded"]["activation_value"] is False
    assert t["orgene.numeric.bigm_bounded"]["features_used"] == ["fixed_cost_terms", "integer_terms"]
    assert t["orgene.execution.runs"]["activation_rule"] == "always" and t["orgene.execution.runs"]["activation_value"]


def test_per_problem_keeps_genes_whose_rule_is_true_in_the_usual_order():
    store = _mixed_store()
    act, _ = G.activate(store, "C3L", features=feats("Decide whether to open each depot; the fixed cost is 900."))
    all_c3l, _ = G.activate(store, "C3L", mode="all")
    assert [g["geneId"] for g in act] == [g["geneId"] for g in all_c3l]
    prio = [(-g["preference"]["priority"], g["geneId"]) for g in act]
    assert prio == sorted(prio)


def test_mode_all_ignores_rules_but_records_them():
    store = _mixed_store()
    act, trace = G.activate(store, "C3L", features=feats("Maximize output."), mode="all")
    assert GATED <= {g["geneId"] for g in act}
    t = {x["geneId"]: x for x in trace}
    assert t["orgene.numeric.bigm_bounded"]["included"] and t["orgene.numeric.bigm_bounded"]["activation_value"] is False


def test_mode_all_without_features_leaves_values_unevaluated():
    _, trace = G.activate(_mixed_store(), "C3L", mode="all")
    t = {x["geneId"]: x for x in trace}
    assert t["orgene.numeric.bigm_bounded"]["activation_value"] is None


def test_mode_none_activates_nothing():
    act, trace = G.activate(_mixed_store(), "C3", features=feats("x"), mode="none")
    assert act == [] and all("activation mode none" in t["reasons"] for t in trace)


def test_unknown_mode_is_an_error():
    with pytest.raises(ValueError, match="activation mode"):
        G.activate(G.load_store(R1_GENES), "C3", mode="sometimes")


def test_per_problem_without_features_raises_when_a_rule_needs_them():
    with pytest.raises(ValueError, match="needs the problem features"):
        G.activate(_mixed_store(), "C3L")


def test_constant_rules_need_no_features():
    store = _plain_store()
    for g in store:
        if g["geneId"] == "orgene.numeric.bigm_bounded":
            g["activation"] = {"rule": {"not": "always"}}
        if g["geneId"] == "orgene.model.binary_cardinality_linked":
            g["activation"] = {"rule": {"any": ["always"]}}
    act, trace = G.activate(store, "C3L")
    ids = {g["geneId"] for g in act}
    assert "orgene.numeric.bigm_bounded" not in ids and "orgene.model.binary_cardinality_linked" in ids
    t = {x["geneId"]: x for x in trace}
    assert t["orgene.numeric.bigm_bounded"]["activation_value"] is False
    assert t["orgene.numeric.bigm_bounded"]["features_used"] == []


def test_per_problem_without_features_is_fine_when_the_gated_genes_are_out_of_scope():
    store = _mixed_store()
    act, _ = G.activate(store, "C3E")
    assert {g["geneId"] for g in act}.isdisjoint(GATED)
    assert [g["geneId"] for g in act] == [g["geneId"] for g in G.activate(store, "C3E", mode="all")[0]]


def test_scope_and_lifecycle_still_decide_first():
    store = _mixed_store()
    for g in store:
        if g["geneId"] == "orgene.numeric.bigm_bounded":
            g["lifecycle"] = dict(g["lifecycle"], state="retired")
    act, trace = G.activate(store, "C3L", features=feats("An integer number of trucks with a fixed cost."))
    t = {x["geneId"]: x for x in trace}
    assert "orgene.numeric.bigm_bounded" not in {g["geneId"] for g in act}
    assert t["orgene.numeric.bigm_bounded"]["reasons"] == ["lifecycle=retired"]


def test_activate_does_not_modify_gene_records():
    store = _mixed_store()
    before = copy.deepcopy(store)
    _, trace = G.activate(store, "C3", features=feats("integer fixed cost"))
    trace[0]["activation_rule"] = "tampered"
    for t in trace:
        if isinstance(t["activation_rule"], dict):
            t["activation_rule"]["mutated"] = True
    assert store == before


def test_missing_activation_field_behaves_as_always():
    store = _plain_store()
    explicit = [dict(copy.deepcopy(g), activation={"rule": "always"}) for g in store]
    fs = feats("Maximize output.")
    for cond in ("C3", "C3L", "C3E"):
        a, ta = G.activate(store, cond, features=fs)
        b, tb = G.activate(explicit, cond, features=fs)
        assert [g["geneId"] for g in a] == [g["geneId"] for g in b]
        assert [t["included"] for t in ta] == [t["included"] for t in tb]


def test_activate_case_reads_the_statement_only():
    store = _mixed_store()
    case = {"case_id": "self-1", "text": "Decide whether to open a depot with a fixed cost of 50.",
            "reference": {"objective": 1.0}, "spec": {"decision_variables": []}, "code": "import pulp"}
    act, trace, info = G.activate_case(store, case, LEX, condition="C3L")
    assert info["features"] == feats(case["text"])
    assert info["features_sha256"] == F.features_sha256(info["features"])
    assert info["lexicon_sha256"] == LEX.sha256 and info["mode"] == "per_problem"
    assert GATED <= {g["geneId"] for g in act}
    changed = dict(case, reference={"objective": 2.0}, spec=None, code="")
    assert G.activate_case(store, changed, LEX, condition="C3L")[2]["features"] == info["features"]


def test_activation_summary_rates():
    store = _mixed_store()
    texts = ["An integer number of vans.", "Decide whether to open a site.", "Maximize output.",
             "A fixed cost and an integer count, whether or not."]
    traces = [G.activate(store, "C3L", features=feats(t))[1] for t in texts]
    s = G.activation_summary(traces)
    big = s["orgene.numeric.bigm_bounded@1.0.0"]
    assert (big["n"], big["n_included"], big["n_rule_true"]) == (4, 2, 2) and big["included_rate"] == 0.5
    card = s["orgene.model.binary_cardinality_linked@1.0.0"]
    assert (card["n_included"], card["rule_true_rate"]) == (2, 0.5)
    spec = s["orgene.artifact.spec_present@1.0.0"]  # C3-only gene: out of scope for C3L, rule "always"
    assert spec["n_included"] == 0 and spec["rule_true_rate"] == 1.0


# ----------------------------------------------------------------------------- regression: digests unchanged


def _digests(store, **kw):
    return {c: G.store_digest(G.activate(store, c, **kw)[0]) for c in ("C3", "C3L", "C3E")}


def _feature_variants():
    return [None, base_features(), {n: (True if t == "bool" else 99) for n, t in LEX.types.items()},
            feats("Decide whether to ship an integer number of crates over the next three months.")]


def test_rule_free_library_digests_do_not_depend_on_mode_or_features():
    """A library without activation fields activates exactly as before E04, whatever the features."""
    store = _plain_store()
    ref = _digests(store)
    for fs in _feature_variants():
        for mode in ("all", "per_problem"):
            assert _digests(store, features=fs, mode=mode) == ref, (mode, fs)


def test_mode_all_digests_ignore_rules():
    """The all-active ablation (C3L-ALL) sees the same gene set as a rule-free library."""
    mixed, plain = _mixed_store(), _plain_store()
    for fs in _feature_variants():
        got = _digests(mixed, features=fs, mode="all")
        assert [len(G.activate(mixed, c, features=fs, mode="all")[0]) for c in ("C3", "C3L", "C3E")] == \
               [len(G.activate(plain, c)[0]) for c in ("C3", "C3L", "C3E")]
        assert got["C3E"] == _digests(plain)["C3E"]  # no C3E gene is gated in the mixed store


@pytest.mark.skipif(not os.path.exists(V1_GENES), reason="releases/v1.0 is not in the anonymous repository")
def test_v1_library_digests_reproduce_the_anchors_in_both_modes():
    import anchor_hashes as A
    store = G.load_store(V1_GENES)
    want = A.EXPECTED_V1["activation_digest"]
    for fs in _feature_variants():
        for mode in ("all", "per_problem"):
            got = _digests(store, features=fs, mode=mode)
            assert all(got[c].startswith(want[c]) for c in want), (mode, got)
            assert {c: len(G.activate(store, c, features=fs, mode=mode)[0]) for c in want} == A.EXPECTED_V1["n_active"]


# ----------------------------------------------------------------------------- working library: evidence and examples


def _split_ids(kind):
    ids = set()
    base = os.path.join(ROOT, "data", "splits")
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name, f"{kind}_ids.json")
        if os.path.exists(p):
            ids |= set(json.load(open(p, encoding="utf-8")))
    return ids


def test_working_library_activation_evidence_uses_dev_ids_only():
    dev, test = _split_ids("dev"), _split_ids("test")
    for g in G.load_store(R1_GENES):
        ev = set((g.get("activation") or {}).get("devEvidence", []))
        assert not (ev & test), g["geneId"]
        assert ev <= dev, (g["geneId"], sorted(ev - dev))


def test_working_library_activation_examples():
    """Template for stage 1C: every gene with a non-trivial rule has >= 2 active and >= 2 inactive examples."""
    problems = F.check_activation_examples(G.load_store(R1_GENES), F.load_examples(), LEX)
    assert problems == [], problems


def test_example_checker_catches_missing_and_wrong_examples():
    store = _mixed_store()
    doc = {"genes": {
        "orgene.numeric.bigm_bounded": {
            "active": ["Trucks come in whole units only.", "A set-up cost of 80 is charged per run."],
            "inactive": ["Blend two oils freely.", "An integer number of vans is needed."]},  # 2nd is wrong
        "orgene.code.tuple_key_indexing": {"active": ["x", "y"], "inactive": ["z", "w"]},  # gene has no rule
    }}
    problems = F.check_activation_examples(store, doc, LEX)
    assert any("bigm_bounded" in p and "inactive[1]" in p for p in problems)
    assert any("binary_cardinality_linked" in p and "needs >= 2" in p for p in problems)
    assert any("tuple_key_indexing" in p and "no gene with a non-trivial" in p for p in problems)
    ok = {"genes": {
        "orgene.numeric.bigm_bounded": {
            "active": ["Trucks come in whole units only.", "A set-up cost of 80 is charged per run."],
            "inactive": ["Blend two oils freely.", "Minimize the cost of the diet."]},
        "orgene.model.binary_cardinality_linked": {
            "active": ["Decide whether to open the plant.", "Select two of the sites."],
            "inactive": ["Blend two oils freely.", "Minimize the cost of the diet."]},
    }}
    assert F.check_activation_examples(store, ok, LEX) == []


# ----------------------------------------------------------------------------- version rule


def test_parse_version():
    assert parse_version("1.0.1") == (1, 0, 1) and parse_version("1.10.0") > parse_version("1.9.9")
    for bad in ("1.0", "1.0.0-rc1", "v1.0.0", "1..0"):
        with pytest.raises(ValueError):
            parse_version(bad)


def _store():
    return [copy.deepcopy(g) for g in G.load_store(R1_GENES)]


def _set(store, gid, **kw):
    for g in store:
        if g["geneId"] == gid:
            g.update(kw)
    return store


def test_version_rule_accepts_an_identical_library_and_a_proper_bump():
    prev = _store()
    assert compare_stores(prev, _store())["ok"]
    new = _set(_store(), "orgene.numeric.bigm_bounded", version="1.1.0",
               activation={"rule": R_INT, "rationale": "integer models only"})
    res = compare_stores(prev, new)
    assert res["ok"] and res["bumped"] == ["orgene.numeric.bigm_bounded@1.0.0->1.1.0"]
    new.append(dict(copy.deepcopy(new[0]), geneId="orgene.new.gene", version="1.0.0"))
    assert compare_stores(prev, new)["added"] == ["orgene.new.gene@1.0.0"]


def test_version_rule_rejects_a_change_without_a_bump():
    prev = _store()
    old = {g["geneId"]: g for g in prev}["orgene.numeric.bigm_bounded"]
    assert old["validation"]["severity"] == "soft"
    new = _set(_store(), "orgene.numeric.bigm_bounded", validation=dict(old["validation"], severity="hard"))
    res = compare_stores(prev, new)
    assert not res["ok"] and any("bigm_bounded 1.0.0: content changed (validation)" in p for p in res["problems"])


def test_version_rule_rejects_an_activation_added_without_a_bump():
    res = compare_stores(_store(), _set(_store(), "orgene.numeric.bigm_bounded", activation={"rule": R_INT}))
    assert not res["ok"] and any("content changed (activation)" in p for p in res["problems"])


@pytest.mark.parametrize("new_version,msg", [("0.9.0", "not higher"), ("1.0.1", "without a content change")])
def test_version_rule_rejects_bad_bumps(new_version, msg):
    res = compare_stores(_store(), _set(_store(), "orgene.numeric.bigm_bounded", version=new_version))
    assert not res["ok"] and any(msg in p for p in res["problems"])


def _add_version(store, gid, version, **changes):
    g = copy.deepcopy({x["geneId"]: x for x in store}[gid])
    g.update(version=version, **changes)
    store.append(g)
    return store


def test_version_rule_checks_new_versions_kept_next_to_the_released_one():
    """A new version added while the released one stays in the library obeys the same rule as a replacement."""
    gid = "orgene.numeric.bigm_bounded"
    same = compare_stores(_store(), _add_version(_store(), gid, "1.0.1"))
    assert not same["ok"] and any("without a content change" in p for p in same["problems"])
    lower = compare_stores(_store(), _add_version(_store(), gid, "0.9.0", activation={"rule": R_INT}))
    assert not lower["ok"] and any("not higher" in p for p in lower["problems"])
    good = compare_stores(_store(), _add_version(_store(), gid, "1.1.0", activation={"rule": R_INT}))
    assert good["ok"] and good["bumped"] == [f"{gid}@1.0.0->1.1.0"] and f"{gid}@1.0.0" in good["unchanged"]


def test_version_rule_rejects_removal_and_malformed_versions():
    new = [g for g in _store() if g["geneId"] != "orgene.numeric.bigm_bounded"]
    assert any("removed" in p for p in compare_stores(_store(), new)["problems"])
    res = compare_stores(_store(), _set(_store(), "orgene.numeric.bigm_bounded", version="1.1"))
    assert any("MAJOR.MINOR.PATCH" in p for p in res["problems"])


@pytest.mark.skipif(not os.path.exists(V1_GENES), reason="releases/v1.0 is not in the anonymous repository")
def test_working_library_follows_the_version_rule_against_v1():
    res = compare_stores(G.load_store(V1_GENES), G.load_store(R1_GENES))
    assert res["ok"], res["problems"]
    assert any(b.startswith("orgene.objective.aggregates_declared_variables@1.0.0->") for b in res["bumped"])


@pytest.mark.skipif(not os.path.exists(V1_GENES), reason="releases/v1.0 is not in the anonymous repository")
def test_version_tool_exit_codes(tmp_path, capsys):
    import check_gene_versions as T
    assert T.main(["--prev", V1_GENES, "--new", R1_GENES]) == 0
    bad = write_store(tmp_path / "bad.jsonl",
                      _set(_store(), "orgene.numeric.bigm_bounded", activation={"rule": R_INT}))
    assert T.main(["--prev", V1_GENES, "--new", bad]) == 1
    out = capsys.readouterr().out
    assert "/" + "Users" + "/" not in out
