"""MIPLIB-NL instance -> R1 problem text (E22). The benchmark's own wording is kept verbatim.

Isolation: this file holds the glue wording of engineering hold-out cases (data/cases/README_ISOLATION.md).

An instance directory holds instance.json (abstract_problem, parameters, files, optimal_value) and the CSV files it
names. The R1 system prompts forbid reading files, so the data travel inside the text: the problem text is
  abstract_problem, verbatim;
  the instance parameters (JSON, as in the file);
  for every data file, its key, its path and its description, verbatim, followed by the file's full contents.
Only fixed glue lines (GLUE) are added; nothing is reworded. optimal_value never enters the text.
"""
import hashlib
import json
import os

CONVERTER_VERSION = "miplib_nl.v1"

GLUE = {
    "parameters": "Instance parameters:",
    "files": "Data files. Each file is described below, followed by its full contents.",
    "no_files": "There are no data files.",
    "file": "File `{key}` ({path}):",
    "contents": "Contents:",
}


class ConvertError(ValueError):
    """The instance directory cannot be converted as it is."""


def _read_text(path):
    with open(path, "rb") as f:
        b = f.read()
    try:
        t = b.decode("utf-8")
    except UnicodeDecodeError:
        raise ConvertError(f"{os.path.basename(path)} is not UTF-8") from None
    if t.startswith("﻿"):
        raise ConvertError(f"{os.path.basename(path)} starts with a byte-order mark")
    if "```" in t:
        raise ConvertError(f"{os.path.basename(path)} contains a code fence")
    return t


def convert(instance_dir):
    """(text, info) for one instance directory."""
    with open(os.path.join(instance_dir, "instance.json"), encoding="utf-8") as f:
        inst = json.load(f)
    for k in ("abstract_problem", "parameters", "files"):
        if k not in inst:
            raise ConvertError(f"instance.json has no {k}")
    parts = [inst["abstract_problem"].strip(), "",
             GLUE["parameters"], "```json", json.dumps(inst["parameters"], indent=2, ensure_ascii=False), "```", ""]
    files = inst["files"] or {}
    file_info = {}
    if not files:
        parts.append(GLUE["no_files"])
    else:
        parts.append(GLUE["files"])
        for key, entry in files.items():
            path = entry["path"]
            src = os.path.normpath(os.path.join(instance_dir, path))
            if not src.startswith(os.path.normpath(instance_dir) + os.sep):
                raise ConvertError(f"file {key} points outside the instance directory")
            if not os.path.isfile(src):
                raise ConvertError(f"file {key} ({path}) is missing")
            body = _read_text(src)
            file_info[key] = {"path": path, "bytes": os.path.getsize(src),
                              "sha256": hashlib.sha256(open(src, "rb").read()).hexdigest(),
                              "crlf": "\r\n" in body}
            parts += ["", GLUE["file"].format(key=key, path=path), entry.get("description", "").strip(),
                      GLUE["contents"], "```csv", body.rstrip("\n"), "```"]
    text = "\n".join(parts) + "\n"
    info = {"converter_version": CONVERTER_VERSION,
            "glue_sha256": hashlib.sha256(json.dumps(GLUE, sort_keys=True).encode("utf-8")).hexdigest(),
            "files": file_info, "parameters": inst["parameters"],
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "text_chars": len(text), "text_bytes": len(text.encode("utf-8"))}
    return text, info


def official_value(instance_dir):
    """optimal_value of instance.json as a float (it is a number or a numeric string); None when absent."""
    with open(os.path.join(instance_dir, "instance.json"), encoding="utf-8") as f:
        v = json.load(f).get("optimal_value")
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
