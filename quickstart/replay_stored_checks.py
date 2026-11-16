#!/usr/bin/env python3
"""Run the rule checks again on programs stored in the held-out test and compare with the stored records.

    python quickstart/replay_stored_checks.py            # 24 units, about a minute
    python quickstart/replay_stored_checks.py --n 0      # every gene-repair unit of the main model

For each unit of the gene-repair condition, the first program the model wrote is checked again with
quickstart/check_program.py. The active rules, the failed rules and the repair message must equal the
ones recorded during the test. The stored programs are model-written code and are executed: run this
in a virtual environment or a container, as you would any code you did not write.
"""
import argparse
import json
import os
import random
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(ROOT, "quickstart"))
import check_program as C  # noqa: E402

STAGES = (("industryor-test", "industryor"), ("mamo-test", "mamo_complex_lp"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=24, help="units to replay, split over the two benchmarks (0 = all)")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    try:
        import pulp  # noqa: F401
    except ImportError:
        sys.exit("PuLP is not installed in this interpreter: pip install -r requirements.txt (inside a virtual environment)")
    rng, same, different = random.Random(a.seed), 0, []
    for stage, bench in STAGES:
        text = {}
        with open(os.path.join(ROOT, "frozen_tree", "data", "cases", bench + ".jsonl"), encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if "case_id" in r:
                    text[r["case_id"]] = r["text"]
        with tarfile.open(os.path.join(ROOT, "outputs", "test-main-20261006", stage + ".tar.gz")) as tf:
            names = sorted(m.name for m in tf if "qwen3-8b.main/units/" in m.name and m.name.endswith(".C3L.r0.json"))
            if a.n:
                names = rng.sample(names, min(len(names), a.n // 2))
            for name in names:
                u = json.load(tf.extractfile(name))
                r0 = u["rounds"][0]
                stored = r0["validated"]
                content = r0["calls"][-1].get("content") if r0.get("calls") else None
                if content is None:  # the first program is shared with direct generation; rebuild the answer from it
                    content = "```python\n" + stored["code"] + "\n```" if stored.get("code") else ""
                active, v, repair, _ = C.check(text[u["case_id"]], content)
                ok = ([g["geneId"] for g in active] == [g["geneId"] for g in u["activation"]["active_genes"]]
                      and v["hard_failed_genes"] == stored["hard_failed_genes"]
                      and (repair or None) == (r0.get("repair_text") or None))
                same += ok
                if not ok:
                    different.append(u["case_id"])
                print(f"{u['case_id']:<24}{'same' if ok else 'DIFFERENT':<10}failed rules: {len(stored['hard_failed_genes'])}")
    print(f"\n{same} of {same + len(different)} units give the stored active rules, failed rules and repair message.")
    if different:
        print("different: " + ", ".join(different))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
