#!/usr/bin/env python3
"""Export the generic repair template (C3E, C2E) and its whitelist as files for the freeze (E05 items), from the
code that renders the messages; --check compares the committed files with the code.

  /opt/homebrew/bin/python3 tools/export_generic_repair.py [--check]

Writes conditions/C3E_generic_repair_template.json (orgene.genes.generic_template(), with the template's
sha256 as generic_template_sha256() computes it) and conditions/generic_repair_whitelist.txt (one allowed line per
line, sorted; orgene.genes.generic_whitelist()). The runtime keeps rendering from the code; these files pin it.
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))
from orgene import genes as G  # noqa: E402

TEMPLATE = "conditions/C3E_generic_repair_template.json"
WHITELIST = "conditions/generic_repair_whitelist.txt"


def render():
    doc = G.generic_template()
    doc = dict(doc, template_sha256=G.generic_template_sha256())
    tpl = (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode()
    wl = ("\n".join(sorted(G.generic_whitelist())) + "\n").encode()
    return tpl, wl


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    tpl, wl = render()
    paths = {TEMPLATE: tpl, WHITELIST: wl}
    if a.check:
        bad = [p for p, body in paths.items()
               if not os.path.exists(os.path.join(ROOT, p)) or open(os.path.join(ROOT, p), "rb").read() != body]
        print(f"RESULT: {'PASS' if not bad else 'FAIL'} ({', '.join(bad) if bad else 'files equal the code'})")
        return 1 if bad else 0
    for p, body in paths.items():
        with open(os.path.join(ROOT, p), "wb") as f:
            f.write(body)
    print(f"wrote {TEMPLATE} (template sha256 {json.loads(tpl)['template_sha256'][:12]}) and {WHITELIST} "
          f"({len(wl.decode().splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
