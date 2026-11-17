#!/usr/bin/env python3
"""Check that sender samples line up with the trace's switch boundaries.

For every boundary b, find the 200 ms window in [b-1.5, b+3] s with the lowest delivery rate
(the switch outage) and print its offset from b, with and without removing wall-clock steps.
Aligned data puts the dip within a few hundred ms of b at every boundary.
Usage: check_alignment.py RUN_DIR...
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leoan

def dips(S, bounds):
    out = []
    for b in bounds:
        best = None
        for i in range(-30, 60):
            t = b + i * 0.05
            r = leoan.series_rate(S, "bytes_acked", t, t + 0.2)
            if best is None or r < best[0]:
                best = (r, t - b)
        out.append(round(best[1], 2))
    return out

for d in sys.argv[1:]:
    meta = leoan.read_kv(os.path.join(d, "meta.txt"))
    times = leoan.read_kv(os.path.join(d, "times.txt"))
    t0 = float(times["trace_start_ms"]) / 1000.0
    tr = leoan.Trace(meta["trace"])
    info = {}
    raw = leoan.parse_ss(os.path.join(d, "sender_ss.log"), t0)
    fix = leoan.parse_ss(os.path.join(d, "sender_ss.log"), t0, remove_steps=True, info=info)
    bounds = [b for b in tr.boundaries if 3 < b < raw[-1]["t"] - 4]
    print(d.split("results/")[-1], "steps=%d removed=%.2fs" % (info["clock_steps"], info["clock_steps_removed_s"]))
    print("   dip offset vs boundary, raw  :", dips(raw, bounds))
    print("   dip offset vs boundary, fixed:", dips(fix, bounds))
