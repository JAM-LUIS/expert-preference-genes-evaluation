#!/usr/bin/env python3
"""Check the gpt-oss tokenizer of the local counts against the model's own blob and against the server (E23).

Run with the .venv-tools interpreter (it needs tiktoken), from the repository root:
  .venv-tools/bin/python -B tools/gptoss_tokenizer_check.py vocab  [--model gpt-oss:20b] [--out FILE]
  .venv-tools/bin/python -B tools/gptoss_tokenizer_check.py server --model <tag> --requests R.jsonl [...] \
        [--think low] [--synthetic] [--keep-alive 30s] [--out FILE]
  .venv-tools/bin/python -B tools/gptoss_tokenizer_check.py llama  [--model gpt-oss:20b] --requests R.jsonl [...]

vocab   Reads the tokenizer metadata of the weights blob (orgene.gguf_vocab; only the header) and compares every token
        id with tiktoken's o200k_harmony, built offline from the registered o200k_base file: byte-level tokens by their
        bytes, special tokens by name; checks that every merge joins two tokens into a token and that the merges are
        ordered by the rank of the joined token (the order tiktoken merges in). No model call.
server  For every request [system, user] in the requests files (and, with --synthetic, fixed edge strings sent as the
        user message), asks the server for its own token ids of the prompt it renders: /api/generate with the same
        system text, user text and think value, num_predict 1, temperature 0; the response's `context` is the
        prompt's ids plus the one generated id. Compares them with the local count's ids (render_gptoss +
        o200k_harmony, special tokens parsed), and the user text's ids with o200k_base (special-token text as text).
        One model call per prompt (--keep-alive keeps the model loaded between them; the default is 0).
llama   llama-tokenize over the tokenizer-only GGUF derived from the blob (the other tokenizer choice) against
        tiktoken, on the same prompts and texts. Reports "unavailable" when llama-tokenize is missing.

Output: counts, ids' hashes, case ids and positions only — never text.
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))

from orgene import gguf_vocab as GV  # noqa: E402
from orgene import tokcount as T  # noqa: E402
from orgene import tokcount_harmony as H  # noqa: E402

HOST = "http://127.0.0.1:11434"
PAD_BASE = 200019  # first unused reserved id of the gpt-oss vocabulary ([PAD0] in the blob)
# edge strings sent as user messages (self-made): numbers, case changes, contractions, whitespace, non-ASCII letters
# and marks, symbols, code; the pre-tokenizer pattern matters most here
SYNTHETIC = [
    "12345678901234567890 3.14159 -2.5e-3 1,234,567.89 100% x1 x22 x333 A1b2C3",
    "HelloWorld camelCaseName snake_case_name UPPER lower MixedUPPERCase McDonald's O'Neil",
    "don't I'LL we've THEY'RE it's 's 'd 'm",
    "    indented\n\tTabbed\r\nCRLF line\n\n\n   trailing   \n  \n",
    "Ångström İstanbul Σύνολο éèê näive ßẞ",
    "最优化模型：目标函数与约束条件。 日本語 한국어",
    "≤ ≥ ≠ × ÷ ∑ √ ∂ ≈ € £ — – “q” ‘s’ ✓ \U0001F600",
    "print(\"x\\n\", end=\"\")\nprint(f\"{v:.2f}\\t{w}\")\nprob += lpSum(c[i,j]*x[(i,j)] for i in I for j in J) <= 100\n",
    "STATUS: Optimal\nFINAL_OBJECTIVE: 2600.0\n",
]


def _sha_ids(ids):
    return hashlib.sha256(json.dumps(ids).encode()).hexdigest()[:16]


def _first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def tiktoken_encodings():
    """(o200k_base, o200k_harmony) built offline from the registered o200k_base file (no download possible)."""
    import tiktoken
    import tiktoken.load as tl
    import tiktoken_ext.openai_public as op
    path, sha = H.registered_encoding()
    data = open(path, "rb").read()
    if hashlib.sha256(data).hexdigest() != sha:
        raise SystemExit("[tokcheck] the o200k_base file does not match its registered sha256")
    ranks = {base64.b64decode(t): int(r) for t, r in (ln.split() for ln in data.splitlines() if ln.strip())}

    def _no_network(*a, **k):
        raise RuntimeError("download attempted")
    for name in ("read_file", "read_file_cached"):
        if hasattr(tl, name):
            setattr(tl, name, _no_network)

    def _local(blobpath, expected_hash=None):
        if expected_hash is not None and expected_hash != sha:
            raise RuntimeError("not the expected encoding file")
        return ranks
    op.load_tiktoken_bpe = _local
    base = tiktoken.Encoding(**op.ENCODING_CONSTRUCTORS["o200k_base"]())
    harmony = tiktoken.Encoding(**op.ENCODING_CONSTRUCTORS["o200k_harmony"]())
    return base, harmony, tiktoken.__version__


def _byte_decoder():
    """GPT-2 byte-level alphabet (tokenizer.ggml.model gpt2): character -> byte."""
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("\xa1"), ord("\xac") + 1)) + list(range(ord("\xae"), ord("\xff") + 1))
    cs, n = bs[:], 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {chr(c): b for b, c in zip(bs, cs)}


def cmd_vocab(a):
    m = T.resolve_ollama_model(a.model)
    hdr = GV.read_kv(m["weights_path"], decode=("*",), with_raw=False)
    kv = {p["key"]: p.get("value") for p in hdr["pairs"]}
    toks, types, merges = kv["tokenizer.ggml.tokens"], kv["tokenizer.ggml.token_type"], kv["tokenizer.ggml.merges"]
    base, harmony, version = tiktoken_encodings()
    special = {}
    for k, v in harmony._special_tokens.items():
        special.setdefault(v, set()).add(k)
    dec = _byte_decoder()
    tok_bytes, n_equal, bad, n_special, bad_types = [], 0, [], 0, {}
    pad_named = []  # unused reserved ids: '<|reserved_N|>' in tiktoken, '[PADk]' (user-defined) in the blob
    for i, (s, ty) in enumerate(zip(toks, types)):
        if i in special:
            n_special += 1
            ok = s in special[i] and ty in (3, 4)
            if not ok and s == f"[PAD{i - PAD_BASE}]" and special[i] == {f"<|reserved_{i}|>"} and ty == 4:
                pad_named.append(i)
                tok_bytes.append(None)
                continue
            tok_bytes.append(None)
        else:
            try:
                b = bytes(dec[ch] for ch in s)
            except KeyError:
                b = None
            tok_bytes.append(b)
            ok = b is not None and ty == 1 and b == harmony.decode_single_token_bytes(i)
        if ok:
            n_equal += 1
        else:
            bad.append(i)
            bad_types[str(ty)] = bad_types.get(str(ty), 0) + 1
    rank_of = {b: i for i, b in enumerate(tok_bytes) if b is not None}
    merge_ranks, merge_bad = [], 0
    for mg in merges:
        left, _, right = mg.partition(" ")
        try:
            joined = bytes(dec[ch] for ch in left + right)
        except KeyError:
            merge_bad += 1
            continue
        r = rank_of.get(joined)
        if r is None:
            merge_bad += 1
        else:
            merge_ranks.append(r)
    ordered = all(x <= y for x, y in zip(merge_ranks, merge_ranks[1:]))
    out = {"check": "vocab", "model": a.model, "weights_sha256": m["weights_sha256"], "tiktoken_version": version,
           "encoding": harmony.name, "n_vocab_tiktoken": harmony.n_vocab, "n_tokens_blob": len(toks),
           "n_special": n_special, "n_equal": n_equal, "n_different": len(bad), "different_ids": bad[:50],
           "different_by_token_type": bad_types,
           "n_reserved_named_differently": len(pad_named),
           "reserved_named_differently": ([pad_named[0], pad_named[-1]] if pad_named else None),
           "reserved_note": "unused reserved ids: the blob names them [PAD0]..[PADn] (user-defined, so llama.cpp reads "
                            "that text as one token), tiktoken <|reserved_N|>; neither text occurs in the prompts",
           "pre_in_blob": kv.get("tokenizer.ggml.pre"),
           "architecture_in_blob": kv.get("general.architecture"), "n_merges": len(merges),
           "merges_not_joining_two_tokens": merge_bad, "merges_ordered_by_joined_rank": ordered,
           "ok": (len(bad) == 0 and len(toks) == harmony.n_vocab and merge_bad == 0 and ordered
                  and n_equal + len(pad_named) == len(toks))}
    return out


def _generate(model, system, prompt, think, keep_alive):
    body = {"model": model, "prompt": prompt, "stream": False, "keep_alive": keep_alive,
            "options": {"temperature": 0.0, "top_k": 40, "top_p": 0.9, "seed": 1, "num_ctx": 32768, "num_predict": 1}}
    if system:
        body["system"] = system
    if think is not None:
        body["think"] = think
    req = urllib.request.Request(HOST + "/api/generate", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read().decode())


def _prompts(paths, synthetic):
    """[(label, system text or None, user text)] from requests files ([system, user] only) and the edge strings."""
    out = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                msgs = r["messages"]
                if [m["role"] for m in msgs] != ["system", "user"]:
                    raise SystemExit(f"[tokcheck] {r.get('request_id')}: only [system, user] requests are checked")
                out.append((r["request_id"], msgs[0]["content"], msgs[1]["content"]))
    if synthetic:
        out += [(f"synthetic-{i:02d}", None, s) for i, s in enumerate(SYNTHETIC)]
    return out


def _user_segment(ids, harmony):
    """The ids of the last user message's text: between <|start|>user<|message|> and the next <|end|>."""
    start, message, end = (harmony.encode(t, allowed_special="all")[0] for t in ("<|start|>", "<|message|>", "<|end|>"))
    user = harmony.encode("user")
    for i in range(len(ids) - 1, -1, -1):
        if ids[i] == start and ids[i + 1:i + 1 + len(user)] == user and ids[i + 1 + len(user)] == message:
            j = ids.index(end, i + 2 + len(user)) if end in ids[i + 2 + len(user):] else len(ids)
            return ids[i + 2 + len(user):j]
    return None


def _think(v):
    if v in (None, "none"):
        return None
    if v in ("true", "false"):
        return v == "true"
    return v


def cmd_server(a):
    base, harmony, version = tiktoken_encodings()
    counter_render = T.OllamaCounter(a.model).render
    think = _think(a.think)
    rows, t0 = [], time.time()
    for label, system, user in _prompts(a.requests, a.synthetic):
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
        prompt, info = counter_render(msgs, think)
        local = harmony.encode(prompt, allowed_special="all")
        r = _generate(a.model, system, user, think, a.keep_alive)
        ctx = r.get("context")
        if not ctx:
            raise SystemExit(f"[tokcheck] {label}: the server returned no context")
        server = ctx[:-1]  # the last id is the one generated token
        seg = _user_segment(server, harmony)
        user_base = base.encode(user, disallowed_special=())
        rows.append({"label": label, "n_server": len(server), "n_local": len(local), "prompt_eval_count": r.get("prompt_eval_count"),
                     "equal": server == local, "first_diff": _first_diff(server, local),
                     "user_ids_equal_o200k_base": seg == user_base if seg is not None else None,
                     "n_user_o200k_base": len(user_base), "server_ids_sha": _sha_ids(server),
                     "current_date": info.get("current_date"), "load_s": round((r.get("load_duration") or 0) / 1e9, 2)})
        print(json.dumps(rows[-1]), flush=True)
    n_eq = sum(1 for x in rows if x["equal"])
    n_user = sum(1 for x in rows if x["user_ids_equal_o200k_base"])
    return {"check": "server", "model": a.model, "think": think, "tiktoken_version": version, "n_prompts": len(rows),
            "n_equal": n_eq, "n_user_equal_o200k_base": n_user,
            "n_tokens_server_total": sum(x["n_server"] for x in rows), "seconds": round(time.time() - t0, 1),
            "rows": rows, "ok": n_eq == len(rows) and n_user == len(rows)}


def cmd_llama(a):
    base, harmony, version = tiktoken_encodings()
    m = T.resolve_ollama_model(a.model)
    try:
        tok = H.DerivedVocabTokenizer(m["weights_path"], m["weights_sha256"])
    except T.TokenizerError as e:
        return {"check": "llama", "model": a.model, "available": False, "reason": str(e)[:200], "ok": None}
    rows = []
    think = _think(a.think)
    for label, system, user in _prompts(a.requests, a.synthetic):
        texts = ([system] if system else []) + [user]
        for k, t in enumerate(texts):
            lt, tt = tok.ids(t, parse_special=False), base.encode(t, disallowed_special=())
            rows.append({"label": f"{label}#{'system' if system and k == 0 else 'user'}", "n_llama": len(lt), "n_tiktoken": len(tt),
                         "equal": lt == tt, "first_diff": _first_diff(lt, tt)})
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
        prompt, _ = T.TEMPLATE_RENDERERS[m["template_sha256"]][1](msgs, think=think)
        lp, tp = tok.ids(prompt, parse_special=True), harmony.encode(prompt, allowed_special="all")
        rows.append({"label": f"{label}#rendered", "n_llama": len(lp), "n_tiktoken": len(tp), "equal": lp == tp,
                     "first_diff": _first_diff(lp, tp)})
    n_eq = sum(1 for x in rows if x["equal"])
    return {"check": "llama", "model": a.model, "available": True, "llama_tokenize": tok.identity(),
            "tiktoken_version": version, "n_texts": len(rows), "n_equal": n_eq, "rows": rows, "ok": n_eq == len(rows)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["vocab", "server", "llama"])
    ap.add_argument("--model", default="gpt-oss:20b")
    ap.add_argument("--requests", nargs="*", default=[])
    ap.add_argument("--think", default="low", help="low|medium|high|true|false|none (none: no think field)")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--keep-alive", default=0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    out = {"vocab": cmd_vocab, "server": cmd_server, "llama": cmd_llama}[a.what](a)
    text = json.dumps(out, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    summary = {k: v for k, v in out.items() if k != "rows"}
    print(json.dumps(summary, indent=1))
    return 0 if out.get("ok") in (True, None) else 1


if __name__ == "__main__":
    sys.exit(main())
