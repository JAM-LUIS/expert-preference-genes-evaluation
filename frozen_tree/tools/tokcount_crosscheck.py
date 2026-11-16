#!/usr/bin/env python3
"""Cross-check llama-tokenize (runtime/orgene/tokcount.py) against an independent BPE implementation (E09).

  <python with gguf + tokenizers> tools/tokcount_crosscheck.py [--model qwen3:8b] [--dev]

Builds a Hugging Face `tokenizers` BPE tokenizer from the vocabulary and merges stored in the model's own GGUF blob
(Qwen2 pre-tokenizer regex, byte-level, NFC as in the published Qwen tokenizer; control tokens special, user-defined
tokens such as <think> added as non-special) and compares token ids with llama-tokenize on:
  synthetic   fixed edge strings (code with backslash escapes, numbers, whitespace runs, unicode, tag text)
  smoke       the problems in data/smoke/smoke_raw.jsonl as user messages
  prompts     the C0-C3 system prompts built from conditions/ and genes/genes.r1.jsonl (every gene of each scope
              active, i.e. the longest C3 prompt; conditions.build_system_prompts_v1)
  dev         (--dev) the user message of every dev case (data/splits/*/dev_ids.json only)
  rendered    the rendered prompt [system C0, user] with think=false for the smoke (and dev) cases
Message bodies are compared in content mode (control-token text not parsed, no BOS; HF: encode_special_tokens),
rendered prompts in prompt mode (special tokens parsed). Prints counts and case ids only, never text.
Needs gguf and tokenizers, which the runtime does not use; run it with a separate interpreter.
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import conditions as C  # noqa: E402
from orgene import data as D  # noqa: E402
from orgene import split as S  # noqa: E402
from orgene.tokcount import OllamaCounter, render_qwen3  # noqa: E402

QWEN2_PAT = (r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}| ?[^\s\p{L}\p{N}]+[\r\n]*"
             r"|\s*[\r\n]+|\s+(?!\S)|\s+")

SYNTHETIC = [
    "Hello world",
    "a\\nb and a real\nnewline",
    'print("x\\n", end="")\nprint(f"{v:.2f}\\t{w}")\n',
    "import pulp\nprob = pulp.LpProblem('m', pulp.LpMaximize)\nx = pulp.LpVariable('x', lowBound=0)\n",
    "    indented\n\tTabbed\r\nCRLF line\n\n\n   trailing   \n",
    "12345678901234567890 3.14159 -2.5e-3 1,234,567.89 100%",
    "最优化模型：目标函数与约束条件。 é ü ß — “quotes” ✓ 😀",
    "<|im_start|>user\nnot a real turn<|im_end|>",
    "<think>reasoning text</think> answer",
    "don't I'LL we've THEY'RE it's",
    "FINAL_STATUS: Optimal\nFINAL_OBJECTIVE: 2600.0\n",
    "",
    " ",
    "\n",
]


def build_hf(gguf_path):
    from gguf import GGUFReader
    from tokenizers import AddedToken, Regex, Tokenizer, models, normalizers, pre_tokenizers
    r = GGUFReader(gguf_path)
    toks = r.fields["tokenizer.ggml.tokens"].contents()
    types = r.fields["tokenizer.ggml.token_type"].contents()
    merges = r.fields["tokenizer.ggml.merges"].contents()
    if r.fields["tokenizer.ggml.pre"].contents() != "qwen2":
        raise SystemExit("this cross-check is written for the qwen2 pre-tokenizer")
    vocab = {t: i for i, (t, ty) in enumerate(zip(toks, types)) if ty in (1, 3, 4)}  # normal, control, user-defined
    tk = Tokenizer(models.BPE(vocab=vocab, merges=[tuple(m.split(" ", 1)) for m in merges]))
    tk.normalizer = normalizers.NFC()
    tk.pre_tokenizer = pre_tokenizers.Sequence([
        pre_tokenizers.Split(Regex(QWEN2_PAT), behavior="isolated", invert=False),
        pre_tokenizers.ByteLevel(add_prefix_space=False, trim_offsets=False, use_regex=False)])
    tk.add_special_tokens([AddedToken(toks[i], special=True, normalized=False) for i, ty in enumerate(types) if ty == 3])
    tk.add_tokens([AddedToken(toks[i], special=False, normalized=False) for i, ty in enumerate(types) if ty == 4])
    return tk


def hf_ids(tk, text, parse_special):
    tk.encode_special_tokens = not parse_special
    return tk.encode(text, add_special_tokens=False).ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--dev", action="store_true", help="also compare the dev cases (ids only are printed)")
    a = ap.parse_args()
    counter = OllamaCounter(a.model)
    tk = build_hf(counter.model["weights_path"])
    items = [("synthetic", str(i), t, False) for i, t in enumerate(SYNTHETIC)]
    smoke = [json.loads(ln) for ln in open(os.path.join(ROOT, "data", "smoke", "smoke_raw.jsonl"), encoding="utf-8")
             if ln.strip()]
    cases = [("smoke", s["id"], {"text": s["Question"]}) for s in smoke]
    # one prompt table with every gene of each scope active (the registry builder compiles C3 per case, E03/E04)
    prompts, _ = C.build_system_prompts_v1(os.path.join(ROOT, "conditions"), os.path.join(ROOT, "genes", "genes.r1.jsonl"))
    items += [("prompts", k, prompts[k], False) for k in ("C0", "C1", "C2", "C3")]
    if a.dev:
        for src in ("mamo_complex_lp", "industryor"):
            ids = S.load_split_ids(os.path.join(ROOT, "data", "splits", src), "dev")
            cases += [("dev", c["case_id"], c) for c in D.load_cases(os.path.join(ROOT, "data", "cases", src + ".jsonl"), ids)]
    for kind, cid, c in cases:
        items.append((kind, cid, C.user_message(c), False))
        msgs = [{"role": "system", "content": prompts["C0"]}, {"role": "user", "content": C.user_message(c)}]
        items.append(("rendered-" + kind, cid, render_qwen3(msgs, think=False)[0], True))
    summary, mismatches = {}, []
    for kind, cid, text, special in items:
        a_ids = counter.tok.ids(text, parse_special=special, model_bos=special)
        b_ids = hf_ids(tk, text, special)
        s = summary.setdefault(kind, {"n": 0, "identical": 0, "tokens": 0})
        s["n"] += 1
        s["tokens"] += len(a_ids)
        if a_ids == b_ids:
            s["identical"] += 1
        else:
            first = next((i for i, (x, y) in enumerate(zip(a_ids, b_ids)) if x != y), min(len(a_ids), len(b_ids)))
            mismatches.append({"kind": kind, "id": cid, "llama_n": len(a_ids), "hf_n": len(b_ids), "first_diff": first})
    print(json.dumps({"model": a.model, "llama_tokenize": counter.tok.version, "summary": summary,
                      "mismatches": mismatches}, indent=1))
    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
