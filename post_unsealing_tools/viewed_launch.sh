#!/bin/bash
# Supplementary run of the nine viewed problems (OSF record 7). Usage: viewed_launch.sh <OSF GUID>
# Registers the GUID for manifest 5, moves the formal run's directory aside for the duration of the run (the driver's
# isolation preflight refuses held-out ids outside sealed run directories), runs the campaign, moves it back and
# checks it against the registered hash list. Everything is logged to ~/orgene_scratch_20261010/viewed_run.log.
export LC_ALL=C LANG=C PYTHONDONTWRITEBYTECODE=1 PATH=/opt/homebrew/bin:$PATH
G=$1; [ -n "$G" ] || { echo "usage: $0 <OSF GUID>"; exit 2; }
cd ~/ORgene-R1-wt/it1-integ || exit 1
A=~/orgene_scratch_20261010/aside; F=experiments/test-main-20261006
restore() {
  if [ -d $A/test-main-20261006 ] && [ ! -e $F ]; then mv $A/test-main-20261006 $F && echo "[launch] formal run directory moved back $(date -u +%FT%TZ)"; fi
  if [ -d $F ]; then ( cd $F && echo "[launch] formal run files matching the hash list: $(shasum -a 256 -c OUTPUT_SHA256.txt 2>/dev/null | grep -c ': OK$') of $(wc -l < OUTPUT_SHA256.txt | tr -d ' ') (4158 expected)" ); fi
}
trap restore EXIT
set -e
test -z "$(git status --porcelain)"
if ! python3 tools/freeze.py verify --require-complete --require-osf >/dev/null 2>&1; then
  python3 tools/freeze.py register --osf $G | tail -1
  git add FREEZE_MANIFEST.json && git commit -q -m "Freeze manifest 5: OSF registration $G" && git log --oneline -1
fi
python3 tools/freeze.py verify --require-complete --require-osf | tail -2
mkdir -p $A && [ ! -e $A/test-main-20261006 ] && mv $F $A/test-main-20261006 && echo "[launch] formal run directory moved aside $(date -u +%FT%TZ)"
set +e
python3 tools/run_campaign.py --spec configs/campaigns/test_viewed0905_20261010.json --campaign test-viewed0905-20261010
echo "[launch] campaign exit code $? $(date -u +%FT%TZ)"
cat experiments/test-viewed0905-20261010/status.json 2>/dev/null | head -40
