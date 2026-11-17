#!/bin/bash
# One LeoReplayer experiment run.
#
# Usage (as root):
#   run_one.sh -a ALG -t TRACE_DIR -o OUT_DIR [-d up|down] [-T seconds] [-l loss]
#              [-k module.ko] [-p "modparam=val ..."] [-c]
#
#   -a  congestion control name passed to iperf3 -C (cubic, bbr, leocc, leocc_g, ...)
#   -t  trace directory containing bw_N.txt and delay_N.txt
#   -o  output directory (created)
#   -d  direction: down (default; iperf3 -R, sender outside the emulator)
#       or up (sender inside the emulator)
#   -T  run duration in seconds (default 120)
#   -l  random loss rate on the data direction (default 0.0001)
#   -k  kernel module to (re)load before the run, e.g. modules/leocc/leocc.ko
#   -p  module parameters for -k, e.g. "offset=12000 min_rtt_fluctuation=10000"
#   -q  droptail queue length in packets (default 50000 down / 500 up, LeoReplayer README)
#   -c  also capture packet headers (sender.pcap; large at downlink rates)
#
# Outputs in OUT_DIR:
#   meta.txt       all settings
#   times.txt      shell_start (= trace time 0) and iperf_start, epoch seconds
#   sender_ss.log  sender socket state every 50 ms ("t=<epoch>" then ss -tin lines)
#   iperf.json     iperf3 client report, 0.1 s intervals
#   mm.log         emulator stderr
#   kernel.log     kernel log lines from the run (LeoCC-G decisions, any kernel warnings)
#   queue_log_*.gz per-packet log of the emulator's link queue
set -u
ALG=""; TRACE=""; OUT=""; DIR=down; DUR=120; LOSS=0.0001; KO=""; PARAMS=""; CAP=0; QARG=""
while getopts "a:t:o:d:T:l:k:p:q:c" opt; do
  case $opt in
    a) ALG=$OPTARG;; t) TRACE=$OPTARG;; o) OUT=$OPTARG;; d) DIR=$OPTARG;;
    T) DUR=$OPTARG;; l) LOSS=$OPTARG;; k) KO=$OPTARG;; p) PARAMS=$OPTARG;; c) CAP=1;;
    q) QARG=$OPTARG;;
    *) sed -n '2,25p' "$0"; exit 2;;
  esac
done
[ -n "$ALG" ] && [ -d "$TRACE" ] && [ -n "$OUT" ] || { sed -n '2,25p' "$0"; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 2; }

BW=$(ls "$TRACE"/bw_*.txt | head -1); DELAY=$(ls "$TRACE"/delay_*.txt | head -1)
rm -rf "$OUT"; mkdir -p "$OUT"; OUT=$(cd "$OUT"; pwd)

cleanup() {
  pkill -x iperf3 2>/dev/null; pkill -x tcpdump 2>/dev/null
  pkill -x mm-link 2>/dev/null; pkill -x mm-loss 2>/dev/null; pkill -x mm-delay 2>/dev/null
  sleep 0.5
}
cleanup

# (Re)load the congestion control module with this run's parameters.
if [ -n "$KO" ]; then
  MOD=$(basename "$KO" .ko)
  rmmod "$MOD" 2>/dev/null
  insmod "$KO" $PARAMS || { echo "insmod $KO failed"; exit 1; }
fi
grep -qw "$ALG" /proc/sys/net/ipv4/tcp_available_congestion_control || modprobe "tcp_$ALG" 2>/dev/null
grep -qw "$ALG" /proc/sys/net/ipv4/tcp_available_congestion_control || { echo "CC $ALG not available"; exit 1; }
sysctl -qw net.ipv4.ip_forward=1
# Allow windows large enough for 400 Mbps x ~150 ms plus queueing.
sysctl -qw net.core.rmem_max=268435456 net.core.wmem_max=268435456
sysctl -qw net.ipv4.tcp_rmem="4096 131072 268435456" net.ipv4.tcp_wmem="4096 65536 268435456"

if [ "$DIR" = up ]; then QLEN=500; LOSSDIR=uplink; else QLEN=50000; LOSSDIR=downlink; fi
[ -n "$QARG" ] && QLEN=$QARG

cat > "$OUT/meta.txt" <<META
date=$(date -Is)
kernel=$(uname -r)
alg=$ALG
trace=$TRACE
bw_file=$BW
delay_file=$DELAY
direction=$DIR
duration_s=$DUR
loss=$LOSS
queue_packets=$QLEN
module=$KO
module_params=$PARAMS
emulator_allow_reorder=${LEOREPLAYER_ALLOW_REORDER:-0}
emulator_clock=$( [ "${LEOREPLAYER_REALTIME:-0}" != 1 ] && strings /usr/local/bin/mm-delay | grep -q LEOREPLAYER_CLOCK_OFFSET_US && echo monotonic || echo realtime )
META

# ss sampler for the data sender. Data flow = the 5201 connection with most bytes.
SAMPLER=$(mktemp)
cat > "$SAMPLER" <<'S_EOF'
#!/bin/bash
# $1 = output file, $2 = seconds, $3 = ss filter
end=$((SECONDS + $2))
while [ $SECONDS -lt $end ]; do
  echo "t=$(date +%s.%N)"; ss -tin $3 2>/dev/null | tail -n +2
  sleep 0.05
done > "$1"
S_EOF
chmod +x "$SAMPLER"

dmesg -C; DMESG_START=0
iperf3 -s -1 -D --logfile "$OUT/iperf_server.log"

# Outside the emulator: wait for its interface, add the route, sample/capture.
(
  for _ in $(seq 200); do
    DEV=$(ip -br link | grep -o 'delay-[0-9]*' | head -1)
    [ -n "$DEV" ] && break; sleep 0.05
  done
  [ -z "$DEV" ] && { echo "emulator interface never appeared" >> "$OUT/mm.log"; exit 1; }
  ip route add 100.64.0.0/24 dev "$DEV" 2>/dev/null
  [ $CAP = 1 ] && timeout $((DUR + 15)) tcpdump -q -i "$DEV" -s 66 -w "$OUT/sender.pcap" 2>/dev/null &
  [ "$DIR" = down ] && "$SAMPLER" "$OUT/sender_ss.log" $((DUR + 5)) "( sport = :5201 )"
  wait
) &
OUTER=$!

# Inside the emulator: the iperf3 client (and the sampler when it is the sender).
INNER=$(mktemp)
cat > "$INNER" <<'INNER_EOF'
#!/bin/bash
ALG=$1; DUR=$2; OUT=$3; DIR=$4; SAMPLER=$5; MOD=$6
# Direction is passed as a word, not "-R": mm-link would parse a dash argument
# as one of its own options.
RFLAG=""; [ "$DIR" = down ] && RFLAG="-R"
# The emulator replays the trace from shell start; log it so trace time
# (switch boundaries) can be mapped onto the samples' clock.
echo "shell_start=$(date +%s.%N)" > "$OUT/times.txt"
# Trace time 0 = BASE_TIMESTAMP (epoch ms), set by the outermost emulator process (mm-delay)
# and used by both its delay queue and the link queue. The inner shell starts ~0.2 s later.
T0_MS=${BASE_TIMESTAMP:-$(date +%s%3N)}
echo "trace_start_ms=$T0_MS" >> "$OUT/times.txt"
# Anchor a LeoCC-family module's 15 s schedule to the trace start (not to socket creation).
[ -n "$MOD" ] && [ -w /sys/module/$MOD/parameters/t0_ms ] && echo "$T0_MS" > /sys/module/$MOD/parameters/t0_ms
[ "$DIR" = up ] && { "$SAMPLER" "$OUT/sender_ss.log" $((DUR + 5)) "dst 100.64.0.1" & }
echo "iperf_start=$(date +%s.%N)" >> "$OUT/times.txt"
iperf3 -c 100.64.0.1 -C "$ALG" -t "$DUR" -i 0.1 $RFLAG --json > "$OUT/iperf.json"
INNER_EOF

# The emulator writes queue_log_* / delay_queue.log into its working directory,
# so start it from the run's output directory.
cd "$OUT"
timeout $((DUR + 30)) mm-delay 10 "$DELAY" \
  mm-loss $LOSSDIR "$LOSS" \
  mm-link "$BW" "$BW" \
    --uplink-queue droptail --uplink-queue-args packets=$QLEN \
    --downlink-queue droptail --downlink-queue-args packets=$QLEN \
  bash "$INNER" "$ALG" "$DUR" "$OUT" "$DIR" "$SAMPLER" "${KO:+$(basename "$KO" .ko)}" 2>> "$OUT/mm.log"
RC=$?
pkill -f "$SAMPLER" 2>/dev/null
wait $OUTER 2>/dev/null
rm -f "$INNER" "$SAMPLER"
cleanup
# Kernel log lines from this run (LeoCC-G logs every guard / measurement / switch decision).
dmesg | tail -n +$((DMESG_START + 1)) | grep -E 'leocc|BUG|WARNING|Call Trace' > "$OUT/kernel.log"
# Per-packet queue log from the emulator (enter/leave time, queueing delay): keep, compressed.
gzip -qf "$OUT"/queue_log_*.txt "$OUT"/delay_queue.log 2>/dev/null
python3 - "$OUT/iperf.json" <<'PY' || echo "RUN_FAILED rc=$RC (see $OUT/mm.log)"
import json, sys
d = json.load(open(sys.argv[1]))
e = d["end"]; s = e["sum_sent"]; r = e["sum_received"]
print(f"RUN_OK goodput={r['bits_per_second']/1e6:.1f}Mbps retrans={s.get('retransmits','?')} "
      f"sender_cc={e.get('sender_tcp_congestion','?')}")
PY
