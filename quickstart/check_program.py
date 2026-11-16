#!/usr/bin/env python3
"""Let the review rules of the article read a PuLP program.

    python quickstart/check_program.py --example
    python quickstart/check_program.py --problem my_problem.txt --program my_model.py

The gene-repair condition of the article uses 16 of the 21 rules. The problem
statement decides which of them apply (the same activation as in the evaluation). The program is then checked before and after it runs, exactly as the
gene-repair condition of the article checks a model-written program. For every
failed rule the output gives what was found and the repair instruction; the last
block is the message the evaluation would send back to the language model.

The program must build a PuLP model, call .solve() and print two final lines:
    STATUS: <pulp.LpStatus[prob.status]>
    FINAL_OBJECTIVE: <the objective value>

Needs PuLP in the interpreter that runs this script (pip install -r requirements.txt
inside a virtual environment). Exit status: 0 no hard failure, 2 at least one.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = os.path.join(ROOT, "frozen_tree")
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(FROZEN, "runtime"))
from orgene import genes as G  # noqa: E402  (frozen code of the evaluation)
from orgene import pipeline as P  # noqa: E402

GENES = os.path.join(FROZEN, "genes", "genes.it1.jsonl")              # the registered library
LEXICON = os.path.join(FROZEN, "genes", "activation_lexicon.v2.json")  # decides which rules a problem activates
SCOPE, REPAIR, CLOSING = "C3L", "gene", "program"                      # the gene-repair condition of the article
EXAMPLE = os.path.join(ROOT, "quickstart", "example")


def check(problem_text, program_text, timeout=60):
    """Returns (active rules, validated record, repair message or None, number of rules gene repair uses)."""
    case = {"case_id": "user-0001", "source": "user", "text": problem_text}
    store = G.load_store(GENES, lexicon=LEXICON)
    active, _trace, _info = G.activate_case(store, case, lexicon=LEXICON, condition=SCOPE)
    content = program_text if "```" in program_text else "```python\n" + program_text.rstrip() + "\n```"
    v, repair_text, _applied = P.validate_one(
        case, {"content": content, "ok": True}, active, 0, {}, cond=SCOPE, repeat=0, act=True,
        max_rounds=G.MAX_REPAIR_ROUNDS, repair=REPAIR, closing=CLOSING, timeout=timeout, python=sys.executable)
    in_scope = sum(1 for g in store if SCOPE in (g["scope"].get("conditions") or []))
    return active, v, repair_text, in_scope


def report(active, v, repair_text, in_scope, out=sys.stdout):
    by_id = {g["geneId"]: g for g in active}
    w = lambda s="": print(s, file=out)  # noqa: E731
    ex = v.get("exec") or {}
    w(f"Rules active for this problem: {len(active)} of the {in_scope} that gene repair uses")
    w(f"Program ran: {'yes' if ex.get('exec_ok') else 'no'}"
      + (f"   status: {ex.get('status')}   objective: {ex.get('objective')}" if ex.get("exec_ok") else ""))
    hard = [i for i in v["issues"] if i.get("ok") is False and i.get("severity") == "hard"]
    soft = [i for i in v["issues"] if i.get("ok") is False and i.get("severity") == "soft"]
    passed = sum(1 for i in v["issues"] if i.get("ok") is True)
    w(f"Checks passed: {passed}   failed: {len(hard)}   warnings: {len(soft)}")
    for kind, items in (("FAILED", hard), ("WARNING", soft)):
        for i in items:
            g = by_id.get(i["geneId"], {})
            w()
            w(f"{kind}  {i['geneId']}")
            w(f"  Rule:  {g.get('preference', {}).get('statement', '')}")
            lines = G.scrub_exec_paths(str(i["detail"])).strip().splitlines()
            w(f"  Found: {lines[0]}" if len(lines) == 1 else f"  Found: {lines[0].split(':')[0]}: {lines[-1].strip()}")
            if kind == "FAILED":
                w(f"  Fix:   {g.get('repair', {}).get('instruction', '')}")
    if repair_text:
        w()
        w("---- message the evaluation would send back to the model ----")
        w(repair_text)
    elif not hard:
        w()
        w("No rule failed. The rules check what can be written as a program; a missing constraint that leaves")
        w("the model feasible is outside them (Section 9 of the article).")
    return 2 if hard else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--problem", help="text file with the problem statement")
    ap.add_argument("--program", help="Python file with the PuLP program")
    ap.add_argument("--example", action="store_true", help="run on quickstart/example/ (a program that reads its variables with the wrong key)")
    ap.add_argument("--timeout", type=int, default=60, help="seconds the program may run (default 60)")
    a = ap.parse_args()
    if a.example:
        a.problem, a.program = os.path.join(EXAMPLE, "problem.txt"), os.path.join(EXAMPLE, "program_with_flaws.py")
    if not a.problem or not a.program:
        ap.error("give --problem and --program, or --example")
    try:
        import pulp  # noqa: F401
    except ImportError:
        sys.exit("PuLP is not installed in this interpreter: pip install -r requirements.txt (inside a virtual environment)")
    problem = open(a.problem, encoding="utf-8").read()
    program = open(a.program, encoding="utf-8").read()
    return report(*check(problem, program, a.timeout))


if __name__ == "__main__":
    sys.exit(main())
