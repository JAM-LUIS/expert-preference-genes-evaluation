#!/usr/bin/env python3
"""Build the blind re-derivation package and the hidden reference file (agent double re-derivation, 2026-09-29).

  python3 build_blind_package.py              # verify sources, build everything, write all manifests
  python3 build_blind_package.py --check      # verify sources and rebuild in memory; compare with what is on disk
  python3 build_blind_package.py --manifest-only   # refresh MANIFEST.sha256 files after editing a hand-written file

ISOLATION: this script reads problem statements (incl. TEST statements) and reference answers. It prints ids, counts,
hashes and booleans only. It never writes a reference answer into stage1/annotation_agent/; reference answers go only
to stage1/annotation_agent_hidden/references.json.

Statement source of truth: the R1 neutral cases files (Mac Studio ~/ORgene-R1/data/cases/, commit 1825ea5, copied
read-only to annotation_agent_hidden/source_cases/). Verified byte for byte against stage0/data/v5_copy/cases/, the
annotation packet (csv, xlsx, html) and the official releases (IndustryOR HF b008119, MAMO @2c91069).

Outputs
  stage1/annotation_agent/
    case_set.json                      125 case ids with benchmark, split, needs_reference_check, needs_type_label,
                                       statement sha256 (no answers)
    groups.json                        batch A / B partitions (8 groups each), seeds, method
    batch_A/A01..A08/, batch_B/B01..B08/
        <case_id>.txt                  exact statement bytes (read-only)
        REDERIVATION_INSTRUCTIONS.md   master instructions + group appendix (read-only)
        MANIFEST.sha256
    MANIFEST.sha256 (every directory)
  stage1/annotation_agent_hidden/
    references.json                    reference per case (b008119 / Mamo@2c91069) + older-release answers
    MANIFEST.sha256 (every directory)
"""
import argparse
import csv
import html
import json
import os
import re
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

R1 = C.R1_LOCAL
S0D = os.path.join(R1, "stage0", "data")
S1D = os.path.join(R1, "stage1", "data")
PACKET = os.path.join(R1, "stage1", "annotation_packet")
PKG = C.PKG
HID = C.HIDDEN_DEFAULT

# pinned inputs (sha256)
PIN = {
    "hidden/source_cases/industryor.jsonl": "13ae3ea9a4c13482904b2cc1ca3e80440ece10140dfa27af3b72a72d11adcec6",
    "hidden/source_cases/mamo_complex_lp.jsonl": "743b6c1ed2179a77b5943b57ce24956831d6edf3a6aa206cbbf045e4497b009a",
    "stage0/data/v5_copy/cases/industryor.jsonl": "7817c234a9af88c02ae01d51caf74479220131b6233a1c68c00656bd241538dd",
    "stage0/data/v5_copy/cases/mamo_complex_lp.jsonl": "10b91fd35521011a06af46d9211525dd7a4247b948fd686ebccc61c1aea83484",
    "stage0/data/raw/official_orig/IndustryOR.json": "5b889e49d9aa64ae5b368bc80a05ee71a1daf20d126f54efc6207c98f9095f36",
    "stage0/data/raw/official_orig/mamo_complex_lp.jsonl": "07eb3db3d2af099871dfa4425b14887775179c158c38944fe4fe152b615bbfc3",
    "stage0/data/raw/industryor_hf_revisions/IndustryOR.e1bb6174927454e8d66aebe5c512857e2eb0a031.json":
        "756549264386d9c28f3bf15b442e4d45e345f809155f7c7951c9b7edfd25ee8b",
    "stage0/data/raw/industryor_hf_revisions/IndustryOR.bd09345a7fbbadedb900b0776e258c445d2cabf2.json":
        "cf725d3255de794ad335ba40c4110c66bb67be2e6c6e4def7b7f531220a8850e",
    "stage1/data/analysis_sets.json": "6baf6b7f8678e78f12884f5775ebbfda8d4b396e9b793abee6133f1462a5205d",
    "stage1/data/reference_check_sample.json": "d70ea6ae445f7e720cbdeccde10c8dedb5b229fea8f6ed5f40d6befebf50e1ad",
}
R1_COMMIT = "1825ea59770b4473cdd45c63f595042197405aa2"
IOR_REV = "b00811923f167cdf4ae1677c33cd61d4eea78f48"
MAMO_COMMIT = "2c91069dee5c1e4db4b899eb176ec987d0251bb3"
BENCH_LABEL = {"industryor": f"IndustryOR (HF CardinalOperations/IndustryOR, revision {IOR_REV[:7]}, 2026-05-03)",
               "mamo_complex_lp": f"MAMO ComplexLP (FreedomIntelligence/Mamo@{MAMO_COMMIT[:7]})"}

CHECKS = []


def check(name, ok):
    CHECKS.append((name, bool(ok)))
    if not ok:
        print(f"FAIL: {name}")
    return ok


def p(rel):
    if rel.startswith("hidden/"):
        return os.path.join(HID, rel[len("hidden/"):])
    return os.path.join(R1, rel)


def read_lines(path):
    with open(path, "rb") as f:
        return f.read().split(b"\n")


def load_cases_file(path):
    hdr, recs = None, {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("_header"):
                hdr = r
            else:
                recs[r["case_id"]] = r
    return hdr, recs


def load_json_any(path):
    s = open(path, encoding="utf-8").read()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return [json.loads(x) for x in s.splitlines() if x.strip()]


# ------------------------------------------------------------------ verification of statement sources

def verify_sources():
    for rel, h in PIN.items():
        check(f"pinned sha256 {rel}", C.sha256_file(p(rel)) == h)

    r1 = {s: load_cases_file(p(f"hidden/source_cases/{s}.jsonl")) for s in ("industryor", "mamo_complex_lp")}
    v5 = {s: load_cases_file(p(f"stage0/data/v5_copy/cases/{s}.jsonl")) for s in ("industryor", "mamo_complex_lp")}
    for s in r1:
        check(f"{s}: R1 header source", r1[s][0]["source"] == s)
        check(f"{s}: R1 record count", len(r1[s][1]) == {"industryor": 100, "mamo_complex_lp": 211}[s])
        a = read_lines(p(f"hidden/source_cases/{s}.jsonl"))
        b = read_lines(p(f"stage0/data/v5_copy/cases/{s}.jsonl"))
        check(f"{s}: R1 lines 2.. byte-identical to v5_copy", a[1:] == b[1:])
        check(f"{s}: same case ids R1/v5", set(r1[s][1]) == set(v5[s][1]))
        check(f"{s}: statement text and reference identical R1/v5 (all cases)",
              all(r1[s][1][c]["text"] == v5[s][1][c]["text"] and r1[s][1][c]["reference"] == v5[s][1][c]["reference"]
                  for c in r1[s][1]))
    cases = {**r1["industryor"][1], **r1["mamo_complex_lp"][1]}

    # official releases
    off_ior = {int(r["id"]): r for r in load_json_any(p("stage0/data/raw/official_orig/IndustryOR.json"))}
    e1b = {int(r["id"]): r for r in load_json_any(
        p("stage0/data/raw/industryor_hf_revisions/IndustryOR.e1bb6174927454e8d66aebe5c512857e2eb0a031.json"))}
    off_mamo = {int(r["id"]): r for r in load_json_any(p("stage0/data/raw/official_orig/mamo_complex_lp.jsonl"))}
    o24 = load_json_any(p("stage0/data/raw/industryor_hf_revisions/IndustryOR.bd09345a7fbbadedb900b0776e258c445d2cabf2.json"))
    stats = {"ior_exact": 0, "ior_strip": 0, "mamo_exact": 0, "mamo_strip": 0}
    for c, r in r1["industryor"][1].items():
        o = off_ior[int(r["source_id"])]
        if r["text"] == o["en_question"]:
            stats["ior_exact"] += 1
        elif r["text"].strip() == o["en_question"].strip():
            stats["ior_strip"] += 1
        check(f"{c}: reference equals b008119 en_answer",
              r["reference"]["raw"] == str(o["en_answer"]).strip() or r["reference"]["objective"] == float(o["en_answer"]))
    check("IndustryOR: 100/100 statements equal b008119 en_question (exact or up to outer whitespace)",
          stats["ior_exact"] + stats["ior_strip"] == 100)
    # b008119 vs e1bb617: statements identical, 7 answers differ beyond the primary tolerance (known)
    diff7 = sorted(f"industryor-{i:04d}" for i in off_ior
                   if not C.within(float(e1b[i]["en_answer"]), float(off_ior[i]["en_answer"])))
    check("IndustryOR: e1bb617 statements identical to b008119 (100/100)",
          all(e1b[i]["en_question"] == off_ior[i]["en_question"] for i in off_ior))
    check("IndustryOR: 7 answers differ between e1bb617 and b008119 (0001 0007 0022 0029 0040 0091 0098)",
          diff7 == [f"industryor-{i:04d}" for i in (1, 7, 22, 29, 40, 91, 98)])
    check("IndustryOR: R1 references follow b008119 on those 7 cases (not e1bb617)",
          all(cases[c]["reference"]["objective"] == float(off_ior[int(c[-4:])]["en_answer"]) for c in diff7))
    norm = lambda t: " ".join(t.split())
    s24 = {norm(o["en_question"]) for o in o24}
    stats["ior_equal_2024_statement"] = sum(norm(r["text"]) in s24 for r in r1["industryor"][1].values())
    for c, r in r1["mamo_complex_lp"][1].items():
        o = off_mamo[int(r["source_id"])]
        if r["text"] == o["Question"]:
            stats["mamo_exact"] += 1
        elif r["text"].strip() == o["Question"].strip():
            stats["mamo_strip"] += 1
    check("MAMO: 211/211 statements equal Mamo@2c91069 Question (exact or up to outer whitespace)",
          stats["mamo_exact"] + stats["mamo_strip"] == 211)
    return cases, off_ior, e1b, o24, stats, diff7


def verify_packet(cases, union_ids, ref_ids, ior_ids):
    """Statements in the old annotation packet (csv, xlsx, html) equal the R1 statements."""
    out = {}

    def csv_rows(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            rd = csv.reader(f)
            hdr = [h.split("｜")[0].strip() for h in next(rd)]
            return [dict(zip(hdr, r)) for r in rd]

    for who in ("A", "B"):
        rows = csv_rows(os.path.join(PACKET, "a_industryor_type", "csv", f"industryor_type_annotation_{who}.csv"))
        ok = len(rows) == 100 and {r["case_id"] for r in rows} == ior_ids and all(
            r["problem_text"] == cases[r["case_id"]]["text"] for r in rows)
        out[f"packet a csv {who}"] = check(f"packet (a) csv {who}: 100 statements byte-identical", ok)
        rows = csv_rows(os.path.join(PACKET, "b_reference_check", "csv", f"reference_check_{who}.csv"))
        ok = len(rows) == 66 and {r["case_id"] for r in rows} == ref_ids and all(
            r["problem_text"] == cases[r["case_id"]]["text"] and r["reference_answer"] == cases[r["case_id"]]["reference"]["raw"]
            for r in rows)
        out[f"packet b csv {who}"] = check(f"packet (b) csv {who}: 66 statements byte-identical", ok)
    try:
        from openpyxl import load_workbook
        for sub, fn, n, col, ids in (("a_industryor_type", "industryor_type_annotation_{}.xlsx", 100, 2, ior_ids),
                                     ("b_reference_check", "reference_check_{}.xlsx", 66, 4, ref_ids)):
            for who in ("A", "B"):
                ws = load_workbook(os.path.join(PACKET, sub, fn.format(who)), read_only=True)["annotation"]
                rows = list(ws.iter_rows(min_row=2, values_only=True))
                ok = len(rows) == n and {r[0] for r in rows} == ids and all(r[col - 1] == cases[r[0]]["text"] for r in rows)
                out[f"packet {sub} xlsx {who}"] = check(f"packet {sub} xlsx {who}: {n} statements byte-identical", ok)
    except ImportError:
        check("openpyxl available for the xlsx comparison", False)
    pat = re.compile(r"<div class='case' id='([^']*)'><h2>[^<]*</h2><div class='sub'>[^<]*</div><pre>(.*?)</pre></div>", re.S)
    for sub, fn, n, ids in (("a_industryor_type", "industryor_problems_readable.html", 100, ior_ids),
                            ("b_reference_check", "reference_check_problems_readable.html", 66, ref_ids)):
        s = open(os.path.join(PACKET, sub, fn), encoding="utf-8").read()
        items = pat.findall(s)
        ok = len(items) == n and {html.unescape(c) for c, _ in items} == ids and all(
            html.unescape(t) == cases[html.unescape(c)]["text"] for c, t in items)
        out[f"packet {sub} html"] = check(f"packet {sub} html: {n} statements byte-identical", ok)
    return out


# ------------------------------------------------------------------ case set, groups, references

def build_case_set():
    sets = C.load_json(p("stage1/data/analysis_sets.json"))["sets"]
    sample = C.load_json(p("stage1/data/reference_check_sample.json"))
    split = {}
    for name in ("industryor_main_rev2026_100", "mamo_sensitivity_full211"):
        for side in ("dev", "test"):
            for c in sets[name][side]:
                split[c] = side
    ref_ids = {r["case_id"] for r in sample["rows"]}
    ior_ids = set(sets["industryor_main_rev2026_100"]["dev"] + sets["industryor_main_rev2026_100"]["test"])
    check("reference-check sample: 66 rows, 66 distinct ids", sample["n_rows"] == 66 and len(ref_ids) == 66)
    check("sample split column matches analysis_sets", all(split[r["case_id"]] == r["split"] for r in sample["rows"]))
    union = sorted(ref_ids | ior_ids)
    bench = lambda c: c.rsplit("-", 1)[0]
    entries = [{"case_id": c, "benchmark": bench(c), "split": split[c],
                "needs_reference_check": c in ref_ids, "needs_type_label": c in ior_ids} for c in union]
    return entries, sample, ref_ids, ior_ids


def partition(ids, seed, n_groups):
    order = sorted(ids, key=lambda c: C.rank_hash(seed, c))
    base, extra = divmod(len(order), n_groups)
    sizes = [base + (1 if i < extra else 0) for i in range(n_groups)]
    out, k = [], 0
    for s in sizes:
        out.append(order[k:k + s])
        k += s
    return out


def build_groups(entries):
    ids = [e["case_id"] for e in entries]
    groups = {}
    for b in C.BATCHES:
        parts = partition(ids, C.GROUP_SEEDS[b], C.N_GROUPS)
        groups[b] = {f"{b}{i + 1:02d}": sorted(g) for i, g in enumerate(parts)}
    for b in C.BATCHES:
        flat = [c for g in groups[b].values() for c in g]
        check(f"batch {b}: groups partition the 125 cases", sorted(flat) == sorted(ids) and len(flat) == len(set(flat)))
        check(f"batch {b}: group sizes 15-16", all(len(g) in (15, 16) for g in groups[b].values()))
    a_sets = {frozenset(g) for g in groups["A"].values()}
    check("batch A and B partitions differ (no identical group)", not any(frozenset(g) in a_sets for g in groups["B"].values()))
    overlap = max(len(set(ga) & set(gb)) for ga in groups["A"].values() for gb in groups["B"].values())
    pair_a = {(x, y) for g in groups["A"].values() for x in g for y in g if x < y}
    pair_b = {(x, y) for g in groups["B"].values() for x in g for y in g if x < y}
    return groups, {"max_overlap_between_an_A_group_and_a_B_group": overlap,
                    "case_pairs_together_in_A": len(pair_a), "case_pairs_together_in_B": len(pair_b),
                    "case_pairs_together_in_both": len(pair_a & pair_b)}


def build_references(entries, cases, off_ior, e1b, o24, sample, diff7):
    comp = {r["case_id"]: r for r in csv.DictReader(open(p("stage0/data/case_comparison.csv"), encoding="utf-8-sig"))}
    mapd = {r["case_id"]: r for r in csv.DictReader(open(p("stage0/data/case_mapping_detail.csv"), encoding="utf-8-sig"))}
    forced24 = sample["forced_industryor"]
    forced25 = sample["forced_industryor_rev_e1bb617_b008119"]
    refs = {}
    for e in entries:
        c = e["case_id"]
        r = cases[c]
        refs[c] = {**e, "source_id": r["source_id"], "reference": dict(r["reference"]), "other_releases": []}
    for c in forced24:
        d = mapd[c]
        i = int(d["orig2024_index"])
        ans24 = str(o24[i]["en_answer"]).strip()
        check(f"{c}: 2024 answer (HF bd09345) equals LLM4OR-clean answer in case_comparison.csv",
              C.num(ans24) == C.num(comp[c]["ref_new"]))
        check(f"{c}: 2024 answer differs from the 2026 reference beyond tolerance",
              not C.within(C.num(ans24), cases[c]["reference"]["objective"]))
        refs[c]["other_releases"].append({
            "release": "IndustryOR first release, HF revision bd09345a (2024-05-29)", "answer_raw": ans24,
            "statement": "worded differently from the 2026 statement (the 2026 revision rewrote all statements)",
            "lineage_match_confidence": d["match_conf"],
            "lineage_note": "matched by stage0/data/scripts/build_comparison.py; 'medium' matches need human confirmation"})
    check("the 6 addendum cases + industryor-0040 are exactly the 7 e1bb617/b008119 answer changes",
          sorted(set(forced25) | {"industryor-0040"}) == diff7)
    for c in diff7:
        i = int(cases[c]["source_id"])
        ans = str(e1b[i]["en_answer"]).strip()
        check(f"{c}: e1bb617 answer differs from b008119 beyond tolerance", not C.within(C.num(ans), cases[c]["reference"]["objective"]))
        refs[c]["other_releases"].append({
            "release": "IndustryOR HF revision e1bb6174 (2025-10-11)", "answer_raw": ans,
            "statement": "identical to the 2026 statement; the dataset authors changed this answer in revision b008119 (2026-05-03)"})
    # packet consistency: the packet's other_release_answer column = the 2024 answer for the 10 forced cases
    with open(os.path.join(PACKET, "b_reference_check", "csv", "reference_check_A.csv"), encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        hdr = [h.split("｜")[0].strip() for h in next(rd)]
        prow = {r[0]: dict(zip(hdr, r)) for r in rd}
    check("packet other_release_answer = 2024 answer for the 10 forced cases, empty elsewhere",
          all((C.num(prow[c]["other_release_answer"]) == C.num(next(x["answer_raw"] for x in refs[c]["other_releases"]
                                                                   if x["release"].startswith("IndustryOR first release"))))
              if c in forced24 else prow[c]["other_release_answer"] == "" for c in prow))
    return refs


# ------------------------------------------------------------------ writing

APPENDIX = """

---

## 本组信息（由 scripts/build_blind_package.py 生成）

- 组名：{group}（第 {batch} 批）
- 本组目录（只能读写这个目录）：`{path}`
- 本组题数：{n}（其中 industryor 题 {n_ior} 道，要标题型；mamo_complex_lp 题 {n_mamo} 道，不用标题型）
- 完成标志：`results.jsonl` 共 {n} 行，题号与下表一一对应；`models/` 里每题至少有一个 `.py` 和一个 `.out.txt`。

| # | 题号（题面文件 = 题号 + .txt） | 要标题型 |
|---|---|---|
{rows}
"""


def make_readonly(path):
    os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def write_file(path, data, readonly=False):
    if os.path.exists(path):
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    with open(path, "wb") as f:
        f.write(data)
    if readonly:
        make_readonly(path)


def group_payload(batch, group, ids, cases, master):
    gdir = C.group_dir(PKG, batch, group)
    rows = "\n".join(f"| {i + 1} | `{c}` | {'是' if c.startswith('industryor-') else '否'} |" for i, c in enumerate(ids))
    n_ior = sum(c.startswith("industryor-") for c in ids)
    instr = master + APPENDIX.format(group=group, batch=batch, path=gdir + "/", n=len(ids), n_ior=n_ior,
                                     n_mamo=len(ids) - n_ior, rows=rows)
    files = {f"{c}.txt": cases[c]["text"].encode("utf-8") for c in ids}
    files["REDERIVATION_INSTRUCTIONS.md"] = instr.encode("utf-8")
    return gdir, files


def all_manifest_dirs():
    dirs = [PKG, os.path.join(PKG, "scripts")]
    for b in C.BATCHES:
        bd = os.path.join(PKG, f"batch_{b}")
        if os.path.isdir(bd):
            dirs.append(bd)
            dirs += [os.path.join(bd, g) for g in sorted(os.listdir(bd)) if os.path.isdir(os.path.join(bd, g))]
    dirs += [HID] + [os.path.join(HID, d) for d in ("source_cases",) if os.path.isdir(os.path.join(HID, d))]
    return dirs


def write_all_manifests():
    for d in all_manifest_dirs():
        mp = os.path.join(d, C.MANIFEST)
        if os.path.exists(mp):
            os.chmod(mp, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    n = {}
    # innermost first so that outer manifests are written after inner ones (outer manifests skip MANIFEST files anyway)
    for d in sorted(all_manifest_dirs(), key=lambda x: -x.count(os.sep)):
        n[os.path.relpath(d, os.path.dirname(PKG))] = C.write_manifest(d)
        if os.path.basename(os.path.dirname(d)).startswith("batch_"):
            make_readonly(os.path.join(d, C.MANIFEST))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify and compare with the files on disk; write nothing")
    ap.add_argument("--manifest-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="rebuild even if a group directory already holds agent outputs")
    a = ap.parse_args()
    if a.manifest_only:
        for k, v in write_all_manifests().items():
            print(f"MANIFEST {k}: {v} files")
        return 0

    cases, off_ior, e1b, o24, st, diff7 = verify_sources()
    entries, sample, ref_ids, ior_ids = build_case_set()
    union = {e["case_id"] for e in entries}
    verify_packet(cases, union, ref_ids, ior_ids)
    groups, gstats = build_groups(entries)
    refs = build_references(entries, cases, off_ior, e1b, o24, sample, diff7)

    counts = {
        "n_cases": len(entries),
        "by_benchmark": {b: sum(e["benchmark"] == b for e in entries) for b in ("mamo_complex_lp", "industryor")},
        "by_benchmark_split": {f"{b}/{s}": sum(e["benchmark"] == b and e["split"] == s for e in entries)
                               for b in ("mamo_complex_lp", "industryor") for s in ("dev", "test")},
        "needs_reference_check": sum(e["needs_reference_check"] for e in entries),
        "needs_type_label": sum(e["needs_type_label"] for e in entries),
        "both_tasks": sum(e["needs_reference_check"] and e["needs_type_label"] for e in entries),
        "reference_check_only": sum(e["needs_reference_check"] and not e["needs_type_label"] for e in entries),
        "type_label_only": sum(e["needs_type_label"] and not e["needs_reference_check"] for e in entries),
        "reference_check_by_benchmark_split": {
            f"{b}/{s}": sum(e["benchmark"] == b and e["split"] == s and e["needs_reference_check"] for e in entries)
            for b in ("mamo_complex_lp", "industryor") for s in ("dev", "test")},
    }
    check("125 cases = MAMO 25 + IndustryOR 100", counts["n_cases"] == 125 and counts["by_benchmark"] ==
          {"mamo_complex_lp": 25, "industryor": 100})
    check("66 reference checks, 100 type labels, 41 both", (counts["needs_reference_check"], counts["needs_type_label"],
                                                             counts["both_tasks"]) == (66, 100, 41))
    for e in entries:
        e["statement_sha256"] = C.sha256_bytes(cases[e["case_id"]]["text"].encode("utf-8"))
    for e in entries:
        refs[e["case_id"]]["statement_sha256"] = e["statement_sha256"]

    case_set = {
        "schema": "orgene-r1/annotation_agent/case_set/v1",
        "created": "2026-09-29",
        "purpose": "agent double re-derivation of all 125 cases: reference-answer check of the 66 sampled cases, full "
                   "screening of the 59 unsampled IndustryOR cases, IndustryOR type labels (100)",
        "statement_source": {"file": "R1 ~/ORgene-R1/data/cases/{industryor,mamo_complex_lp}.jsonl", "r1_commit": R1_COMMIT,
                             "sha256": {"industryor": PIN["hidden/source_cases/industryor.jsonl"],
                                        "mamo_complex_lp": PIN["hidden/source_cases/mamo_complex_lp.jsonl"]},
                             "industryor_release": BENCH_LABEL["industryor"], "mamo_release": BENCH_LABEL["mamo_complex_lp"]},
        "inputs": {"analysis_sets.json": PIN["stage1/data/analysis_sets.json"],
                   "reference_check_sample.json": PIN["stage1/data/reference_check_sample.json"]},
        "counts": counts,
        "cases": entries,
        "note": "no reference answers in this file; statement_sha256 = sha256 of the exact UTF-8 statement bytes "
                "(= the <case_id>.txt problem file)",
    }
    groups_doc = {
        "schema": "orgene-r1/annotation_agent/groups/v1",
        "created": "2026-09-29",
        "method": "per batch: sort the 125 case ids by sha256(f'{seed}|{case_id}') and cut into 8 contiguous groups "
                  "(sizes 16,16,16,16,16,15,15,15); the two batches use different seeds",
        "seeds": C.GROUP_SEEDS,
        "audit_draw": {"reference_check": {"seed": C.REF_AUDIT_SEED, "n": C.N_AUDIT,
                                           "from": "cases auto-settled CORRECT (both batches match the reference)"},
                       "type_label": {"seed": C.TYPE_AUDIT_SEED, "n": C.N_AUDIT,
                                      "from": "IndustryOR cases auto-labelled (A = B in LP/MILP/IP, no LOW type confidence)"},
                       "rule": "rank the eligible cases by sha256(f'{seed}|{case_id}') and take the first n"},
        "comparison_rules": {
            "fixed": "2026-09-29, main session, before any re-derivation result exists",
            "tolerance": "abs(x - ref) <= max(1e-4, 1e-4*abs(ref)) (E13 primary tier); A vs B: the same rule either way",
            "sample": "the 66 cases of stage1/data/reference_check_sample.json: AUTO_CORRECT iff both batches are "
                      "Optimal, within tolerance of the reference, issue NONE, confidence not LOW and their printed "
                      "FINAL_OBJECTIVE matches the reported value; every other case is adjudicated",
            "screening": "the 59 IndustryOR cases outside the sample: adjudicated only if A and B agree with each other "
                         "and neither matches the reference (full-screening finding); otherwise the original reference "
                         "is kept and the case only enters the agreement statistics",
            "type_label": "the 100 IndustryOR cases: AUTO iff A and B give the same label in LP/MILP/IP and neither "
                          "type_confidence is LOW; every other case is adjudicated",
            "adjudicator": "code C (co-author Qi Deng, not involved in gene drafting or review)"},
        "planned_models": {"A": "Fable 5.1", "B": "Opus 5.5"},
        "groups": groups,
        "group_stats": {b: {g: {"n": len(ids), "industryor": sum(c.startswith("industryor-") for c in ids),
                                "mamo_complex_lp": sum(c.startswith("mamo_") for c in ids)}
                            for g, ids in groups[b].items()} for b in C.BATCHES},
        "partition_stats": gstats,
    }
    references = {
        "schema": "orgene-r1/annotation_agent_hidden/references/v1",
        "created": "2026-09-29",
        "WARNING": "reference answers: re-derivation agents and anyone who writes genes must not open this file",
        "source": case_set["statement_source"],
        "other_release_sources": {
            "2024": "stage0/data/raw/industryor_hf_revisions/IndustryOR.bd09345a....json via case_mapping_detail.csv "
                    "orig2024_index (cross-checked against case_comparison.csv ref_new)",
            "2025-10": "stage0/data/raw/industryor_hf_revisions/IndustryOR.e1bb6174....json"},
        "cases": refs,
    }

    master = open(os.path.join(PKG, "REDERIVATION_INSTRUCTIONS.md"), encoding="utf-8").read()
    planned = {}
    for b in C.BATCHES:
        for g, ids in groups[b].items():
            gdir, files = group_payload(b, g, ids, cases, master)
            planned[gdir] = files
    for gdir, files in planned.items():
        for fn, data in files.items():
            if fn.endswith(".txt"):
                check(f"{os.path.basename(gdir)}/{fn}: sha256 = statement_sha256",
                      C.sha256_bytes(data) == next(e["statement_sha256"] for e in entries if f"{e['case_id']}.txt" == fn))

    if a.check:
        same = True
        for gdir, files in planned.items():
            for fn, data in files.items():
                fp = os.path.join(gdir, fn)
                same &= os.path.exists(fp) and open(fp, "rb").read() == data
            extra = {x for x in os.listdir(gdir) if x not in files and x not in (C.MANIFEST,) + C.AGENT_OUTPUTS} \
                if os.path.isdir(gdir) else {"<missing dir>"}
            same &= not extra
        for path, doc in ((os.path.join(PKG, "case_set.json"), case_set), (os.path.join(PKG, "groups.json"), groups_doc),
                          (os.path.join(HID, "references.json"), references)):
            data = (json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
            same &= os.path.exists(path) and open(path, "rb").read() == data
        check("--check: files on disk equal a fresh build", same)
    else:
        for gdir in planned:
            if os.path.isdir(gdir) and any(os.path.exists(os.path.join(gdir, x)) for x in C.AGENT_OUTPUTS) and not a.force:
                sys.exit(f"refusing to rebuild: {os.path.relpath(gdir, PKG)} already holds agent outputs (use --force)")
        for gdir, files in planned.items():
            os.makedirs(gdir, exist_ok=True)
            for fn, data in files.items():
                write_file(os.path.join(gdir, fn), data, readonly=True)
            stale = [x for x in os.listdir(gdir) if x not in files and x not in (C.MANIFEST,) + C.AGENT_OUTPUTS]
            for x in stale:
                fp = os.path.join(gdir, x)
                os.chmod(fp, stat.S_IRUSR | stat.S_IWUSR)
                os.remove(fp)
        C.dump_json(os.path.join(PKG, "case_set.json"), case_set)
        C.dump_json(os.path.join(PKG, "groups.json"), groups_doc)
        rp = os.path.join(HID, "references.json")
        if os.path.exists(rp):
            os.chmod(rp, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        C.dump_json(rp, references)
        make_readonly(rp)
        for k, v in write_all_manifests().items():
            print(f"MANIFEST {k}: {v} files")

    print(json.dumps(counts, indent=1, ensure_ascii=False))
    print("statement match counts:", json.dumps(st))
    print("partition stats:", json.dumps(gstats))
    for b in C.BATCHES:
        print(f"batch {b}:", ", ".join(f"{g}={len(ids)} (ior {sum(c.startswith('industryor-') for c in ids)})"
                                        for g, ids in groups[b].items()))
    n_fail = sum(not ok for _, ok in CHECKS)
    print(f"checks: {len(CHECKS)} run, {len(CHECKS) - n_fail} passed, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
