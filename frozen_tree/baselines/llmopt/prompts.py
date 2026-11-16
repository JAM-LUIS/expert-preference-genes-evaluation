#!/usr/bin/env python3
"""The LLMOPT prompts: pinned, kept out of git and out of any release (E18).

Source: github.com/antgroup/LLMOPT at commit 1492dd33e39ea13f1afe32a0adc13d4217334195, file
prompts/generate_prompt.py (3843 bytes, sha256 20797b50...). That repository has no license file, so its prompts are
used for internal evaluation only, with attribution, and are never distributed:

  - the file lives in baselines/llmopt/vendor/, which baselines/llmopt/.gitignore excludes from git (and therefore from
    the anonymous repository and from any archive made from git); it is named *.upstream so that no code glob of the
    freeze manifest picks it up;
  - this module pins its sha256 and refuses any other bytes, so the frozen code fixes the prompts exactly;
  - run directories keep the rendered prompts in requests.q2f.jsonl / requests.f2c.jsonl, which the driver lists
    under `not_for_release` in run_config.json: a release of run outputs leaves those two files out.

Installing (once per host; no download is made here):
  $PY baselines/llmopt/prompts.py install --from-file <copy of prompts/generate_prompt.py at the pinned commit>
  $PY baselines/llmopt/prompts.py install --from-smoke-script <baseline-environment smoke script embedding it>
  $PY baselines/llmopt/prompts.py check

The file only defines strings and the functions Q2F / F2C / Q2C / QF2C; it is executed in a fresh namespace after its
hash has been checked.
"""
import argparse
import base64
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(HERE, "vendor")
VENDOR_FILE = os.path.join(VENDOR_DIR, "generate_prompt.py.upstream")
UPSTREAM = {
    "repository": "github.com/antgroup/LLMOPT",
    "commit": "1492dd33e39ea13f1afe32a0adc13d4217334195",
    "path": "prompts/generate_prompt.py",
    "size": 3843,
    "sha256": "20797b501d6c167a4dd28cdbd30b32a7252a6cc332ac13e709f23fe97e279a51",
    "license": "none (the repository has no license file): internal evaluation only, attributed, not distributed",
}
PROMPTS_SHA256 = UPSTREAM["sha256"]
REQUIRED_FUNCTIONS = ("Q2F", "F2C")
_B64_RE = re.compile(r'LLMOPT_PROMPTS_B64\s*=\s*"([A-Za-z0-9+/=]+)"')


class PromptsError(RuntimeError):
    """The pinned prompt file is missing or is not the pinned bytes."""


class Prompts:
    """Q2F(question) and F2C(five_elements) from the pinned upstream file."""

    def __init__(self, source, sha256):
        ns = {"__name__": "llmopt_generate_prompt"}
        exec(compile(source, "generate_prompt.py", "exec", dont_inherit=True), ns)  # noqa: S102 (pinned by hash)
        missing = [f for f in REQUIRED_FUNCTIONS if not callable(ns.get(f))]
        if missing:
            raise PromptsError(f"prompt file defines no {missing}")
        self.Q2F, self.F2C, self.sha256 = ns["Q2F"], ns["F2C"], sha256


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def load(path=None, expected_sha256=PROMPTS_SHA256):
    """The pinned prompts. Raises PromptsError when the file is missing or its bytes are not the pinned ones."""
    path = path or VENDOR_FILE
    if not os.path.isfile(path):
        raise PromptsError("LLMOPT prompt file not installed (baselines/llmopt/vendor/, not in git); see "
                           "`baselines/llmopt/prompts.py install --help`")
    with open(path, "rb") as f:
        b = f.read()
    got = _sha(b)
    if got != expected_sha256:
        raise PromptsError(f"LLMOPT prompt file sha256 {got[:12]}... is not the pinned {expected_sha256[:12]}...")
    return Prompts(b.decode("utf-8"), got)


def from_smoke_script(text):
    """The prompt file embedded (base64) in the baseline-environment smoke script."""
    m = _B64_RE.search(text)
    if not m:
        raise PromptsError("no LLMOPT_PROMPTS_B64 string in the given script")
    return base64.b64decode(m.group(1))


def install(data, dest=None, expected_sha256=PROMPTS_SHA256):
    """Write the prompt bytes to the vendor directory after checking their hash. Returns the destination path."""
    got = _sha(data)
    if got != expected_sha256:
        raise PromptsError(f"refused: sha256 {got[:12]}... is not the pinned {expected_sha256[:12]}...")
    dest = dest or VENDOR_FILE
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(prog="llmopt prompts", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("install")
    g = i.add_mutually_exclusive_group(required=True)
    g.add_argument("--from-file")
    g.add_argument("--from-smoke-script")
    sub.add_parser("check")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "install":
            if a.from_file:
                with open(a.from_file, "rb") as f:
                    data = f.read()
            else:
                with open(a.from_smoke_script, encoding="utf-8") as f:
                    data = from_smoke_script(f.read())
            install(data)
            print("[prompts] installed baselines/llmopt/vendor/generate_prompt.py.upstream "
                  f"(sha256 {PROMPTS_SHA256[:12]}...)")
        else:
            p = load()
            print(f"[prompts] OK sha256 {p.sha256[:12]}... ({UPSTREAM['repository']} @ {UPSTREAM['commit'][:7]})")
    except (PromptsError, OSError) as e:
        print(f"[prompts] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
