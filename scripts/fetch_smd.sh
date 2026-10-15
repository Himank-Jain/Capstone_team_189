#!/usr/bin/env bash
# Fetch the Server Machine Dataset (Su et al., KDD 2019, github.com/NetManAIOps/OmniAnomaly, MIT licence) used as third-party data.
# usage: scripts/fetch_smd.sh [machine ...]   default: machine-1-1 ... machine-1-8   (~20 MB per machine)
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=https://raw.githubusercontent.com/NetManAIOps/OmniAnomaly/master/ServerMachineDataset
M=("$@"); [ ${#M[@]} -eq 0 ] && M=(machine-1-1 machine-1-2 machine-1-3 machine-1-4 machine-1-5 machine-1-6 machine-1-7 machine-1-8)
for m in "${M[@]}"; do
  for d in train test test_label interpretation_label; do
    f=data/external/smd/$d/$m.txt
    [ -s "$f" ] || curl -fsS --retry 3 -m 300 -o "$f" "$BASE/$d/$m.txt"
  done
done
du -sh data/external/smd
