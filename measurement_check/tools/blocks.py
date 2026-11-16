#!/usr/bin/env python3
"""Block-wise judging for the measurement check (BLOCK_RULE_20261012.md).

Written after unsealing, outside the frozen tree. The registered sample, booklet, workbook columns and analysis
are unchanged; this script only (a) cuts the booklet and the step 1 workbook into three contiguous blocks, and
(b) puts returned block workbooks back together into complete workbooks that the frozen measurement_check.py
reads. key.json is never opened.

  blocks.py plan     --export DIR                                  print the three blocks (from items.json alone)
  blocks.py pack     --export DIR --template EN.xlsx --guide G.pdf --rater R4 --block C --out DIR
  blocks.py status   --export DIR WORKBOOK [WORKBOOK ...]          which blocks each workbook completes
  blocks.py merge    --export DIR --template EN.xlsx --label NAME --part A=W.xlsx --part B=W.xlsx --part C=W.xlsx
                     --out OUT.xlsx                                one complete workbook from one source per block
  blocks.py unresolved --consensus C.xlsx                          no discussion: mark every listed program

--template is a blank English step 1 workbook of this export (all 68 rows), for example the one sent as R3.
A source given to merge may be a block workbook or a complete one; only the rows of that block are taken.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = os.path.join(HERE, "..", "..", "release_repo", "expert-preference-genes-evaluation", "frozen_tree")
NAMES = ("A", "B", "C")
CJK = re.compile(r"[\u3000-\u303f\u3400-\u9fff\uff00-\uffef]")
DEADLINE = "noon (US Eastern time) on Sunday, 18 October 2026"


def load_mc():
    sys.path.insert(0, os.path.join(FROZEN, "runtime"))
    sys.path.insert(0, os.path.join(FROZEN, "analysis", "r1"))
    import measurement_check as MC
    return MC


def sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def plan(items):
    """Three contiguous blocks in booklet order; boundaries from the number of programs per problem alone.
    Smallest spread (max - min) of programs per block; ties: shortest first block, then shortest second."""
    probs = items["problems"]
    n = [len(p["programs"]) for p in probs]
    best = None
    for a in range(1, len(n) - 1):
        for b in range(a + 1, len(n)):
            s = (sum(n[:a]), sum(n[a:b]), sum(n[b:]))
            cand = (max(s) - min(s), a, b)
            if best is None or cand < best:
                best = cand
    _, a, b = best
    cuts = {"A": probs[:a], "B": probs[a:b], "C": probs[b:]}
    return {k: {"problems": [p["problem_id"] for p in v], "programs": [x for p in v for x in p["programs"]]}
            for k, v in cuts.items()}


def load_items(export):
    man = json.load(open(os.path.join(export, "export_manifest.json"), encoding="utf-8"))
    items = json.load(open(os.path.join(export, "items.json"), encoding="utf-8"))
    for f in ("items.json", "booklet.html"):
        if sha256_file(os.path.join(export, f)) != man["files"][f]:
            raise SystemExit(f"{f} does not match the export manifest")
    return man, items


def cut_booklet(html, block, name):
    """Header, a nav with the block's problems, and the block's sections byte for byte as in the full booklet."""
    head, rest = html.split("<nav>", 1)
    _, body = rest.split("</nav>\n", 1)
    parts = re.split(r"(?=<h2 id='P\d+'>)", body)
    tail = "</body></html>\n"
    if not parts[-1].endswith(tail):
        raise SystemExit("unexpected end of the booklet")
    parts[-1] = parts[-1][:-len(tail)]
    secs = {re.match(r"<h2 id='(P\d+)'>", p).group(1): p for p in parts if p}
    if "".join(secs[k] for k in secs) + tail != body:
        raise SystemExit("booklet sections do not add up to the booklet")
    ids = block["problems"]
    note = (f"<p><b>Block {name}</b>: problems {ids[0]} to {ids[-1]} ({len(ids)} problems, "
            f"{len(block['programs'])} programs). This is one of three parts of the full booklet.</p>")
    nav = "<nav>\n" + "".join(f"<a href='#{i}'>{i}</a>\n" for i in ids) + "</nav>\n"
    return head + note + nav + "".join(secs[i] for i in ids) + tail, [secs[i] for i in ids]


def cut_workbook(template, block, name, rater, man, out):
    from openpyxl import load_workbook
    MC = load_mc()
    wb = load_workbook(template)
    ws = wb["judgments"]
    keys = [c.value for c in ws[1]]
    col = {k: i + 1 for i, k in enumerate(keys)}
    rows = [(ws.cell(r, col["problem_id"]).value, ws.cell(r, col["program_id"]).value)
            for r in range(MC.FIRST_ROW, ws.max_row + 1) if ws.cell(r, col["program_id"]).value]
    for r in range(MC.FIRST_ROW, ws.max_row + 1):
        for k in keys[:-1]:
            if k not in ("problem_id", "program_id") and ws.cell(r, col[k]).value not in (None, ""):
                raise SystemExit("the template workbook is not blank")
    keep = [x for x in rows if x[1] in set(block["programs"])]
    if [x[1] for x in keep] != block["programs"]:
        raise SystemExit("template rows do not match the block")
    # the check formula of each row refers to its own row only, so the block's IDs are written from the top
    for i, (prob, prog) in enumerate(keep):
        ws.cell(MC.FIRST_ROW + i, col["problem_id"]).value = prob
        ws.cell(MC.FIRST_ROW + i, col["program_id"]).value = prog
    first_free = MC.FIRST_ROW + len(keep)
    ws.delete_rows(first_free, ws.max_row - first_free + 1)
    meta = wb["meta"]
    for row in meta.iter_rows(min_row=2):
        if row[0].value == "rater_id":
            row[1].value = rater
            row[2].value = "Reviewer number."
    for k, v, note in (("block", name, "Block of the booklet judged in this workbook (BLOCK_RULE_20261012)."),
                       ("block_problems", len(block["problems"]), "Problems in this block."),
                       ("block_programs", len(block["programs"]), "Programs in this block.")):
        meta.append([k, v, note])
    # the header notes (hover comments) of the bilingual template keep their Chinese half in the English display
    # copy; a block workbook goes to English-speaking reviewers, so only the English half is kept
    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for c in row:
                if c.comment is not None and CJK.search(c.comment.text or ""):
                    eng = [x.strip() for x in re.split(r"\s*/\s+", c.comment.text) if x.strip() and not CJK.search(x)]
                    if not eng:
                        raise SystemExit(f"{sheet.title}!{c.coordinate}: note without an English half")
                    c.comment.text = eng[-1]
    ex = wb["example"]                                   # 'big_m Big-M' in the example: show the code alone, as the list does
    for row in ex.iter_rows(min_row=MC.FIRST_ROW, min_col=col["error_category"], max_col=col["error_category"]):
        if isinstance(row[0].value, str) and row[0].value.strip():
            row[0].value = row[0].value.split()[0]
    rd = wb["README"]
    rd.insert_rows(3)
    rd.cell(3, 1).value = (f"This workbook is block {name}: problems {block['problems'][0]} to "
                           f"{block['problems'][-1]}, {len(block['programs'])} programs.")
    wb.save(out)
    with zipfile.ZipFile(out) as z:                       # nothing Chinese may be left anywhere in the file
        left = [n for n in z.namelist() if CJK.search(z.read(n).decode("utf-8", "ignore"))]
    if left:
        raise SystemExit(f"Chinese text left in {os.path.basename(out)}: {left}")


COVER = """Measurement check: your part (block {name})

Thank you for helping. Besides this note, the folder contains three files.

  reviewer_guide.pdf      the instructions. Sections 3 (keep it blind and independent), 4 (what to judge),
                          5, 6 and 9 (a worked example) are the ones you need.
  booklet_block_{name}.html    your problems and programs. Open it in any web browser.
  judgments_{rater}_block_{name}.xlsx    the workbook to fill in and send back.

Your part is block {name}: problems {first} to {last}, that is {np} problems and {ng} programs. The full sample has
34 problems and 68 programs and is shared among several reviewers, so the guide speaks of a larger set.

What differs from the guide for you:
  - You judge only the programs of block {name}. At about 4 minutes per program this is about an hour and a half.
    The times in sections 1 and 7 of the guide are for the full set.
  - Only step 1 applies. There is no discussion with another reviewer (step 2, section 8) and no read-through
    of the modeling rules (step 3, section 10).
  - Everything else is as in the guide: the criteria, the three judgments, the error categories, the notes,
    and section 3 in full. Please work on your own and do not discuss the materials with anyone, since
    other reviewers judge the same programs.

Please send the completed workbook back by e-mail to <author e-mail> by {deadline}.
If anything is unclear, please ask at the same address (guide, section 11).
"""


def cmd_plan(a):
    _, items = load_items(a.export)
    p = plan(items)
    for k in NAMES:
        print(f"block {k}: {p[k]['problems'][0]}-{p[k]['problems'][-1]}, {len(p[k]['problems'])} problems, "
              f"{len(p[k]['programs'])} programs")
    if a.out:
        json.dump({"rule": "BLOCK_RULE_20261012", "blocks": p}, open(a.out, "w", encoding="utf-8"), indent=1)
    return 0


def cmd_pack(a):
    man, items = load_items(a.export)
    block = plan(items)[a.block]
    d = os.path.join(a.out, f"measurement_check_{a.rater}_block_{a.block}")
    os.makedirs(d, exist_ok=True)
    html = open(os.path.join(a.export, "booklet.html"), encoding="utf-8").read()
    cut, _ = cut_booklet(html, block, a.block)
    files = {f"booklet_block_{a.block}.html": cut.encode("utf-8"), "reviewer_guide.pdf": open(a.guide, "rb").read(),
             "READ_ME_FIRST.txt": COVER.format(name=a.block, rater=a.rater, first=block["problems"][0],
                                               last=block["problems"][-1], np=len(block["problems"]),
                                               ng=len(block["programs"]), deadline=DEADLINE).encode("utf-8")}
    for f, data in files.items():
        open(os.path.join(d, f), "wb").write(data)
    wbname = f"judgments_{a.rater}_block_{a.block}.xlsx"
    cut_workbook(a.template, block, a.block, a.rater, man, os.path.join(d, wbname))
    z = d + ".zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(d)):
            zf.write(os.path.join(d, f), os.path.join(os.path.basename(d), f))
    print(f"[pack] {os.path.basename(z)}: block {a.block}, {len(block['problems'])} problems, "
          f"{len(block['programs'])} programs, sha256 {sha256_file(z)}")
    return 0


def read_rows(MC, path):
    """{program_id: judgment dict or reason it cannot be used}, and the workbook's meta."""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    meta = {r[0]: r[1] for r in wb["meta"].iter_rows(min_row=2, values_only=True) if r[0]}
    if meta.get("schema") != MC.WORKBOOK_SCHEMA or meta.get("file_role") != "judgments":
        raise SystemExit(f"{os.path.basename(path)}: not a judgments workbook of {MC.WORKBOOK_SCHEMA}")
    ws = wb["judgments"]
    keys = [c.value for c in ws[1]]
    out = {}
    for row in ws.iter_rows(min_row=MC.FIRST_ROW, values_only=True):
        r = dict(zip(keys, row))
        pid = r.get("program_id")
        if not pid:
            continue
        raw = {k: r.get(k) for k in MC.ASPECTS + ("overall", "error_category", "notes")}
        j = {k: MC._code(r.get(k)) for k in MC.ASPECTS + ("overall", "error_category")}
        notes = r.get("notes").strip() if isinstance(r.get("notes"), str) else ""
        if all(v in (None, "") for v in raw.values()):
            why = "not judged"
        elif j["overall"] not in MC.JUDGMENTS or any(j[k] not in MC.JUDGMENTS for k in MC.ASPECTS):
            why = "judgment missing or outside the list"
        elif j["overall"] == "incorrect" and j["error_category"] not in MC.CATEGORIES:
            why = "incorrect without a valid error category"
        elif j["overall"] == "cannot_judge" and not notes:
            why = "cannot_judge without a note"
        else:
            why = None
        out[pid] = {"raw": raw, "why": why}
    return out, meta


def block_state(rows, block):
    bad = [(p, rows[p]["why"] if p in rows else "row missing") for p in block["programs"]
           if p not in rows or rows[p]["why"]]
    judged = sum(1 for p in block["programs"] if p in rows and rows[p]["why"] != "not judged")
    return judged, bad


def cmd_status(a):
    MC = load_mc()
    _, items = load_items(a.export)
    p = plan(items)
    for w in a.workbooks:
        rows, meta = read_rows(MC, w)
        print(f"{os.path.basename(w)}: rater {meta.get('rater_id')}, block in meta {meta.get('block', 'none (full)')}")
        for k in NAMES:
            judged, bad = block_state(rows, p[k])
            state = "complete" if not bad else ("not started" if judged == 0 else "incomplete")
            print(f"  block {k}: {judged}/{len(p[k]['programs'])} judged, {state}"
                  + ("" if not bad or judged == 0 else f"; {bad[:4]}"))
    return 0


def cmd_merge(a):
    from openpyxl import load_workbook
    MC = load_mc()
    man, items = load_items(a.export)
    p = plan(items)
    src = dict(x.split("=", 1) for x in a.part)
    if sorted(src) != list(NAMES):
        raise SystemExit("merge needs exactly one source for each of A, B and C")
    wb = load_workbook(a.template)
    ws = wb["judgments"]
    keys = [c.value for c in ws[1]]
    col = {k: i + 1 for i, k in enumerate(keys)}
    rowof = {ws.cell(r, col["program_id"]).value: r for r in range(MC.FIRST_ROW, ws.max_row + 1)
             if ws.cell(r, col["program_id"]).value}
    prov = {"rule": "BLOCK_RULE_20261012", "label": a.label, "export_id": man["export_id"], "blocks": {}}
    for k in NAMES:
        rows, meta = read_rows(MC, src[k])
        if meta.get("export_id") != man["export_id"]:
            raise SystemExit(f"{src[k]}: workbook of another export")
        judged, bad = block_state(rows, p[k])
        if bad:
            raise SystemExit(f"{os.path.basename(src[k])}: block {k} is not complete: {bad[:6]}")
        for pid in p[k]["programs"]:
            for f, v in rows[pid]["raw"].items():
                ws.cell(rowof[pid], col[f]).value = v
        prov["blocks"][k] = {"rater_id": meta.get("rater_id"), "file": os.path.basename(src[k]),
                             "sha256": sha256_file(src[k]), "programs": len(p[k]["programs"])}
    for row in wb["meta"].iter_rows(min_row=2):
        if row[0].value == "rater_id":
            row[1].value = a.label
            row[2].value = "Put together from block workbooks (BLOCK_RULE_20261012); see the .provenance.json file."
    wb.save(a.out)
    got = MC.read_judgments(a.out, items, a.label)             # the frozen reader accepts it, all 68 rows
    prov["programs"] = len(got)
    prov["sha256"] = sha256_file(a.out)
    json.dump(prov, open(a.out + ".provenance.json", "w", encoding="utf-8"), indent=1)
    print(f"[merge] {os.path.basename(a.out)}: {len(got)} programs from "
          + ", ".join(f"{k}={prov['blocks'][k]['rater_id']}" for k in NAMES))
    return 0


def cmd_unresolved(a):
    """Rule 6: no discussion. A program whose overall judgments differ gets 'unresolved' (no final label).
    A program that both judged incorrect with different categories keeps 'incorrect'; the consensus sheet needs a
    category there, so 'other' is written as a placeholder and the program is listed in the .json file: in the
    table of error categories these programs are reported as 'category not agreed', not as 'other'."""
    from openpyxl import load_workbook
    MC = load_mc()
    wb = load_workbook(a.consensus)
    ws = wb["consensus"]
    keys = [c.value for c in ws[1]]
    col = {k: i + 1 for i, k in enumerate(keys)}
    kind_key = "reason"
    un, cat = [], []
    for r in range(MC.FIRST_ROW, ws.max_row + 1):
        pid = ws.cell(r, col["program_id"]).value
        if not pid:
            continue
        if ws.cell(r, col[kind_key]).value == "overall_differs":
            ws.cell(r, col["final_overall"]).value = "unresolved"
            ws.cell(r, col["final_error_category"]).value = None
            un.append(pid)
        elif ws.cell(r, col[kind_key]).value == "category_differs":
            ws.cell(r, col["final_overall"]).value = "incorrect"
            ws.cell(r, col["final_error_category"]).value = "other"
            cat.append(pid)
        else:
            raise SystemExit(f"{pid}: unknown kind of disagreement")
    wb.save(a.consensus)
    json.dump({"rule": "BLOCK_RULE_20261012 rule 6", "unresolved": un, "category_not_agreed": cat},
              open(a.consensus + ".no_discussion.json", "w", encoding="utf-8"), indent=1)
    print(f"[unresolved] {len(un)} unresolved, {len(cat)} incorrect with category not agreed")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan"); s.add_argument("--export", required=True); s.add_argument("--out")
    s = sub.add_parser("pack")
    for x in ("--export", "--template", "--guide", "--rater", "--out"):
        s.add_argument(x, required=True)
    s.add_argument("--block", required=True, choices=NAMES)
    s = sub.add_parser("status"); s.add_argument("--export", required=True); s.add_argument("workbooks", nargs="+")
    s = sub.add_parser("merge")
    for x in ("--export", "--template", "--label", "--out"):
        s.add_argument(x, required=True)
    s.add_argument("--part", action="append", required=True)
    s = sub.add_parser("unresolved"); s.add_argument("--consensus", required=True)
    a = ap.parse_args(argv)
    return {"plan": cmd_plan, "pack": cmd_pack, "status": cmd_status, "merge": cmd_merge,
            "unresolved": cmd_unresolved}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
