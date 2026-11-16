#!/usr/bin/env python3
"""Reference renderings for the two chat templates of the LLMOPT anchor (E18). Loads no model.

  python3 baselines/llmopt/template_ref.py > runtime/tests/fixtures/llmopt_template_reference.json

Needs `go` (Go's text/template, through E09's generic renderer tools/qwen3_template_ref/main.go, which applies
Ollama's collate step) and a Python with jinja2 (environment as in HF transformers' apply_chat_template:
ImmutableSandboxedEnvironment, trim_blocks, lstrip_blocks, loopcontrols). The cases are the synthetic conversations
in runtime/tests/fixtures/llmopt_template_cases.json; runtime/tests/test_llmopt_anchor.py checks the Python ports in
templates.py against this file byte for byte.
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FIX = os.path.join(ROOT, "runtime", "tests", "fixtures")
CASES = os.path.join(FIX, "llmopt_template_cases.json")
GO_TEMPLATE = os.path.join(FIX, "llmopt_ollama_template.gotmpl")
JINJA_TEMPLATE = os.path.join(FIX, "qwen25_chat_template.jinja")
GO_RENDERER = os.path.join("tools", "qwen3_template_ref", "main.go")


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def render_go(cases):
    with open(CASES, "rb") as f:
        p = subprocess.run(["go", "run", GO_RENDERER, os.path.relpath(GO_TEMPLATE, ROOT)], input=f.read(),
                           capture_output=True, cwd=ROOT, check=True)
    ref = json.loads(p.stdout)
    out = {c["name"]: c["prompt"] for c in ref["cases"]}
    return out, ref["go_version"], ref["template_sha256"]


def render_jinja(cases):
    import jinja2
    from jinja2.ext import loopcontrols
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True, extensions=[loopcontrols])
    env.filters["tojson"] = lambda x, indent=None: json.dumps(x, ensure_ascii=False, indent=indent)
    with open(JINJA_TEMPLATE, encoding="utf-8", newline="") as f:
        tmpl = env.from_string(f.read())
    out = {c["name"]: tmpl.render(messages=c["messages"], tools=None, add_generation_prompt=True) for c in cases}
    return out, jinja2.__version__


def main():
    with open(CASES, encoding="utf-8") as f:
        cases = json.load(f)
    go, go_version, go_sha = render_go(cases)
    jj, jinja_version = render_jinja(cases)
    ref = {"generator": "baselines/llmopt/template_ref.py",
           "go": {"template_sha256": go_sha, "go_version": go_version, "renderer": GO_RENDERER},
           "jinja": {"template_sha256": sha(JINJA_TEMPLATE), "jinja2_version": jinja_version,
                     "environment": "ImmutableSandboxedEnvironment(trim_blocks, lstrip_blocks, loopcontrols), "
                                    "add_generation_prompt=True, tools=None"},
           "cases": [{"name": c["name"], "messages": c["messages"], "modelfile": go[c["name"]],
                      "gguf": jj[c["name"]]} for c in cases]}
    json.dump(ref, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
