#!/usr/bin/env bash
# Freeze a read-only evidence snapshot of everything a dev (or test) claim rests on.
#
#   analysis/make_evidence_snapshot.sh [--include-test] <label>        e.g. dev-snapshot-20260906
#
# Copies metrics / results / reports / taxonomy / genes / decisions and writes SHA256SUMS.
# Default: dev and smoke runs only; a run whose name contains "test", or whose content touches sealed cases
# (tools/freeze.py sealed-run), is never taken (E21). --include-test also takes
# test runs, and only after the freeze gate passes (tools/freeze.py gate: complete, verified, OSF-registered manifest);
# the gate record is written into the snapshot.
set -euo pipefail
INCLUDE_TEST=0
if [ "${1:-}" = "--include-test" ]; then INCLUDE_TEST=1; shift; fi
LABEL="${1:?snapshot label, e.g. dev-snapshot-20260906}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DST="$ROOT/paper/evidence/$LABEL"
PY="${ORGENE_PY:-/opt/homebrew/bin/python3}"   # fixed interpreter, never PATH's python3
if [ "$INCLUDE_TEST" = 1 ]; then
  "$PY" "$ROOT/tools/freeze.py" gate --stage snapshot > /dev/null || { echo "[snapshot] --include-test refused by the freeze gate" >&2; exit 1; }
fi
mkdir -p "$DST/runs"
if [ "$INCLUDE_TEST" = 1 ]; then "$PY" "$ROOT/tools/freeze.py" gate --stage snapshot --record-dir "$DST" > /dev/null; fi

cd "$ROOT"
for RUN in experiments/*/; do
  [ -d "$RUN" ] || continue
  name="$(basename "$RUN")"
  case "$name" in
    *test*|*TEST*|*Test*) [ "$INCLUDE_TEST" = 1 ] || { echo "[snapshot] not taken (name contains test): $name"; continue; } ;;
    *dev*|*smoke*) ;;
    *) continue ;;
  esac
  # the name is not trusted alone: without --include-test a run whose content touches sealed cases (split test or
  # eng_holdout, a sealed id in its files, or a gate record) is skipped too; any error also skips it
  if [ "$INCLUDE_TEST" = 0 ] && ! "$PY" "$ROOT/tools/freeze.py" sealed-run "$RUN" > /dev/null 2>&1; then
    echo "[snapshot] not taken (run touches sealed cases): $name"; continue
  fi
  found=0
  for f in "$RUN"metrics.*.json "$RUN"results.*.jsonl "$RUN"report.md "$RUN"run_config.json \
           "$RUN"error_taxonomy.dev.csv "$RUN"dev_failures.md "$RUN"repair_budget.log; do
    [ -e "$f" ] || continue
    mkdir -p "$DST/runs/$name"; cp "$f" "$DST/runs/$name/"; found=1
  done
  [ "$found" = 1 ] && echo "[snapshot] $name"
done

mkdir -p "$DST/config"
for f in genes/genes.r1.jsonl genes/CANDIDATES.md DECISIONS.md RECORDS.md HANDOFF.md PAPER_SPEC.md \
         data/EXCLUSIONS.md data/README.md data/mamo_underspecified_ids.json \
         conditions/base_system.md conditions/C0_direct.md conditions/C1_generic_expert_pool.md \
         conditions/C2_schema_only.md conditions/C3_orgene.md conditions/spec_schema_summary.md \
         schema/optimization_model_spec.v3.schema.json \
         data/splits/mamo_complex_lp/SPLIT_LOCK.json data/splits/industryor/SPLIT_LOCK.json; do
  [ -e "$f" ] || continue
  mkdir -p "$DST/config/$(dirname "$f")"; cp "$f" "$DST/config/$f"
done

"$PY" - "$DST" <<'PY'
import sys, hashlib, os, json
sys.path.insert(0, os.path.join(os.getcwd(), "runtime"))
from orgene import genes as G
dst = sys.argv[1]
store = "genes/genes.r1.jsonl"
gs = G.load_store(store); act, _ = G.activate(gs, "C3")
text, info = G.compile_contract(act)
meta = {
  "store_file_sha256": hashlib.sha256(open(store, "rb").read()).hexdigest(),
  "store_digest": G.store_digest(act),
  "contract_sha256": info["contract_sha256"],
  "contract_chars": len(text),
  "n_active": len(act),
  "n_hard": sum(1 for g in act if g["validation"]["severity"] == "hard"),
  "n_soft": sum(1 for g in act if g["validation"]["severity"] == "soft"),
  "n_executable": sum(1 for g in act if g["validation"]["mode"] == "executable"),
  "n_prompt_only": sum(1 for g in act if g["validation"]["mode"] != "executable"),
  "n_seed": sum(1 for g in act if g["audit"]["sourceType"] == "seed_structural"),
  "n_dev_derived": sum(1 for g in act if g["audit"]["sourceType"] == "dev_failure_derived"),
  "genes": [{"geneId": g["geneId"], "version": g["version"], "severity": g["validation"]["severity"],
             "mode": g["validation"]["mode"], "predicateId": g["validation"].get("predicateId"),
             "sourceType": g["audit"]["sourceType"], "devCaseIds": g["audit"]["devCaseIds"]} for g in act],
}
json.dump(meta, open(os.path.join(dst, "gene_store_summary.json"), "w"), ensure_ascii=False, indent=2)
print("[snapshot] gene_store_summary.json:", meta["n_active"], "active,",
      meta["n_hard"], "hard /", meta["n_soft"], "soft")
PY

cd "$DST"
find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 shasum -a 256 > SHA256SUMS
chmod -R a-w "$DST"
echo "[snapshot] $(wc -l < SHA256SUMS) files -> $DST (read-only)"
