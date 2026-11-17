#!/bin/bash
# Follow-up experiments after run_all.sh, in priority order:
#  1. threshold sweep + timing error on Trace B (on Trace A the 100 ms buffer is ~4 BDP, so
#     post-switch loss is ~0 for every sender and these experiments cannot discriminate)
#  2. timing error +-500 ms with online phase correction ON, both traces (RQ4 "does online
#     correction close the gap")
#  3. main comparison with the authors' 50,000-packet buffer (sensitivity)
# Usage: run_extra.sh PREFIX QLEN     e.g. run_extra.sh clk_q3300 3300
set -u
P=$(cd "$(dirname "$0")/.."; pwd)
PREFIX=$1; Q=$2
TA=$HOME/leocc-g/traces/Anonymous_A_downlink/3
TB=$HOME/leocc-g/traces/Anonymous_C_downlink/1
REPS=${REPS:-5}

for rep in $(seq 1 "$REPS"); do
  R=rep$rep
  "$P/scripts/run_batch.sh" "${PREFIX}_sweepB/$R" 1 \
      "leocc_g:g_keep_pct=5,g_replace_pct=15 leocc_g:g_keep_pct=20,g_replace_pct=40 leocc_g:g_keep_pct=30,g_replace_pct=60" \
      "$TB" -q "$Q"
  "$P/scripts/run_batch.sh" "${PREFIX}_timingB/$R" 1 \
      "leocc_g:shift=-500,g_phase_correct=0 leocc_g:shift=-100,g_phase_correct=0 leocc_g:shift=100,g_phase_correct=0 leocc_g:shift=500,g_phase_correct=0" \
      "$TB" -q "$Q"
done
for rep in $(seq 1 "$REPS"); do
  "$P/scripts/run_batch.sh" "${PREFIX}_timingon/rep$rep" 1 \
      "leocc_g:shift=-500,g_phase_correct=1 leocc_g:shift=500,g_phase_correct=1" "$TA $TB" -q "$Q"
done
for rep in $(seq 1 "$REPS"); do
  # e.g. PREFIX final_q3300 -> final_q50000_main, clk_q3300 -> clk_q50000_main
  "$P/scripts/run_batch.sh" "${PREFIX%_q*}_q50000_main/rep$rep" 1 \
      "cubic bbr leocc_g:g_mode=2 leocc leocc_g" "$TA $TB" -q 50000
done
echo "EXTRA_DONE $(date -Is)"
