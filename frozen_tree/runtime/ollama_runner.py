#!/usr/bin/env python3
"""
ollama_runner.py — reproducible batch generation against a local Ollama server through the native /api/chat
(thin wrapper over orgene.backends.ollama + orgene.runner; R1, E08). Standard library only.

USAGE
  $ORGENE_PY runtime/ollama_runner.py --model qwen3:8b --requests experiments/<run>/requests.C0.jsonl \
      --out experiments/<run>/gen.C0.r0 [--num-ctx 32768] [--num-predict 6000] [--temperature 0] [--top-k 20] \
      [--top-p 0.95] [--seed 1] [--repeat 1] [--keep-alive 0] [--think [LEVEL]] [--schema FILE|json] [--limit N] [--no-resume] \
      [--registry configs/model_registry.json --registry-entry ID] [--local-tokens on|off] \
      [--token-counter module:function] [--require-local-tokens] [--host http://127.0.0.1:11434] [--timeout 900] \
      [--max-attempts 2]

INPUT / OUTPUT: see orgene/runner.py (v5 layout: config.json, outputs/<request_id>.r<k>.json, receipts.jsonl,
metrics.json). Every call record carries started_at, finished_at, seed, digest, the options as sent,
request_sha256, done_reason, the server's token counts and local_tokens.

WHAT IS SENT (every call)
  options: temperature, top_k, top_p, seed, num_ctx, num_predict — all explicit, so nothing is inherited from the
           Modelfile except parameters this runner does not set (recorded as `inherited_server_defaults`);
  think:   explicit true/false (default false; bare --think = true), or a reasoning level low|medium|high
           (gpt-oss, E23: its reasoning cannot be switched off; the study sends --think low);
  keep_alive: default 0 — the model is unloaded after every call (a warm KV cache can change greedy output);
  seed:    --seed + k for repeat k.

LOCAL TOKEN COUNTS (E09, --local-tokens on by default)
  Every answered call also gets `local_tokens` (orgene/tokcount.py): llama-tokenize over the model's own weights blob
  counts each message body, the prompt as Ollama renders it (should equal prompt_eval_count) and the completion.
  The counter's identity is recorded as `local_tokenizer` in config.json and pinned for resume. The runner stops
  before the first call if the server reports no digest or a digest other than the local manifest's, if the
  tokenizer, the blob or the template port is missing, or if a request carries something the local port does not
  render (images, tool calls, unknown roles). A counter that fails on one answered call leaves local_tokens None and
  the reason in local_tokens_error; the answer itself is kept. `--token-counter module:function` replaces the
  built-in counter (tests, other tokenizers); `--local-tokens off` is only for runs outside the study.

REFUSALS (before any call): resume with settings that differ from the existing config.json (the local tokenizer
included); settings that differ from the given registry entry; missing or mismatched local tokenizer (above);
--require-local-tokens without a counter.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from orgene import runner as RN  # noqa: E402
from orgene.backends.base import BackendError, OptionsError, sha256_hex  # noqa: E402
from orgene.backends.ollama import OllamaBackend, parse_keep_alive, parse_think  # noqa: E402

CODE_FILES = [os.path.abspath(__file__)] + [os.path.join(HERE, "orgene", p) for p in
                                            ("runner.py", os.path.join("backends", "base.py"), os.path.join("backends", "ollama.py"))]
TOKCOUNT_FILE = os.path.join(HERE, "orgene", "tokcount.py")
# E23: the gpt-oss port (harmony template, tokenizers) that tokcount loads
TOKCOUNT_EXTRA_FILES = [os.path.join(HERE, "orgene", p) for p in ("tokcount_harmony.py", "gguf_vocab.py")]


def think_arg(v):
    """--think value: true / false / low / medium / high (a bare --think is true)."""
    try:
        return parse_think(v)
    except OptionsError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def build_parser():
    ap = argparse.ArgumentParser(description="Reproducible batch runner for Ollama /api/chat")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--model", required=True)
    ap.add_argument("--requests", required=True, help="JSONL file of requests")
    ap.add_argument("--out", required=True, help="output run directory (created if missing)")
    ap.add_argument("--schema", default=None, help="path to a JSON schema file, or the literal 'json' for unconstrained JSON mode")
    ap.add_argument("--num-ctx", type=int, default=32768)
    ap.add_argument("--num-predict", type=int, default=6000)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="only run the first N requests (smoke tests)")
    ap.add_argument("--no-resume", action="store_true", help="re-run even if an output file exists")
    ap.add_argument("--think", nargs="?", const=True, default=False, type=think_arg,
                    help="thinking: absent = false, bare --think = true, or true|false|low|medium|high (a reasoning "
                         "level: gpt-oss); sent explicitly either way")
    ap.add_argument("--keep-alive", default="0", help="seconds or a duration such as 30m (default 0: unload after each call)")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per call")
    ap.add_argument("--max-attempts", type=int, default=2)
    ap.add_argument("--retry-sleep", type=float, default=5.0, help="seconds x attempt number between attempts (max 30)")
    ap.add_argument("--registry", default=None, help="model registry JSON (E19); with --registry-entry")
    ap.add_argument("--registry-entry", default=None)
    ap.add_argument("--local-tokens", choices=["on", "off"], default="on",
                    help="record local tokenizer counts per call (E09); 'off' only for runs outside the study")
    ap.add_argument("--token-counter", default=None,
                    help="module:function (or counter object) replacing the built-in local counter (E09 hook)")
    ap.add_argument("--require-local-tokens", action="store_true")
    ap.add_argument("--note", default="", help="free-text note stored in config.json")
    return ap


def _builtin_counter(backend, prefix="[runner]"):
    """E09: orgene.tokcount.OllamaCounter over the blobs the server serves. Exits before any call when it cannot be
    built: no digest from the server, a digest that is not the local manifest, a missing tokenizer, blob or template
    port."""
    from orgene.tokcount import OllamaCounter, TokenizerError
    try:
        digest = backend.digest()
    except BackendError as e:
        raise SystemExit(f"{prefix} {e}")
    try:
        if not digest:
            raise TokenizerError(f"the server reports no digest for {backend.model}")
        return OllamaCounter(backend.model, expect_digest=digest)
    except TokenizerError as e:
        raise SystemExit(f"{prefix} local token counts unavailable: {e}")


def _check_renderable(counter, requests, think, prefix="[runner]"):
    """E09: every request must be renderable by the local template port before any call is made."""
    if not hasattr(counter, "render"):
        return
    from orgene.tokcount import TokenizerError
    for r in requests:
        try:
            counter.render(r["messages"], think)
        except TokenizerError as e:
            raise SystemExit(f"{prefix} local token counts unavailable for {r['request_id']}: {e}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    fmt, schema_sha = None, None
    if args.schema:
        if args.schema == "json":
            fmt = "json"
        else:
            with open(args.schema, "rb") as f:
                raw = f.read()
            schema_sha = sha256_hex(raw)
            fmt = json.loads(raw.decode("utf-8"))
    try:
        keep_alive = parse_keep_alive(args.keep_alive)
    except OptionsError as e:
        raise SystemExit(f"[runner] {e}")
    if args.local_tokens == "off" and args.token_counter:
        raise SystemExit("[runner] --token-counter needs --local-tokens on")
    backend = OllamaBackend(args.model, host=args.host, timeout=args.timeout, max_attempts=args.max_attempts,
                            retry_sleep=args.retry_sleep)
    registry = RN.load_registry_entry(args.registry, args.registry_entry)
    requests = RN.load_requests(args.requests)
    if args.limit:
        requests = requests[: args.limit]
    code_files = list(CODE_FILES)
    counter, counter_id = None, None
    if args.token_counter:
        counter, counter_id = RN.load_token_counter(args.token_counter), args.token_counter
    elif args.local_tokens == "on":
        counter = _builtin_counter(backend)
        counter_id = "orgene.tokcount:OllamaCounter"
        code_files += [TOKCOUNT_FILE] + TOKCOUNT_EXTRA_FILES
    if counter is not None:
        _check_renderable(counter, requests, args.think)
        backend.token_counter, backend.token_counter_id = counter, counter_id
    opts = {"temperature": args.temperature, "top_k": args.top_k, "top_p": args.top_p, "seed": args.seed,
            "num_ctx": args.num_ctx, "num_predict": args.num_predict, "think": args.think, "keep_alive": keep_alive}
    return RN.run_batch(backend, requests, args.out, opts, repeat=args.repeat, fmt=fmt, schema_path=args.schema,
                        schema_sha256=schema_sha, requests_path=args.requests, resume=not args.no_resume,
                        argv=[os.path.abspath(__file__)] + (sys.argv[1:] if argv is None else list(argv)),
                        code_files=code_files, note=args.note, registry=registry,
                        require_local_tokens=args.require_local_tokens, prefix="[runner]")


if __name__ == "__main__":
    sys.exit(main())
