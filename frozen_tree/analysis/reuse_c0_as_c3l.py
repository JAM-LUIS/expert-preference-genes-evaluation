#!/usr/bin/env python3
"""Seed a configuration's round 0 from another configuration's run, with no new model calls.

  $ORGENE_PY analysis/reuse_c0_as_c3l.py --c0-run <source run dir> --c3l-run <target run dir> \
      [--src-cond C0] [--dst-cond C3L]

C3L and C3E reuse C0's round 0; C2E reuses C2's (E05). The two system prompts are byte-identical, temperature is 0
and the seed is the same, so round 0 of the target is the same generation as the source. The outputs are copied
verbatim; only the two identity fields (`request_id` suffix and `condition`) are rewritten, and every other byte,
including `content` and its sha256, is preserved and verified afterwards.

Before copying, the request files of both configurations (requests.<src>.jsonl in the source run,
requests.<dst>.jsonl in the target run) must exist and carry the same messages for every case: this is what makes
the reuse valid, and it stops a wrong pairing (e.g. C2E seeded from C0). With --expect-* (run_condition.sh passes
them), the source generation's config.json must also show the model, num_ctx, num_predict, temperature and repeat
that the target run uses for its repair rounds, and --expect-registry-entry the same model registry entry (id and
entry sha256 as recorded by the runner; the entry fixes every other option, keep_alive and think included).
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEFAULT_MODEL_REGISTRY = os.path.join(ROOT, "configs", "model_registry.json")


def _messages_by_case(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[r["case_id"]] = r["messages"]
    return out


def check_same_requests(src_run, src_cond, dst_run, dst_cond):
    """Every target request must have a source request for the same case with the same messages."""
    sp = os.path.join(src_run, f"requests.{src_cond}.jsonl")
    dp = os.path.join(dst_run, f"requests.{dst_cond}.jsonl")
    for p in (sp, dp):
        if not os.path.exists(p):
            raise SystemExit(f"[reuse] missing {p}: build the requests of both configurations first")
    src, dst = _messages_by_case(sp), _messages_by_case(dp)
    missing = sorted(set(dst) - set(src))
    differ = sorted(c for c in set(dst) & set(src) if dst[c] != src[c])
    if missing or differ:
        raise SystemExit(f"[reuse] {dst_cond} cannot reuse the round 0 of {src_cond}: "
                         f"{len(missing)} cases without a source request, {len(differ)} with different messages")
    return len(dst)


def _entry_sha256(registry_path, entry_id):
    """sha256 of a registry entry, computed as the runner records it (orgene.runner.load_registry_entry)."""
    runtime = os.path.join(ROOT, "runtime")
    if runtime not in sys.path:
        sys.path.insert(0, runtime)
    from orgene.runner import load_registry_entry
    return load_registry_entry(registry_path, entry_id, prefix="[reuse]")[1]["entry_sha256"]


def check_source_settings(src_gen_dir, expect, registry_path=None):
    """The source generation must have been run with the settings the target run uses for its repair rounds.

    `expect` maps model / num_ctx / num_predict / temperature / repeat / registry_entry to the target's values
    (None = not checked; registry_entry also needs the source's entry to hash as the entry does now, `entry_sha256`).
    They are compared with the runner's config.json in the source generation directory; a missing config.json
    cannot be checked and is refused. Returns the number of settings checked."""
    want = {k: v for k, v in expect.items() if v is not None}
    if not want:
        return 0
    p = os.path.join(src_gen_dir, "config.json")
    if not os.path.exists(p):
        raise SystemExit(f"[reuse] no config.json in the source generation {os.path.basename(src_gen_dir)}: "
                         "its settings cannot be checked")
    cfg = json.load(open(p, encoding="utf-8"))
    # the R1 runner (orgene/runner.py, E08) records the settings as sent under "opts"; v5's runner used "options"
    opts = cfg.get("opts") if isinstance(cfg.get("opts"), dict) else (cfg.get("options") or {})
    reg = cfg.get("registry") if isinstance(cfg.get("registry"), dict) else {}
    have = {"model": (cfg.get("identity") or {}).get("model"), "num_ctx": opts.get("num_ctx"),
            "num_predict": opts.get("num_predict"), "temperature": opts.get("temperature"),
            "repeat": cfg.get("repeat"), "registry_entry": reg.get("entry_id")}
    bad = []
    for k, v in sorted(want.items()):
        h = have.get(k)
        if k in ("model", "registry_entry"):
            same = h == v
        else:
            try:
                same = h is not None and float(h) == float(v)
            except (TypeError, ValueError):
                same = False
        if not same:
            bad.append(f"{k}: source {h!r}, this run {v!r}")
        elif k == "registry_entry":
            now = _entry_sha256(registry_path or DEFAULT_MODEL_REGISTRY, v)
            if reg.get("entry_sha256") != now:
                bad.append(f"registry entry {v}: the source ran under another version of it "
                           f"(sha256 {str(reg.get('entry_sha256'))[:12]}, now {now[:12]})")
    if bad:
        raise SystemExit("[reuse] the source round 0 was generated with other settings: " + "; ".join(bad))
    return len(want)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--c0-run", required=True)
    ap.add_argument("--c3l-run", required=True)
    ap.add_argument("--src-cond", default="C0")
    ap.add_argument("--dst-cond", default="C3L")
    # settings of the target run (run_condition.sh passes all of them); the source generation must match
    ap.add_argument("--expect-model", default=None)
    ap.add_argument("--expect-num-ctx", default=None)
    ap.add_argument("--expect-num-predict", default=None)
    ap.add_argument("--expect-temperature", default=None)
    ap.add_argument("--expect-repeat", default=None)
    ap.add_argument("--expect-registry-entry", default=None, help="model registry entry id of this run's repair rounds")
    ap.add_argument("--registry", default=None, help="model registry file (default configs/model_registry.json)")
    a = ap.parse_args()

    src = os.path.join(a.c0_run, f"gen.{a.src_cond}.r0")
    dst = os.path.join(a.c3l_run, f"gen.{a.dst_cond}.r0")
    if not os.path.isdir(src):
        raise SystemExit(f"missing {src}")
    n_req = check_same_requests(a.c0_run, a.src_cond, a.c3l_run, a.dst_cond)
    print(f"[reuse] requests.{a.src_cond} and requests.{a.dst_cond}: same messages for all {n_req} cases")
    n_set = check_source_settings(src, {"model": a.expect_model, "num_ctx": a.expect_num_ctx,
                                        "num_predict": a.expect_num_predict, "temperature": a.expect_temperature,
                                        "repeat": a.expect_repeat, "registry_entry": a.expect_registry_entry},
                                  registry_path=a.registry)
    if n_set:
        print(f"[reuse] source generation settings match this run ({n_set} checked)")
    os.makedirs(os.path.join(dst, "outputs"), exist_ok=True)

    n, unchanged = 0, 0
    for path in sorted(glob.glob(os.path.join(src, "outputs", "**", "*.json"), recursive=True)):
        rec = json.load(open(path, encoding="utf-8"))
        content = rec.get("content")
        before = hashlib.sha256((content or "").encode("utf-8")).hexdigest()
        rec["request_id"] = rec["request_id"].replace(f".{a.src_cond}", f".{a.dst_cond}")
        rec["condition"] = a.dst_cond
        rec.setdefault("meta", {})["reused_from"] = {
            "run": os.path.basename(os.path.abspath(a.c0_run)), "condition": a.src_cond,
            "note": f"round 0 copied verbatim; {a.dst_cond}'s system prompt is byte-identical to {a.src_cond}'s, "
                    "so this is the same generation",
        }
        after = hashlib.sha256((rec.get("content") or "").encode("utf-8")).hexdigest()
        assert before == after and rec.get("content") == content, path
        unchanged += 1
        name = os.path.basename(path).replace(f".{a.src_cond}.", f".{a.dst_cond}.")
        json.dump(rec, open(os.path.join(dst, "outputs", name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        n += 1

    # receipts, rewritten the same way
    rsrc = os.path.join(src, "receipts.jsonl")
    if os.path.exists(rsrc):
        rows = []
        for line in open(rsrc, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            r["request_id"] = r["request_id"].replace(f".{a.src_cond}", f".{a.dst_cond}")
            r["condition"] = a.dst_cond
            rows.append(json.dumps(r, ensure_ascii=False))
        open(os.path.join(dst, "receipts.jsonl"), "w", encoding="utf-8").write("\n".join(rows) + "\n")

    csrc = os.path.join(src, "config.json")
    if os.path.exists(csrc):
        cfg = json.load(open(csrc, encoding="utf-8"))
        cfg["reused_from"] = {"run": os.path.basename(os.path.abspath(a.c0_run)), "condition": a.src_cond,
                              "reason": f"{a.dst_cond} round 0 == {a.src_cond} round 0 (identical system prompt, temp 0, "
                                        "same seed); no new model calls"}
        json.dump(cfg, open(os.path.join(dst, "config.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        shutil.copy(csrc, os.path.join(dst, "config.c0_original.json"))

    print(f"[reuse] {n} outputs copied {a.src_cond} -> {a.dst_cond}; content sha256 unchanged for {unchanged}/{n}")


if __name__ == "__main__":
    main()
