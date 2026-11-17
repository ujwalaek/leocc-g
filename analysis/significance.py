#!/usr/bin/env python3
"""Exact two-sided permutation tests on the per-run summaries (5 runs per configuration).

Compares LeoCC-G (G1, main comparison) with every other configuration on one trace, for one
metric of summary.json. With 5 vs 5 runs there are C(10,5) = 252 relabellings, so the smallest
possible p-value is 2/252 = 0.008.

Usage: significance.py PREFIX [--trace C_downlink_1] [--metric post_switch_retx_mean]
  e.g. significance.py clk_q3300
"""
import argparse
import glob
import itertools
import json
import os
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "..", "results")


def values(prefix, exp, trace, sender, metric):
    pat = os.path.join(RESULTS, f"{prefix}_{exp}", "rep*", trace, sender, "rep1", "summary.json")
    return [json.load(open(f))[metric] for f in sorted(glob.glob(pat))]


def perm_test(a, b):
    pooled = a + b
    obs = abs(st.mean(a) - st.mean(b))
    hits = total = 0
    for idx in itertools.combinations(range(len(pooled)), len(a)):
        x = [pooled[i] for i in idx]
        y = [pooled[i] for i in range(len(pooled)) if i not in idx]
        total += 1
        hits += abs(st.mean(x) - st.mean(y)) >= obs - 1e-9
    return hits / total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("--trace", default="C_downlink_1")
    ap.add_argument("--metric", default="post_switch_retx_mean")
    args = ap.parse_args()

    g1 = values(args.prefix, "main", args.trace, "leocc_g", args.metric)
    if not g1:
        raise SystemExit(f"no G1 runs for {args.prefix} / {args.trace}")
    others = [("main", s) for s in ("cubic", "bbr", "leocc", "leocc_g-g_mode_2")]
    others += [("ablation", "leocc_g-g_mode_1")]
    for exp in ("sweepB", "sweep", "timingB", "timing", "timingon"):
        for d in sorted(glob.glob(os.path.join(RESULTS, f"{args.prefix}_{exp}", "rep1", args.trace, "*"))):
            others.append((exp, os.path.basename(d)))

    print(f"{args.metric}, {args.trace}: G1 mean {st.mean(g1):.1f} (n={len(g1)})")
    for exp, sender in others:
        v = values(args.prefix, exp, args.trace, sender, args.metric)
        if len(v) < 2:
            continue
        print(f"  {exp:9s} {sender:42s} mean {st.mean(v):9.1f} (n={len(v)})  p = {perm_test(g1, v):.3f}")


if __name__ == "__main__":
    main()
