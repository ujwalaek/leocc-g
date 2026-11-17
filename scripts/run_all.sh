#!/bin/bash
# All experiments of the spec ("Setup and experiments"): 95 runs x 120 s.
#
#   Main comparison  B1-B4, G1 x 2 traces x 5 reps   50 runs   RQ1, RQ2
#   Ablation         A1 x 2 traces x 5 reps          10 runs   RQ3
#   Threshold sweep  G1 at 3 threshold pairs x A x 5 15 runs   RQ3
#   Timing error     G1 shifted -500/-100/+100/+500 ms, correction off, x A x 5
#                                                     20 runs   RQ4
#
# Senders: B1 cubic | B2 bbr (BBRv3) | B3 leocc_g:g_mode=2 (freeze-only)
#          B4 leocc (original) | G1 leocc_g | A1 leocc_g:g_mode=1 (guard + hard replace)
#
# Usage: run_all.sh PREFIX [extra run_one.sh args, e.g. -q 3300]
# Repetitions are the outer loop, so a partial run still covers every configuration.
set -u
P=$(cd "$(dirname "$0")/.."; pwd)
PREFIX=$1; shift
EXTRA=("$@")
TA=$HOME/leocc-g/traces/Anonymous_A_downlink/3     # Trace A: base RTT ~22 ms
TB=$HOME/leocc-g/traces/Anonymous_C_downlink/1     # Trace B: base RTT ~112 ms
REPS=${REPS:-5}

for rep in $(seq 1 "$REPS"); do
  # each call does one repetition; run_batch numbers it rep1, so pass the rep via a sub-batch
  R=rep$rep
  "$P/scripts/run_batch.sh" "${PREFIX}_main/$R" 1 \
      "cubic bbr leocc_g:g_mode=2 leocc leocc_g" "$TA $TB" "${EXTRA[@]}"
  "$P/scripts/run_batch.sh" "${PREFIX}_ablation/$R" 1 \
      "leocc_g:g_mode=1" "$TA $TB" "${EXTRA[@]}"
  "$P/scripts/run_batch.sh" "${PREFIX}_sweep/$R" 1 \
      "leocc_g:g_keep_pct=5,g_replace_pct=15 leocc_g:g_keep_pct=20,g_replace_pct=40 leocc_g:g_keep_pct=30,g_replace_pct=60" \
      "$TA" "${EXTRA[@]}"
  "$P/scripts/run_batch.sh" "${PREFIX}_timing/$R" 1 \
      "leocc_g:shift=-500,g_phase_correct=0 leocc_g:shift=-100,g_phase_correct=0 leocc_g:shift=100,g_phase_correct=0 leocc_g:shift=500,g_phase_correct=0" \
      "$TA" "${EXTRA[@]}"
done
echo "ALL_DONE $(date -Is)"
