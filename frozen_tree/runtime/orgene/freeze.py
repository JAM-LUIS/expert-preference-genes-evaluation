"""Freeze manifest and test gate (E21).

  make      hash everything the freeze spec (configs/freeze_spec.json) lists -> FREEZE_MANIFEST.json
  verify    recompute every hash in the manifest; any changed, missing or added file fails
  register  record the OSF registration id of the uploaded manifest (outside the hashed content)
  gate      stages that touch sealed cases (test, and the engineering hold-out) refuse to run unless the manifest
            is complete, verifies, and carries an OSF registration id for exactly this content; every pass is
            appended to <run>/freeze_gate.jsonl, so each test run records the manifest it ran under

Manifest layout (JSON, keys sorted):
  schema, created_at, spec {path, sha256}, complete, missing[], items {id: {...}}, supersedes[],
  files {"<path relative to the repository root>": {sha256, bytes, items[]}},
  computed {id: {status, value, info}}, anon_scan {...},
  content_sha256   sha256 of the canonical JSON of every key above
  osf              {registration_id, registered_content_sha256, recorded_at}; NOT part of content_sha256, so the id
                   can be filled in after the upload (and swapped for an anonymous link at submission) without
                   changing the frozen hash.
The `files` table has the shape runtime/orgene/refs.py (E13) reads: {path: {"sha256": ...}}.

Nothing here prints file contents: reports carry paths, hashes and counts only.
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import types
from datetime import datetime, timezone

from . import anon as A
from .paths import ROOT, rel

SPEC_SCHEMA = "orgene.freeze_spec.v1"
MANIFEST_SCHEMA = "orgene.freeze_manifest.v1"
DEFAULT_SPEC = os.path.join("configs", "freeze_spec.json")
DEFAULT_MANIFEST = "FREEZE_MANIFEST.json"
GATE_LOG = "freeze_gate.jsonl"

# Splits whose cases are sealed until the freeze, and the id files that list them (under data/splits*/).
SEALED_SPLITS = ("test", "eng_holdout")
SEALED_ID_FILES = ("test_ids.json", "eng_holdout_ids.json")
SEALED_ID_GLOBS = tuple(os.path.join("data", "splits*", "**", f) for f in SEALED_ID_FILES)

CATEGORIES = ("gene", "prompts", "code", "config", "data", "baselines", "model", "text")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
# OSF GUIDs are five lower-case letters/digits; accepted as the GUID, an osf.io URL or the OSF DOI.
_OSF_GUID = re.compile(r"^[a-z0-9]{5}$")
_OSF_FORMS = (re.compile(r"^(?:https?://)?(?:www\.)?osf\.io/([a-z0-9]{5})/?$", re.I),
              re.compile(r"^(?:https?://doi\.org/)?10\.17605/osf\.io/([a-z0-9]{5})$", re.I))
_OSF_PLACEHOLDERS = {"abcde", "12345", "01234", "dummy", "tbd00", "xxxx0", "osfid", "fake0", "fake1", "test0", "test1",
                     "later", "draft", "empty", "blank", "none0", "null0", "unset"}
_GLOB_SKIP = ("__pycache__", ".DS_Store", ".pytest_cache")


class FreezeError(RuntimeError):
    """The manifest cannot be made or registered."""


class ProviderError(RuntimeError):
    """A computed item could not be computed."""


class GateRefused(RuntimeError):
    """A stage that touches sealed cases is not allowed to run."""


# ------------------------------------------------------------------ helpers


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def content_sha256(manifest):
    return sha_bytes(canon({k: v for k, v in manifest.items() if k not in ("content_sha256", "osf")}))


def _inside(root, relpath):
    if not isinstance(relpath, str) or not relpath or os.path.isabs(relpath):
        return False
    full = os.path.realpath(os.path.join(root, relpath))
    r = os.path.realpath(root)
    return full == r or full.startswith(r + os.sep)


def _git(root, *args):
    try:
        p = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise ProviderError(f"git not available ({type(e).__name__})") from None
    if p.returncode != 0:
        raise ProviderError(f"git {args[0]} failed")
    return p.stdout


def normalize_osf_id(value):
    """OSF registration GUID (lower case) from a GUID, an osf.io URL or an OSF DOI; None when not recognised."""
    v = str(value or "").strip()
    guid = None
    if _OSF_GUID.match(v.lower()):
        guid = v.lower()
    else:
        for rx in _OSF_FORMS:
            m = rx.match(v)
            if m:
                guid = m.group(1).lower()
                break
    if guid is None or guid in _OSF_PLACEHOLDERS or len(set(guid)) == 1:
        return None
    return guid


# ------------------------------------------------------------------ spec


def load_spec(root, spec_path=None):
    """(spec dict, spec path relative to root, spec sha256)."""
    sp = spec_path or os.path.join(root, DEFAULT_SPEC)
    if not os.path.isabs(sp):
        sp = os.path.join(root, sp)
    if not os.path.isfile(sp):
        raise FreezeError(f"freeze spec not found: {os.path.relpath(sp, root)}")
    raw = open(sp, "rb").read()
    try:
        spec = json.loads(raw)
    except ValueError:
        raise FreezeError("freeze spec is not valid JSON") from None
    if spec.get("schema") != SPEC_SCHEMA:
        raise FreezeError(f"freeze spec schema must be {SPEC_SCHEMA}")
    ids = set()
    for it in spec.get("items", []):
        iid = it.get("id")
        if not iid or iid in ids:
            raise FreezeError(f"freeze spec: missing or duplicate item id {iid!r}")
        ids.add(iid)
        if it.get("category") not in CATEGORIES:
            raise FreezeError(f"freeze spec item {iid}: category must be one of {CATEGORIES}")
        kinds = [k for k in ("path", "glob", "pending") if it.get(k)]
        if len(kinds) != 1:
            raise FreezeError(f"freeze spec item {iid}: exactly one of path / glob / pending")
        for p in ([it["path"]] if it.get("path") else []) + (_as_list(it.get("glob"))):
            if not _inside(root, p) or ".." in p.replace("\\", "/").split("/"):
                raise FreezeError(f"freeze spec item {iid}: paths must be relative and inside the repository")
    for c in spec.get("computed", []):
        cid = c.get("id")
        if not cid or cid in ids:
            raise FreezeError(f"freeze spec: missing or duplicate computed id {cid!r}")
        ids.add(cid)
        if c.get("kind") not in ("git_trees", "call"):
            raise FreezeError(f"freeze spec computed {cid}: kind must be git_trees or call")
    return spec, os.path.relpath(sp, root).replace(os.sep, "/"), sha_bytes(raw)


def _as_list(x):
    if not x:
        return []
    return [x] if isinstance(x, str) else list(x)


def expand_glob(root, patterns):
    out = set()
    for pat in _as_list(patterns):
        for p in glob.glob(os.path.join(root, pat), recursive=True):
            if not os.path.isfile(p):
                continue
            r = os.path.relpath(p, root).replace(os.sep, "/")
            if any(s in r.split("/") for s in _GLOB_SKIP):
                continue
            out.add(r)
    return sorted(out)


# ------------------------------------------------------------------ computed items


def provider_git_trees(root, c):
    """Tree hashes of the frozen directories at HEAD. Refuses when any of them has uncommitted or untracked files,
    because then the tree hash would not describe the files on disk. Tree hashes are content addressed, so a clone
    with the same files reproduces them whatever its history."""
    dirs = list(c.get("dirs", []))
    missing = [d for d in dirs if not os.path.isdir(os.path.join(root, d))]
    if missing:
        raise ProviderError(f"frozen directories missing: {', '.join(missing)}")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all", "--", *dirs)
    if dirty.strip():
        n = len([ln for ln in dirty.splitlines() if ln.strip()])
        raise ProviderError(f"{n} uncommitted or untracked file(s) under the frozen directories; commit first")
    trees = {}
    for d in dirs:
        try:
            trees[d] = _git(root, "rev-parse", f"HEAD:{d}").strip()
        except ProviderError:
            raise ProviderError(f"{d} is not committed") from None
    info = {"head_commit": _git(root, "rev-parse", "HEAD").strip(), "head_tree": _git(root, "rev-parse", "HEAD^{tree}").strip()}
    return {"dirs": trees}, info


def provider_call(root, c):
    """`call`: "<file relative to root>:<function>"; path_args are resolved against the root and passed in order.
    The function returns JSON-serialisable data (paths in it must be relative)."""
    target = c.get("call", "")
    if ":" not in target:
        raise ProviderError("call must be <file>:<function>")
    fpath, fn = target.rsplit(":", 1)
    if not _inside(root, fpath) or not os.path.isfile(os.path.join(root, fpath)):
        raise ProviderError(f"provider file not found: {fpath}")
    full = os.path.join(root, fpath)
    # compiled from source every time: a cached .pyc with the same mtime and size could hide an edit
    mod = types.ModuleType("orgene_freeze_provider_" + re.sub(r"\W", "_", fpath))
    mod.__file__ = full
    try:
        with open(full, "r", encoding="utf-8") as f:
            exec(compile(f.read(), full, "exec"), mod.__dict__)  # noqa: S102 - repository file named by the frozen spec
        func = getattr(mod, fn)
        args = []
        for p in c.get("path_args", []):
            if not _inside(root, p) or not os.path.exists(os.path.join(root, p)):
                raise ProviderError(f"provider argument not found: {p}")
            args.append(os.path.join(root, p))
        value = func(*args)
    except ProviderError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ProviderError(f"{target} raised {type(e).__name__}") from None
    try:
        return json.loads(canon(value)), {}
    except (TypeError, ValueError):
        raise ProviderError(f"{target} returned data that is not JSON") from None


PROVIDERS = {"git_trees": provider_git_trees, "call": provider_call}


def compute(root, c):
    return PROVIDERS[c["kind"]](root, c)


# ------------------------------------------------------------------ make


def collect(root, spec):
    """(items, files, missing) for the spec's path/glob/pending items."""
    items, files, missing = {}, {}, []
    for it in spec.get("items", []):
        iid, req = it["id"], bool(it.get("required", True))
        rec = {"category": it["category"], "required": req}
        if it.get("pending"):
            rec.update(status="pending", pending=it["pending"])
            if req:
                missing.append({"id": iid, "reason": "pending: " + it["pending"]})
            items[iid] = rec
            continue
        if it.get("path"):
            paths = [it["path"]] if os.path.isfile(os.path.join(root, it["path"])) else []
            rec["path"] = it["path"]
            need = 1
        else:
            paths = expand_glob(root, it["glob"])
            rec["glob"] = it["glob"]
            need = int(it.get("min_count", 1))
        rec["paths"] = paths
        if len(paths) < need:
            rec["status"] = "missing"
            if req:
                missing.append({"id": iid, "reason": f"{len(paths)} file(s) found, {need} required"})
        else:
            rec["status"] = "ok"
        items[iid] = rec
        for p in paths:
            f = files.setdefault(p, {"sha256": sha_file(os.path.join(root, p)), "bytes": os.path.getsize(os.path.join(root, p)), "items": []})
            f["items"].append(iid)
    return items, files, missing


def make(root=ROOT, spec_path=None, out_path=None, allow_incomplete=False, terms_file=None, allow_no_terms=False,
         supersede=False, created_at=None):
    """Build and write the manifest. Returns the manifest dict. Raises FreezeError (nothing is written) when:
    a required item is missing (unless allow_incomplete: a rehearsal manifest with complete=false is written),
    the neutral-writing scan finds anything, or a registered manifest would be overwritten without supersede."""
    root = os.path.abspath(root)
    spec, spec_rel, spec_sha = load_spec(root, spec_path)
    out = out_path or os.path.join(root, DEFAULT_MANIFEST)
    supersedes = []
    if os.path.exists(out):
        prev = json.load(open(out, encoding="utf-8"))
        if (prev.get("osf") or {}).get("registration_id"):
            if not supersede:
                raise FreezeError("the existing manifest is registered; a new freeze must be made with --supersede")
            supersedes = list(prev.get("supersedes", [])) + [{
                "content_sha256": prev.get("content_sha256"), "created_at": prev.get("created_at"),
                "osf_registration_id": prev["osf"]["registration_id"]}]
    items, files, missing = collect(root, spec)
    computed = {}
    for c in spec.get("computed", []):
        req = bool(c.get("required", True))
        try:
            value, info = compute(root, c)
            computed[c["id"]] = {"status": "ok", "kind": c["kind"], "required": req, "value": value, "info": info}
        except ProviderError as e:
            computed[c["id"]] = {"status": "error", "kind": c["kind"], "required": req, "error": str(e)}
            if req:
                missing.append({"id": c["id"], "reason": str(e)})
    # neutral-writing scan of everything that is hashed (the spec and the manifest text included)
    try:
        scanner, _ = A.build_scanner(root, terms_file, require_terms=not allow_no_terms)
    except A.TermsError as e:
        raise FreezeError(f"neutral-writing scan: {e}; pass --anon-terms FILE (or --allow-no-terms for a rehearsal)") from None
    report = A.scan(root, paths=sorted(files) + [spec_rel], git_meta=True, scanner=scanner)
    manifest = {
        "schema": MANIFEST_SCHEMA, "created_at": created_at or now_iso(),
        "spec": {"path": spec_rel, "sha256": spec_sha},
        "complete": not missing, "missing": missing, "items": items, "files": files, "computed": computed,
        "supersedes": supersedes,
        "anon_scan": {"files_scanned": report["files_scanned"], "binary_skipped": report["binary_skipped"],
                      "identity_terms": report["identity_terms"], "local_identity_terms": report["local_identity_terms"],
                      "git_commits_checked": report["git"].get("commits", 0), "hits": len(report["hits"])},
    }
    text_hits = A.scan_text(scanner, "<manifest>", json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False))
    if report["hits"] or text_hits:
        rep = dict(report, hits=report["hits"] + text_hits)
        raise FreezeError(f"neutral-writing scan found {len(rep['hits'])} hit(s); nothing written\n" + A.format_hits(rep))
    if missing and not allow_incomplete:
        raise FreezeError(f"{len(missing)} required item(s) missing; nothing written: " + ", ".join(m["id"] for m in missing))
    manifest["content_sha256"] = content_sha256(manifest)
    manifest["osf"] = {"registration_id": None, "registered_content_sha256": None, "recorded_at": None}
    write_manifest(out, manifest)
    return manifest


def write_manifest(path, manifest):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def load_manifest(path):
    if not os.path.isfile(path):
        raise FreezeError(f"no freeze manifest at {os.path.basename(path)}")
    try:
        m = json.load(open(path, encoding="utf-8"))
    except ValueError:
        raise FreezeError("freeze manifest is not valid JSON") from None
    if m.get("schema") != MANIFEST_SCHEMA:
        raise FreezeError(f"freeze manifest schema must be {MANIFEST_SCHEMA}")
    return m


# ------------------------------------------------------------------ verify


def _verify_manifest_bindings(root, spec, manifest):
    """Check that the manifest records this spec, including absent prerequisites.

    Rehearsals may faithfully record pending/missing/error requirements; only a
    manifest claiming complete must have every required item and computed value.
    This checks the existing integrity contract, not scientific prerequisites.
    """
    problems = []
    tables = [manifest.get(k, {}) for k in ("items", "files", "computed")]
    if not all(isinstance(t, dict) for t in tables):
        raise FreezeError("manifest items, files and computed must be objects")
    if not all(isinstance(rec, dict) for table in tables for rec in table.values()):
        raise FreezeError("manifest item, file and computed records must be objects")
    items, files, computed = tables
    definitions = {it["id"]: it for it in spec.get("items", [])}
    providers = {c["id"]: c for c in spec.get("computed", [])}
    for label, records, expected in (("items", items, definitions), ("computed", computed, providers)):
        if set(records) != set(expected):
            problems.append(f"manifest {label} do not cover exactly the freeze spec: "
                            f"{len(set(expected) - set(records))} missing, {len(set(records) - set(expected))} extra")
    bindings = {}
    for iid, definition in definitions.items():
        rec = items.get(iid)
        required = bool(definition.get("required", True))
        if definition.get("pending"):
            paths, status, kind = [], "pending", "pending"
        elif definition.get("path"):
            path = definition["path"]
            paths = [path] if os.path.isfile(os.path.join(root, path)) else []
            status, kind = ("ok" if paths else "missing"), "path"
        else:
            paths = expand_glob(root, definition["glob"])
            status, kind = ("ok" if len(paths) >= int(definition.get("min_count", 1)) else "missing"), "glob"
        for path in paths:
            bindings.setdefault(path, set()).add(iid)
        if not isinstance(rec, dict):
            problems.append(f"manifest item {iid}: missing or invalid record")
            continue
        declared = rec.get("paths", [])
        declared_kinds = {k for k in ("path", "glob", "pending") if k in rec}
        if (rec.get("category") != definition["category"] or rec.get("required") is not required or
                declared_kinds != {kind} or rec.get(kind) != definition[kind] or
                rec.get("status") != status or not isinstance(declared, list) or declared != paths):
            problems.append(f"manifest item {iid}: spec, status or paths do not match")
        if manifest.get("complete") is True and required and status != "ok":
            problems.append(f"manifest claims complete but required item {iid} is {status}")
    if set(files) != set(bindings):
        problems.append("manifest files do not cover exactly the spec item paths")
    for path, rec in files.items():
        members = rec.get("items") if isinstance(rec, dict) else None
        if (not isinstance(members, list) or not all(isinstance(x, str) for x in members) or
                len(members) != len(set(members)) or set(members) != bindings.get(path, set())):
            problems.append(f"manifest file {path}: item bindings do not match")
        if (not isinstance(rec, dict) or not isinstance(rec.get("sha256"), str) or
                not _HEX64.fullmatch(rec["sha256"]) or
                type(rec.get("bytes")) is not int or rec["bytes"] < 0):
            raise FreezeError(f"manifest file {path}: invalid hash or byte-count record")
        full = os.path.join(root, path)
        if _inside(root, path) and os.path.isfile(full) and os.path.getsize(full) != rec["bytes"]:
            problems.append(f"manifest file {path}: byte count changed")
    for cid, definition in providers.items():
        rec = computed.get(cid)
        required = bool(definition.get("required", True))
        if not isinstance(rec, dict):
            problems.append(f"manifest computed {cid}: missing or invalid record")
            continue
        if rec.get("kind") != definition["kind"] or rec.get("required") is not required:
            problems.append(f"manifest computed {cid}: spec binding does not match")
        if (rec.get("status") not in ("ok", "error") or
                (rec.get("status") == "ok" and "value" not in rec) or
                (manifest.get("complete") is True and required and rec.get("status") != "ok")):
            problems.append(f"manifest computed {cid}: required status or value not frozen")
    return problems


def verify(root=ROOT, manifest_path=None):
    """Recompute everything. Returns a report; report["ok"] is True only when nothing changed.

    report["complete"] and report["osf"] are reported separately (the gate needs all three)."""
    root = os.path.abspath(root)
    mp = manifest_path or os.path.join(root, DEFAULT_MANIFEST)
    m = load_manifest(mp)
    rep = {"manifest": rel(mp, root), "manifest_file_sha256": sha_file(mp), "content_sha256": m.get("content_sha256"),
           "complete": m.get("complete") is True and m.get("missing") == [], "problems": []}
    probs = rep["problems"]
    if type(m.get("complete")) is not bool or not isinstance(m.get("missing"), list):
        probs.append("manifest complete must be Boolean and missing must be a list")
    if m.get("complete") is True and m.get("missing") != []:
        probs.append("manifest claims complete but missing is not empty")
    if content_sha256(m) != m.get("content_sha256"):
        probs.append("manifest content does not match its content_sha256 (edited after make)")
    spec_path = os.path.join(root, (m.get("spec") or {}).get("path", DEFAULT_SPEC))
    spec = None
    if not os.path.isfile(spec_path):
        probs.append("freeze spec missing")
    elif sha_file(spec_path) != m["spec"]["sha256"]:
        probs.append("freeze spec changed")
    else:
        spec = json.load(open(spec_path, encoding="utf-8"))
        probs.extend(_verify_manifest_bindings(root, spec, m))
    changed, gone = [], []
    for p, f in sorted((m.get("files") or {}).items()):
        full = os.path.join(root, p)
        if not _inside(root, p) or not os.path.isfile(full):
            gone.append(p)
        elif sha_file(full) != f.get("sha256"):
            changed.append(p)
    added, removed = [], []
    for iid, it in sorted((m.get("items") or {}).items()):
        if it.get("glob") is not None and it.get("status") == "ok":
            now = set(expand_glob(root, it["glob"]))
            was = set(it.get("paths", []))
            added += sorted(now - was)
            removed += sorted(was - now)
    if changed:
        probs.append(f"{len(changed)} frozen file(s) changed: " + ", ".join(changed[:20]))
    if gone:
        probs.append(f"{len(gone)} frozen file(s) missing: " + ", ".join(gone[:20]))
    if added:
        probs.append(f"{len(added)} file(s) added under frozen patterns: " + ", ".join(added[:20]))
    rep.update(files_checked=len(m.get("files") or {}), changed=changed, missing_files=gone, added=added)
    comp = {}
    if spec is not None:
        defs = {c["id"]: c for c in spec.get("computed", [])}
        for cid, rec in sorted((m.get("computed") or {}).items()):
            if rec.get("status") != "ok":
                comp[cid] = "not frozen"
                continue
            try:
                value, _ = compute(root, defs[cid])
                comp[cid] = "ok" if canon(value) == canon(rec["value"]) else "changed"
            except (ProviderError, KeyError) as e:
                comp[cid] = f"error: {e}"
            if comp[cid] != "ok":
                probs.append(f"computed {cid}: {comp[cid]}")
    rep["computed"] = comp
    osf = m.get("osf") or {}
    oid = normalize_osf_id(osf.get("registration_id"))
    rep["osf"] = {"registration_id": oid, "id_valid": oid is not None,
                  "matches_content": bool(oid) and osf.get("registered_content_sha256") == m.get("content_sha256")}
    rep["ok"] = not probs
    return rep


def register(root=ROOT, manifest_path=None, osf_id=None, recorded_at=None):
    """Record the OSF registration id for the current manifest content (the content must verify and be complete)."""
    root = os.path.abspath(root)
    mp = manifest_path or os.path.join(root, DEFAULT_MANIFEST)
    oid = normalize_osf_id(osf_id)
    if oid is None:
        raise FreezeError("not an OSF registration id (a 5-character GUID of lower-case letters/digits, an osf.io URL or an OSF DOI)")
    rep = verify(root, mp)
    if not rep["ok"]:
        raise FreezeError("manifest does not verify; not registering: " + "; ".join(rep["problems"]))
    if not rep["complete"]:
        raise FreezeError("manifest is a rehearsal (complete=false); not registering")
    m = load_manifest(mp)
    prev = (m.get("osf") or {}).get("registration_id")
    if prev and normalize_osf_id(prev) != oid:
        raise FreezeError("manifest already carries another registration id")
    m["osf"] = {"registration_id": oid, "registered_content_sha256": m["content_sha256"], "recorded_at": recorded_at or now_iso()}
    write_manifest(mp, m)
    return m["osf"]


# ------------------------------------------------------------------ gate


def sealed_ids(root=ROOT):
    """Union of the ids in data/splits*/**/{test_ids,eng_holdout_ids}.json (ids only; no case text is read)."""
    out = set()
    for pat in SEALED_ID_GLOBS:
        for p in glob.glob(os.path.join(root, pat), recursive=True):
            try:
                out.update(str(x) for x in json.load(open(p, encoding="utf-8")))
            except (ValueError, TypeError):
                raise GateRefused(f"unreadable sealed id file {os.path.relpath(p, root)}") from None
    return out


def _ids_from_jsonl(path):
    ids = set()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and "case_id" in r:
                ids.add(str(r["case_id"]))
    return ids


def run_case_ids(run_dir, extra_dirs=()):
    """(case ids found in a run directory, split recorded in its run_config, gated before).

    Reads request/validated/final/result files and runner outputs for their case_id fields only."""
    ids, split, gated = set(), None, False
    if not run_dir or not os.path.isdir(run_dir):
        return ids, split, gated
    for pat in ("requests*.jsonl", "validated.*.jsonl", "final.*.jsonl", "results.*.jsonl"):
        for p in glob.glob(os.path.join(run_dir, pat)):
            ids |= _ids_from_jsonl(p)
    for d in [os.path.join(run_dir, x) for x in os.listdir(run_dir) if x.startswith("gen")] + list(extra_dirs or ()):
        for p in glob.glob(os.path.join(d, "outputs", "*.json")):
            try:
                r = json.load(open(p, encoding="utf-8", errors="replace"))
            except ValueError:
                continue
            if isinstance(r, dict) and "case_id" in r:
                ids.add(str(r["case_id"]))
    cfg = os.path.join(run_dir, "run_config.json")
    if os.path.isfile(cfg):
        try:
            split = (json.load(open(cfg, encoding="utf-8")) or {}).get("split")
        except ValueError:
            pass
    gated = os.path.isfile(os.path.join(run_dir, GATE_LOG))
    return ids, split, gated


def gate_reason(root, split=None, case_ids=(), gated_before=False):
    """(required?, reason, number of sealed cases among case_ids)."""
    n = len(set(case_ids or ()) & sealed_ids(root)) if case_ids else 0
    if split in SEALED_SPLITS:
        return True, f"split={split}", n
    if n:
        return True, "sealed case ids", n
    if gated_before:
        return True, "run was gated before", n
    return False, None, 0


def _tracked(root, relpath):
    try:
        return subprocess.run(["git", "-C", root, "ls-files", "--error-unmatch", "--", relpath],
                              capture_output=True, text=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def unfrozen_inputs(root, manifest, paths):
    """The files among `paths` (what a gated stage reads) that the freeze does not cover, as paths relative to the root
    (<outside>/name for a file outside it). A file is covered when the manifest lists it, or when git tracks it inside
    a directory whose tree hash the manifest records: after a passing verify both are unchanged. Without this a test
    run could be built from a gene library, lexicon, registry or template outside the frozen tree while the
    repository itself still verifies."""
    root_r = os.path.realpath(root)
    files = manifest.get("files") or {}
    trees = (((manifest.get("computed") or {}).get("git_trees") or {}).get("value") or {}).get("dirs") or {}
    out = set()
    for p in paths:
        full = os.path.realpath(p)
        r = os.path.relpath(full, root_r).replace(os.sep, "/") if full.startswith(root_r + os.sep) else None
        covered = r is not None and os.path.isfile(full) and (
            r in files or (any(r.startswith(d.rstrip("/") + "/") for d in trees) and _tracked(root, r)))
        if not covered:
            out.add(r or rel(full, root))
    return sorted(out)


def check_gate(root=ROOT, manifest_path=None, split_dir=None, inputs=()):
    """Raise GateRefused unless the manifest is complete, verifies, and is registered for exactly this content.

    split_dir: the split directory the stage uses; its sealed id files must be among the frozen files.
    inputs: files the stage reads (cases, gene library, configuration registry, lexicon, templates); every one must
    be covered by the freeze (unfrozen_inputs)."""
    root = os.path.abspath(root)
    mp = manifest_path or os.path.join(root, DEFAULT_MANIFEST)
    try:
        rep = verify(root, mp)
    except FreezeError as e:
        raise GateRefused(f"{e}; freeze first (tools/freeze.py make, upload, register)") from None
    if not rep["ok"]:
        raise GateRefused("freeze manifest does not verify: " + "; ".join(rep["problems"]))
    if not rep["complete"]:
        raise GateRefused("freeze manifest is a rehearsal (complete=false)")
    if not rep["osf"]["id_valid"]:
        raise GateRefused("freeze manifest has no OSF registration id (tools/freeze.py register --osf ID)")
    if not rep["osf"]["matches_content"]:
        raise GateRefused("the OSF registration recorded in the manifest is for other content")
    if split_dir:
        m = load_manifest(mp)
        for fn in SEALED_ID_FILES:
            p = os.path.join(split_dir, fn)
            if os.path.isfile(p):
                r = os.path.relpath(os.path.abspath(p), root).replace(os.sep, "/")
                if r not in (m.get("files") or {}):
                    raise GateRefused(f"the split used ({fn} in the given split directory) is not in the freeze manifest")
    if inputs:
        loose = unfrozen_inputs(root, load_manifest(mp), inputs)
        if loose:
            raise GateRefused(f"{len(loose)} input file(s) not covered by the freeze manifest: " + ", ".join(loose[:20])
                              + " (a gated stage reads frozen files only)")
    return {"manifest": rep["manifest"], "manifest_file_sha256": rep["manifest_file_sha256"],
            "content_sha256": rep["content_sha256"], "osf_registration_id": rep["osf"]["registration_id"]}


def gate_stage(stage, run_dir=None, case_ids=None, split=None, split_dir=None, root=ROOT, manifest_path=None,
               extra_dirs=(), inputs=()):
    """Gate one stage. Returns None when the stage touches no sealed case; otherwise checks the freeze (raises
    GateRefused), appends a record to <run_dir>/freeze_gate.jsonl and returns it.

    case_ids: the cases the stage will touch; when None they are read from run_dir.
    inputs: files the stage reads that must be frozen (check_gate); a refusal comes before the record is written."""
    root = os.path.abspath(root)
    gated_before = False
    if case_ids is None:
        ids, run_split, gated_before = run_case_ids(run_dir, extra_dirs)
        case_ids, split = ids, split or run_split
    need, reason, n = gate_reason(root, split, case_ids, gated_before)
    if not need:
        return None
    try:
        rec = check_gate(root, manifest_path, split_dir, inputs=inputs)
    except GateRefused as e:
        raise GateRefused(f"{stage} touches sealed cases ({reason}; {n} sealed id(s)): {e}") from None
    rec = dict({"stage": stage, "checked_at": now_iso(), "reason": reason, "n_sealed_cases": n}, **rec)
    if run_dir:
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, GATE_LOG), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
    return rec


def summary_lines(rep):
    lines = [f"manifest {rep['manifest']}  content_sha256 {str(rep['content_sha256'])[:16]}  file sha256 {rep['manifest_file_sha256'][:16]}",
             f"files checked: {rep['files_checked']}  changed: {len(rep['changed'])}  missing: {len(rep['missing_files'])}  added: {len(rep['added'])}",
             "computed: " + (", ".join(f"{k}={v}" for k, v in rep["computed"].items()) or "none"),
             f"complete: {rep['complete']}  osf: {rep['osf']['registration_id'] or 'none'} (matches content: {rep['osf']['matches_content']})"]
    lines += [f"PROBLEM: {p}" for p in rep["problems"]]
    lines.append("VERIFY: " + ("PASS" if rep["ok"] else "FAIL"))
    return lines


__all__ = ["make", "verify", "register", "check_gate", "gate_stage", "sealed_ids", "run_case_ids", "normalize_osf_id",
           "unfrozen_inputs", "FreezeError", "GateRefused", "ProviderError", "rel"]
