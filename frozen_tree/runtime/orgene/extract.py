"""Extract the spec JSON block and the Python program from a model response."""
import json
import re

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)[ \t]*\n(.*?)```", re.DOTALL)


def strip_thinking(text: str) -> str:
    return _THINK_RE.sub("", text or "")


def fenced_blocks(text: str):
    """Return list of (lang_lower, body) for every fenced block."""
    out = []
    for m in _FENCE_RE.finditer(text or ""):
        out.append((m.group(1).strip().lower(), m.group(2)))
    return out


def _parse_json_loose(s: str):
    s = s.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        pass
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(s[a:b + 1])
        except Exception:  # noqa: BLE001
            return None
    return None


def extract(text: str):
    """Return {"spec": dict|None, "spec_raw": str|None, "code": str|None, "n_json_blocks": int, "n_code_blocks": int}."""
    text = strip_thinking(text)
    blocks = fenced_blocks(text)
    json_blocks = [b for lang, b in blocks if lang in ("json", "jsonc", "json5")]
    code_blocks = [b for lang, b in blocks if lang in ("python", "py", "python3")]
    # unlabeled fences: guess by content
    for lang, b in blocks:
        if lang == "":
            bs = b.strip()
            if bs.startswith("{") and bs.endswith("}"):
                json_blocks.append(b)
            elif "import pulp" in b or "LpProblem" in b:
                code_blocks.append(b)
    spec = None
    spec_raw = None
    for jb in json_blocks:
        parsed = _parse_json_loose(jb)
        if isinstance(parsed, dict):
            spec, spec_raw = parsed, jb
            break
    code = code_blocks[-1] if code_blocks else None  # last program wins (repair outputs may restate)
    if code is None:
        # fallback: unfenced program
        i = text.find("import pulp")
        if i == -1:
            i = text.find("from pulp import")
        if i != -1:
            code = text[i:]
    if code is not None:
        code = code.strip("\n") + "\n"
    return {
        "spec": spec,
        "spec_raw": spec_raw,
        "code": code,
        "n_json_blocks": len(json_blocks),
        "n_code_blocks": len(code_blocks),
    }
