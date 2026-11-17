# LeoCC-G: Graded Reset for LEO Congestion Control

LeoCC-G is a Linux kernel congestion-control module built from LeoCC (SIGCOMM 2025). At every
Starlink satellite switch (every 15 s), LeoCC throws away its path estimates and restarts BBR's
STARTUP. LeoCC-G instead measures how much the path changed and **keeps** (change < 10 %),
**blends** (10–30 %) or **replaces** (> 30 %) the old estimates, and never restarts STARTUP.

Headline result (Trace B, 112 ms base RTT, 100 ms buffer, 5 runs): same goodput as LeoCC
(368 vs 369 Mbit/s), 13x fewer retransmissions in the first second after a switch (295 vs 3,843).
 

## Layout

| Path | What it is |
|---|---|
| `modules/leocc_g/leocc_g.c` | **LeoCC-G** kernel module (one module, three senders via `g_mode`: 0 graded, 1 hard replace, 2 freeze-only) |
| `modules/leocc/leocc.c` | Original LeoCC (simulation version) with a `get_info` hook for logging |
| `scripts/run_one.sh` | One 120 s experiment: loads the module, runs iperf3 through LeoReplayer, samples `ss` |
| `scripts/run_batch.sh` | A batch of runs + per-run analysis (`summary.json`) |
| `scripts/run_all.sh` | The spec's 95 runs (main comparison, ablation, sweep, timing) |
| `scripts/run_extra.sh` | Follow-ups: sweep/timing on Trace B, correction on, 50,000-packet buffer |
| `scripts/find_offset.py` | Finds a trace's 15 s schedule offset from its delay file |
| `patches/` | Two LeoReplayer fixes: FIFO delay queue (no reordering) and monotonic clock |
| `analysis/leoan.py` | Per-run metrics (goodput, RTT, post-switch retransmissions, recovery, estimate error) |
| `analysis/make_figures.py` | Figures 1–6 and the summary table for one experiment prefix |
| `analysis/rq1_traces.py` | RQ1: path change at 5,652 switches across the trace sets |
| `analysis/significance.py` | Exact permutation tests, LeoCC-G vs every other configuration (5 runs each) |
| `analysis/figures/clk_q3300/` | **Final figures** (100 ms buffer) used in the report |
| `analysis/figures/clk_q50000/` | Sensitivity figures (50,000-packet buffer) |
| `docs/WORKLOG.md` | Detailed log of every step, problem and number |

`results/` holds every final run (`clk_*`, 200 runs): per run `summary.json` (all metrics),
`kernel.log` (one line per switch decision), `meta.txt` (settings), `boundaries.csv` and `mm.log`.
The three large per-run logs (`sender_ss.log`, `iperf.json`, `iperf_server.log`, 1.9 GB in total)
are not in git; they are in the separate archive `LeoCC-G-raw-logs.tar.gz`. `significance.py` and the
tables run from `results/` alone; `make_figures.py` also needs the `ss` samples from the archive.

## Demo: what LeoCC-G decides at a switch

`kernel.log` of one LeoCC-G run on Trace B (`results/clk_q3300_main/rep1/C_downlink_1/leocc_g/rep1/`),
two switches, shortened:

```
leocc_g: switch t=7804  old_bw=379 meas_bw=372 new_bw=379 Mbps ... dbw=1%  drtt=0%  delta=1%  alpha=0/256
leocc_g: switch t=22672 old_bw=293 meas_bw=362 new_bw=362 Mbps ... dbw=23% drtt=77% delta=77% alpha=256/256
```

At the first switch the path changed by 1 %, so LeoCC-G keeps its estimate (alpha = 0). At the
second the RTT changed by 77 %, so it replaces it (alpha = 1). LeoCC would have restarted STARTUP at both.

## Requirements

- Linux with Google's BBRv3 kernel branch (`github.com/google/bbr`, branch `v3`); we used
  6.8.0-rc3 under WSL2 (Ubuntu 24.04). LeoCC's code needs BBRv3's internals.
- LeoReplayer from the LeoCC repository (`github.com/SpaceNetLab/LeoCC`), built with the two
  patches in `patches/` (`leoreplayer-delay-queue-and-clock.diff`).
- The LeoCC Starlink traces (Trace A = `Anonymous_A_downlink/3`, Trace B = `Anonymous_C_downlink/1`).
- iperf3, Python 3 with numpy, scipy and matplotlib. The run scripts call `sudo` themselves (we used
  passwordless sudo).

## Reproduce

```bash
# build the modules (KDIR = the BBRv3 kernel source tree)
make -C modules/leocc   KDIR=~/leocc-g/bbr-kernel
make -C modules/leocc_g KDIR=~/leocc-g/bbr-kernel

# all experiments (about 7 hours, 200 runs x 120 s), 3,300-packet (100 ms) buffer
REPS=5 scripts/run_all.sh clk_q3300 -q 3300
scripts/run_extra.sh clk_q3300 3300

# figures and tables
python3 analysis/make_figures.py clk_q3300 --rq1 analysis/out/rq1_changes.csv
python3 analysis/make_figures.py clk_q50000

# which differences are statistically significant (Trace B, retransmissions 1 s after a switch)
python3 analysis/significance.py clk_q3300
```

With 5 runs per configuration, LeoCC-G's post-switch loss on Trace B is significantly lower than
LeoCC's, BBRv3's and freeze-only's (p = 0.008, the smallest possible). It is **not** significantly
lower than the hard-replace ablation (p = 0.21) or the 30/60 % thresholds (p = 0.44). "Retx total" in
the summary tables counts from the end of the 2 s warm-up, so it is lower than iperf3's own count.

One run by hand (graded reset on Trace B):

```bash
scripts/run_batch.sh demo 1 "leocc_g" "$HOME/leocc-g/traces/Anonymous_C_downlink/1" -q 3300
```

LeoCC-G parameters (`modinfo -p modules/leocc_g/leocc_g.ko`): `g_mode`, `g_keep_pct` (10),
`g_replace_pct` (30), `g_phase_correct`, `g_gap_ms` (30), `g_rtt_refresh_ms` (10000), `g_log`.

## Two things to know before running

- **Use the patched emulator.** Unpatched LeoReplayer reorders packets at ~400 Mbit/s (85 % of
  BBRv3's retransmissions were spurious) and uses the wall clock; in a VM the clock steps forward
  when the host is idle, which releases the whole queue at once and creates impossible RTT samples.
- If a run is killed mid-way, an orphaned socket can keep `leocc_g` loaded ("insmod: File exists").
  Fix: `sysctl net.ipv4.tcp_orphan_retries=1`, wait about a minute, `rmmod leocc_g`, set it back to 0.

## Credits

`modules/leocc/leocc.c` and the base of `modules/leocc_g/leocc_g.c` are LeoCC by Lai et al.
(SIGCOMM 2025, [SpaceNetLab/LeoCC](https://github.com/SpaceNetLab/LeoCC), `MODULE_LICENSE("Dual BSD/GPL")`),
itself derived from Linux's `tcp_bbr.c`. The patches in `patches/` apply to LeoReplayer from the same
repository. Our changes are marked "LeoCC-G" in the code.
