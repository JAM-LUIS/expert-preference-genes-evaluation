#!/usr/bin/env python3
"""Set-wise judging for the measurement check (SET_RULE_20261013.md): each block of BLOCK_RULE_20261012 is cut
into sets of three problems (the last set of a block may have two), so that a reviewer can take as little as one
set. Outside the frozen tree; builds on audit/20261012_blocks/blocks.py and changes nothing there.
key.json is never opened.

  sets.py plan    --export DIR [--out sets.json]
  sets.py pack    --export DIR --template EN.xlsx --guide G.pdf --rater R5 --set B4 --out DIR
  sets.py status  --export DIR WORKBOOK [WORKBOOK ...]        which sets each workbook completes
  sets.py merge   --export DIR --template EN.xlsx --label NAME --part B4=W.xlsx --part C=W.xlsx ... --out OUT.xlsx

A --part key is a set (B4) or a block (C, meaning all sets of block C); every set must be covered exactly once.
A source may be a set workbook, a block workbook or a complete one; only the rows of the named sets are taken.
Disagreements are then listed and marked as in blocks.py (frozen 'consensus', then 'blocks.py unresolved').
"""
import argparse
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "20261012_blocks"))
import blocks as B  # noqa: E402

SIZE = 3
DEADLINE = B.DEADLINE


def plan(items):
    """{set name: {block, problems, programs}} in booklet order: A1..A4, B1..B4, C1..C4."""
    progs = {p["problem_id"]: p["programs"] for p in items["problems"]}
    out = {}
    for blk, b in B.plan(items).items():
        ps = b["problems"]
        for j in range(0, len(ps), SIZE):
            g = ps[j:j + SIZE]
            out[f"{blk}{j // SIZE + 1}"] = {"block": blk, "problems": g, "programs": [x for p in g for x in progs[p]]}
    return out


def expand(key, sets):
    if key in sets:
        return [key]
    got = [k for k, v in sets.items() if v["block"] == key]
    if not got:
        raise SystemExit(f"unknown set or block: {key}")
    return got


COVER = """Measurement check: your part (set {name})

Thank you for helping. Besides this note, the folder contains three files.

  reviewer_guide.pdf      the instructions. Sections 3 (keep it blind and independent), 4 (what to judge),
                          5, 6 and 9 (a worked example) are the ones you need.
  booklet_set_{name}.html      your problems and programs. Open it in any web browser.
  judgments_{rater}_set_{name}.xlsx     the workbook to fill in and send back.

Your part is set {name}: problems {first} to {last}, that is {np} problems and {ng} programs. The full sample has
34 problems and 68 programs and is shared among a group of reviewers, so the guide speaks of a larger set.

What differs from the guide for you:
  - You judge only the programs of set {name}. The times in sections 1 and 7 of the guide are for the full
    sample and, we have been told by an experienced modeler, on the low side: a careful judgment can take
    30 to 40 minutes per problem. Please take the time you need. When you send the workbook back, it would
    help us to know roughly how long it took you.
  - Only step 1 applies. There is no discussion with another reviewer (step 2, section 8) and no read-through
    of the modeling rules (step 3, section 10).
  - Everything else is as in the guide: the criteria, the three judgments, the error categories, the notes,
    and section 3 in full. Please work on your own and do not discuss the materials with anyone, since
    other reviewers judge the same programs.

If you have time for more than one set, tell us and we will send another.

Please send the completed workbook back by e-mail to <author e-mail> by {deadline}.
If anything is unclear, please ask at the same address (guide, section 11).
"""


def cmd_plan(a):
    _, items = B.load_items(a.export)
    s = plan(items)
    for k, v in s.items():
        print(f"set {k}: {v['problems'][0]}-{v['problems'][-1]}, {len(v['problems'])} problems, "
              f"{len(v['programs'])} programs")
    assert [x for v in s.values() for x in v["programs"]] == [x for p in items["problems"] for x in p["programs"]]
    if a.out:
        json.dump({"rule": "SET_RULE_20261013", "sets": s}, open(a.out, "w", encoding="utf-8"), indent=1)
    return 0


def cmd_pack(a):
    from openpyxl import load_workbook
    man, items = B.load_items(a.export)
    sets = plan(items)
    if a.set not in sets:
        raise SystemExit(f"unknown set: {a.set}")
    unit = sets[a.set]
    d = os.path.join(a.out, f"measurement_check_{a.rater}_set_{a.set}")
    os.makedirs(d, exist_ok=True)
    html = open(os.path.join(a.export, "booklet.html"), encoding="utf-8").read()
    cut, _ = B.cut_booklet(html, unit, a.set)
    note = (f"<p><b>Set {a.set}</b>: problems {unit['problems'][0]} to {unit['problems'][-1]} "
            f"({len(unit['problems'])} problems, {len(unit['programs'])} programs). "
            f"This is one of twelve parts of the full booklet.</p>")
    cut, n = re.subn(r"<p><b>Block [^<]*</b>:[^<]*</p>", lambda m: note, cut, count=1)
    if n != 1:
        raise SystemExit("booklet note not found")
    files = {f"booklet_set_{a.set}.html": cut.encode("utf-8"), "reviewer_guide.pdf": open(a.guide, "rb").read(),
             "READ_ME_FIRST.txt": COVER.format(name=a.set, rater=a.rater, first=unit["problems"][0],
                                               last=unit["problems"][-1], np=len(unit["problems"]),
                                               ng=len(unit["programs"]), deadline=DEADLINE).encode("utf-8")}
    for f, data in files.items():
        open(os.path.join(d, f), "wb").write(data)
    wbpath = os.path.join(d, f"judgments_{a.rater}_set_{a.set}.xlsx")
    B.cut_workbook(a.template, unit, a.set, a.rater, man, wbpath)
    wb = load_workbook(wbpath)                               # block wording of blocks.py -> set wording
    for row in wb["meta"].iter_rows(min_row=2):
        if row[0].value == "block":
            row[1].value, row[2].value = unit["block"], "Block of the booklet (BLOCK_RULE_20261012)."
        elif row[0].value == "block_problems":
            row[0].value, row[2].value = "set_problems", "Problems in this set."
        elif row[0].value == "block_programs":
            row[0].value, row[2].value = "set_programs", "Programs in this set."
    wb["meta"].append(["set", a.set, "Set of the booklet judged in this workbook (SET_RULE_20261013)."])
    rd = wb["README"]
    for row in rd.iter_rows(min_row=1, max_row=6):
        if isinstance(row[0].value, str) and row[0].value.startswith("This workbook is block"):
            row[0].value = (f"This workbook is set {a.set}: problems {unit['problems'][0]} to "
                            f"{unit['problems'][-1]}, {len(unit['programs'])} programs.")
    wb.save(wbpath)
    with zipfile.ZipFile(wbpath) as z:
        if any(B.CJK.search(z.read(n).decode("utf-8", "ignore")) for n in z.namelist()):
            raise SystemExit("Chinese text left in the workbook")
    z = d + ".zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(d)):
            zf.write(os.path.join(d, f), os.path.join(os.path.basename(d), f))
    print(f"[pack] {os.path.basename(z)}: set {a.set}, {len(unit['problems'])} problems, "
          f"{len(unit['programs'])} programs, sha256 {B.sha256_file(z)}")
    return 0


def cmd_status(a):
    MC = B.load_mc()
    _, items = B.load_items(a.export)
    sets = plan(items)
    for w in a.workbooks:
        rows, meta = B.read_rows(MC, w)
        done, part = [], []
        for k, v in sets.items():
            judged, bad = B.block_state(rows, v)
            if not bad:
                done.append(k)
            elif judged:
                part.append(f"{k} ({judged}/{len(v['programs'])})")
        print(f"{os.path.basename(w)}: rater {meta.get('rater_id')}; complete sets: {' '.join(done) or 'none'}"
              + (f"; started: {', '.join(part)}" if part else ""))
    return 0


def cmd_merge(a):
    from openpyxl import load_workbook
    MC = B.load_mc()
    man, items = B.load_items(a.export)
    sets = plan(items)
    src = {}
    for x in a.part:
        key, path = x.split("=", 1)
        for k in expand(key, sets):
            if k in src:
                raise SystemExit(f"set {k} has two sources")
            src[k] = path
    if sorted(src) != sorted(sets):
        raise SystemExit(f"sets without a source: {sorted(set(sets) - set(src))}")
    wb = load_workbook(a.template)
    ws = wb["judgments"]
    keys = [c.value for c in ws[1]]
    col = {k: i + 1 for i, k in enumerate(keys)}
    rowof = {ws.cell(r, col["program_id"]).value: r for r in range(MC.FIRST_ROW, ws.max_row + 1)
             if ws.cell(r, col["program_id"]).value}
    prov = {"rule": "SET_RULE_20261013", "label": a.label, "export_id": man["export_id"], "sets": {}}
    cache = {}
    for k in sets:
        if src[k] not in cache:
            cache[src[k]] = B.read_rows(MC, src[k])
        rows, meta = cache[src[k]]
        if meta.get("export_id") != man["export_id"]:
            raise SystemExit(f"{src[k]}: workbook of another export")
        _, bad = B.block_state(rows, sets[k])
        if bad:
            raise SystemExit(f"{os.path.basename(src[k])}: set {k} is not complete: {bad[:6]}")
        for pid in sets[k]["programs"]:
            for f, v in rows[pid]["raw"].items():
                ws.cell(rowof[pid], col[f]).value = v
        prov["sets"][k] = {"rater_id": meta.get("rater_id"), "file": os.path.basename(src[k]),
                           "sha256": B.sha256_file(src[k]), "programs": len(sets[k]["programs"])}
    for row in wb["meta"].iter_rows(min_row=2):
        if row[0].value == "rater_id":
            row[1].value = a.label
            row[2].value = "Put together from set workbooks (SET_RULE_20261013); see the .provenance.json file."
    wb.save(a.out)
    got = MC.read_judgments(a.out, items, a.label)             # the frozen reader accepts it, all 68 rows
    prov["programs"], prov["sha256"] = len(got), B.sha256_file(a.out)
    json.dump(prov, open(a.out + ".provenance.json", "w", encoding="utf-8"), indent=1)
    print(f"[merge] {os.path.basename(a.out)}: {len(got)} programs from "
          + ", ".join(f"{k}={prov['sets'][k]['rater_id']}" for k in sets))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan"); s.add_argument("--export", required=True); s.add_argument("--out")
    s = sub.add_parser("pack")
    for x in ("--export", "--template", "--guide", "--rater", "--set", "--out"):
        s.add_argument(x, required=True)
    s = sub.add_parser("status"); s.add_argument("--export", required=True); s.add_argument("workbooks", nargs="+")
    s = sub.add_parser("merge")
    for x in ("--export", "--template", "--label", "--out"):
        s.add_argument(x, required=True)
    s.add_argument("--part", action="append", required=True)
    a = ap.parse_args(argv)
    return {"plan": cmd_plan, "pack": cmd_pack, "status": cmd_status, "merge": cmd_merge}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
