#!/bin/bash
# Run a batch of experiments and analyze each run.
#
# Usage: run_batch.sh BATCH_NAME REPS "SENDER ..." "TRACE_DIR ..." [extra run_one.sh args]
#   SENDER: cubic | bbr | leocc | leocc_g[:param=val,param=val,...,shift=ms]
#           (module senders get offset=<trace offset> min_rtt_fluctuation=10000 added
#            automatically; shift=<ms> adds a timing error to the offset)
#   e.g.  leocc_g                  graded reset (G1)
#         leocc_g:g_mode=1         guard + hard replace (A1)
#         leocc_g:g_mode=2         freeze-only (B3)
#         leocc_g:g_keep_pct=5,g_replace_pct=20
#         leocc_g:shift=-500,g_phase_correct=0
# Example:
#   run_batch.sh baseline 1 "cubic bbr leocc" "$HOME/leocc-g/traces/Anonymous_A_downlink/3"
#
# Results: results/BATCH_NAME/<trace-tag>/<sender>/rep<k>/ ; one line per run in results/BATCH_NAME/runs.log
set -u
P=$(cd "$(dirname "$0")/.."; pwd)
BATCH=$1; REPS=$2; SENDERS=$3; TRACES=$4; shift 4
EXTRA=("$@")
OUTROOT=$P/results/$BATCH
mkdir -p "$OUTROOT"
LOG=$OUTROOT/runs.log
MRF=${MIN_RTT_FLUCTUATION:-10000}

for rep in $(seq 1 "$REPS"); do
  for T in $TRACES; do
    TAG=$(basename "$(dirname "$T")" | sed 's/Anonymous_//')_$(basename "$T")
    OFF=$(python3 "$P/scripts/find_offset.py" "$T"/delay_*.txt | cut -f2)
    for S in $SENDERS; do
      NAME=${S%%:*}
      KO=""; PARAMS=""
      # Options after "leocc_g:" are comma-separated module parameters, plus the
      # pseudo-option shift=<ms> which moves the predicted schedule (RQ4 timing error).
      OPTS=""; [[ $S == *:* ]] && OPTS=${S#*:}
      SHIFT=$(echo "$OPTS" | tr ',' '\n' | sed -n 's/^shift=//p')
      OPTS=$(echo "$OPTS" | tr ',' '\n' | grep -v '^shift=' | tr '\n' ' ')
      SOFF=$((OFF + ${SHIFT:-0})); [ $SOFF -lt 0 ] && SOFF=$((SOFF + 15000))
      case $NAME in
        leocc)   KO=$P/modules/leocc/leocc.ko; PARAMS="offset=$SOFF min_rtt_fluctuation=$MRF $OPTS";;
        leocc_g) KO=$P/modules/leocc_g/leocc_g.ko; PARAMS="offset=$SOFF min_rtt_fluctuation=$MRF $OPTS";;
      esac
      LABEL=$(echo "$S" | tr ':= /' '-__-' | sed 's/\.ko//')
      OUT=$OUTROOT/$TAG/$LABEL/rep$rep
      # Resume support: a run is finished once run_one.sh has written kernel.log and the
      # analysis has written summary.json; finished runs are skipped, unfinished ones redone.
      if [ -f "$OUT/kernel.log" ] && [ -f "$OUT/summary.json" ]; then
        echo "$(date +%T) $TAG $LABEL rep$rep | skipped (already done)"
        continue
      fi
      ARGS=(-a "$NAME" -t "$T" -o "$OUT" "${EXTRA[@]}")
      [ -n "$KO" ] && ARGS+=(-k "$KO" -p "$PARAMS")
      RES=$(sudo -n "$P/scripts/run_one.sh" "${ARGS[@]}" 2>/dev/null | tail -1)
      sudo -n chown -R "$(id -u):$(id -g)" "$OUT"
      AN=$(python3 "$P/analysis/leoan.py" run "$OUT" 2>&1 | python3 -c '
import sys, json
txt = sys.stdin.read(); j = json.loads(txt[:txt.rindex("}") + 1])
print("util=%.2f p95rtt=%.1fms postretx=%.1f rec=%.2fs" % (j["utilization"], j["rtt_p95_ms"], j["post_switch_retx_mean"], j["recovery_s_mean"]))' 2>/dev/null || echo "analysis-failed")
      echo "$(date +%T) $TAG $LABEL rep$rep | $RES | $AN" | tee -a "$LOG"
    done
  done
done
