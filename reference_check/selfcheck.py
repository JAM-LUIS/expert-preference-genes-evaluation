#!/usr/bin/env python3
"""Self-check of the blind package and the hidden reference file.

  python3 selfcheck.py [--show-hits]

Prints counts, file names and pass/fail only. The hit-by-hit record of the answer-leak scan (which case's answer a
number coincides with) would reveal answers, so it is written only to annotation_agent_hidden/selfcheck/ ;
--show-hits prints it on the console for manual review (coordinator only).

Checks
 1 ids: case_set.json = the 66 sampled cases U the 100 IndustryOR cases (125); flags and counts; groups.json
   partitions the 125 ids in each batch; each group directory holds exactly its <case_id>.txt files,
   REDERIVATION_INSTRUCTIONS.md and MANIFEST.sha256 (plus agent outputs once they exist); problem files read-only.
 2 statements: every <case_id>.txt equals the R1 statement byte for byte; sha256 = case_set.json statement_sha256.
 3 instructions: each group copy = the master file + an appendix whose id table lists exactly the group's ids.
 4 answer-leak scan: every package file (agent outputs excluded) is tokenised into numbers; a number equal to a
   reference answer or an older-release answer of ANY case (absolute value; for answers with 2+ decimals also the value
   rounded to 1 and 2 decimals) is a hit.
   - hit inside a problem file: accepted as "inherent" only if the same number occurs the same number of times in
     that case's statement in the official release file (IndustryOR HF b008119 / MAMO @2c91069), checked hit by hit;
   - hit in any other file: must be covered by the hand-reviewed list annotation_agent_hidden/selfcheck/
     reviewed_tokens.json (value + file patterns + why the number is there); anything not covered fails. The list
     lives in the hidden directory because it says which small numbers coincide with some answer.
   Tokens with a leading zero (the digits of case ids such as 0005) are not numbers here.
 5 text-leak scan: 8-word shingles of every statement (R1 cases, IndustryOR releases 2024-2026, LLM4OR clean) against
   every non-problem file of the package.
 6 manifests: every MANIFEST.sha256 under the package and the hidden directory verifies.
 7 README_ISOLATION.md carries the required sentence.
 8 hidden: references.json covers the 125 ids and equals the R1 cases files; older-release answers present.
"""
import argparse
import fnmatch
import json
import os
import re
import stat
import sys
from decimal import ROUND_HALF_UP, Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

PKG, HID = C.PKG, C.HIDDEN_DEFAULT
S0 = os.path.join(C.R1_LOCAL, "stage0", "data")
REQUIRED_SENTENCE = "写 gene 的人和 agent 不得打开本目录和 hidden 目录"
NUM_RE = re.compile(r"(?<![0-9A-Za-z_.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)(?![0-9A-Za-z_])")
WORD_RE = re.compile(r"[a-z0-9]+")
RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    return cond


def dec(s):
    s = s.replace(",", "")
    if re.match(r"^0\d", s):
        return None                     # digits with a leading zero: an id, not a number
    try:
        return Decimal(s).normalize()
    except Exception:
        return None


def value_forms(raw):
    x = C.num(raw)
    if x is None:
        return set()
    d = Decimal(repr(abs(x)))
    forms = {d.normalize()}
    if -d.as_tuple().exponent >= 2:
        for k in (1, 2):
            forms.add(d.quantize(Decimal(1).scaleb(-k), rounding=ROUND_HALF_UP).normalize())
    return forms


def numbers(text):
    """[(line_no, token, Decimal)] of the numeric tokens in text."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in NUM_RE.finditer(line):
            v = dec(m.group(1))
            if v is not None:
                out.append((i, m.group(1), v))
    return out


def load_any(path):
    s = open(path, encoding="utf-8").read()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return [json.loads(x) for x in s.splitlines() if x.strip()]


def package_files():
    """Package files only: inside a group directory only the problem files, the instructions and the manifest
    (agent outputs and anything else an agent wrote there are never opened)."""
    out = []
    for dp, dns, fns in os.walk(PKG):
        grp = C.in_group_dir(dp)
        dns[:] = [d for d in dns if d not in ("__pycache__", "models") and not d.startswith(".") and not grp]
        for fn in fns:
            if fn.startswith(".") or fn.endswith(".pyc") or fn == "results.jsonl":
                continue
            if grp and not C.GROUP_FILE_RE.match(fn):
                continue
            out.append(os.path.join(dp, fn))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-hits", action="count", default=0,
                    help="print uncovered hits (twice: all hits) with their context; coordinator only")
    a = ap.parse_args()
    cs = C.load_case_set()
    groups = C.load_groups()["groups"]
    refdoc = C.load_references()
    refs = refdoc["cases"]
    texts = C.load_source_texts()
    sets = C.load_json(os.path.join(C.STAGE1, "data", "analysis_sets.json"))["sets"]
    sample = C.load_json(os.path.join(C.STAGE1, "data", "reference_check_sample.json"))

    # ---------------- 1 ids
    ids = [e["case_id"] for e in cs["cases"]]
    sampled = {r["case_id"] for r in sample["rows"]}
    ior = set(sets["industryor_main_rev2026_100"]["dev"] + sets["industryor_main_rev2026_100"]["test"])
    ok("1a case_set: 125 distinct ids = 66 sampled U 100 IndustryOR", len(ids) == len(set(ids)) == 125
       and set(ids) == sampled | ior)
    ok("1b flags: needs_reference_check = sampled, needs_type_label = IndustryOR",
       all(e["needs_reference_check"] == (e["case_id"] in sampled) and e["needs_type_label"] == (e["case_id"] in ior)
           for e in cs["cases"]))
    bm = {b: sum(e["benchmark"] == b for e in cs["cases"]) for b in ("mamo_complex_lp", "industryor")}
    ok("1c counts: MAMO 25 + IndustryOR 100; 66 reference checks; 100 type labels; 41 both",
       bm == {"mamo_complex_lp": 25, "industryor": 100} and sum(e["needs_reference_check"] for e in cs["cases"]) == 66
       and sum(e["needs_type_label"] for e in cs["cases"]) == 100
       and sum(e["needs_reference_check"] and e["needs_type_label"] for e in cs["cases"]) == 41, json.dumps(bm))
    split = {}
    for name in ("industryor_main_rev2026_100", "mamo_sensitivity_full211"):
        for side in ("dev", "test"):
            for c in sets[name][side]:
                split[c] = side
    ok("1d splits equal analysis_sets.json", all(split[e["case_id"]] == e["split"] for e in cs["cases"]))
    for b in C.BATCHES:
        flat = [c for g in groups[b].values() for c in g]
        ok(f"1e batch {b}: {len(groups[b])} groups partition the 125 ids (sizes {sorted({len(g) for g in groups[b].values()})})",
           len(groups[b]) == 8 and sorted(flat) == sorted(ids) and len(set(flat)) == 125)
    ok("1f the two batches use different partitions",
       not ({frozenset(g) for g in groups["A"].values()} & {frozenset(g) for g in groups["B"].values()}))
    dir_ok, ro_ok = True, True
    for b in C.BATCHES:
        bdir = os.path.join(PKG, f"batch_{b}")
        dir_ok &= sorted(x for x in os.listdir(bdir) if not x.startswith(".") and x != C.MANIFEST) == sorted(groups[b])
        for g, gids in groups[b].items():
            gd = C.group_dir(PKG, b, g)
            have = {x for x in os.listdir(gd) if not x.startswith(".")} - set(C.AGENT_OUTPUTS)
            want = {f"{c}.txt" for c in gids} | {"REDERIVATION_INSTRUCTIONS.md", C.MANIFEST}
            dir_ok &= have == want
            for fn in want:
                ro_ok &= not (os.stat(os.path.join(gd, fn)).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    ok("1g each group directory holds exactly its problem files, the instructions and a manifest", dir_ok)
    ok("1h problem files, instructions and group manifests are read-only", ro_ok)

    # ---------------- 2 statements
    sha = {e["case_id"]: e["statement_sha256"] for e in cs["cases"]}
    st_ok, n_files = True, 0
    for b in C.BATCHES:
        for g, gids in groups[b].items():
            for c in gids:
                data = open(os.path.join(C.group_dir(PKG, b, g), f"{c}.txt"), "rb").read()
                n_files += 1
                st_ok &= data == texts[c].encode("utf-8") and C.sha256_bytes(data) == sha[c]
    ok(f"2 {n_files} problem files equal the R1 statements byte for byte (sha256 as in case_set.json)", st_ok and n_files == 250)

    # ---------------- 3 instructions
    master = open(os.path.join(PKG, "REDERIVATION_INSTRUCTIONS.md"), encoding="utf-8").read()
    ins_ok = True
    for b in C.BATCHES:
        for g, gids in groups[b].items():
            s = open(os.path.join(C.group_dir(PKG, b, g), "REDERIVATION_INSTRUCTIONS.md"), encoding="utf-8").read()
            listed = re.findall(r"^\| \d+ \| `([^`]+)` \|", s, re.M)
            ins_ok &= s.startswith(master) and listed == gids and f"组名：{g}（第 {b} 批）" in s
    ok("3 group instructions = master + appendix listing exactly the group's ids", ins_ok)

    # ---------------- 4 answer-leak scan
    forms = {}                      # Decimal form -> [(case_id, kind)]
    for c, r in refs.items():
        for f in value_forms(r["reference"]["raw"]) | value_forms(r["reference"].get("objective")):
            forms.setdefault(f, []).append((c, "reference"))
        for o in r.get("other_releases", []):
            for f in value_forms(o["answer_raw"]):
                forms.setdefault(f, []).append((c, "older_release"))
    off_ior = {int(r["id"]): r["en_question"] for r in load_any(os.path.join(S0, "raw", "official_orig", "IndustryOR.json"))}
    off_mamo = {int(r["id"]): r["Question"] for r in load_any(os.path.join(S0, "raw", "official_orig", "mamo_complex_lp.jsonl"))}
    official = {c: (off_ior if c.startswith("industryor-") else off_mamo)[int(refs[c]["source_id"])] for c in refs}
    problem_hits, other_hits, inherent_ok = [], [], True
    files = package_files()
    for path in files:
        rel = os.path.relpath(path, PKG)
        text = open(path, encoding="utf-8", errors="replace").read()
        toks = [(ln, t, v) for ln, t, v in numbers(text) if v in forms]
        m = re.match(r"^batch_[AB]/[AB]\d\d/((?:industryor|mamo_complex_lp)-\d{4})\.txt$", rel)
        if m:
            cid = m.group(1)
            offn = [v for _, _, v in numbers(official[cid]) if v in forms]
            for ln, t, v in toks:
                same = sum(x == v for x in offn) == sum(x == v for _, _, x in toks)
                inherent_ok &= same
                problem_hits.append({"file": rel, "line": ln, "token": t, "inherent": same,
                                     "matches": forms[v]})
        else:
            for ln, t, v in toks:
                other_hits.append({"file": rel, "line": ln, "token": t, "matches": forms[v],
                                   "context": text.splitlines()[ln - 1][:160]})
    ok(f"4a answer-leak scan of {len(files)} package files: {len(problem_hits)} hits inside problem files, "
       f"all present equally often in the official statement (inherent)", inherent_ok)
    rv_path = os.path.join(HID, "selfcheck", "reviewed_tokens.json")
    reviewed = C.load_json(rv_path)["reviewed"] if os.path.exists(rv_path) else []

    def covered(h):
        v = dec(h["token"])
        return any(dec(r["value"]) == v and any(fnmatch.fnmatch(h["file"], pat) for pat in r["files"]) for r in reviewed)

    for h in other_hits:
        h["reviewed"] = covered(h)
    unrev = [h for h in other_hits if not h["reviewed"]]
    distinct = sorted({(h["file"], h["line"], h["token"]) for h in other_hits})
    ok(f"4b hits outside problem files: {len(distinct)} (file, line, number) places, {len(other_hits) - len(unrev)} hits "
       f"covered by the hand-reviewed list ({len(reviewed)} entries), {len(unrev)} not covered", not unrev,
       " ".join(sorted({f"{h['file']}:{h['line']}" for h in unrev})[:20]))
    os.makedirs(os.path.join(HID, "selfcheck"), exist_ok=True)
    C.dump_json(os.path.join(HID, "selfcheck", "answer_leak_scan.json"),
                {"WARNING": "reveals which answers coincide with numbers in package files; hidden directory only",
                 "problem_file_hits": problem_hits, "other_hits": other_hits})
    if a.show_hits:
        for h in other_hits:
            if not h["reviewed"] or a.show_hits > 1:
                print(f"   {h['file']}:{h['line']} token {h['token']!r} = answer of {[m[0] for m in h['matches']]} | "
                      f"{h['context']}")
    by_value = {}
    for h in other_hits:
        by_value.setdefault("covered" if h["reviewed"] else "NOT covered", set()).add(h["file"])
    print("   files with covered hits:", len(by_value.get("covered", ())), "; files with uncovered hits:",
          len(by_value.get("NOT covered", ())))

    # ---------------- 5 text-leak scan
    stmts = list(texts.values())
    for fn in os.listdir(os.path.join(S0, "raw", "industryor_hf_revisions")):
        if fn.endswith(".json"):
            stmts += [r["en_question"] for r in load_any(os.path.join(S0, "raw", "industryor_hf_revisions", fn))]
    stmts += [r["en_question"] for r in load_any(os.path.join(S0, "raw", "llm4or_clean", "IndustryOR.jsonl"))]
    sh = set()
    for s in stmts:
        w = WORD_RE.findall(s.lower())
        sh |= {" ".join(w[i:i + 8]) for i in range(len(w) - 7)}
    leak = []
    for path in files:
        rel = os.path.relpath(path, PKG)
        if re.match(r"^batch_[AB]/[AB]\d\d/.*\.txt$", rel):
            continue
        w = WORD_RE.findall(open(path, encoding="utf-8", errors="replace").read().lower())
        n = sum(" ".join(w[i:i + 8]) in sh for i in range(len(w) - 7))
        if n:
            leak.append((rel, n))
    ok(f"5 text-leak scan: 8-word shingles of {len(stmts)} statements vs {len(files) - 250} non-problem files: "
       f"{sum(n for _, n in leak)} hits", not leak, " ".join(f"{r}:{n}" for r, n in leak))

    # ---------------- 6 manifests
    mprobs, nman = [], 0
    for root in (PKG, HID):
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in ("__pycache__", "models") and not d.startswith(".")
                      and not C.in_group_dir(dp)]
            if C.MANIFEST in fns:
                nman += 1
                n, pr = C.verify_manifest(dp)
                mprobs += [f"{os.path.relpath(dp, os.path.dirname(PKG))}: {x}" for x in pr]
    ok(f"6 {nman} MANIFEST.sha256 files verify", not mprobs, "; ".join(mprobs[:10]))

    # ---------------- 7 isolation notice
    ri = open(os.path.join(PKG, "README_ISOLATION.md"), encoding="utf-8").read()
    rh = open(os.path.join(HID, "README_ISOLATION.md"), encoding="utf-8").read()
    ok("7 README_ISOLATION.md (package and hidden) carries the required sentence",
       REQUIRED_SENTENCE in ri and REQUIRED_SENTENCE in rh)

    # ---------------- 8 hidden references
    r1 = {}
    for src in ("industryor", "mamo_complex_lp"):
        for line in open(os.path.join(HID, "source_cases", f"{src}.jsonl"), encoding="utf-8"):
            r = json.loads(line)
            if not r.get("_header"):
                r1[r["case_id"]] = r["reference"]
    ok("8a references.json: 125 ids, reference values equal the R1 cases files",
       set(refs) == set(ids) and all(refs[c]["reference"] == r1[c] for c in refs))
    n24 = sum(any(o["release"].startswith("IndustryOR first release") for o in r["other_releases"]) for r in refs.values())
    n25 = sum(any("e1bb6174" in o["release"] for o in r["other_releases"]) for r in refs.values())
    ok("8b older-release answers: 10 cases with the 2024 answer, 7 with the 2025-10 (e1bb617) answer", (n24, n25) == (10, 7))
    ok("8c references.json is read-only", not (os.stat(os.path.join(HID, "references.json")).st_mode
                                              & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)))
    n_fail = sum(not x for _, x in RESULTS)
    print(f"selfcheck: {len(RESULTS)} checks, {len(RESULTS) - n_fail} passed, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
