#!/usr/bin/env python3
"""Figures 1-6 of the report + summary tables.

Usage: make_figures.py PREFIX [--rq1 analysis/out/rq1_changes.csv] [--out analysis/figures]
  PREFIX  results prefix, e.g. clk_q3300 -> results/clk_q3300_{main,ablation,sweep,timing,...}

Every run is re-analysed with leoan.analyze_run (cached in analysis/out/cache_PREFIX.pkl).
Means with 95 % confidence intervals (Student t) over repetitions.
"""
import argparse
import csv
import glob
import math
import os
import pickle
import re
import statistics as st
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from scipy import stats  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from leoan import analyze_run, parse_kernel_log, read_kv, Trace, parse_ss  # noqa: E402

RES = os.path.join(HERE, "..", "results")

# ---------------------------------------------------------------- style (reference palette, light)
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SENDERS = [  # id, label, color (fixed per entity, categorical slots in order)
    ("G1", "LeoCC-G", "#2a78d6"),
    ("B4", "LeoCC", "#eb6834"),
    ("B2", "BBRv3", "#1baf7a"),
    ("B3", "Freeze-only", "#eda100"),
    ("B1", "CUBIC", "#e87ba4"),
    ("A1", "Hard replace", "#008300"),
]
COLOR = {s[0]: s[2] for s in SENDERS}
NAME = {s[0]: s[1] for s in SENDERS}
ORDER_MAIN = ["B1", "B2", "B3", "B4", "G1"]
TRACE_NAME = {"A_downlink_3": "Trace A (base RTT 22 ms)", "C_downlink_1": "Trace B (base RTT 112 ms)"}
SEQ = ["#86b6ef", "#3987e5", "#256abf", "#104281"]  # ordinal blue ramp (step 250..650)

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "legend.frameon": False, "lines.linewidth": 2,
})


def label_to_sender(label):
    if label == "cubic":
        return "B1"
    if label == "bbr":
        return "B2"
    if label == "leocc":
        return "B4"
    if label == "leocc_g":
        return "G1"
    if label == "leocc_g-g_mode_2":
        return "B3"
    if label == "leocc_g-g_mode_1":
        return "A1"
    return "G1"  # sweep / timing variants of LeoCC-G


def variant(label):
    """thresholds 'k/r', timing shift (ms) and correction flag for LeoCC-G variants."""
    k = re.search(r"g_keep_pct_(\d+)", label)
    r = re.search(r"g_replace_pct_(\d+)", label)
    sh = re.search(r"shift_(-?\d+)", label)
    pc = re.search(r"g_phase_correct_(\d)", label)
    return {"thr": f"{k.group(1)}/{r.group(1)}" if k and r else "10/30",
            "shift": int(sh.group(1)) if sh else 0,
            "correct": int(pc.group(1)) if pc else 1}


def collect(prefix, refresh=False):
    cache = os.path.join(HERE, "out", f"cache_{prefix}.pkl")
    runs = {}
    if os.path.exists(cache) and not refresh:
        runs = pickle.load(open(cache, "rb"))
    dirs = sorted(glob.glob(os.path.join(RES, f"{prefix}_*", "rep*", "*", "*", "rep1")))
    for d in dirs:
        # kernel.log is written by run_one.sh after the run has finished
        if d in runs or not os.path.exists(os.path.join(d, "kernel.log")):
            continue
        parts = d.split(os.sep)
        exp = parts[-5][len(prefix) + 1:]
        try:
            summ, rows, S = analyze_run(d)
        except Exception as e:  # incomplete / failed run
            print("skip", d, e)
            continue
        runs[d] = {"exp": exp, "rep": parts[-4], "trace": parts[-3], "label": parts[-2],
                   "sender": label_to_sender(parts[-2]), **variant(parts[-2]),
                   "summary": summ, "rows": rows,
                   "decisions": parse_kernel_log(os.path.join(d, "kernel.log"))}
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    pickle.dump(runs, open(cache, "wb"))
    return list(runs.values())


def ci(vals):
    vals = [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not vals:
        return float("nan"), 0.0, 0
    m = st.mean(vals)
    if len(vals) < 2:
        return m, 0.0, len(vals)
    h = stats.t.ppf(0.975, len(vals) - 1) * st.stdev(vals) / math.sqrt(len(vals))
    return m, h, len(vals)


def bars(ax, groups, values, errs, colors, fmt="{:.0f}", ylabel=""):
    xs = range(len(groups))
    ax.bar(xs, values, width=0.62, color=colors, edgecolor=SURFACE, linewidth=2,
           yerr=errs, error_kw={"ecolor": INK2, "elinewidth": 1, "capsize": 3})
    ax.set_xticks(list(xs), groups)
    ax.set_ylabel(ylabel)
    ax.grid(axis="x", visible=False)
    top = max((v + e for v, e in zip(values, errs) if not math.isnan(v)), default=1)
    for x, v, e in zip(xs, values, errs):
        if not math.isnan(v):
            ax.text(x, v + e + top * 0.02, fmt.format(v), ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_ylim(0, top * 1.15 if top > 0 else 1)


def save(fig, out, name):
    os.makedirs(out, exist_ok=True)
    # leave room for the figure title above the panel titles
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(out, f"{name}.{ext}"), dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("wrote", os.path.join(out, name + ".png"))


# ---------------------------------------------------------------- Figure 1 (RQ1)
def fig1(rq1_csv, out):
    if not rq1_csv or not os.path.exists(rq1_csv):
        print("fig1: no RQ1 data")
        return
    rows = list(csv.DictReader(open(rq1_csv)))
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.2))
    for i, metric, title in ((0, "d_bw", "Bandwidth change at a switch"), (1, "d_rtt", "Base-RTT change at a switch")):
        ax = axes[i]
        for j, s in enumerate("ABCD"):
            v = sorted(100 * float(r[metric]) for r in rows if r["set"] == f"Anonymous_{s}_downlink")
            if not v:
                continue
            ax.plot(v, [(k + 1) / len(v) for k in range(len(v))], color=SEQ[j], label=f"Set {s} (downlink)")
        for x, txt in ((10, "keep | blend"), (30, "blend | replace")):
            ax.axvline(x, color=INK2, lw=1, ls="--")
            ax.text(x + 1, 0.04, txt, color=INK2, fontsize=7, rotation=90, va="bottom")
        ax.set_xlim(0, 80)
        ax.set_ylim(0, 1)
        ax.set_xlabel("relative change (%)")
        ax.set_ylabel("fraction of switches")
        ax.set_title(title, loc="left")
    axes[0].legend(loc="lower right", fontsize=7)
    # (c) share of switches per band, every set
    ax = axes[2]
    sets = [f"Anonymous_{s}_{d}" for d in ("downlink", "uplink") for s in "ABCD"]
    labels, keep, blend, repl = [], [], [], []
    for s in sets:
        r = [float(x["delta"]) for x in rows if x["set"] == s]
        if not r:
            continue
        labels.append(s.replace("Anonymous_", "").replace("_downlink", " dn").replace("_uplink", " up"))
        keep.append(100 * sum(v < 0.10 for v in r) / len(r))
        repl.append(100 * sum(v > 0.30 for v in r) / len(r))
        blend.append(100 - keep[-1] - repl[-1])
    xs = range(len(labels))
    b1 = ax.bar(xs, keep, color=SEQ[0], edgecolor=SURFACE, linewidth=1.5, label="keep (Δ<10%)")
    b2 = ax.bar(xs, blend, bottom=keep, color=SEQ[1], edgecolor=SURFACE, linewidth=1.5, label="blend (10–30%)")
    ax.bar(xs, repl, bottom=[a + b for a, b in zip(keep, blend)], color=SEQ[3], edgecolor=SURFACE,
           linewidth=1.5, label="replace (Δ>30%)")
    for x, k, r in zip(xs, keep, repl):
        ax.text(x, k / 2, f"{k:.0f}", ha="center", va="center", fontsize=7, color=INK)
        ax.text(x, 100 - r / 2, f"{r:.0f}", ha="center", va="center", fontsize=7, color="white")
    ax.set_xticks(list(xs), labels, rotation=45, ha="right")
    ax.set_ylim(0, 100)
    ax.set_ylabel("% of switches")
    ax.set_title("Reset needed? (Δ = max of the two)", loc="left")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.32), ncol=3, fontsize=7)
    fig.suptitle("Figure 1 — How much the path changes at Starlink reconfigurations (RQ1)", x=0.01, ha="left",
                 fontsize=11, fontweight="bold")
    save(fig, out, "fig1_rq1_path_change")


# ---------------------------------------------------------------- Figure 2 (estimates vs truth)
def fig2(runs, out, trace="C_downlink_1", t_range=(33, 80)):
    pick = {}
    for r in runs:
        if r["exp"] == "main" and r["trace"] == trace and r["rep"] == "rep1" and r["sender"] in ("B2", "B3", "B4", "G1"):
            pick[r["sender"]] = r
    if not pick:
        print("fig2: no data")
        return
    order = [s for s in ("B2", "B3", "B4", "G1") if s in pick]
    fig, axes = plt.subplots(len(order), 1, figsize=(9, 1.9 * len(order)), sharex=True, sharey=True)
    axes = axes if len(order) > 1 else [axes]
    tr = Trace(read_kv(os.path.join(pick[order[0]]["summary"]["run"], "meta.txt"))["trace"])
    ep = tr.epochs(guard_s=0.0)
    for ax, s in zip(axes, order):
        d = pick[s]["summary"]["run"]
        times = read_kv(os.path.join(d, "times.txt"))
        t0 = float(times["trace_start_ms"]) / 1000
        S = parse_ss(os.path.join(d, "sender_ss.log"), t0)
        xs = [p["t"] for p in S if "est_bw_mbps" in p and t_range[0] <= p["t"] <= t_range[1]]
        ys = [p["est_bw_mbps"] for p in S if "est_bw_mbps" in p and t_range[0] <= p["t"] <= t_range[1]]
        for e in ep:
            a, b = max(e["start"], t_range[0]), min(e["end"], t_range[1])
            if a < b:
                ax.plot([a, b], [e["cap_mbps"]] * 2, color=INK2, lw=2, solid_capstyle="butt")
        for b in tr.boundaries:
            if t_range[0] <= b <= t_range[1]:
                ax.axvline(b, color=GRID, lw=1, ls="--", zorder=0)
        ax.plot(xs, ys, color=COLOR[s], lw=1.2)
        ax.text(0.005, 0.92, f"{s} {NAME[s]}", transform=ax.transAxes, fontsize=9, fontweight="bold",
                color=INK, va="top")
        ax.set_ylabel("Mbit/s")
        ax.set_ylim(0, 650)
    axes[0].plot([], [], color=INK2, lw=2, label="true epoch capacity (trace)")
    axes[0].plot([], [], color=INK2, lw=1.2, alpha=0.6, label="sender's bandwidth estimate")
    axes[0].legend(loc="upper right", fontsize=7, ncol=2)
    axes[-1].set_xlabel("trace time (s); dashed = predicted switch")
    fig.suptitle(f"Figure 2 — Bandwidth estimate vs. true path capacity across switches, "
                 f"{TRACE_NAME.get(trace, trace)} (RQ2)", x=0.01, ha="left", fontsize=11, fontweight="bold")
    save(fig, out, "fig2_estimates")


def per_sender(runs, exp, trace, metric, senders):
    vals, errs = [], []
    for s in senders:
        m, h, _ = ci([r["summary"][metric] for r in runs if r["exp"] == exp and r["trace"] == trace and r["sender"] == s])
        vals.append(m)
        errs.append(h)
    return vals, errs


# ---------------------------------------------------------------- Figure 3 (goodput, RTT)
def fig3(runs, out):
    traces = [t for t in TRACE_NAME if any(r["trace"] == t for r in runs)]
    if not traces:
        return
    fig, axes = plt.subplots(2, len(traces), figsize=(5 * len(traces), 5.6), squeeze=False)
    for j, t in enumerate(traces):
        g, ge = per_sender(runs, "main", t, "goodput_mbps", ORDER_MAIN)
        bars(axes[0][j], [NAME[s] for s in ORDER_MAIN], g, ge, [COLOR[s] for s in ORDER_MAIN],
             ylabel="goodput (Mbit/s)")
        axes[0][j].set_title(TRACE_NAME[t], loc="left")
        p, pe = per_sender(runs, "main", t, "rtt_p95_ms", ORDER_MAIN)
        bars(axes[1][j], [NAME[s] for s in ORDER_MAIN], p, pe, [COLOR[s] for s in ORDER_MAIN],
             ylabel="p95 RTT (ms)")
    fig.suptitle("Figure 3 — Goodput and p95 RTT per sender (mean, 95% CI, 5 runs) (RQ2)", x=0.01,
                 ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    save(fig, out, "fig3_goodput_rtt")


# ---------------------------------------------------------------- Figure 4 (post-switch loss, recovery)
def fig4(runs, out):
    traces = [t for t in TRACE_NAME if any(r["trace"] == t for r in runs)]
    if not traces:
        return
    fig, axes = plt.subplots(3, len(traces), figsize=(5 * len(traces), 8), squeeze=False)
    for j, t in enumerate(traces):
        for i, (metric, lab, fmt) in enumerate((
                ("post_switch_retx2_mean", "retransmissions in 2 s\nafter a switch", "{:.0f}"),
                ("post_switch_util_05", "goodput / capacity\n0–0.5 s after a switch", "{:.2f}"),
                ("recovery_s_mean", "recovery time (s)", "{:.2f}"))):
            v, e = per_sender(runs, "main", t, metric, ORDER_MAIN)
            bars(axes[i][j], [NAME[s] for s in ORDER_MAIN], v, e, [COLOR[s] for s in ORDER_MAIN], fmt=fmt, ylabel=lab)
        axes[0][j].set_title(TRACE_NAME[t], loc="left")
    fig.suptitle("Figure 4 — What happens right after a switch: loss, throughput dip, recovery (RQ2)", x=0.01,
                 ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    save(fig, out, "fig4_post_switch")


# ---------------------------------------------------------------- Figure 5 (RQ3)
def fig5(runs, out, sweep_trace="A_downlink_3"):
    traces = [t for t in TRACE_NAME if any(r["trace"] == t for r in runs)]
    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    # (a) keep vs graded vs replace: post-switch retransmissions per trace
    trio = ["B3", "G1", "A1"]
    ax = axes[0][0]
    w = 0.26
    for k, s in enumerate(trio):
        vals, errs = [], []
        for t in traces:
            exp = "ablation" if s == "A1" else "main"
            m, h, _ = ci([r["summary"]["post_switch_retx2_mean"] for r in runs
                          if r["exp"] == exp and r["trace"] == t and r["sender"] == s])
            vals.append(m)
            errs.append(h)
        xs = [i + (k - 1) * w for i in range(len(traces))]
        ax.bar(xs, vals, width=w, color=COLOR[s], edgecolor=SURFACE, linewidth=1.5, yerr=errs,
               error_kw={"ecolor": INK2, "elinewidth": 1, "capsize": 2}, label=f"{NAME[s]}")
        for x, v in zip(xs, vals):
            if not math.isnan(v):
                ax.text(x, v, f"{v:.0f}", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(range(len(traces)), [TRACE_NAME[t].split(" (")[0] for t in traces])
    ax.set_ylabel("retransmissions in 2 s after a switch")
    ax.set_title("(a) Always keep vs graded vs always replace", loc="left")
    ax.legend(fontsize=7)
    ax.grid(axis="x", visible=False)
    # (b) measured vs true change at each switch (LeoCC-G decisions)
    ax = axes[0][1]
    pts = []
    for r in runs:
        if r["exp"] != "main" or r["sender"] != "G1" or not r["decisions"]:
            continue
        tr_dir = r["summary"]["trace"]
        truth = {round(c["boundary_s"], 1): c["delta"] for c in Trace(tr_dir).changes()}
        for dcs in r["decisions"]:
            tb = min(truth, key=lambda b: abs(b - dcs["t_s"])) if truth else None
            if tb is not None and abs(tb - dcs["t_s"]) < 2 and "delta" in dcs:
                pts.append((100 * truth[tb], dcs["delta"], dcs["alpha"], r["trace"]))
    for t, mk in zip(traces, ("o", "s")):
        p = [x for x in pts if x[3] == t]
        ax.scatter([x[0] for x in p], [x[1] for x in p], s=22, marker=mk, c=[x[2] for x in p], cmap="Blues",
                   vmin=-0.3, vmax=1, edgecolors=INK2, linewidths=0.4, label=TRACE_NAME[t].split(" (")[0])
    lim = max([60] + [x[0] for x in pts] + [min(x[1], 150) for x in pts])
    ax.plot([0, lim], [0, lim], color=INK2, lw=1, ls=":")
    for v in (10, 30):
        ax.axhline(v, color=GRID, lw=1, ls="--")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, min(lim, 150))
    ax.set_xlabel("true path change Δ from the trace (%)")
    ax.set_ylabel("Δ measured by LeoCC-G (%)")
    ax.set_title("(b) LeoCC-G's measurement (darker = more replaced)", loc="left")
    ax.legend(fontsize=7, loc="upper left")
    # (c) threshold sweep: decision mix
    thr_order = ["5/15", "10/30", "20/40", "30/60"]

    def sweep_runs(thr):
        if thr == "10/30":
            return [r for r in runs if r["exp"] == "main" and r["trace"] == sweep_trace and r["sender"] == "G1"]
        return [r for r in runs if r["exp"].startswith("sweep") and r["trace"] == sweep_trace and r["thr"] == thr]

    ax = axes[1][0]
    present = [t for t in thr_order if sweep_runs(t)]
    keep, blend, repl = [], [], []
    for thr in present:
        a = [d["alpha"] for r in sweep_runs(thr) for d in r["decisions"] if "alpha" in d]
        n = max(len(a), 1)
        keep.append(100 * sum(x == 0 for x in a) / n)
        repl.append(100 * sum(x >= 0.999 for x in a) / n)
        blend.append(100 - keep[-1] - repl[-1])
    xs = range(len(present))
    ax.bar(xs, keep, color=SEQ[0], edgecolor=SURFACE, linewidth=1.5, label="keep")
    ax.bar(xs, blend, bottom=keep, color=SEQ[1], edgecolor=SURFACE, linewidth=1.5, label="blend")
    ax.bar(xs, repl, bottom=[a + b for a, b in zip(keep, blend)], color=SEQ[3], edgecolor=SURFACE, linewidth=1.5,
           label="replace")
    ax.set_xticks(list(xs), [f"{t} %" for t in present])
    ax.set_xlabel("keep / replace thresholds")
    ax.set_ylabel("% of switches")
    ax.set_ylim(0, 100)
    ax.set_title(f"(c) Decisions vs thresholds ({TRACE_NAME.get(sweep_trace, sweep_trace).split(' (')[0]})", loc="left")
    ax.legend(fontsize=7, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.18))
    ax.grid(axis="x", visible=False)
    # (d) threshold sweep: post-switch throughput dip
    ax = axes[1][1]
    vals, errs = [], []
    for thr in present:
        m, h, _ = ci([r["summary"]["post_switch_retx2_mean"] for r in sweep_runs(thr)])
        vals.append(m)
        errs.append(h)
    bars(ax, [f"{t} %" for t in present], vals, errs, [COLOR["G1"]] * len(present), fmt="{:.0f}",
         ylabel="retransmissions in 2 s after a switch")
    ax.set_xlabel("keep / replace thresholds")
    ax.set_title("(d) Sensitivity to the thresholds", loc="left")
    fig.suptitle("Figure 5 — Does grading help, and how sensitive is it? (RQ3)", x=0.01, ha="left",
                 fontsize=11, fontweight="bold")
    fig.tight_layout()
    save(fig, out, f"fig5_rq3_grading_{sweep_trace}")


# ---------------------------------------------------------------- Figure 6 (RQ4)
def fig6(runs, out, trace="A_downlink_3", metric="post_switch_retx2_mean", tag=""):
    def mean_of(sel):
        return ci([r["summary"][metric] for r in sel])

    bbr = mean_of([r for r in runs if r["exp"] == "main" and r["trace"] == trace and r["sender"] == "B2"])
    if math.isnan(bbr[0]):
        print("fig6: no BBRv3 reference")
        return
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    for corr, ls, lab in ((0, "-", "online correction off"), (1, "--", "online correction on")):
        xs, ys, es = [], [], []
        for sh in (-500, -100, 0, 100, 500):
            if sh == 0 and corr == 1:
                sel = [r for r in runs if r["exp"] == "main" and r["trace"] == trace and r["sender"] == "G1"]
            else:
                sel = [r for r in runs if r["exp"].startswith("timing") and r["trace"] == trace
                       and r["shift"] == sh and r["correct"] == corr]
            m, h, n = mean_of(sel)
            if n:
                xs.append(sh)
                ys.append(m)
                es.append(h)
        if xs:
            ax.errorbar(xs, ys, yerr=es, color=COLOR["G1"], ls=ls, marker="o", ms=6, capsize=3, label=f"LeoCC-G, {lab}")
    ax.axhline(bbr[0], color=COLOR["B2"], lw=2, label="BBRv3")
    leo = mean_of([r for r in runs if r["exp"] == "main" and r["trace"] == trace and r["sender"] == "B4"])
    if not math.isnan(leo[0]):
        ax.axhline(leo[0], color=COLOR["B4"], lw=2, label="LeoCC (exact schedule)")
    ax.set_xlabel("error in the predicted switch time (ms)")
    ax.set_ylabel("retransmissions in 2 s\nafter a switch")
    ax.set_xticks([-500, -100, 0, 100, 500])
    ax.legend(fontsize=7)
    fig.suptitle(f"Figure 6 — Tolerance to switch-timing error, {TRACE_NAME.get(trace, trace)} (RQ4)", x=0.01,
                 ha="left", fontsize=11, fontweight="bold")
    save(fig, out, f"fig6_rq4_timing{tag}")


# ---------------------------------------------------------------- summary table
def table(runs, out):
    keys = [("goodput_mbps", "goodput Mbit/s", "{:.1f}"), ("utilization", "util", "{:.3f}"),
            ("rtt_p50_ms", "p50 RTT ms", "{:.1f}"), ("rtt_p95_ms", "p95 RTT ms", "{:.1f}"),
            ("retx_total", "retx total", "{:.0f}"), ("post_switch_retx_mean", "retx 1s/switch", "{:.1f}"),
            ("post_switch_retx2_mean", "retx 2s/switch", "{:.1f}"), ("post_switch_util_05", "util 0-0.5s", "{:.3f}"),
            ("recovery_s_mean", "recovery s", "{:.2f}"), ("bw_err_mean", "bw est err", "{:.3f}"),
            ("rtt_err_mean", "RTT est err", "{:.3f}")]
    groups = {}
    for r in runs:
        name = NAME[r["sender"]]
        if r["exp"].startswith("sweep"):
            name += f" {r['thr']}"
        if r["exp"].startswith("timing"):
            name += f" shift {r['shift']:+d} corr {r['correct']}"
        groups.setdefault((r["exp"], r["trace"], name), []).append(r)
    lines = ["| exp | trace | sender | n | " + " | ".join(k[1] for k in keys) + " |",
             "|" + "---|" * (4 + len(keys))]
    for (exp, t, name), rs in sorted(groups.items()):
        cells = []
        for k, _, fmt in keys:
            m, h, n = ci([r["summary"].get(k, float("nan")) for r in rs])
            cells.append("–" if math.isnan(m) else f"{fmt.format(m)} ± {fmt.format(h)}")
        lines.append(f"| {exp} | {t} | {name} | {len(rs)} | " + " | ".join(cells) + " |")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "summary_table.md"), "w").write("\n".join(lines) + "\n")
    print("wrote", os.path.join(out, "summary_table.md"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("--rq1", default=os.path.join(HERE, "out", "rq1_changes.csv"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    out = a.out or os.path.join(HERE, "figures", a.prefix)
    runs = collect(a.prefix, a.refresh)
    print(f"{len(runs)} runs")
    fig1(a.rq1, out)
    fig2(runs, out)
    fig3(runs, out)
    fig4(runs, out)
    for t in TRACE_NAME:
        if any(r["exp"].startswith("sweep") and r["trace"] == t for r in runs):
            fig5(runs, out, sweep_trace=t)
        fig6(runs, out, trace=t, tag="_" + t)
    table(runs, out)
