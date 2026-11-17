#!/usr/bin/env python3
"""LeoCC-G analysis library + CLI.

Trace ground truth
  bw_N.txt    one line per 1500-byte delivery opportunity at that ms (12 Mbit/s per line per ms)
  delay_N.txt one-way delay (ms) per 10 ms slot; applied in both directions, so base RTT = 2 x delay
  Boundaries  offset + 15 s * k  (offset from find_offset.py), in trace time (0 = emulator shell start)
  Epoch k     [boundary_k, boundary_k+1): true capacity = mean delivery rate, true base RTT = 2 x median delay

Run logs (from scripts/run_one.sh)
  times.txt      shell_start (trace time 0)
  sender_ss.log  "t=<epoch>" lines followed by `ss -tin` output for the sender socket(s)

Metrics per run (spec "Metrics and figures")
  goodput, utilization, p50/p95 RTT (smoothed RTT from ss), post-switch retransmissions in the first
  1 s after each boundary, recovery time (until goodput is back to 90 % of the pre-switch level),
  bandwidth/RTT estimate error vs. the true per-epoch values (only for senders that report estimates).

CLI
  leoan.py run RUN_DIR [--offset MS]           print summary JSON, write RUN_DIR/summary.json, boundaries.csv
  leoan.py epochs TRACE_DIR [--offset MS]      per-epoch true capacity / RTT and change across boundaries
"""
import bisect
import collections
import csv
import glob
import json
import math
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import find_offset as _fo  # noqa: E402

PERIOD_S = 15.0
PKT_BITS = 1500 * 8


def offset_from_delays(delay_list):
    """find_offset.find_offset() on an in-memory delay list (same method)."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(str(x) for x in delay_list))
        name = f.name
    try:
        return _fo.find_offset(name)
    finally:
        os.unlink(name)


# ----------------------------------------------------------------------------- trace
class Trace:
    def __init__(self, trace_dir=None, offset_ms=None, slots=None, delay=None):
        """Load from a trace directory, or from already-parsed lists (slots, delay)."""
        self.dir = trace_dir
        if trace_dir is not None:
            self.bw_file = sorted(glob.glob(os.path.join(trace_dir, "bw_*.txt")))[0]
            self.delay_file = sorted(glob.glob(os.path.join(trace_dir, "delay_*.txt")))[0]
            slots = [int(x) for x in open(self.bw_file) if x.strip()]          # ms timestamps
            delay = [int(x) for x in open(self.delay_file) if x.strip()]       # ms per 10 ms
        self.slots, self.delay = list(slots), list(delay)
        self.duration_s = min(self.slots[-1] / 1000.0, len(self.delay) / 100.0)
        if offset_ms is None:
            offset_ms = offset_from_delays(self.delay)[0]
        self.offset_s = offset_ms / 1000.0
        self.boundaries = []
        b = self.offset_s
        while b < self.duration_s:
            self.boundaries.append(b)
            b += PERIOD_S

    def capacity_mbps(self, t0, t1):
        """Mean deliverable rate in [t0, t1) seconds of trace time."""
        lo = bisect.bisect_left(self.slots, t0 * 1000)
        hi = bisect.bisect_left(self.slots, t1 * 1000)
        return (hi - lo) * PKT_BITS / max(t1 - t0, 1e-9) / 1e6

    def base_rtt_ms(self, t0, t1):
        seg = self.delay[int(t0 * 100):max(int(t1 * 100), int(t0 * 100) + 1)]
        return 2.0 * st.median(seg) if seg else float("nan")

    def epochs(self, guard_s=0.5):
        """True per-epoch values. guard_s is skipped after each boundary (handover transient)."""
        edges = [0.0] + self.boundaries + [self.duration_s]
        out = []
        for i in range(len(edges) - 1):
            a, b = edges[i], edges[i + 1]
            a2 = a + guard_s if i > 0 else a
            if b - a2 < 1.0:
                continue
            out.append({"start": a, "end": b,
                        "cap_mbps": self.capacity_mbps(a2, b),
                        "rtt_ms": self.base_rtt_ms(a2, b)})
        return out

    def epoch_at(self, t, epochs):
        for e in epochs:
            if e["start"] <= t < e["end"]:
                return e
        return None

    def changes(self, epochs=None):
        """Relative change of capacity and base RTT across each boundary (RQ1)."""
        epochs = epochs or self.epochs()
        out = []
        for prev, cur in zip(epochs, epochs[1:]):
            if abs(cur["start"] - prev["end"]) > 1e-6:
                continue
            d_bw = abs(cur["cap_mbps"] - prev["cap_mbps"]) / prev["cap_mbps"]
            d_rtt = abs(cur["rtt_ms"] - prev["rtt_ms"]) / prev["rtt_ms"]
            out.append({"boundary_s": cur["start"], "d_bw": d_bw, "d_rtt": d_rtt,
                        "delta": max(d_bw, d_rtt)})
        return out


# ----------------------------------------------------------------------------- run logs
SS_FIELDS = {
    "rtt": re.compile(r"\brtt:([\d.]+)/"),
    "bytes_acked": re.compile(r"\bbytes_acked:(\d+)"),
    "retrans_total": re.compile(r"\bretrans:\d+/(\d+)"),
    "cwnd": re.compile(r"\bcwnd:(\d+)"),
    "bbr": re.compile(r"bbr:\(bw:([\d.]+)([KMG]?)bps,mrtt:([\d.]+)(?:,pacing_gain:([\d.]+))?(?:,cwnd_gain:([\d.]+))?"),
}
UNIT = {"": 1, "K": 1e3, "M": 1e6, "G": 1e9}


def read_kv(path):
    d = {}
    if os.path.exists(path):
        for line in open(path):
            if "=" in line:
                k, v = line.rstrip("\n").split("=", 1)
                d[k] = v
    return d


STEP_GAP_S = 0.4       # sampler loop period is ~0.056 s; a gap above this is a wall-clock step
SAMPLE_DT_S = 0.056


def parse_ss(path, t0, remove_steps=False, info=None):
    """Return samples (dicts) of the data-carrying socket, time relative to t0 (trace time).

    The sampler stamps samples with the wall clock (`date`). With the steady-clock emulator
    (WORKLOG step 45) the wall clock can step forward relative to the emulator (WSL time sync:
    ~+1.3 s every ~33 s when the host is idle); with remove_steps=True each such step (a gap
    > STEP_GAP_S between consecutive samples of a ~56 ms loop) is subtracted from all later samples,
    putting them back on the emulator's timeline."""
    per_conn = collections.defaultdict(list)
    t = None
    conn = None
    prev_raw = None
    removed = 0.0
    steps = 0
    for line in open(path):
        if line.startswith("t="):
            raw = float(line[2:].split()[0])
            if remove_steps and prev_raw is not None and raw - prev_raw > STEP_GAP_S:
                removed += raw - prev_raw - SAMPLE_DT_S
                steps += 1
            prev_raw = raw
            t = raw - removed - t0
            continue
        if not line.startswith((" ", "\t")):
            parts = line.split()
            conn = " ".join(parts[3:5]) if len(parts) >= 5 else None
            continue
        if conn is None or t is None:
            continue
        s = {"t": t}
        for k, rx in SS_FIELDS.items():
            m = rx.search(line)
            if not m:
                continue
            if k == "bbr":
                s["est_bw_mbps"] = float(m.group(1)) * UNIT[m.group(2)] / 1e6
                s["est_rtt_ms"] = float(m.group(3))
                if m.group(4):
                    s["pacing_gain"] = float(m.group(4))
                if m.group(5):
                    s["cwnd_gain"] = float(m.group(5))
            else:
                s[k] = float(m.group(1))
        per_conn[conn].append(s)
    if info is not None:
        info["clock_steps"] = steps
        info["clock_steps_removed_s"] = round(removed, 3)
    if not per_conn:
        return []
    # data connection = the one that acked the most bytes
    best = max(per_conn.values(), key=lambda v: max((x.get("bytes_acked", 0) for x in v), default=0))
    return [x for x in best if "bytes_acked" in x]


def series_rate(samples, key, t0, t1):
    """Average rate of a cumulative counter between t0 and t1 (per second)."""
    ts = [s["t"] for s in samples]
    i0 = max(bisect.bisect_left(ts, t0) - 1, 0)
    i1 = min(bisect.bisect_left(ts, t1), len(samples) - 1)
    if i1 <= i0:
        return float("nan")
    a, b = samples[i0], samples[i1]
    return (b.get(key, 0) - a.get(key, 0)) / max(b["t"] - a["t"], 1e-9)


def counter_delta(samples, key, t0, t1):
    ts = [s["t"] for s in samples]
    i0 = max(bisect.bisect_left(ts, t0) - 1, 0)
    i1 = min(bisect.bisect_right(ts, t1), len(samples) - 1)
    return samples[i1].get(key, 0) - samples[i0].get(key, 0)


def pct(vals, p):
    vals = sorted(v for v in vals if not math.isnan(v))
    if not vals:
        return float("nan")
    k = (len(vals) - 1) * p / 100.0
    f = math.floor(k)
    c = min(f + 1, len(vals) - 1)
    return vals[f] + (vals[c] - vals[f]) * (k - f)


KLOG_SWITCH = re.compile(r"leocc_g: switch t=(\d+) g_mode=(\d+) (.*)")


def parse_kernel_log(path):
    """LeoCC-G decisions: list of dicts (t_s, g_mode, and every key=value of the switch line)."""
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path):
        m = KLOG_SWITCH.search(line)
        if not m:
            continue
        d = {"t_s": int(m.group(1)) / 1000.0, "g_mode": int(m.group(2))}
        for k, v in re.findall(r"(\w+)=(-?\d+)", m.group(3)):
            d[k] = int(v)
        if "alpha" in d:
            d["alpha"] = d["alpha"] / 256.0
        elif "keep" in m.group(3):
            d["alpha"] = 0.0
        out.append(d)
    return out


def analyze_run(run_dir, offset_ms=None, warmup_s=2.0, post_window_s=1.0,
                pre_window=(3.0, 0.5), recovery_frac=0.9, recovery_cap_s=5.0):
    meta = read_kv(os.path.join(run_dir, "meta.txt"))
    times = read_kv(os.path.join(run_dir, "times.txt"))
    trace = Trace(meta["trace"], offset_ms)
    # trace time 0: BASE_TIMESTAMP of the emulator if recorded (accurate), else inner-shell start
    t0 = float(times["trace_start_ms"]) / 1000.0 if "trace_start_ms" in times else float(times["shell_start"])
    # steady-clock emulator (patches/fix_clock.py): take wall-clock steps out of the sampler times.
    # With the old wall-clock emulator the emulator itself jumped with the wall clock, so no correction.
    clock_info = {}
    S = parse_ss(os.path.join(run_dir, "sender_ss.log"), t0,
                 remove_steps=meta.get("emulator_clock") == "monotonic", info=clock_info)
    if len(S) < 10:
        raise RuntimeError(f"too few ss samples in {run_dir}")
    t_start, t_end = S[0]["t"] + warmup_s, S[-1]["t"]
    epochs = trace.epochs()

    goodput = series_rate(S, "bytes_acked", t_start, t_end) * 8 / 1e6
    cap = trace.capacity_mbps(t_start, min(t_end, trace.duration_s))
    rtts = [s["rtt"] for s in S if "rtt" in s and t_start <= s["t"] <= t_end]

    rows = []
    for b in trace.boundaries:
        if b - pre_window[0] < t_start or b + recovery_cap_s > t_end:
            continue
        pre = series_rate(S, "bytes_acked", b - pre_window[0], b - pre_window[1]) * 8 / 1e6
        retx = counter_delta(S, "retrans_total", b, b + post_window_s)
        retx2 = counter_delta(S, "retrans_total", b, b + 2.0)
        retx_base = counter_delta(S, "retrans_total", b - pre_window[0], b - pre_window[1]) \
            * post_window_s / (pre_window[0] - pre_window[1])
        # recovery: first time t >= b from which the 200 ms goodput stays >= 90 % of the
        # pre-switch goodput for the next 0.5 s (0 if it never drops)
        thr = recovery_frac * pre
        steps = [b + i * 0.05 for i in range(int((recovery_cap_s + 0.5) / 0.05) + 1)]
        ok = [series_rate(S, "bytes_acked", t, t + 0.2) * 8 / 1e6 >= thr for t in steps]
        rec = recovery_cap_s
        for i in range(len(steps)):
            if steps[i] - b > recovery_cap_s:
                break
            if all(ok[i:i + 11]):
                rec = steps[i] - b
                break
        min_gp = min(series_rate(S, "bytes_acked", x / 20.0, x / 20.0 + 0.2) * 8 / 1e6
                     for x in range(int(b * 20), int((b + 2.0) * 20)))
        gp_05 = series_rate(S, "bytes_acked", b, b + 0.5) * 8 / 1e6
        cap_05 = trace.capacity_mbps(b, b + 0.5)
        rows.append({"boundary_s": round(b, 3), "pre_goodput_mbps": pre, "retx_1s": retx,
                     "retx_2s": retx2, "retx_1s_baseline": retx_base, "recovery_s": rec,
                     "min_goodput_2s_mbps": min_gp, "goodput_0_05_mbps": gp_05,
                     "util_0_05": gp_05 / cap_05 if cap_05 > 0 else float("nan")})

    est = {}
    est_samples = [s for s in S if "est_bw_mbps" in s and t_start <= s["t"] <= t_end]
    if est_samples:
        e_bw, e_rtt = [], []
        for s in est_samples:
            ep = trace.epoch_at(s["t"], epochs)
            if not ep:
                continue
            e_bw.append(abs(s["est_bw_mbps"] - ep["cap_mbps"]) / ep["cap_mbps"])
            e_rtt.append(abs(s["est_rtt_ms"] - ep["rtt_ms"]) / ep["rtt_ms"])
        est = {"bw_err_mean": st.mean(e_bw), "bw_err_p95": pct(e_bw, 95),
               "rtt_err_mean": st.mean(e_rtt), "rtt_err_p95": pct(e_rtt, 95)}

    summary = {
        "run": run_dir, "alg": meta.get("alg"), "trace": meta.get("trace"),
        "module_params": meta.get("module_params", ""),
        "offset_s": trace.offset_s, "n_boundaries": len(rows),
        "emulator_clock": meta.get("emulator_clock", "realtime"), **clock_info,
        "goodput_mbps": goodput, "capacity_mbps": cap, "utilization": goodput / cap,
        "rtt_p50_ms": pct(rtts, 50), "rtt_p95_ms": pct(rtts, 95),
        "retx_total": counter_delta(S, "retrans_total", t_start, t_end),
        "post_switch_retx_mean": st.mean(r["retx_1s"] for r in rows) if rows else float("nan"),
        "post_switch_retx2_mean": st.mean(r["retx_2s"] for r in rows) if rows else float("nan"),
        "post_switch_util_05": st.mean(r["util_0_05"] for r in rows) if rows else float("nan"),
        "post_switch_excess_retx_mean": st.mean(r["retx_1s"] - r["retx_1s_baseline"] for r in rows) if rows else float("nan"),
        "recovery_s_mean": st.mean(r["recovery_s"] for r in rows) if rows else float("nan"),
        **est,
    }
    return summary, rows, S


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, target = sys.argv[1], sys.argv[2]
    off = None
    if "--offset" in sys.argv:
        off = int(sys.argv[sys.argv.index("--offset") + 1])
    if cmd == "run":
        summary, rows, _ = analyze_run(target, off)
        json.dump(summary, open(os.path.join(target, "summary.json"), "w"), indent=1)
        with open(os.path.join(target, "boundaries.csv"), "w", newline="") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        print(json.dumps(summary, indent=1))
        for r in rows:
            print("  " + "  ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k, v in r.items()))
    elif cmd == "epochs":
        tr = Trace(target, off)
        print(f"offset={tr.offset_s:.2f}s duration={tr.duration_s:.1f}s boundaries={tr.boundaries}")
        for e in tr.epochs():
            print(f"  epoch {e['start']:6.2f}-{e['end']:6.2f}s cap={e['cap_mbps']:6.1f}Mbps rtt={e['rtt_ms']:5.1f}ms")
        for c in tr.changes():
            print(f"  boundary {c['boundary_s']:6.2f}s dBW={100*c['d_bw']:5.1f}% dRTT={100*c['d_rtt']:5.1f}% delta={100*c['delta']:5.1f}%")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
