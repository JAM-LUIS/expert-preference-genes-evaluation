#!/usr/bin/env python3
"""Recompute the v1.0 anchor hashes (gene library, contract, activation digests, system prompts) and the data hashes.

  /opt/homebrew/bin/python3 tools/anchor_hashes.py [--release releases/v1.0] [--genes genes/genes.r1.jsonl] [--check]

Run from anywhere; every path is relative to the repository root and is printed relative. Prints JSON:
  release   : the frozen v1.0 inputs (gene library, conditions/, schema/) under --release, if that directory exists
  working   : the R1 working gene library with the R1 conditions/ (neutral successor of v1.0)
  data      : cases files (whole file and lines 2..), dev/test id hashes recomputed from the id files, SPLIT_LOCK
              consistency, raw benchmark files if present, the under-specification screen file
--check exits 1 unless every release value matches EXPECTED_V1 (the values recorded when v1.0 was frozen).
Only hashes and counts are printed; no case text is read beyond hashing the bytes.
"""
import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import conditions as C  # noqa: E402
from orgene import configs as CF  # noqa: E402
from orgene import genes as G  # noqa: E402
from orgene.conditions import build_system_prompts_v1  # noqa: E402

# Recorded when the v5 gene library 1.0 was frozen (full values where the record has them, else 16-hex prefixes).
EXPECTED_V1 = {
    "gene_store_file_sha256": "dffff83adde65a8b250b74698c99c4a72a77184c7d0de87edce7db1559319d66",
    "contract_sha256": "055f9ab4a7afd87efee79959688c9568899704acab9f1a8787587e2142607102",
    "contract_chars": 5306,
    "n_active": {"C3": 17, "C3L": 13, "C3E": 5},
    "activation_digest": {"C3": "8b58e7ceeeb86ef5", "C3L": "81f05b7b158fb026", "C3E": "806fdb5cc214b4d5"},
    "system_prompt_sha256": {"C0": "dbae2eec5bb77466", "C1": "94c42eedc7d68ca3", "C2": "d59532d6bbebfc8e",
                             "C3": "c432a57891f57280"},
}
EXPECTED_DATA_V5 = {
    "cases_sha256": {"mamo_complex_lp": "10b91fd35521011a06af46d9211525dd7a4247b948fd686ebccc61c1aea83484",
                     "industryor": "7817c234a9af88c02ae01d51caf74479220131b6233a1c68c00656bd241538dd"},
    "dev_sha256": {"mamo_complex_lp": "3e179dd617c2ffb6ec12c4e8a6fc3be96fe84a45a2dc00c3a34343849e3969fb",
                   "industryor": "f45a5a02b8afaf74075c34fdf1b983fb499cf005f1d342f5de3be0c58ad22868"},
    "test_sha256": {"mamo_complex_lp": "b4f0f6c26cdd3f937e5406471ff229e96ca70f1d44c7afe58eefab36c48bdca7",
                    "industryor": "e2233fd44afe90d626734db3807ea6e1efa29052ac43526c8429403585c2ce88"},
    "raw_sha256": {"data/raw/Mamo/data/optimization/Complex_LP/mamo_complex_lp.jsonl":
                   "07eb3db3d2af099871dfa4425b14887775179c158c38944fe4fe152b615bbfc3",
                   "data/raw/industryor/IndustryOR.json":
                   "5b889e49d9aa64ae5b368bc80a05ee71a1daf20d126f54efc6207c98f9095f36"},
    "mamo_underspecified_ids_sha256": "3589315e83e5e2437224e34e262797b3567964b29de90a36bb485fbff29e721a",
}
SOURCES = ("mamo_complex_lp", "industryor")


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def relp(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def gene_side(genes_path, cond_dir):
    store = G.load_store(genes_path)
    out = {"gene_store": relp(genes_path), "conditions_dir": relp(cond_dir),
           "gene_store_file_sha256": sha_file(genes_path), "n_genes": len(store),
           "n_active": {}, "activation_digest": {}}
    for cond in ("C3", "C3L", "C3E"):
        active, _ = G.activate(store, condition=cond)
        out["n_active"][cond] = len(active)
        out["activation_digest"][cond] = G.store_digest(active)
    active, _ = G.activate(store, condition="C3")
    text, info = G.compile_contract(active)
    out["contract_sha256"] = info["contract_sha256"]
    out["contract_chars"] = len(text)
    prompts, pinfo = build_system_prompts_v1(cond_dir, genes_path)
    out["system_prompt_sha256"] = {k: pinfo["system_prompt_sha256"][k] for k in ("C0", "C1", "C2", "C3", "C3L", "C3E")}
    out["system_prompt_chars"] = {k: pinfo["system_prompt_chars"][k] for k in ("C0", "C1", "C2", "C3", "C3L", "C3E")}
    out["c1_c3_char_ratio"] = pinfo["c1_c3_char_ratio"]
    out["c3l_c3e_prompt_equals_c0"] = prompts["C3L"] == prompts["C0"] == prompts["C3E"]
    return out


def config_anchors(genes_path, cond_dir, configs_path, lexicon_path=None):
    """Gene anchors of every registered configuration, for the freeze manifest (configs/freeze_spec.json
    `gene_anchors`; engineering plan 5.3 "activation-set digest of each configuration", E21 verification 4.3).

    Per configuration: prompt, validator, gene scope, activation mode, repair, pipeline; the scope's gene set with
    every rule ignored (n_scope_genes, scope_gene_set_digest: the library-level record); activation_digest, equal
    to the scope digest when the configuration activates the whole scope and None when it activates per problem
    (those sets follow from the scope set, the activation lexicon and features.py, all frozen, and every request
    records its own in meta.gene_set_digest); system_prompt_sha256 when the system prompt does not depend on the
    case (None for the per-problem C3 and C0R prompts and for pipelines with their own stage prompts); for a C0R
    configuration also the scope its contract is compiled from (contract_scope, contract_scope_gene_set_digest). Plus the C3 contract
    with every gene of scope C3 active. Genes are always activated with mode "all" here, so a library with
    per-problem rules is anchored without problem features.
    """
    store = G.load_store(genes_path, lexicon=lexicon_path)  # the it1 library needs its lexicon (v2)
    reg = CF.load_registry(configs_path)
    T = C.load_templates(cond_dir)
    out = {"gene_store": relp(genes_path), "gene_store_file_sha256": sha_file(genes_path), "n_genes": len(store),
           "conditions_dir": relp(cond_dir), "config_registry": relp(configs_path),
           "config_registry_sha256": sha_file(configs_path), "configs": {}}
    pool_c3, _, _ = C.activate_for(store, "C3", "all")
    text, info = G.compile_contract(pool_c3)
    out["c3_all_active"] = {"n_active": len(pool_c3), "gene_set_digest": G.store_digest(pool_c3),
                            "contract_sha256": info["contract_sha256"], "contract_chars": len(text)}
    for cid, c in sorted(reg["configs"].items()):
        pipeline = c.get("pipeline") or "standard"
        rec = {"prompt": c["prompt"], "validator": c["validator"], "gene_scope": c["gene_scope"],
               "activation": c["activation"], "repair": c["repair"], "pipeline": pipeline}
        if c["gene_scope"] is None or c["activation"] == "none":
            rec.update(n_scope_genes=0, scope_gene_set_digest=None, activation_digest=None)
        else:
            pool, _, _ = C.activate_for(store, c["gene_scope"], "all")
            d = G.store_digest(pool)
            rec.update(n_scope_genes=len(pool), scope_gene_set_digest=d,
                       activation_digest=d if c["activation"] == "all" else None)
        if c.get("contract_scope"):
            # C0R (D12): the contract in the prompt comes from its own scope, activated per problem
            cpool, _, _ = C.activate_for(store, c["contract_scope"], "all")
            rec.update(contract_scope=c["contract_scope"], contract_scope_gene_set_digest=G.store_digest(cpool))
        if pipeline != "standard" or (c["prompt"] == "C3" and c["activation"] == "per_problem") or c["prompt"] == "C0R":
            rec["system_prompt_sha256"] = None
        else:
            # C0, C1, C2 prompts carry no contract, so the activation mode does not change them
            cfg = c if c["prompt"] == "C3" else dict(c, activation="all")
            _, meta = C.build_prompt(cfg, None, store, templates=T)
            rec["system_prompt_sha256"] = meta["system_prompt_sha256"]
        out["configs"][cid] = rec
    return out


def data_side():
    out = {"cases": {}, "splits": {}, "raw": {}}
    for s in SOURCES + ("smoke",):
        p = os.path.join(ROOT, "data", "cases", f"{s}.jsonl")
        if not os.path.exists(p):
            continue
        data = open(p, "rb").read()
        nl = data.find(b"\n")
        out["cases"][s] = {"path": relp(p), "sha256": hashlib.sha256(data).hexdigest(),
                           "lines2plus_sha256": hashlib.sha256(data[nl + 1:]).hexdigest()}
    for s in SOURCES:
        d = os.path.join(ROOT, "data", "splits", s)
        lock_p = os.path.join(d, "SPLIT_LOCK.json")
        if not os.path.exists(lock_p):
            continue
        lock = json.load(open(lock_p, encoding="utf-8"))
        dev = json.load(open(os.path.join(d, "dev_ids.json"), encoding="utf-8"))
        test = json.load(open(os.path.join(d, "test_ids.json"), encoding="utf-8"))
        cp = lock["cases_path"] if os.path.isabs(lock["cases_path"]) else os.path.join(ROOT, lock["cases_path"])
        out["splits"][s] = {
            "lock_sha256": sha_file(lock_p),
            "cases_path_is_relative": not os.path.isabs(lock["cases_path"]),
            "cases_sha256_lock": lock["cases_sha256"],
            "cases_sha256_matches_file": os.path.exists(cp) and sha_file(cp) == lock["cases_sha256"],
            "dev_sha256": hashlib.sha256(json.dumps(dev).encode()).hexdigest(),
            "test_sha256": hashlib.sha256(json.dumps(test).encode()).hexdigest(),
            "dev_sha256_matches_lock": hashlib.sha256(json.dumps(dev).encode()).hexdigest() == lock["dev_sha256"],
            "test_sha256_matches_lock": hashlib.sha256(json.dumps(test).encode()).hexdigest() == lock["test_sha256"],
            "n_dev": len(dev), "n_test": len(test), "dev_test_disjoint": not (set(dev) & set(test)),
        }
    for rp in EXPECTED_DATA_V5["raw_sha256"]:
        p = os.path.join(ROOT, rp)
        if os.path.exists(p):
            out["raw"][rp] = sha_file(p)
    up = os.path.join(ROOT, "data", "mamo_underspecified_ids.json")
    if os.path.exists(up):
        out["mamo_underspecified_ids_sha256"] = sha_file(up)
    return out


def check_release(rel_side):
    """List of (key, got, want, ok) for the v1.0 anchors; prefixes compare with startswith."""
    rows = []
    e = EXPECTED_V1
    rows.append(("gene_store_file_sha256", rel_side["gene_store_file_sha256"], e["gene_store_file_sha256"]))
    rows.append(("contract_sha256", rel_side["contract_sha256"], e["contract_sha256"]))
    rows.append(("contract_chars", rel_side["contract_chars"], e["contract_chars"]))
    for c, n in e["n_active"].items():
        rows.append((f"n_active.{c}", rel_side["n_active"][c], n))
    for c, d in e["activation_digest"].items():
        rows.append((f"activation_digest.{c}", rel_side["activation_digest"][c], d))
    for c, d in e["system_prompt_sha256"].items():
        rows.append((f"system_prompt_sha256.{c}", rel_side["system_prompt_sha256"][c], d))
    for c in ("C3L", "C3E"):
        rows.append((f"system_prompt_sha256.{c}==C0", rel_side["system_prompt_sha256"][c], rel_side["system_prompt_sha256"]["C0"]))
    out = []
    for k, got, want in rows:
        ok = str(got).startswith(str(want)) if isinstance(want, str) else got == want
        out.append({"key": k, "got": got, "want": want, "ok": ok})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default=os.path.join(ROOT, "releases", "v1.0"))
    ap.add_argument("--genes", default=os.path.join(ROOT, "genes", "genes.r1.jsonl"))
    ap.add_argument("--cond-dir", default=os.path.join(ROOT, "conditions"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    res = {}
    rel_genes = os.path.join(a.release, "genes.v3.jsonl")
    if os.path.exists(rel_genes):
        res["release"] = gene_side(rel_genes, os.path.join(a.release, "conditions"))
        res["release_check"] = check_release(res["release"])
    if os.path.exists(a.genes):
        res["working"] = gene_side(a.genes, a.cond_dir)
    res["data"] = data_side()
    print(json.dumps(res, indent=2, ensure_ascii=False))
    if a.check:
        if "release_check" not in res:
            print("[anchor] release directory not found", file=sys.stderr)
            return 1
        bad = [r for r in res["release_check"] if not r["ok"]]
        print(f"[anchor] release anchors: {len(res['release_check']) - len(bad)}/{len(res['release_check'])} reproduced",
              file=sys.stderr)
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
