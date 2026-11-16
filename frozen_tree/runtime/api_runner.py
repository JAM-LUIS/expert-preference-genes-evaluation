#!/usr/bin/env python3
"""
api_runner.py — reproducible batch generation against an OFFICIAL model API
(thin wrapper over orgene.backends.{openai_compat,anthropic} + orgene.runner; R1, E08). Standard library only.

Same input/output contract as ollama_runner.py, so `orgene_cli.py validate` reads both. Keys come from environment
variables only and are never written anywhere.

BACKENDS
  --backend openai      OpenAI Chat Completions (OPENAI_API_KEY; base https://api.openai.com/v1)
  --backend deepseek    DeepSeek official, OpenAI-compatible (DEEPSEEK_API_KEY; base https://api.deepseek.com)
  --backend anthropic   Anthropic Messages API (ANTHROPIC_API_KEY; base https://api.anthropic.com)
  --backend compat      any OpenAI-compatible OFFICIAL endpoint: pass --base-url and --api-key-env
  Third-party relay gateways are out of policy for this project and are refused.

USAGE
  export OPENAI_API_KEY=...
  $ORGENE_PY runtime/api_runner.py --backend openai --model <dated snapshot> --requests experiments/<run>/requests.C3.jsonl \
      --out experiments/<run>/gen.C3.r0 --max-tokens 4000 --temperature 0 [--top-p P] [--repeat 1] [--limit N] [--no-resume] \
      [--registry configs/model_registry.json --registry-entry ID] [--token-counter module:function]

OUTPUT (--out): config.json, outputs/<request_id>.r<k>.json, receipts.jsonl, metrics.json  (same layout as ollama_runner)
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from orgene import runner as RN  # noqa: E402
from orgene.backends.base import BackendError, OptionsError  # noqa: E402

PRESETS = ("openai", "deepseek", "anthropic", "compat")


def build_parser():
    ap = argparse.ArgumentParser(description="Reproducible batch runner for official model APIs")
    ap.add_argument("--backend", choices=sorted(PRESETS), required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--requests", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-url", default=None, help="override base URL (required for --backend compat)")
    ap.add_argument("--api-key-env", default=None, help="env var holding the key (default per backend)")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--no-temperature", action="store_true", help="do not send temperature (reasoning models)")
    ap.add_argument("--top-p", type=float, default=None, help="sent only when given (OpenAI-compatible backends)")
    ap.add_argument("--max-tokens", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=1, help="OpenAI-compatible only; best-effort determinism")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--retry-sleep", type=float, default=5.0, help="seconds x attempt number between attempts (max 60)")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between calls (rate limiting)")
    ap.add_argument("--registry", default=None, help="model registry JSON (E19); with --registry-entry")
    ap.add_argument("--registry-entry", default=None)
    ap.add_argument("--token-counter", default=None, help="module:function giving local token counts (E09)")
    ap.add_argument("--require-local-tokens", action="store_true")
    ap.add_argument("--note", default="")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    counter = RN.load_token_counter(args.token_counter, prefix="[api_runner]")
    common = dict(timeout=args.timeout, max_attempts=args.max_attempts, retry_sleep=args.retry_sleep,
                  token_counter=counter, token_counter_id=args.token_counter)
    temperature = None if args.no_temperature else args.temperature
    try:
        if args.backend == "anthropic":
            from orgene.backends.anthropic import AnthropicBackend
            backend = AnthropicBackend(args.model, base_url=args.base_url, key_env=args.api_key_env or "ANTHROPIC_API_KEY", **common)
            opts = {"temperature": temperature, "max_tokens": args.max_tokens}
            module = "anthropic.py"
        else:
            from orgene.backends.openai_compat import OpenAICompatBackend
            if args.backend == "compat" and not (args.base_url and args.api_key_env):
                raise SystemExit("[api_runner] --backend compat needs --base-url and --api-key-env")
            backend = OpenAICompatBackend(args.model, preset=args.backend, base_url=args.base_url, key_env=args.api_key_env, **common)
            opts = {"temperature": temperature, "top_p": args.top_p, "seed": args.seed, "max_tokens": args.max_tokens}
            module = "openai_compat.py"
    except (OptionsError, BackendError) as e:
        raise SystemExit(f"[api_runner] {e}")
    registry = RN.load_registry_entry(args.registry, args.registry_entry, prefix="[api_runner]")
    requests = RN.load_requests(args.requests, prefix="[api_runner]")
    if args.limit:
        requests = requests[: args.limit]
    code_files = [os.path.abspath(__file__)] + [os.path.join(HERE, "orgene", p) for p in
                                                ("runner.py", os.path.join("backends", "base.py"), os.path.join("backends", module))]
    return RN.run_batch(backend, requests, args.out, opts, repeat=args.repeat, requests_path=args.requests,
                        resume=not args.no_resume,
                        argv=[os.path.abspath(__file__)] + (sys.argv[1:] if argv is None else list(argv)),
                        code_files=code_files, note=args.note, registry=registry, sleep=args.sleep,
                        require_local_tokens=args.require_local_tokens, prefix="[api_runner]")


if __name__ == "__main__":
    sys.exit(main())
