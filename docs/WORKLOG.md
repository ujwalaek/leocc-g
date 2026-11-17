# LeoCC-G — Work Log

Running log of everything done on this project: what, why, exact commands, what broke and
how it was fixed, and results. Newest entries are at the bottom of each day.
A copy lives in the project repo at `~/leocc-g/project/docs/WORKLOG.md` (inside WSL Ubuntu).

---

## Quick reference (current state)

| What | Where / value |
|---|---|
| Spec | `final_project/LeoCC-G Graded Reset for LEO Congestion Control.pdf` |
| Linux environment | WSL2, Ubuntu 24.04, user `ajay`, passwordless sudo |
| Kernel running in WSL | `6.8.0-rc3-bbr3-wsl` (Google BBRv3 tree) |
| Kernel source | `~/leocc-g/bbr-kernel` (branch `bbr-v3-2024-02-22-01`) |
| Kernel image (Windows side) | `C:\Users\Ajay\wsl-kernel\bzImage-bbr3` |
| WSL config | `C:\Users\Ajay\.wslconfig` → `kernel=C:/Users/Ajay/wsl-kernel/bzImage-bbr3` (backup: `.wslconfig.bak-before-bbr3`) |
| LeoCC upstream code | `~/leocc-g/LeoCC` (github.com/SpaceNetLab/LeoCC, commit `69df640`) |
| Emulator | LeoReplayer (Mahimahi fork), installed as `/usr/local/bin/mm-*` |
| Traces archive | `~/leocc-g/traces-dl/4.8K.zip` (732 MB; 60 GB unzipped — never extract all) |
| Extracted traces | `~/leocc-g/traces/Anonymous_{A,B,C,D}_{uplink,downlink}/N/{bw_N,delay_N}.txt` |
| Project repo | `~/leocc-g/project` (git) — `scripts/`, `modules/`, `analysis/`, `results/` (not committed) |

**Undo the custom kernel:** delete the `kernel=` line in `C:\Users\Ajay\.wslconfig`, then `wsl --shutdown`.

**Open Ubuntu from Windows:** `wsl -d Ubuntu`, then `cd ~/leocc-g/project`.
From Windows Explorer the files are at `\\wsl.localhost\Ubuntu\home\ajay\leocc-g`.

### Decisions taken
| Decision | Choice | Reason |
|---|---|---|
| Where to run | WSL2 on this laptop | i7-14700HX (28 threads), 16 GB RAM, 245 GB free is plenty; crashes in a kernel module only kill the WSL VM, not Windows |
| Kernel | Build Google's BBRv3 tree with WSL's own config | LeoCC was written against a BBRv3 kernel: needs `ICSK_CA_PRIV_SIZE`=144 (stock = 104; LeoCC state ≈120 B) and the `.tso_segs` hook. LeoCC compiles unchanged. Also gives the real BBRv3 baseline (B2). |
| Direction | **Downlink** (main) | Downlink random loss is 0.01% so switch-induced loss is visible; uplink's 0.2–0.5% random loss explains ~70% of retransmissions and hides switch effects (see Day 1, step 12). Emulator verified to keep up at ~400 Mbps. |
| Random loss | **One value for all algorithms**: 0.0001 (downlink) | Fair comparison. LeoCC README uses different uplink loss per algorithm (0.002 CUBIC vs 0.005 BBR/LeoCC) — not used. |
| Queue | droptail, 50000 packets downlink (500 uplink) | Values from LeoReplayer README / example |
| Trace A / Trace B | Set **A** (one-way delay ≈12 ms) and set **C** (≈54 ms) | Different base RTTs; exact trace numbers chosen in Day 1, step 15 |

---

## Day 1 — 2026-11-04: environment setup and first runs

### 1. Read the spec, checked the laptop
- Spec: implement LeoCC-G (graded keep/blend/replace reset instead of LeoCC's always-restart-STARTUP),
  as a Linux kernel congestion-control module, evaluated on LeoReplayer with Starlink traces.
  95 runs × 120 s ≈ 3.2 h of emulation.
- Laptop: Intel i7-14700HX (20 cores / 28 threads), 15.7 GB RAM, 245 GB free on C:, Windows 11.
- WSL: version 2.5.9, distro `Ubuntu` (WSL2) installed.

### 2. WSL would not start → enabled Virtual Machine Platform
- Error: `Wsl/Service/CreateInstance/CreateVm/HCS/HCS_E_SERVICE_NOT_AVAILABLE`.
- Cause: Hyper-V compute service (`vmcompute`) missing → the **Virtual Machine Platform** Windows feature was off.
- Fix (user, in Administrator PowerShell), then reboot:
  ```powershell
  dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
  dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
  ```
- After reboot: Ubuntu 24.04.4 started, 28 CPUs and 7.6 GB RAM visible in WSL, 1 TB virtual disk.

### 3. How commands are run from Claude Code (technical note)
- Commands are written to a small script file on the Windows side and executed with
  `wsl -d Ubuntu -e bash /mnt/c/.../script.sh` (with `MSYS_NO_PATHCONV=1` in Git Bash).
- Pitfall found: `wsl -- bash -c '...'` expands `$variables` in the wrong shell, so inline commands break.
- Pitfall found: `pkill -f <pattern>` kills the calling command too if the pattern appears in its command line.

### 4. Installed packages (Ubuntu)
```bash
sudo apt-get install -y iproute2 protobuf-compiler libprotobuf-dev autotools-dev dh-autoreconf \
  iptables pkg-config dnsmasq-base apache2-bin debhelper libssl-dev ssl-cert libxcb-present-dev \
  libcairo2-dev libpango1.0-dev apache2-dev iperf3 \
  build-essential libncurses-dev libelf-dev dwarves cpio rsync zstd \
  python3-numpy python3-matplotlib python3-pandas python3-scipy tcpdump
```
(First line = LeoReplayer prerequisites from its README; second = kernel build; third = analysis.)

### 5. Got the code
```bash
mkdir -p ~/leocc-g && cd ~/leocc-g
git clone --depth 1 https://github.com/SpaceNetLab/LeoCC                         # LeoCC + LeoReplayer
git clone --depth 1 -b bbr-v3-2024-02-22-01 https://github.com/google/bbr bbr-kernel   # 1.8 GB
```
- LeoCC repo layout: `leocc/simulation/leocc.c` (the version for LeoReplayer — the one we use),
  `leocc/live_network/` (needs ICMP pinging + netlink; not used), `leoreplayer/replayer/` (Mahimahi fork),
  `traces/` (README + `extract_reconfiguration.py`; actual traces are a separate download).
- Why this BBRv3 branch: it is a 6.8 kernel with BBRv3, has `ICSK_CA_PRIV_SIZE = 144` and the
  `tso_segs` callback that LeoCC's code uses. A newer branch (`bbr-v3-2026-09-16-01`, Linux 7.1-rc5) exists
  but LeoCC predates it.

### 6. Read LeoCC's reset logic (confirms the spec's claim)
File `leocc/simulation/leocc.c`:
- `leocc_main()`: every 15 s (`PERIOD = 15000`), in a 100 ms window ending at `offset` (module parameter,
  ms), sets `reconfiguration_trigger = 1`. Time is measured from `init_stamp` = when the first LeoCC
  connection was created.
- `leocc_update_min_rtt()`: if the trigger is set (and mode is DYNAMIC_CRUISE) → enter **PROBE_RTT**
  (cwnd drops to ½·BDP for 200 ms).
- `leocc_check_probe_rtt_done()`: calls `leocc_reset_mode()`, and if the trigger is set,
  `minmax_reset(&bw, rtt_cnt, reconfiguration_max_bw)` (bandwidth filter reset).
- `leocc_reset_mode()`: `if (!full_bw_reached || reconfiguration_trigger) → STARTUP` — **always restarts
  STARTUP after a switch, no test of how much the path changed.** Exactly what the spec says.
- `leocc_check_drain()`: leaving STARTUP clears the trigger.
- Kalman filters (`bw_hat_post`, `rtt_hat_post`) are updated per round inside DYNAMIC_CRUISE, i.e. within an
  epoch, not at the boundary.
- Module parameters: `offset` (default 12000), `min_rtt_fluctuation` (default 10000 µs; README suggests
  5000–20000), `delta_rtt` (0), `delta_thresh` (45000).
- **Where LeoCC-G changes code:** `leocc_reset_mode()` and the filter reset in `leocc_check_probe_rtt_done()`.
  Note: LeoCC's 200 ms PROBE_RTT already acts partly like the spec's "Guard" step.

### 7. Built and tested LeoReplayer
```bash
cd ~/leocc-g/LeoCC/leoreplayer/replayer
./autogen.sh && ./configure && make -j24 && sudo make install
sudo sysctl -w net.ipv4.ip_forward=1
```
- Built cleanly on Ubuntu 24.04 (README only claims 22.04).
- Smoke test with the bundled example (`example/Cubic/run.sh`, 10 s, uplink, loss 0.002):
  CUBIC 9.5 Mbit/s, 26 retransmissions — works on WSL with the stock WSL kernel.
- How LeoReplayer is driven: `mm-delay 10 delay.txt mm-loss uplink LOSS mm-link bw.txt bw.txt
  --uplink-queue droptail --uplink-queue-args packets=N ... <command>`; the command runs inside a network
  namespace and reaches the host at `100.64.0.1`.

### 8. Downloaded the Starlink traces
- Source (from `LeoCC/traces/README.md`): Tsinghua cloud share `9fc6fd096e764f57bd25`, one file `4.8K.zip`.
  ```bash
  curl -L -o 4.8K.zip "https://cloud.tsinghua.edu.cn/d/9fc6fd096e764f57bd25/files/?p=%2F4.8K.zip&dl=1"
  ```
  732 MB in ~1 min; **60 GB / 14,416 files uncompressed.**
- Contents: `Anonymous_{A,B,C,D}_{downlink,uplink}/`, 600 traces each + `statistics.txt`.
- Trace format: `bw_N.txt` = one line per 12 Mbit/s delivery opportunity at that ms timestamp;
  `delay_N.txt` = one-way delay (ms) per 10 ms slot. Traces last ~120 s.
- Medians of per-trace means across each set of 600:

  | Set | Downlink BW | Uplink BW | One-way delay |
  |---|---|---|---|
  | A | 376 Mbit/s | 19 Mbit/s | ~12 ms |
  | B | 392 | 20 | ~27 ms |
  | C | 395 | 21 | ~54 ms |
  | D | 382 | 20 | ~70 ms |

- Extracted (4.8 GB): all uplink traces, all downlink delay files, downlink traces 1–10 of each set.
  ```bash
  unzip -oq 4.8K.zip '*_uplink/*' -d ../traces
  unzip -oq 4.8K.zip '*_downlink/*/delay_*' -d ../traces
  unzip -oq 4.8K.zip "Anonymous_A_downlink/1/*" -d ../traces    # etc.
  ```

### 9. Built the BBRv3 kernel for WSL (8 minutes)
```bash
cd ~/leocc-g/bbr-kernel
zcat /proc/config.gz > .config            # start from the running WSL kernel's config
scripts/config --set-str LOCALVERSION "-bbr3-wsl" --module TCP_CONG_BBR --module NET_SCH_NETEM \
  --module NET_SCH_FQ --module TUN --module IFB \
  --disable DEBUG_INFO ... --enable DEBUG_INFO_NONE --disable DEBUG_INFO_BTF --disable LOCALVERSION_AUTO
make olddefconfig
make -j28 LOCALVERSION= bzImage modules
sudo make LOCALVERSION= modules_install INSTALL_MOD_STRIP=1
cp arch/x86/boot/bzImage /mnt/c/Users/Ajay/wsl-kernel/bzImage-bbr3
```
- Debug info disabled only to make the build faster/smaller.
- LeoCC (original, unmodified) compiled against it: `make KDIR=~/leocc-g/bbr-kernel` → `leocc.ko`.

### 10. Switched WSL to the new kernel
- `.wslconfig`:
  ```ini
  [wsl2]
  kernel=C:/Users/Ajay/wsl-kernel/bzImage-bbr3
  ```
- **Problem:** first attempt with backslashes → `wsl: Invalid escaped character: 'U'`; WSL silently fell back to
  the stock kernel. **Fix:** forward slashes.
- `wsl --shutdown`, restart → `uname -r` = `6.8.0-rc3-bbr3-wsl`. `modinfo tcp_bbr` → `version: 3`.

### 11. Emulator broke on the new kernel → fixed module autoloading
- **Problem 1:** runs hung. `mm-delay` died with `open /dev/net/tun: No such device` and the example's
  `outer.sh` spins forever waiting for the interface.
- **Problem 2:** after loading `tun`: `iptables ... -j CONNMARK: RULE_APPEND failed`.
- Cause: on the custom kernel these are loadable modules that were not being auto-loaded.
- **Fix:** load them at every boot and keep forwarding on:
  ```bash
  # /etc/modules-load.d/leocc-g.conf
  tun tcp_bbr sch_netem sch_fq ifb nf_nat nft_compat nft_chain_nat iptable_nat xt_nat xt_connmark xt_mark xt_MASQUERADE
  # /etc/sysctl.d/90-leocc-g.conf
  net.ipv4.ip_forward=1
  ```
- Verified it survives `wsl --shutdown`.
- 10 s example trace, uplink: CUBIC 14.7 Mbit/s (79 retx), BBRv3 44.9 (360 retx), **LeoCC 53.9 (707 retx)**.
  No kernel warnings.

### 12. Confirmed the 15 s reconfiguration schedule in the traces (spec Day 1–2 item)
- `scripts/find_offset.py` = the authors' `extract_reconfiguration.py` method, refactored to one file at a time
  and to report how well the 15 s period fits: take the 100 largest delay values in the first 15 s and pick
  the one whose +15 s, +30 s, ... positions also land (±100 ms) on top-100 delay spikes.
- Over all 600 uplink traces per set, fraction with ≥75% of later 15 s boundaries on delay spikes:
  **A 97%, B 96%, C 94%, D 99%.** The 15 s schedule is clearly present.
- Saved: `analysis/offsets_{A,B,C,D}_uplink.tsv` (columns: file, offset_ms, hits/possible).

### 13. Project repo + run harness
- `~/leocc-g/project` (git). First commit `ff5ffc6`.
- `scripts/run_one.sh` — one experiment run (replaces the example's scripts, whose wait loop never times out):
  ```bash
  sudo scripts/run_one.sh -a ALG -t TRACE_DIR -o OUT_DIR [-d down|up] [-T 120] [-l LOSS] \
       [-k module.ko -p "offset=... min_rtt_fluctuation=..."] [-c]
  ```
  Reloads the CC module with this run's parameters, starts iperf3 server, runs the emulator with iperf3
  client inside, samples the **sender's** socket with `ss -tin` every ~50–60 ms, optional header capture.
  Outputs: `meta.txt`, `times.txt` (shell start = trace time 0, iperf start), `sender_ss.log`,
  `iperf.json` (0.1 s intervals), `mm.log`.
- Shell start and iperf start are ~1 ms apart, so trace time ≈ connection time (matters for LeoCC's `offset`).

### 14. First full 120 s runs on a real trace (uplink, A_uplink/1, loss 0.002)
| Algorithm | Goodput | Retransmissions |
|---|---|---|
| CUBIC | 13.1 Mbit/s | 308 |
| BBRv3 | 41.1 Mbit/s | 1,438 |
| LeoCC | 46.0 Mbit/s | 1,384 |

- Retransmissions in the 1 s after each of the 8 boundaries were only ~5–6% of all retransmissions
  (boundary windows are ~7% of the time) — i.e. **no visible post-switch spike**.
- Reason: random loss 0.002 × ~476k packets ≈ 950 of LeoCC's 1,384 retransmissions are just random loss.
  ⇒ **Decision: use downlink (loss 0.0001) as the main setup.**
- `ss -i` exposes BBR's internal estimates (`bbr:(bw:...,mrtt:...,pacing_gain:...,cwnd_gain:...)`);
  LeoCC does not implement `get_info`, so it reports nothing → to add (instrumentation only).

### 15. Switched harness to downlink; verified emulator speed
- Changes: default direction `down` (iperf3 `-R`; sender = iperf3 server **outside** the emulator, so the
  `ss` sampler now runs outside for downlink), default loss 0.0001, larger socket buffers
  (`tcp_rmem/wmem` max 256 MB), packet capture optional (`-c`; ~280 MB/run at 400 Mbit/s).
- **Bug:** `mm-link: invalid option -- 'R'` — Mahimahi parses any dash-argument after its own arguments.
  **Fix:** pass the direction as a word (`down`) and set `-R` inside the emulator shell.
- Test, A_downlink/1, 30 s, loss 0.0001: trace capacity 393 Mbit/s;
  **BBRv3 363 Mbit/s (92% utilization)**, CUBIC 69.8 Mbit/s. Emulator processes at ~10–20% CPU each
  → the emulator keeps up at downlink rates on this laptop.

### 16. Chose Trace A and Trace B (downlink)
- Ran `find_offset.py` on all 600 downlink delay files of sets A and C
  (`analysis/offsets_{A,C}_downlink.tsv`): 81% (A) and 88% (C) clearly periodic.
- Compared traces 1–10 of each set (stats from `statistics.txt` + periodicity):
  - **Trace A = `Anonymous_A_downlink/3`** — mean 393 Mbit/s (set median 376), one-way delay ≈11 ms
    (base RTT 22 ms), 7/7 later boundaries periodic, higher-than-typical bandwidth variance. Offset **10.06 s**.
  - **Trace B = `Anonymous_C_downlink/1`** — mean 393 Mbit/s (set median 395), one-way delay ≈57 ms
    (base RTT 112 ms), 7/7 periodic, high variance. Offset **7.08 s**.
- Path change across the 8 boundaries of each (from `leoan.py epochs`; Δ = max(ΔBW, ΔRTT) relative):

  | Trace | Δ per boundary (%) |
  |---|---|
  | A_downlink/3 | 1.7, 1.1, 13.0, 16.1, 31.0, 48.0, 10.0, 0.2 |
  | C_downlink/1 | 20.1, 43.9, 4.3, 2.5, 12.4, 9.1, 13.7, 1.8 |

  → 7 boundaries < 10% (keep), 6 in 10–30% (blend), 3 > 30% (replace): a good mix for the graded reset.
  Almost all of the change is in **bandwidth**; base RTT changes ≤ 10%.

### 17. LeoCC instrumentation: `get_info`
- LeoCC had no `get_info`, so `ss` showed nothing about its estimates. Added a read-only `leocc_get_info()`
  (script `scripts/add_get_info.py`, idempotent) reporting through the standard `INET_DIAG_BBRINFO`
  attribute: bw = the estimate LeoCC actually uses (max filter or Kalman `bw_hat_post`), mrtt = `min_rtt_us`,
  pacing/cwnd gains (identify the mode: STARTUP 2.89/2.89, DRAIN <1/2.89, cruise ~1/2, PROBE_RTT 1/1), mode.
- No congestion-control state is touched; the diff vs. the original is only this function + one ops line
  (`git diff ff5ffc6 -- modules/leocc/leocc.c`). Verified: `ss` now prints `bbr:(bw:...,mrtt:...)` for LeoCC.

### 18. Emulator queue log
- Found `queue_log_bw_N.txt` appearing in the repo root: LeoReplayer's link queue writes a per-packet log
  (enter time, leave time, queueing delay, size) into its **working directory**. It had been committed by
  accident → removed from git, `.gitignore`d.
- Harness now starts the emulator from the run's output folder and gzips the log after the run
  (~60 MB raw per 120 s downlink run). Useful later as ground-truth queueing delay.

### 19. Analysis library `analysis/leoan.py`
- `leoan.py epochs TRACE_DIR` — per-epoch true capacity and base RTT, and Δ across each boundary (RQ1).
- `leoan.py run RUN_DIR` — writes `summary.json` and `boundaries.csv` for a run:
  - goodput (from the sender's `bytes_acked`), utilization (vs. trace capacity over the same span),
    p50/p95 RTT (sender's smoothed RTT samples), total retransmissions;
  - per boundary: retransmissions in the first 1 s (and a baseline from 3 s→0.5 s before the boundary,
    scaled to 1 s, so "excess" post-switch loss can be reported), pre-switch goodput (3 s→0.5 s before),
    **recovery time** = first time after the boundary from which 200 ms goodput stays ≥ 90% of pre-switch
    goodput for 0.5 s (0 if it never drops; capped at 5 s), minimum goodput in the 2 s after;
  - estimate error: |estimate − true epoch value| / true value, for senders that report estimates (BBRv3, LeoCC).
  - first 2 s of each run are skipped (warm-up).
- First check on a 30 s LeoCC run (Trace A): utilization 0.94, p95 RTT 43 ms (base 22 ms); after each
  switch goodput fell from ~400 to **110–150 Mbit/s** (PROBE_RTT + STARTUP restart) and recovered in
  0.35–0.9 s; **no retransmission spike** (2–4 in the first second vs. ~10/s baseline).
  Interpretation: with the authors' 50,000-packet downlink queue (≈1.4 s of buffering at 400 Mbit/s),
  STARTUP's overshoot is absorbed by the buffer, so LeoCC's cost here shows up as **throughput dips and
  queueing delay**, not loss. To be confirmed on full runs; may affect which "headline metric" the report leads with.

### 20. Batch runner `scripts/run_batch.sh`
```bash
scripts/run_batch.sh BATCH REPS "cubic bbr leocc leocc_g ..." "TRACE_DIR ..." [extra run_one.sh args]
```
- Computes each trace's offset, loads module senders with `offset=<trace offset> min_rtt_fluctuation=10000`,
  runs, analyzes, and appends one line per run to `results/BATCH/runs.log`.
- Started `day3_baseline`: CUBIC, BBRv3, LeoCC × Trace A, Trace B × 1 repetition (120 s each).

### 21. First baseline batch (later found to be affected by an emulator bug)
| Trace | Sender | Util. | p95 RTT | Retx in 1 s after switch | Recovery |
|---|---|---|---|---|---|
| A (22 ms) | CUBIC | 0.17 | 28 ms | 0.2 | 1.0 s |
| A | BBRv3 | 0.92 | 52 ms | 289 | 1.4 s |
| A | LeoCC | 0.94 | 44 ms | 9.4 | 1.9 s |
| B (112 ms) | CUBIC | 0.08 | 122 ms | 0.4 | 2.6 s |
| B | BBRv3 | 0.91 | 296 ms | 28 | 3.0 s |
| B | LeoCC | 0.93 | 340 ms | 24 | 3.0 s |

Kept in `results/day3_baseline_buggy_emulator/` for reference only.

### 22. Investigated CUBIC's low utilization → real, not a bug
- CUBIC's cwnd stays ~100–200 packets and is halved roughly once per second by the 0.01% random loss.
- Mathis et al.: rate ≈ 1.22·MSS / (RTT·√p) = 1.22·1448·8 / (0.022 s · 0.01) ≈ **64 Mbit/s** on Trace A;
  measured 69 Mbit/s. (My earlier "~640 Mbit/s" estimate was an arithmetic slip.)
- So CUBIC is genuinely random-loss-limited on this link — consistent with the LEO literature. Not a setup problem.

### 23. Found and fixed a packet-reordering bug in LeoReplayer
- Symptom: BBRv3 showed 289 retransmissions in the first second after switches although the 50,000-packet
  queue cannot overflow. `ss` counters on the data socket at the end of the run:

  | Run | retrans | dsack_dups (spurious) | reord_seen |
  |---|---|---|---|
  | A / BBRv3 | 7,180 | 6,137 (85%) | 509,133 |
  | A / LeoCC | 2,049 | 1,176 | 513,000 |
  | B / BBRv3 | 4,617 | 2,257 | 502,353 |

- Cause (`leoreplayer/replayer/src/frontend/delay_queue.cc`): packets are kept in a `std::priority_queue`
  keyed only by release time in **whole milliseconds**. `std::priority_queue` is not stable, so the ~33
  packets arriving in the same millisecond at 400 Mbit/s leave in arbitrary heap order → continuous reordering
  → spurious fast retransmits. This is an emulator artifact, not Starlink behaviour.
- Fix 1 (stable order): sequence number as tie-breaker. Reordering dropped ~8× (≈4,200 → ≈540 events/s), but
  77% of BBRv3 retransmissions were still spurious: the trace's one-way delay changes every 10 ms and every
  1 ms decrease lets new packets overtake the previous millisecond's packets.
- Fix 2 (FIFO path, now the default): `release = max(arrival + delay, previous release)` — a packet never
  leaves before the one ahead of it, as on a single FIFO path and as in upstream Mahimahi. Rationale: the
  10 ms delay values come from ICMP pings (jitter), not from observed reordering; leftover reordering would
  fill the headline metric (post-switch retransmissions) with spurious retransmissions for every algorithm.
- `LEOREPLAYER_ALLOW_REORDER=1` (environment) restores time-varying-delay reordering (with stable ties);
  each run records the mode in `meta.txt` (`emulator_allow_reorder=`).
- Patch: `patches/fix_delay_queue.py` (idempotent) and the resulting diff `patches/leoreplayer-delay-queue.diff`.
  Rebuild: `cd ~/leocc-g/LeoCC/leoreplayer/replayer && make -j24 && sudo make install`.
- Verification, Trace A, 30 s:

  | Emulator | Sender | retrans | dsack_dups | reord_seen |
  |---|---|---|---|---|
  | FIFO (default) | BBRv3 | 117 | 0 | 0 |
  | FIFO (default) | LeoCC | 129 | 0 | 0 |
  | allow-reorder (stable ties) | BBRv3 | 639 | 471 | 16,154 |

  With FIFO the ~120 retransmissions per 30 s match the expected random loss (0.0001 × ~960k packets ≈ 96).
- **For the report:** worth a paragraph — the published emulator, as released, reorders packets at high
  rates; results depending on retransmission counts should use the fixed version.
- Baseline batch re-run on the fixed emulator: `results/day3_baseline/` (buggy-emulator results renamed to
  `day3_baseline_buggy_emulator/`).

### 24. Handover signature in the traces (for the Guard window)
- Averaged over all boundaries of 20 downlink traces (A 1–10, C 1–10), relative to the detected boundary:
  capacity nearly vanishes for ~80–100 ms (≈ −100 ms … +50 ms) and one-way delay rises ~+10 ms for
  ~50–100 ms.
- ⇒ Guard window default for LeoCC-G: from 100 ms before the predicted boundary to 150 ms after it **plus one
  smoothed RTT** (the sender sees the outage through ACKs one RTT later).

### 25. Baselines on the fixed (FIFO) emulator — `results/day3_baseline/`
| Trace | Sender | Goodput | Util. | p95 RTT | Retx total | Retx 1 s after switch | Recovery |
|---|---|---|---|---|---|---|---|
| A | CUBIC | 65.6 | 0.17 | 27.9 ms | 57 | 0.9 | 0.86 s |
| A | BBRv3 | 356.5 | 0.91 | 55.5 ms | 496 | 4.6 | 1.37 s |
| A | LeoCC | 374.5 | 0.95 | 54.9 ms | 481 | 2.2 | 1.54 s |
| B | CUBIC | 31.3 | 0.07 | 122.5 ms | 77 | 0.1 | 1.90 s |
| B | BBRv3 | 353.2 | 0.91 | 351.8 ms | 353 | 2.9 | 2.06 s |
| B | LeoCC | 366.2 | 0.94 | 343.3 ms | 2,273 | 3.4 | 2.16 s |

(These LeoCC runs still had the schedule-alignment problem of step 28; superseded.)
- Binning retransmissions by time since the last switch (0.5 s bins): **no post-switch loss spike for
  any sender** — ~11–12 per bin everywhere = the random loss. LeoCC's 2,273 on Trace B come from its
  **initial** STARTUP (before the first switch). On Trace B LeoCC is in STARTUP for a long time after
  switches (samples with pacing gain 2.89 up to ~12 s after a boundary) → costs queueing delay, not loss.
- **Finding:** with the authors' 50,000-packet downlink queue (~1.5 s of buffering at 400 Mbit/s),
  STARTUP overshoot never overflows the buffer, so the spec's headline metric (retransmissions in the
  first second after a switch) cannot separate the senders. Throughput dip / recovery and delay can.
  → testing a realistic ~100 ms buffer (3,300 packets; harness option `-q`), step 30.

### 26. LeoCC-G implementation (`modules/leocc_g/leocc_g.c`)
Built from the instrumented LeoCC source; module name / CC name `leocc_g`. LeoCC's own trigger
(PROBE_RTT + filter reset + STARTUP at every switch) is removed; everything else (Kalman filters,
cruise cycling, normal 20 s PROBE_RTT) is unchanged. One module covers three senders via `g_mode`:
**0 = graded (G1)**, **1 = guard + always replace, no STARTUP (A1)**, **2 = freeze-only: guard, keep old
estimates (B3)**.

| Step | Implementation |
|---|---|
| Predict | boundary = `offset` + phase correction + k·15 s. Online correction: an **ACK gap** ≥ `g_gap_ms` (30 ms) within ±1 s of a predicted boundary is taken as the real switch; observed boundary = gap centre − ½·minRTT + 25 ms (outage centre is ~25 ms before the boundary, step 24); correction moves halfway (robust to a false detection) and is applied once the flow is >2 s from any boundary. `g_phase_correct=0` disables it. |
| Guard | from `g_guard_pre_ms` (100) before to `g_guard_post_ms` (150) + sRTT after the predicted boundary: cwnd held at its value at guard start, pacing at the pre-switch bw, no estimator updates, recovery state tracked so handover loss doesn't trigger packet conservation. |
| Measure | round 0 at 1.25× pacing (cwnd 2 BDP); rounds 1..R (`g_measure_rounds`, 2) with inflight ≤ 1 BDP; max delivery rate from rounds 1..R, min RTT from round R. |
| Graded reset | Δ = max(ΔBW, ΔRTT); α = 0 below `g_keep_pct` (10), linear to 1 at `g_replace_pct` (30); bw filter, Kalman bw and base RTT set to α·measured + (1−α)·old; Kalman uncertainty reset only on full replace; mode → cruise (never STARTUP). |
| Logging | `pr_info` for init, guard start, every evidence and every decision (old/measured/new bw, RTTs, Δ, α) → `kernel.log` in each run folder. |

- State fits the kernel limit exactly: 7 new u32 fields (one fills an alignment hole after `full_bw`) and 6 bits
  in LeoCC's `unused` bitfield → 144 bytes = `ICSK_CA_PRIV_SIZE`; LeoCC's `BUILD_BUG_ON` checks it.
- Module parameters: `g_mode g_keep_pct g_replace_pct g_guard_pre_ms g_guard_post_ms g_measure_rounds
  g_phase_correct g_gap_ms g_log` (+ LeoCC's `offset min_rtt_fluctuation ...`), see `modinfo -p`.
- Batch runner syntax: `leocc_g`, `leocc_g:g_mode=1`, `leocc_g:g_keep_pct=5,g_replace_pct=20`,
  `leocc_g:shift=-500,g_phase_correct=0` (shift = timing error added to the offset, for RQ4).

### 27. First LeoCC-G test exposed a design bug (RTT handling) → fixed
- Run 1 (Trace A): utilization only **0.65**. Kernel log: at the first switch the "old" RTT (min over the last
  round, 36.6 ms) contained a standing queue, the post-guard measurement (22.5 ms) did not; the reset moved
  the base-RTT estimate down by 14 ms to ≈5–8 ms → BDP and cwnd collapsed → the flow sat at 3–9 Mbit/s until
  the routine 20 s PROBE_RTT refreshed the min RTT.
- Also: measured RTTs right after the guard were 45–95 ms (base ~20 ms) — ACKs of packets that sat in the
  queue during the outage — so ΔRTT dominated Δ and almost every switch became "replace".
- Fixes:
  1. Don't sample round 0 (its ACKs are for packets sent during the guard).
  2. Measure with inflight ≤ 1 BDP (after the 1.25× round) so the outage queue drains; take min RTT from the
     last measurement round only.
  3. Base RTT update bounded: candidate = old base + (new short-window min − old short-window min), clamped to
     [min(old base, measured), measured] — the base RTT can never exceed a measured RTT nor be pushed below both
     the old base and the measurement by a queue that drained. ΔRTT is computed from this candidate.

### 28. Schedule alignment bug (affected LeoCC too) → fixed with a trace-start anchor
- LeoCC's simulation version counts its 15 s schedule from flow init and assumes init = trace time 0.
  Measured: the sender socket is initialised **~210 ms after the inner shell starts** (iperf3 `-R` handshake),
  and the inner shell itself starts **~120 ms after the emulator's trace clock** (`BASE_TIMESTAMP`, set by the
  outermost `mm-delay`; used by both the delay and the link queue). Total ≈ **330 ms late**: LeoCC's
  100 ms trigger window fired after the real outage. (LeoCC-G's phase correction converged to −340 ms,
  which is how this was found.)
- Fix (alignment only, same for LeoCC and LeoCC-G): `scripts/add_trace_anchor.py` adds a `t0_ms` module
  parameter (epoch ms of trace start); at init the schedule is back-dated by (now − t0_ms). The harness writes
  `$BASE_TIMESTAMP` to `/sys/module/<mod>/parameters/t0_ms` from inside the emulator, records
  `trace_start_ms` in `times.txt`, and the analysis uses it as trace time 0.
- After the fix the ACK-gap evidence lands within ±10 ms of the predicted boundaries (phase correction ≈ −4 ms).
- **All earlier LeoCC runs were misaligned → all experiments are re-run from scratch for the final results.**

### 29. LeoCC-G vs LeoCC after both fixes (Trace A, 1 run each, 50,000-packet queue)
| | Util. | p95 RTT | Retx 1 s after switch | Recovery |
|---|---|---|---|---|
| LeoCC | 0.96 | 51.8 ms | 2.4 | 1.45 s |
| LeoCC-G | 0.96 | 50.4 ms | 2.6 | 1.43 s |

- LeoCC-G's decisions (α/256) at the 8 switches: 0, 0, 179, 0, 256, 192, 89, 12 — measured Δ 7, 5, 24, 8, 31, 25,
  17, 11 % vs. true trace Δ 1.7, 1.1, 13, 16, 31, 48, 10, 0.2 %. Replaced at the 31 % switch; at the 48 % switch
  (capacity **increase** 290→430) the measurement saw only +25 % (one 1.25× round cannot reveal more) → blend.
- Goodput / capacity right after switches (mean of 7): 0–0.25 s **LeoCC 0.74 vs LeoCC-G 0.87** (LeoCC in
  PROBE_RTT/STARTUP, LeoCC-G keeps sending); 0.25–0.5 s LeoCC 0.99 vs LeoCC-G 0.91 (STARTUP refills the big
  buffer; LeoCC-G's measurement rounds cap inflight at 1 BDP); equal afterwards. On the 22 ms-RTT trace the
  differences are small; expected larger on Trace B (112 ms), where STARTUP and measurement scale with RTT.

### 30. Buffer size: the 50,000-packet queue hides the problem; a ~100 ms buffer exposes it
- Harness option `-q N` sets the droptail queue. 3,300 packets ≈ **100 ms at 400 Mbit/s**
  (≈ 4.3 BDP on Trace A, ≈ 0.85 BDP on Trace B). Results, 1 run each:

  | Trace | Sender | Util. | p95 RTT | Retx total | Retx 1 s after switch | Recovery |
  |---|---|---|---|---|---|---|
  | A | BBRv3 | 0.91 | 56.5 ms | 349 | 3.0 | 1.43 s |
  | A | LeoCC | 0.96 | 52.5 ms | 415 | 2.9 | 1.44 s |
  | A | LeoCC-G | 0.96 | 48.9 ms | 380 | 2.6 | 1.37 s |
  | B | BBRv3 | 0.90 | 241 ms | 28,507 | 1,423 | 2.41 s |
  | B | LeoCC | 0.94 | 224 ms | **95,261** | **4,634** | 1.97 s |
  | B | LeoCC-G (step 26 version) | 0.91 | 227 ms | 27,317 | 2,152 | 1.54 s |

- With a realistic buffer LeoCC shows exactly the behaviour the spec cites (highest retransmissions, a loss
  spike after every switch). Retransmissions per switch by time after the boundary (Trace B):

  | after switch | 0–0.15 s | 0.15–0.3 | 0.3–0.5 | 0.5–0.75 | 0.75–1 | 1–1.5 | 1.5–2 |
  |---|---|---|---|---|---|---|---|
  | BBRv3 | 311 | 1,142 | 451 | 106 | 1 | 7 | 97 |
  | LeoCC | 0 | 0 | 1 | 1,744 | 2,769 | 5,546 | 1,175 |
  | LeoCC-G (step 26) | 0 | 1,291 | 1,459 | 391 | 5 | 2 | 2 |

  - LeoCC: no loss during the outage (its PROBE_RTT starts 100 ms before the boundary and stops sending), then
    STARTUP overshoot loses ~11,000 packets per switch **0.5–2 s after the boundary** — mostly outside the spec's
    1 s window, so the analysis also reports a 2 s window.
  - BBRv3 and LeoCC-G: loss during/just after the outage (~100 ms of near-zero capacity fills a 100 ms buffer).
- **Decision:** main experiments use the **100 ms buffer (`-q 3300`)**; the authors' 50,000-packet buffer is run
  afterwards for the main comparison as a sensitivity check.

### 31. Guard fix: freeze the window at packets in flight
- Cause of LeoCC-G's outage loss: the guard held cwnd at its full value (≈2 BDP) while actual inflight was lower,
  so the sender kept pacing new packets into a link that was delivering almost nothing.
- Fix: at guard start, hold cwnd = min(cwnd, packets in flight) (≥ 4). During the outage no ACKs return, so nothing
  new is sent; sending resumes with the ACK clock. This is still "hold cwnd" in the spec's sense.
- Result (Trace B, 100 ms buffer): retransmissions after a switch per window 0 / 222 / 56 / 1 / 1 / 2 / 2.

  | Trace B, 100 ms buffer | Retx total | Retx 1 s after switch | Util. | p95 RTT | Recovery |
  |---|---|---|---|---|---|
  | LeoCC | 95,261 | 4,634 | 0.94 | 224 ms | 1.97 s |
  | BBRv3 | 28,507 | 1,423 | 0.90 | 241 ms | 2.41 s |
  | **LeoCC-G** | **9,130** | **197** | **0.94** | 225 ms | **1.67 s** |

  → **−96 % post-switch loss vs LeoCC at equal utilization**, faster recovery. Trace A unchanged (util 0.96,
  p95 RTT 45.5 ms). Committed `becbffa`.

### 32. Full experiment suite started (100 ms buffer)
- `scripts/run_all.sh` implements the spec's table (95 runs × 120 s): main comparison (B1 CUBIC, B2 BBRv3,
  B3 freeze-only = `leocc_g:g_mode=2`, B4 LeoCC, G1 LeoCC-G × Trace A, B × 5), ablation A1
  (`leocc_g:g_mode=1` × 2 traces × 5), threshold sweep (keep/replace = 5/15, 20/40, 30/60 % on Trace A × 5;
  10/30 is the default in the main runs), timing error (shift −500/−100/+100/+500 ms, correction off, Trace A × 5).
  Repetitions are the outer loop, so a partial run still covers every configuration.
- Results: `results/final_q3300_{main,ablation,sweep,timing}/repK/<trace>/<sender>/rep1/`, log
  `results/final_q3300.log`. Module checksums at launch: leocc.ko `fcb16191…`, leocc_g.ko `c73ff279…`.
- Note: a suite launched with `nohup … &` from a `wsl -e` call died when that WSL session closed; long runs must
  keep a WSL session open (run in the foreground of a background task).

### 33. Analysis and figure tooling
- `analysis/leoan.py` extended: 2 s post-switch loss window (`retx_2s`, `post_switch_retx2_mean`) because
  LeoCC's STARTUP losses on the long-RTT trace land 0.5–2 s after the boundary; goodput/capacity in the first
  0.5 s after each switch (`post_switch_util_05`); `parse_kernel_log()` for LeoCC-G decisions; `Trace` can be
  built from in-memory data (for reading traces straight from the zip).
- `analysis/rq1_traces.py ZIP OUT.csv N` — RQ1 over N evenly spaced traces per set (all 8 sets), read directly
  from `4.8K.zip`; only clearly periodic traces used; per-boundary ΔBW, ΔRTT, Δ → `analysis/out/rq1_changes.csv`.
- `analysis/make_figures.py PREFIX` — re-analyses every finished run (cached), writes Figures 1–6 (PNG + PDF) and
  `summary_table.md` (mean ± 95 % CI, Student t) to `analysis/figures/PREFIX/`:
  1. RQ1: CDF of ΔBW and ΔRTT per downlink set + share of switches in keep / blend / replace bands, all sets.
  2. Bandwidth estimate vs. true epoch capacity across switches (BBRv3, freeze-only, LeoCC, LeoCC-G), Trace B.
  3. Goodput and p95 RTT per sender, per trace.
  4. Post-switch retransmissions (2 s), goodput/capacity 0–0.5 s after a switch, recovery time.
  5. RQ3: keep vs graded vs replace; LeoCC-G's measured Δ vs. the true Δ per switch; decision mix and
     loss vs. thresholds.
  6. RQ4: post-switch loss vs. timing error, correction off/on, with BBRv3 and LeoCC reference lines.
- Chart style: reference palette (light), one fixed color per sender across all figures (LeoCC-G blue,
  LeoCC orange, BBRv3 aqua, freeze-only yellow, CUBIC magenta, hard-replace green); validated with the palette
  checker (adjacent CVD ΔE ≥ 9.1, normal-vision ≥ 19.6); sender names on every axis so color is never the only cue.
- Plan after the suite: re-run the threshold sweep and timing error on **Trace B** too (on Trace A the 100 ms
  buffer is ~4 BDP, so nobody loses packets after switches and those experiments can't show much), timing error
  with correction **on**, and the main comparison with the authors' 50,000-packet buffer (sensitivity).

### 34. RQ1 result (Figure 1) — most switches don't need a reset
`rq1_traces.py` over 100 evenly spaced traces per set (800), read from the zip; 729 clearly periodic traces used
(downlink A skipped 28 non-periodic, others 1–18). 5,652 switches:

| Set | Switches | Keep (Δ<10 %) | Blend (10–30 %) | Replace (Δ>30 %) | Median ΔBW | Median ΔRTT |
|---|---|---|---|---|---|---|
| A downlink | 566 | 54 % | 37 % | 9 % | 7.0 % | 0.0 % |
| B downlink | 731 | 67 % | 29 % | 5 % | 5.1 % | 0.0 % |
| C downlink | 705 | 67 % | 27 % | 6 % | 5.3 % | 0.9 % |
| D downlink | 639 | 59 % | 33 % | 8 % | 6.5 % | 1.3 % |
| A uplink | 763 | 17 % | 48 % | 35 % | 18.9 % | 9.1 % |
| B uplink | 724 | 23 % | 40 % | 37 % | 21.2 % | 3.9 % |
| C uplink | 745 | 26 % | 33 % | 41 % | 23.2 % | 2.4 % |
| D uplink | 779 | 27 % | 37 % | 36 % | 21.9 % | 1.4 % |

- **Downlink: only 5–9 % of switches change the path by more than 30 %; 54–67 % change it by less than 10 %.**
  LeoCC's full reset + STARTUP is unnecessary for >90 % of downlink switches.
- Base RTT hardly moves at switches (median 0–1.3 % downlink); the change is in **bandwidth**. (The RTT CDF is
  stepped because the trace's delay has 1 ms resolution.)
- Uplink changes are larger (35–41 % > 30 %), so grading still matters there (fewer keeps, more blends).
- Output: `analysis/out/rq1_changes.csv`, `analysis/figures/final_q3300/fig1_rq1_path_change.{png,pdf}`.

### 35. Paused the suite (user needed the laptop) — 11 / 95 runs saved
- Stopped at 14:51 (WSL clock), WSL shut down (`wsl --shutdown`; `wsl -l -v` → Stopped).
- **Resume support added:** `run_batch.sh` now skips any run whose folder already has `kernel.log` and
  `summary.json`; an interrupted run is simply redone. (The original `suite.sh` launcher deleted old results
  first — never use it to resume.)
- **To resume:** `scripts/resume_suite.sh` (inside Ubuntu: `~/leocc-g/project/scripts/resume_suite.sh`) — continues
  `run_all.sh final_q3300 -q 3300`, then `run_extra.sh final_q3300 3300`. The WSL session must stay open while it runs.
- Finished so far: main comparison repetition 1 (all 5 senders × both traces) + ablation A1 rep 1 on Trace A.

  | Rep 1 | Trace A goodput / retx | Trace B goodput / retx |
  |---|---|---|
  | CUBIC | 57.3 Mbit/s / 67 | 32.4 / 32 |
  | BBRv3 | 360.4 / 420 | 348.6 / 36,213 |
  | Freeze-only (B3) | 375.1 / 508 | 357.2 / 15,079 |
  | LeoCC | 377.1 / 388 | 363.0 / **101,719** |
  | **LeoCC-G** | 375.5 / 377 | **368.4 / 10,197** |
  | Hard replace (A1) | 377.6 / 413 | – |

  Trace B: LeoCC-G −90 % retransmissions vs LeoCC with slightly higher goodput; also below BBRv3 (−72 %) and
  freeze-only (−32 %). Trace A: all BBR-family senders within ~1 %, CUBIC random-loss-limited — as expected with
  a buffer of ~4 BDP. Single repetition — confidence intervals need the remaining 4.

## Day 2 — 2026-11-07

### 36. WSL kept restarting by itself → cause
- After `wsl --shutdown`, Ubuntu showed "Running" again with no `wsl.exe` client — only `wslservice` /
  `wslhost` / `wslrelay`. That pattern means a Windows program accessed a `\\wsl.localhost\...` file, which
  boots WSL silently. Cause: the Claude Code session that had edited `leocc_g.c` through `\\wsl.localhost`
  keeps checking that file for changes (VS Code with a WSL folder open does the same).
- `VmmemWSL` can't be ended from Task Manager ("Access denied" — protected VM process); use `wsl --shutdown`.
- Lesson: edit WSL files from inside WSL (scripts), not via `\\wsl.localhost`, or start a fresh session afterwards.

### 37. Resumed the experiments
- `scripts/resume_suite.sh` started; the 11 finished runs were skipped (resume support works) and it continued
  with run 12 (ablation A1, Trace B). Then `run_extra.sh` follows automatically. ~6.5 h in total.
- Note: the WSL clock is UTC (IST − 5:30); times in `runs.log` / the task output are UTC.

### 38. Main suite finished (95/95, 13:30 UTC) — LeoCC-G v1 collapses on Trace B
- Trace A: all senders stable over 5 reps; G1 ≈ 366–376 Mbit/s, ~2–3 post-switch retx per switch.
- Trace B (Anonymous_C_downlink/1, 100 ms buffer ≈ 0.85 BDP), goodput in Mbit/s over reps 1–5:

  | sender | rep1 | rep2 | rep3 | rep4 | rep5 |
  |---|---|---|---|---|---|
  | B2 BBRv3 | 349 | 342 | 352 | 356 | 342 |
  | B4 LeoCC | 363 | 350 | 356 | 341 | 355 |
  | B3 freeze-only | 357 | 276 | 289 | 247 | 314 |
  | **G1 LeoCC-G v1** | 368 | **66** | 189 | **79** | 161 |
  | A1 hard replace | 178 | 69 | 217 | 118 | 55 |

  The threshold-sweep and timing runs on Trace B show the same spread (util 0.10–0.83).
- Diagnosis (`results/final_q3300_main/rep2/C_downlink_1/leocc_g/rep1`, kernel.log + sender_ss.log):
  1. t ≈ 11.3 s: a short dip in the trace delay → RTT sample 66.8 ms → `min_rtt` = 65 ms (real base ≈ 110 ms).
  2. LeoCC uses its Kalman bandwidth estimate and only a 1.05 probe gain whenever
     `rtt_hat_post ≥ min_rtt + min_rtt_fluctuation (10 ms)`. With the stale 65 ms base this is always true,
     and cwnd = 2 · bw · 65 ms is only ~1.1 real BDP.
  3. t ≈ 19 s the RTT rises to 200–270 ms → delivery becomes window-limited → Kalman bw falls → cwnd falls:
     a spiral, 380 → 52 Mbit/s by t = 22 s, with no retransmissions (it is not congestion).
  4. At every later switch the measured RTT is ~75 % above the base (`meas_rtt/base − 1` median 0.73–0.77 in
     all 4 collapsed runs, 0.04–0.29 in every good run), but the candidate `base + meas − old` (step 27)
     keeps the stale base, and the graded reset refreshed `min_rtt_stamp` on every blend — even with zero RTT
     shift — so LeoCC's own 20 s min-RTT expiry never fired either.
  5. Original LeoCC is immune: its PROBE_RTT at every switch sets `min_rtt` to a fresh drained sample. The
     "always restart" design also repairs a stale estimator; the graded reset had lost that side effect.
     Freeze-only (B3) and A1 inherit the same problem (B3 keeps everything, A1's measurement can't fix the
     base either).

### 39. LeoCC-G v2 — stale base-RTT refresh
- New parameter `g_rtt_refresh_ms` (default 10000; 0 = v1 behaviour). In the graded reset:
  - if the base RTT has not been confirmed by any sample for ≥ 10 s it is *stale*; the RTT candidate is then
    this epoch's own minimum, `min(pre-switch round min, measured min)` — what LeoCC's per-switch PROBE_RTT
    would find — and the usual keep/blend/replace grading applies to it;
  - `min_rtt_stamp` is refreshed only when the base actually moved (fixes the "never expires" bug).
  - The switch log line now also prints `base_age` and `stale`.
- Built in `~/leocc-g/build_v2` while the v1 batch was still running (the batch reloads
  `modules/leocc_g/leocc_g.ko` before every run, so v1 must stay in place until it finishes).
- `scripts/run_v2.sh PREFIX QLEN` re-runs every experiment that uses the graded reset (G1, A1, sweep, timing,
  timing+correction, G1 at 50,000 packets): 120 runs ≈ 4.2 h, highest-priority first. Baselines (B1, B2, B3,
  B4) don't use the graded reset and are reused from v1. Launcher tags v1 as `leocc-g-v1`, installs and commits
  v2, then runs it. v1 results stay as an ablation ("without the stale-RTT refresh").

### 40. Follow-up batch finished; v2 rerun started
- `run_extra.sh` finished 17:12 UTC (`EXTRA_DONE`): all 200 v1-era runs done (95 main + 105 extra), 0 failures.
- With the 50,000-packet buffer, v1 G1 also collapses on Trace B (e.g. 174 Mbit/s vs LeoCC 343) → the stale-RTT
  problem does not depend on the buffer size.
- `launch_v2.sh` started right after (log: `results/v2.log`); results go to `results/v2_q3300_*` and
  `results/v2_q50000_main`.

### 41. v2 rerun stopped after 4 runs — the root cause is different from what v2 assumed
- First v2 run on Trace B: 323 Mbit/s but ~1,400 post-switch retx per switch (v1 rep1 had ~200). Stopped the
  rerun (`TaskStop`); the 4 finished runs were moved to `results/v2_partial_superseded/`.
- **Logging bug found:** `kernel.log` was empty for 49 of the later runs (sweepB 6, timingB 12, timingon 17,
  q50000 11, v2 3). The kernel ring buffer was full (2,110 lines, constant), so "count dmesg lines at the start,
  `tail -n +N` at the end" returned nothing. Fixed in `run_one.sh`: `dmesg -C` at the start of each run
  (commit 650cf29). Throughput/RTT/retx of those runs are fine (they come from `sender_ss.log`/iperf); only the
  switch-decision lines are missing.
- **Trace B has no delay dips:** `delay_1.txt` one-way delay is 51–56 ms all the way through (min per 5 s
  window 51–54 ms; only slot 0 is 0 ms). So the true RTT is ≥ ~102 ms and a 62–67 ms RTT sample is physically
  impossible in this emulator (the delay queue applies the trace delay in both directions, FIFO, never shorter;
  `mm-delay 10` = 10 ms slot length, not a delay).
- Yet the kernel's own `tcp_min_rtt` (ss `minrtt:`) and LeoCC's `min_rtt_us` both reach 62–67 ms. In v1 rep2 the
  ss sample at t = 11.31 s shows `rtt:66.784/0.544` between samples of ~118 ms and coincides with a loss
  episode (retrans bytes jump, `lost:558` at 11.42 s). Working hypothesis: some RTT samples taken during loss
  recovery are wrong (e.g. timestamp-echo/ACK of retransmitted or undone segments), not a real path change.
- v2's stale refresh *does* fire (`stale=1`, base reset to ~109 ms) but the base drops back to 62–67 ms within
  seconds, so v2 alone doesn't fix it. Diagnostic runs `results/diag_minrtt/` (3 × Trace B, v2 + diag):
  297 / 315 / 275 Mbit/s (better than v1's 66–189 but below LeoCC ~350) with 470–1,070 post-switch retx.
- The diagnostic (`minrtt_drop` log line in `leocc_update_min_rtt`, only for drops > 10 %) logged **nothing**,
  although `min_rtt_us` went from ~109 to ~67 ms. The only writers of `min_rtt_us` are: the filter
  (`leocc_update_min_rtt`, line ~714), PROBE_RTT end (~740, `min_rtt = rs->rtt_us`), the graded reset (~916),
  and init (`tcp_min_rtt(tp)`). So either the drop is a series of < 10 % steps, or it happens via the PROBE_RTT
  end assignment (LeoCC's own 20 s expiry → PROBE_RTT; that assignment is unconditional and takes whatever the
  last sample was).

## Day 3 — 2026-11-09

### 42. Root cause of the impossible RTTs: the emulator's clock (most likely)
- New diagnostics in `leocc_g.c` (param `g_diag_rtt_us`, default 0 = off): logs every write of `min_rtt_us`
  below the threshold (with where: filter / filter-expired / probe_rtt_end / graded_reset) and every RTT sample
  below it, with the TCP state.
- WSL freshly booted. 22 LeoCC-G v2 runs on Trace B (`results/diag2`, `diag3`, `diag_cap`, `diag_corr`):
  **all 353–370 Mbit/s**, and only **one** low-RTT event (diag3 rep2, t = 99.26 s).
- That event: a burst of normal ACKs (`ca_state=0` Open, `is_retrans=0`, not delayed), all in the same 4 ms tick,
  with RTT falling smoothly 94 → 85 ms. Not loss recovery (the step-41 hypothesis was wrong). A burst of packets
  released at once with RTT below the path delay = the emulator released queued packets early.
- LeoReplayer times everything with `CLOCK_REALTIME` (`src/util/timestamp.cc`), and `systemd-timesyncd` is
  active in WSL (plus Hyper-V time sync). A forward correction of the wall clock releases every packet waiting in
  the delay queue early → RTT samples below the path delay → stale low `min_rtt`. A backward step holds them
  (possibly the 621 ms "base RTT" seen once).
- Fits the history: on Nov 7 (WSL up 7+ h; WSL's clock drift grows with uptime) v1 collapsed in 4/5 main runs and
  all 3 diag runs had a 62–67 ms base; today on a fresh boot 1 event in 22 runs. A 4-min + 17-min clock monitor
  (`clkmon.py`, realtime − monotonic every 50 ms) saw **no** step today, so the link is strongly suggested but not
  caught in the act.
- Also seen: LeoCC's min-RTT filter, when it expires, takes the *current* sample even if it is queue-inflated
  (diag2: base 621 ms just before a switch; the graded reset corrected it to 112 ms).
- **Fix (emulator):** `patches/fix_clock.py` — `raw_timestamp()` = CLOCK_MONOTONIC + a fixed epoch offset, taken
  once and passed to nested shells in `LEOREPLAYER_CLOCK_OFFSET_US`; same units as before, immune to clock
  steps; `LEOREPLAYER_REALTIME=1` restores the original. Full emulator diff:
  `patches/leoreplayer-delay-queue-and-clock.diff`. Installed to `/usr/local/bin`.
- Sanity on the fixed emulator (`results/sanity_clock`): Trace A BBRv3 356 / LeoCC 376 / LeoCC-G 376 Mbit/s;
  Trace B BBRv3 351 — same as before.
- `wire_rtt.py` (analysis/): wire-level RTT from a sender-side pcap (`run_one.sh -c`), for future checks.
- Remaining sanity runs: Trace B LeoCC 365 Mbit/s (108,670 retx), **LeoCC-G v2 362 Mbit/s (17,243 retx)**.

### 43. Decision: rerun the whole suite on the fixed emulator (tonight)
- User chose to rerun all 200 runs (~7 h) so every number comes from the same emulator; prefix `clk_q3300`
  (`run_all.sh`) + `run_extra.sh clk_q3300 3300` (50,000-packet batch → `clk_q50000_main`). Old `final_*`
  results stay as the "realtime-clock emulator" record.
- Laptop: AC sleep timeout is 3 h (`powercfg` STANDBYIDLE AC = 10800 s) → set to Never for the night
  (`powercfg /change standby-timeout-ac 0`), restore to 180 min afterwards. Lid open, plugged in.
- Launcher ready: `launch_clk.sh` (commits code + WORKLOG, checks emulator/module versions, then runs).

## Day 4 — 2026-11-10 (overnight, unattended)

### 44. clk_ suite started (commit ecfda67) — main suite finished, 95/95, 0 failures
- Started ~22:00 UTC (03:30 IST). Watchdog: a Monitor on the task output flags failures, non-CUBIC runs with
  util < 0.80, every 20 runs, and milestones; re-armed every 30 min. Clock monitor runs all night →
  `results/clock_steps_clk.log`.
- `ALL_DONE` 01:23 UTC; `run_extra.sh` continues automatically. Interim figures + table:
  `analysis/figures/clk_q3300/` (make_figures.py works on the full dataset; tested first on `final_q3300`).
- Main results (mean ± 95 % CI, 5 reps, 100 ms buffer):

  | Trace B | goodput Mbit/s | retx 2 s / switch | retx total | p95 RTT ms |
  |---|---|---|---|---|
  | CUBIC | 26 ± 4 | 0.5 | 28 | 123 |
  | BBRv3 | 343 ± 4 | 699 ± 202 | 27,813 | 238 |
  | LeoCC | 355 ± 2 | 1,763 ± 399 | 93,809 | 226 |
  | Freeze-only (B3) | 357 ± 3 | 212 ± 270 | 8,560 | 231 |
  | Hard replace (A1) | 353 ± 5 | 154 ± 142 | 9,157 | 230 |
  | **LeoCC-G (G1)** | **355 ± 7** | **86 ± 39** | **7,687** | **218** |

  Trace A: all non-CUBIC senders 348–366 Mbit/s, 6–7 retx per switch (the 100 ms buffer is ~4 BDP there),
  CUBIC 61 Mbit/s. LeoCC-G v2 on the fixed emulator: no collapse in any of the 5 Trace B reps.
- Note: "util 0–0.5 s" can exceed 1 (goodput right after a switch includes data drained from the queue).
  (Superseded by step 45: those numbers were computed with misaligned sample times.)

### 45. Batch stopped by Claude Code at 162/200 (Windows low on memory); clock steps caught all night
- 03:3x UTC: Claude Code killed the background task because Windows was critically low on memory while the
  session was idle (not a run failure; free RAM afterwards 3.6 / 15.7 GB, vmmemWSL 3.1 GB). Not restarted
  (Claude Code asks not to restart automatically). **Missing: 38 of the 50 runs of `clk_q50000_main`**
  (rep1 complete, rep2 partial; `rep2/A_downlink_3/leocc_g-g_mode_2` incomplete and will be redone).
  Resume = `scripts/run_extra.sh clk_q3300 3300` (skips finished runs; ~80 min).
- **The clock monitor caught the root cause in the act:** from 22:02 UTC (about when the laptop went idle) the
  WSL wall clock was stepped forward by **+0.7 to +2.4 s (typically +1.28 s) every ~33 s, all night**
  (`results/clock_steps_clk.log`, ~350 steps); in the afternoon (user active) there were none. So when the host is
  idle the VM's clock runs ~4 % slow and time sync steps it.
- **Confirms step 42:** the Nov 7 collapsed run (`final_q3300_main/rep2/C_downlink_1/leocc_g`) has 4 such steps
  (~0.84 s) in its sampler log; the first is at t = 10.41 s and the impossible 65 ms RTT appears at t = 11.31 s.
  A +0.84 s step makes the old wall-clock emulator release every queued packet at once (~55 ms early) →
  RTT 120 → 65 ms. Old-emulator runs are additionally wrong because the emulator's trace position jumped while
  TCP and the module's schedule (jiffies) did not.
- **New problem for the clk_ runs:** the emulator is now steady, but the ss sampler stamps samples with `date`
  (wall clock) → each step shifts all later samples by ~1.3 s (up to ~5 s per run). Totals were fine, but per-switch
  windows were misaligned and goodput was ~4 % low (run span looked longer).
- **Fix (analysis):** `leoan.parse_ss(..., remove_steps=True)` — a gap > 0.4 s in the ~56 ms sampling loop is a
  clock step; its excess is subtracted from all later samples. Applied when `meta.txt` has
  `emulator_clock=monotonic` (now written by `run_one.sh`; backfilled for `sanity_clock` and all `clk_*` runs).
  Summary gains `clock_steps`, `clock_steps_removed_s`, `emulator_clock`.
- **Validation** (`analysis/check_alignment.py`: offset of the deepest 200 ms delivery dip from each boundary):
  LeoCC-G run raw `[0.3, -0.95, 0.9, 2.1, 2.3, …]` → fixed `[0.3, -1.2, -0.15, 0.0, -0.05, 0.15, 0.1, -0.05]`;
  LeoCC's restart dip becomes a constant ~1 s after every switch; afternoon run (0 steps) unchanged.
- All 168 clk_/sanity summaries refreshed; figures + table regenerated: `analysis/figures/clk_q3300/`,
  `analysis/figures/clk_q50000/` (partial). make_figures table now labels sweepB thresholds.

### 46. Results (fixed emulator, LeoCC-G v2, step-corrected; mean ± 95 % CI, 5 reps, 100 ms buffer)
| Trace B (base RTT 112 ms) | goodput Mbit/s | retx in 2 s after a switch | retx total | recovery s |
|---|---|---|---|---|
| B1 CUBIC | 27 ± 5 | 0.5 | 28 | 1.58 |
| B2 BBRv3 | 356 ± 3 | 1,222 ± 530 | 27,813 | 2.44 |
| B3 Freeze-only | 370 ± 2 | 456 ± 291 | 8,560 | 1.97 |
| B4 LeoCC | 369 ± 1 | 10,992 ± 1,140 | 93,809 | 2.30 |
| A1 Hard replace | 366 ± 7 | 409 ± 208 | 9,157 | 2.06 |
| **G1 LeoCC-G** | **368 ± 6** | **298 ± 15** | **7,687** | **2.06** |

- Trace A (base RTT 22 ms, buffer ≈ 4 BDP): all non-CUBIC senders 360–378 Mbit/s and 6–7 retx per switch —
  the buffer absorbs switches, nothing to fix there.
- RQ2: LeoCC-G keeps LeoCC's throughput with **37× fewer post-switch retransmissions** (4× fewer than BBRv3).
  Figure 2: LeoCC's estimate crashes to ~200 Mbit/s at every switch (restart), LeoCC-G's stays on the capacity
  line; weakness: after a +12 % capacity step LeoCC-G "kept" and needed ~4 s to catch up.
- RQ3: graded (298 ± 15) < always-replace (409 ± 208) < always-keep (456 ± 291), with a much smaller spread.
  Threshold sweep (Trace B): 5/15 → 403, **10/30 → 298**, 20/40 → 381, 30/60 → 566 ± 699. Figure 5(b): on
  Trace A the measured Δ often overestimates the true change (measurement noise at 22 ms RTT) — report as a caveat.
- RQ4 (Trace B, correction off): −500 ms 262, −100 ms 295, 0 ms 298, **+100 ms 1,059, +500 ms 1,929** → early is
  harmless, late is costly (the guard misses the outage). Online correction on: +500 ms → **613** (most of the
  penalty removed), −500 ms → 374. Trace A: no effect (6–7 retx everywhere).
- Remaining: 38 runs of the 50,000-packet sensitivity check (needs the user's go-ahead); report + slides.

## Day 5 — 2026-11-11

### 47. Finishing the 50,000-packet runs; report and slides drafted
- User OK'd finishing the 38 missing `clk_q50000_main` runs: `scratchpad/resume_q50.sh` (chown the root-owned
  folders, free any module held by orphan sockets, clock monitor on, `scripts/run_extra.sh clk_q3300 3300` —
  skips everything already done). Started 07:54 UTC; ~2 min per run.
- LeoCC-G decisions in the main runs (40 switches per trace, from kernel.log):
  Trace A keep 5 / blend 25 / replace 10 (true mix ≈ 15/15/10 → measurement overestimates Δ at 22 ms RTT);
  Trace B keep 16 / blend 21 / replace 3 (true ≈ 20/15/5). Stale base-RTT refresh fired 18 (A) / 19 (B) times.
- Timing evidence (observed boundary vs prediction, main runs): Trace A median −3 ms (p10 −10, p90 +11);
  Trace B median +17 ms (p10 −309, p90 +131) — some queue-drain ACK gaps on the 112 ms path pass the 30 ms test.
  Correction-on runs converge by halving: Trace A −500 → +488…491, +500 → −497…−504 after 7 switches;
  Trace B settles at −540 (true −500).
- One Trace B run shows the graded reset repairing LeoCC's own filter: base RTT 494 ms (queue-inflated sample
  taken at min-RTT expiry) → measured 112 ms, ΔRTT 77 % → replace.
- Note for the write-up: the spec's headline metric is the **1 s** window: LeoCC-G 295 vs LeoCC 3,843 (13×);
  the 2 s window gives 37× (298 vs 10,992). Both are reported; slides lead with 13×.
- **Report** drafted as a Claude Doc ("LeoCC-G: Graded Reset for LEO Congestion Control — Report"), 11 sections,
  design-flow diagram; figures and the large-buffer section added once the runs finish.
- **Slides** (14, Slides artifact), split for 3 presenters: P1 cover/problem/RQ1/design, P2 setup/emulator
  fixes/headline/post-switch table/estimates, P3 RQ3/RQ4/buffer/limitations/takeaways. Speaker notes per slide.
  Names are placeholders. Exportable to .pptx/PDF; must be shared from its Share menu.

### 48. Large-buffer runs finished; report and slides complete
- `resume_q50.sh` finished 09:12 UTC: `clk_q50000_main` 50/50, 0 RUN_FAILED (all 200 runs of the suite now on
  the fixed emulator). Figures + table: `python3 analysis/make_figures.py clk_q50000 --refresh` →
  `analysis/figures/clk_q50000/` (no Figure 5, no sweep in this experiment).
- Trace B, 50,000-packet queue (≈13 BDP), mean ± 95% CI, 5 runs:

  | Sender | Goodput | p95 RTT ms | Retx 1 s/switch | Retx 2 s/switch | Recovery s |
  |---|---|---|---|---|---|
  | CUBIC | 27.5 ± 5.7 | 123 | 0.3 | 0.5 | 1.98 |
  | BBRv3 | 360.6 ± 2.7 | 353 ± 31 | 11.5 ± 16.3 | 14.6 | 1.64 |
  | Freeze-only | 369.8 ± 1.9 | 263 ± 10 | 2.6 | 6.0 | 1.59 |
  | LeoCC | 371.0 ± 1.1 | 337 ± 4 | 6.4 ± 10.9 | 9.4 | 2.07 |
  | LeoCC-G | 365.1 ± 8.4 | 262 ± 9 | 2.8 ± 1.1 | 5.2 | 1.93 |

  Trace A (≈65 BDP): all non-CUBIC 359–378 Mbit/s, 2.5–3.5 retx/switch; p95 RTT LeoCC-G 49, LeoCC 54, BBRv3 55.
- Reading: a deep buffer hides the loss gap (STARTUP's overshoot fits in the queue) but turns it into delay —
  LeoCC-G's p95 RTT is 75 ms below LeoCC's. LeoCC-G goodput is 1.6 % lower (two runs at 354–357; not
  investigated).
- Report: large-buffer subsection written (end of Section 8), Figures 1–6 uploaded and placed (Fig 1 in RQ1,
  Figs 2–4 in RQ2, Fig 5 A/B in RQ3, Fig 6 A/B in RQ4) plus Figure 7 = Figure 3 with the large buffer.
- Slides: "buffer" slide filled (2.8 vs 6.4 retx, 262 vs 337 ms p95) with Presenter 3 notes.

### 49. References verified; beginner explainer PDF
- All 17 references checked (paper PDFs, DBLP/ACM/IEEE records, OpenAlex, IETF Datatracker) and rewritten in
  the report with full authors, venues and DOIs. Corrections: StarQUIC's full title ("...Congestion Control
  Algorithms for QUIC over LEO Satellite Networks", Kamel/Zhao/Li/Pan); IFIP 2026 Sussex paper authors Mazilu,
  Valentine, Wakeman, Parisis; SatPipe authors Zhao, Zhang, Lee; draft-lai-ccwg-lsncc-01 = "Analysis for the
  Adverse Effects of LEO Mobility on Internet Congestion Control" (informational, Feb 2026, expired); BBRv3
  draft = draft-ietf-ccwg-bbr-06 (Jul 2026); LeoReplayer has no own paper (LeoCC repo, extends Mahimahi, ATC 2015);
  LeoEM is from the SaTCP paper.
- The spec's claim (LeoCC has the highest retransmission rate, caused by STARTUP at every reconfiguration) was
  confirmed verbatim in the Sussex paper.
- `LeoCC-G explained from the basics.pdf` (13 pages, project folder): networking basics, the problem, the idea,
  every tool, results in plain words, what is new vs existing, limitations, glossary, likely examiner questions.
  Generator: scratchpad `explainer/make_explainer.py` (reportlab).

### Where to continue (next session)
1. Fill presenter names on the deck cover and the report byline.
2. Optional: reproduce from a fresh clone (spec Day 13).
- If a run is killed mid-way, an orphaned FIN-WAIT-1 socket keeps `leocc_g` loaded ("insmod: File exists");
  this kernel has no `ss -K`. Fix: `sysctl net.ipv4.tcp_orphan_retries=1`, wait ~1 min, `rmmod leocc_g`, set it
  back to 0.


## Day 6 — 2026-11-17: review before publishing

### 50. Independent check of the results and write-up
- Re-aggregated all 200 `summary.json` files: every mean ± 95 % CI in `analysis/figures/clk_*/summary_table.md`,
  the report and the slides reproduces exactly.
- Cross-checked against iperf3's own report: goodput agrees within ~1 %. iperf3's retransmission count is higher
  because `retx_total` starts after the 2 s warm-up (LeoCC-family STARTUP loss happens there); now stated in README.
- Permutation tests (`analysis/significance.py clk_q3300`, Trace B, retx 1 s after a switch, 5 vs 5 runs):
  G1 vs LeoCC / BBRv3 / freeze-only p = 0.008 (smallest possible); vs hard replace **p = 0.21**; vs 20/40 p = 0.024,
  5/15 p = 0.056, 30/60 p = 0.44; −500 ms correction off vs on p = 0.095; +500 ms off vs on p = 0.008.
- Corrections made to the write-up: "grading beats always-replace" → lower mean and much smaller spread, not
  significant at n = 5; "10/30 best" → lowest mean of the four pairs; correction recovers ~77 % (not two-thirds) of the
  +500 ms penalty; the −500 ms correction cost (259 → 371) is within noise; "retx total" labelled as after warm-up.
- Repo cleanup: removed `analysis/figures/final_q3300/` (realtime-clock emulator, superseded), the stale
  `analysis/out/cache_final_q3300.pkl` and `scripts/run_v2.sh` (v2 is the default); `resume_suite.sh` now resumes
  `clk_q3300`. Added a credits section for LeoCC / LeoReplayer.
