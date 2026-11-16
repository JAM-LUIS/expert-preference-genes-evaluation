#!/usr/bin/env bash
# One configuration, end to end, against local Ollama (resumable: re-run the same command after an interruption).
#   runtime/run_condition.sh <run-dir> <COND> <cases.jsonl> [model] [num_predict] [repeat] [temperature] [registry-entry]
# Example:
#   runtime/run_condition.sh experiments/20260910-qwen3-8b-test-c0c3 C3 data/cases/mamo_complex_lp.jsonl qwen3:8b 6000 1 0
# Requires: requests.<COND>.jsonl already built by `orgene_cli.py requests`.
# Defaults (num_predict 6000, NUM_CTX 32768, KEEP_ALIVE 0) are those of configs/r1_configs.json and the model registry
# entry qwen3-8b.main (runtime/tests/test_wave1_seams.py keeps them equal).
#
# Every runner call carries --registry configs/model_registry.json --registry-entry <entry> (E19): the runner refuses
# before any call when what it would send differs from the entry. The entry is the 8th argument, else
# $REGISTRY_ENTRY, else qwen3-8b.main; $REGISTRY replaces the registry file. The R0 regression runs with
#   REGISTRY_ENTRY=qwen3-8b.r0-v5 NUM_CTX=16384 KEEP_ALIVE=30m   (v5's settings), or
#   REGISTRY_ENTRY=qwen3-8b.r0-ctx16k NUM_CTX=16384               (16384, cold load),
# so that each comparison differs from qwen3-8b.main in one setting.
# Before each repair round the repair prompts are counted with the local tokenizer (think as sent); if any prompt plus
# num_predict exceeds num_ctx the script stops before generating that round.
#
# Repairing configurations (C3, C3L, C3E, C2E) always run to at most 2 repair rounds (D8). The "at most 1 round" and
# "round 0" ladder points are cut from that same run with analysis/derive_repair_ladder.py; they are never run
# separately, so MAX_ROUNDS cannot be changed here.
# C3L and C3E reuse the round 0 of C0, and C2E the round 0 of C2 (identical system prompt): set
#   ROUND0_FROM=<run dir that holds gen.C0.r0 / gen.C2.r0 and its requests file>   (may be <run-dir> itself).
set -euo pipefail
RUN="$1"; COND="$2"; CASES="$3"; MODEL="${4:-qwen3:8b}"; NUM_PREDICT="${5:-6000}"; REPEAT="${6:-1}"; TEMP="${7:-0}"
REGISTRY_ENTRY="${8:-${REGISTRY_ENTRY:-qwen3-8b.main}}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REGISTRY="${REGISTRY:-$(cd "$HERE/.." && pwd)/configs/model_registry.json}"
if [ ! -f "$REGISTRY" ]; then
  echo "[run_condition] model registry not found: $REGISTRY" >&2; exit 1
fi
if [ "${MAX_ROUNDS:-2}" != "2" ]; then
  echo "[run_condition] MAX_ROUNDS is fixed at 2 (D8); cut fewer rounds with analysis/derive_repair_ladder.py" >&2; exit 1
fi
MAX_ROUNDS=2
case "$COND" in
  C3L|C3E) SRC_COND=C0 ;;
  C2E)     SRC_COND=C2 ;;
  *)       SRC_COND="" ;;
esac
if [ -n "$SRC_COND" ] && [ -z "${ROUND0_FROM:-}" ]; then
  echo "[run_condition] $COND reuses the round 0 of $SRC_COND: set ROUND0_FROM=<run dir with gen.$SRC_COND.r0>" >&2; exit 1
fi
# Fixed interpreter (never PATH's python3: a non-interactive shell finds a system python3 without pulp there).
PY="${ORGENE_PY:-/opt/homebrew/bin/python3}"
"$PY" "$HERE/orgene_cli.py" env --python "$PY" > /dev/null || { echo "[run_condition] interpreter check failed: $PY" >&2; exit 1; }
# One context size for every configuration and every round (R1 default practice 1): the repair turns carry the whole
# previous answer, and C3L/C3E/C2E now repair through this script (v5 ran them with 32768 from separate scripts).
# The R0 regression against v5's round 0 sets NUM_CTX=16384 explicitly.
NUM_CTX="${NUM_CTX:-32768}"
KEEP_ALIVE="${KEEP_ALIVE:-0}"         # R1 default: cold load for every call
EXTRA="${OLLAMA_EXTRA:-}"             # e.g. --think, or --think low (a reasoning level: gpt-oss)
THINK_FLAG=""                         # the repair budget check counts the prompt the way the runner renders it
case " $EXTRA " in
  *" --think false "*)  THINK_FLAG="" ;;
  *" --think low "*)    THINK_FLAG="--think low" ;;
  *" --think medium "*) THINK_FLAG="--think medium" ;;
  *" --think high "*)   THINK_FLAG="--think high" ;;
  *" --think "*)        THINK_FLAG="--think" ;;
esac

run_model () {  # $1 requests, $2 out dir, $3 repeat
  "$PY" "$HERE/ollama_runner.py" --model "$MODEL" --requests "$1" --out "$2" \
    --num-ctx "$NUM_CTX" --num-predict "$NUM_PREDICT" --temperature "$TEMP" --repeat "$3" --keep-alive "$KEEP_ALIVE" \
    --registry "$REGISTRY" --registry-entry "$REGISTRY_ENTRY" $EXTRA
}

if [ -n "$SRC_COND" ]; then
  echo "[run_condition] $COND round 0 reused from $SRC_COND in $ROUND0_FROM (no model calls)"
  # the reused round 0 must come from a generation with the settings this run's repair rounds use
  "$PY" "$HERE/../analysis/reuse_c0_as_c3l.py" --c0-run "$ROUND0_FROM" --c3l-run "$RUN" --src-cond "$SRC_COND" --dst-cond "$COND" \
    --expect-model "$MODEL" --expect-num-ctx "$NUM_CTX" --expect-num-predict "$NUM_PREDICT" \
    --expect-temperature "$TEMP" --expect-repeat "$REPEAT" --expect-registry-entry "$REGISTRY_ENTRY"
else
  echo "[run_condition] $COND round 0 generation"
  run_model "$RUN/requests.$COND.jsonl" "$RUN/gen.$COND.r0" "$REPEAT"
fi
"$PY" "$HERE/orgene_cli.py" validate --run "$RUN" --cases "$CASES" --cond "$COND" --round 0 --max-rounds "$MAX_ROUNDS"
# Observe-only configurations write no repair requests, so the loop ends at once for them.
for R in $(seq 1 "$MAX_ROUNDS"); do
  REQ="$RUN/requests.$COND.repair$R.jsonl"
  if [ ! -s "$REQ" ]; then echo "[run_condition] no repair requests for round $R"; break; fi
  echo "[run_condition] $COND repair round $R: $(wc -l < "$REQ") requests"
  if ! "$PY" "$HERE/../analysis/repair_prompt_budget.py" --requests "$REQ" --model "$MODEL" --num-ctx "$NUM_CTX" \
       --num-predict "$NUM_PREDICT" $THINK_FLAG | tee -a "$RUN/repair_budget.log"; then
    echo "[run_condition] repair round $R stopped: a repair prompt plus num_predict exceeds num_ctx, or the local" \
         "count failed (see $RUN/repair_budget.log)" >&2
    exit 1
  fi
  run_model "$REQ" "$RUN/gen.$COND.repair$R" 1
  "$PY" "$HERE/orgene_cli.py" validate --run "$RUN" --cases "$CASES" --cond "$COND" --round "$R" --max-rounds "$MAX_ROUNDS"
done
"$PY" "$HERE/orgene_cli.py" score --run "$RUN" --cases "$CASES" --cond "$COND"
"$PY" "$HERE/orgene_cli.py" report --run "$RUN" > /dev/null
echo "[run_condition] done: $RUN/metrics.$COND.json"
