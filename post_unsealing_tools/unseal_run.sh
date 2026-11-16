#!/bin/bash
# Unsealing run of the formal test (after OSF record 6, y9x3u, is public): refusal rule, scoring, registry, analyses.
# Usage: unseal_run.sh <step> ...   steps: gate refused score register analyze eng
export LC_ALL=C LANG=C PYTHONDONTWRITEBYTECODE=1 PATH=/opt/homebrew/bin:$PATH
cd ~/ORgene-R1-wt/it1-integ || exit 1
E=experiments/test-main-20261006
O=$E/analysis_20261010; mkdir -p $O
PY=python3; VPY=$HOME/ORgene-R1/.venv-tools/bin/python
FM=FREEZE_MANIFEST.json
STAGES="mamo-test:mamo_complex_lp industryor-test:industryor"
run() { echo "### $1"; shift; local t0=$(date +%s) rc; "$@" > $O/last.log 2>&1; rc=$?; tail -${TAILN:-4} $O/last.log | cut -c1-400; echo "rc=$rc ($(( $(date +%s)-t0 ))s)"; }
conds() { ls $1/final.*.jsonl | sed -E "s#.*/final\.(.*)\.jsonl#\1#" | tr "\n" " "; }
add() { # run results config model benchmark split rounds(-|k) round0 [label]
  local a=(--run $1 --results $2 --config $3 --model $4 --benchmark $5 --split $6 --round0 $8)
  [ "$7" != "-" ] && a+=(--max-repair-rounds $7)
  [ -n "$9" ] && a+=(--label $9)
  $PY analysis/r1/registry.py add "${a[@]}" 2>&1 | tail -1 | cut -c1-300; }

step_gate() { $PY tools/freeze.py verify --require-complete --require-osf | tail -2; test -z "$(git status --porcelain)" && echo "tree clean at $(git log --oneline -1 | cut -c1-60)"; }

step_refused() { for st in $STAGES; do s=${st%%:*}; c=${st##*:}
    TAILN=8 run "server_refused derive $s" $PY tools/server_refused.py derive --run $E/$s/by-model/gptoss-20b.main --cases data/cases/$c.jsonl --freeze-manifest $FM
  done; }

step_score() { for st in $STAGES; do s=${st%%:*}; c=${st##*:}
    for m in qwen3-8b.main qwen3-8b.var07; do
      run "score $s $m: $(conds $E/$s/by-model/$m)" $PY runtime/orgene_cli.py score --run $E/$s/by-model/$m --cases data/cases/$c.jsonl --cond $(conds $E/$s/by-model/$m) --freeze-manifest $FM
    done; done
  m=$E/eng-holdout/by-model/qwen3-8b.main
  run "score eng-holdout: $(conds $m)" $PY runtime/orgene_cli.py score --run $m --cases data/cases/eng.jsonl --cond $(conds $m) --freeze-manifest $FM; }

step_register() { for st in $STAGES; do s=${st%%:*}; b=${st##*:}
    m=$E/$s/by-model/qwen3-8b.main
    for c in C0 C1 C2; do add $m results.$c.jsonl $c qwen3:8b $b test - own; done
    for k in 0 1 2; do add $m results.C3.jsonl C3 qwen3:8b $b test $k own; done
    for k in 1 2; do
      add $m results.C2E.jsonl C2E qwen3:8b $b test $k reuse:C2
      for c in C3E C3L C3T C3A; do add $m results.$c.jsonl $c qwen3:8b $b test $k reuse:C0; done
      add $m results.C0R-E.jsonl C0R-E qwen3:8b $b test $k own
    done
    v=$E/$s/by-model/qwen3-8b.var07
    add $v results.C0.jsonl C0 qwen3:8b $b test - own C0.t07
    for k in 1 2; do for c in C3E C3L; do add $v results.$c.jsonl $c qwen3:8b $b test $k reuse:C0 $c@$k.t07; done; done
    g=$E/$s/by-model/gptoss-20b.main.server_refused
    for c in C0 C1 C2; do add $g results.$c.jsonl $c gpt-oss:20b $b test - own; done
    for k in 1 2; do add $g results.C3.jsonl C3 gpt-oss:20b $b test $k own
      for c in C3E C3L; do add $g results.$c.jsonl $c gpt-oss:20b $b test $k reuse:C0; done; done
  done
  $PY analysis/r1/registry.py check 2>&1 | tail -3; }

pair() { # a b [extra args...] -> paired.<a>_vs_<b><suffix>.json
  local a=$1 b=$2 suf=$3; shift 3
  run "paired $a vs $b $suf $*" $PY analysis/r1/paired.py --a $a --b $b --out $O/paired.${a}_vs_${b}${suf}.json "$@"; }

step_analyze() {
  run matrix $PY analysis/r1/registry.py matrix --set main --out $O/matrix.main.jsonl
  Q="--set main --models qwen3:8b"
  for c in C3L@2:C3E@2 C3E@2:C0 C3L@1:C3E@2 C3L@2:C3L@1 C2E@2:C2 C3@2:C3@0 C3L@2:C0 C3L@2:C1 C3L@2:C2 C3L@2:C3@2 C3L@1:C3T@1 C3A@1:C3T@1 C3L@2:C0R-E@2 C3L@1:C3E@1; do
    pair ${c%%:*} ${c##*:} "" $Q; done
  run holm $PY analysis/r1/holm.py --paired $O/paired.C3L@2_vs_C3E@2.json $O/paired.C3E@2_vs_C0.json $O/paired.C3L@1_vs_C3E@2.json $O/paired.C3L@2_vs_C3L@1.json $O/paired.C2E@2_vs_C2.json $O/paired.C3@2_vs_C3@0.json $O/paired.C3L@2_vs_C0.json $O/paired.C3L@2_vs_C1.json $O/paired.C3L@2_vs_C2.json $O/paired.C3L@2_vs_C3@2.json $O/paired.C3L@1_vs_C3T@1.json --out $O/holm.json
  for c in C3L@2:C3E@2 C3L@1:C3T@1 C3L@2:C3L@1; do
    run "tost ${c%%:*} vs ${c##*:}" $PY analysis/r1/tost.py --a ${c%%:*} --b ${c##*:} $Q --out $O/tost.${c%%:*}_vs_${c##*:}.json; done
  run shared $PY analysis/r1/shared_round0.py --a C3L@2 --b C3E@2 --round0-label C0 $Q --out $O/shared_round0.json
  run mechanism $PY analysis/r1/mechanism.py --l C3L@1 --e C3E@1 --t C3T@1 --a C3A@1 --round0-label C0 $Q --out $O/mechanism.json
  run strata $PY analysis/r1/strata.py --a C3L@2 --b C3E@2 --by benchmark scale difficulty type $Q --out $O/strata.json
  run length $VPY analysis/r1/length_model.py --labels C3L@2 C3E@2 C0 $Q --out $O/length.json
  # sensitivity settings of the primary comparison (forest_settings)
  for s in sens_orig_ref sens_full211 sens_incl0905 sens_full211_incl0905 well_specified; do pair C3L@2 C3E@2 .$s --set $s --models qwen3:8b; done
  for t in 1e-06 0.01; do pair C3L@2 C3E@2 .tol$t $Q --outcome correct_tol:$t; done
  pair C3L@2.t07 C3E@2.t07 "" $Q
  pair C3L@2.t07 C0.t07 "" $Q
  # second model: main rule (refused units wrong) and complete case
  pair C3L@2 C3E@2 .gptoss --set main --models gpt-oss:20b
  pair C3L@2 C0 .gptoss --set main --models gpt-oss:20b
  run "paired-cc gptoss" $PY tools/server_refused.py paired-cc --a C3L@2 --b C3E@2 --refused $E/mamo-test/by-model/gptoss-20b.main.server_refused/refused.json $E/industryor-test/by-model/gptoss-20b.main.server_refused/refused.json --set main --models gpt-oss:20b --out $O/paired.C3L@2_vs_C3E@2.gptoss.cc.json; }

step_eng() { m=$E/eng-holdout/by-model/qwen3-8b.main
  TAILN=8 run "reexec eng 600s" $PY tools/reexec_final.py --run $m --cases data/cases/eng.jsonl --timeout 600 --jobs 2 --freeze-manifest $FM; }

step_var07() { for st in $STAGES; do local s=${st%%:*} c=${st##*:}; local v=$E/$s/by-model/qwen3-8b.var07
    TAILN=3 run "score $s var07: $(conds $v)" $PY runtime/orgene_cli.py score --run $v --cases data/cases/$c.jsonl --cond $(conds $v) --freeze-manifest $FM
    add $v results.C0.jsonl C0 qwen3:8b $c test - own C0.t07
    for k in 1 2; do for x in C3E C3L; do add $v results.$x.jsonl $x qwen3:8b $c test $k reuse:C0 $x@$k.t07; done; done
  done; $PY analysis/r1/registry.py check 2>&1 | tail -2; }

for st in "$@"; do echo "================ $st $(date -u +%FT%TZ)"; step_$st; done
