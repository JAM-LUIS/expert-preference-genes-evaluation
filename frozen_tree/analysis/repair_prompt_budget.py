#!/usr/bin/env python3
"""Check that a repair-round conversation still fits the context window, with local token counts (E09).

  python3 analysis/repair_prompt_budget.py --requests <requests.C3.repairN.jsonl> [--model qwen3:8b] \
      --num-ctx 32768 --num-predict 6000 [--think [true|false|low|medium|high]] [--json-out <file>]

A repair turn carries the whole previous answer, so its prompt is much longer than round 0's. Each request is
rendered the way Ollama renders it and counted with the model's own tokenizer (runtime/orgene/tokcount.py; think is
sent as the runner sends it: false unless --think, a level for gpt-oss), and the run needs prompt + num_predict <= num_ctx. Anything over
is printed and the script exits 1, so runtime/run_condition.sh stops before generating that round; the case belongs
in RECORDS. There is no estimate: if the tokenizer is not available the script stops with exit code 2 (v5 divided
characters by 3.5 here). Exit 0 means every request fits.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime"))
from orgene.backends.base import OptionsError  # noqa: E402
from orgene.backends.ollama import parse_think  # noqa: E402
from orgene.tokcount import OllamaCounter, TokenizerError  # noqa: E402


def think_arg(v):
    try:
        return parse_think(v)
    except OptionsError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", required=True)
    ap.add_argument("--model", default="qwen3:8b", help="Ollama model tag whose tokenizer and template are used")
    ap.add_argument("--num-ctx", type=int, default=32768)
    ap.add_argument("--num-predict", type=int, default=6000)
    ap.add_argument("--think", nargs="?", const=True, default=False, type=think_arg,
                    help="as the runner was called: bare --think = true, or true|false|low|medium|high")
    ap.add_argument("--json-out", default=None, help="also write per-request counts as JSON")
    a = ap.parse_args()

    try:
        counter = OllamaCounter(a.model)
        rows = []
        with open(a.requests, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                n_prompt, info = counter.count_prompt(r.get("messages") or [], a.think)
                rows.append({"request_id": r.get("request_id"), "prompt_tokens": n_prompt,
                             "prompt_plus_predict": n_prompt + a.num_predict,
                             "over": n_prompt + a.num_predict > a.num_ctx,
                             "history_think_stripped": info["history_think_stripped"]})
    except TokenizerError as e:
        print(f"[repair-budget] local token count unavailable: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump({"requests": os.path.basename(a.requests), "model": a.model, "num_ctx": a.num_ctx,
                       "num_predict": a.num_predict, "think": a.think, "tokenizer": counter.identity(),
                       "rows": rows}, f, indent=2)
    if not rows:
        print(f"[repair-budget] {a.requests}: no requests")
        return
    over = [x for x in rows if x["over"]]
    mx = max(rows, key=lambda x: x["prompt_plus_predict"])
    print(f"[repair-budget] {a.requests}: n={len(rows)} num_ctx={a.num_ctx} num_predict={a.num_predict} "
          f"| max prompt+predict = {mx['prompt_plus_predict']} tokens ({mx['request_id']}; local tokenizer) "
          f"| over budget: {len(over)}")
    for x in over:
        print(f"[repair-budget]   OVER {x['request_id']}: prompt {x['prompt_tokens']} + predict {a.num_predict} "
              f"= {x['prompt_plus_predict']} > num_ctx {a.num_ctx}")
    if over:
        print(f"[repair-budget] {len(over)} request(s) over budget; not continuing", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
