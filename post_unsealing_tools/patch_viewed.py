import json
p = "tools/run_campaign.py"; s = open(p).read()
a = """    elif set(spec_ids) == {"split", "minus_subset"}:
        drop = set(sub_ids(spec_ids["minus_subset"]))
        ids = [c for c in side_ids(spec_ids["split"]) if c not in drop]
"""
b = a + """    elif set(spec_ids) == {"split", "minus_split_dir"}:
        if spec_ids["split"] != stage["split"]:
            raise ValueError(f"{stage['label']}: a minus_split_dir selector must use the stage's side")
        drop = set(side_ids(spec_ids["split"], spec_ids["minus_split_dir"]))
        ids = [c for c in side_ids(spec_ids["split"]) if c not in drop]
"""
assert s.count(a) == 1; s = s.replace(a, b)
a2 = """                                | {"split": "dev", "minus_subset": "determinism"}
"""
b2 = a2 + """                                | {"split": "test", "minus_split_dir": "data/splits_r1/<other set>"}  # this side
                                                                      # without the ids of another lock's same side
"""
assert s.count(a2) == 1; s = s.replace(a2, b2); open(p, "w").write(s)
env = {"ORGENE_TOOLS_PY": "../../ORgene-R1/.venv-tools/bin/python", "ORGENE_TIKTOKEN_DIR": "../../ORgene-R1/.cache/tiktoken"}
def stage(label, bench, full):
    return {"label": label, "cases": f"data/cases/{bench}.jsonl", "split_dir": f"data/splits_r1/{full}", "split": "test",
            "matrix": f"configs/run_matrix/{label}.json",
            "blocks": [{"registry_entry": "qwen3-8b.main",
                        "ids": {"split": "test", "minus_split_dir": f"data/splits_r1/{full}_excl0905"},
                        "configs": ["C0", "C3E", "C3L"]}],
            "plan": f"configs/run_plans/{label}.plan.json"}
spec = {"schema": "orgene.r1.campaign.v1",
        "about": "Supplementary run, registered and started after the scores of the formal run were unsealed (2026-10-10): "
                 "the nine test problems whose statements were viewed on 2026-09-05 (MAMO ComplexLP 5, IndustryOR 4), which "
                 "the formal run did not include, with the three conditions of the main comparison on qwen3:8b. It supplies "
                 "the preregistered sensitivity analysis that adds these problems back. Post hoc with respect to the "
                 "unsealing; nothing of the formal run is rerun or changed.",
        "seed": 20261010, "genes": "genes/genes.it1.jsonl", "lexicon": "genes/activation_lexicon.v2.json", "env": env,
        "stages": [stage("mamo-viewed0905", "mamo_complex_lp", "mamo_sensitivity_full211"),
                   stage("industryor-viewed0905", "industryor", "industryor_main_rev2026_100")]}
open("configs/campaigns/test_viewed0905_20261010.json", "w").write(json.dumps(spec, indent=1) + "\n")
