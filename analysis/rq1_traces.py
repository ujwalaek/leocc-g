#!/usr/bin/env python3
"""RQ1 (diagnosis): how much do bandwidth and RTT change across reconfigurations, and how
often would a full reset be needed?

Reads traces straight from the LeoCC trace archive (no full extraction), samples N traces
per set (evenly spaced trace numbers, deterministic), finds each trace's 15 s schedule with
the same method as find_offset.py, and computes per-boundary relative changes of the
epoch capacity and base RTT (leoan.Trace.changes: 0.5 s after each boundary skipped,
capacity = mean delivery rate, base RTT = 2 x median one-way delay).

Only traces whose schedule is clearly periodic (>= 75 % of later boundaries on delay
spikes) are used; the rest are counted and reported.

Usage: rq1_traces.py ZIP OUT_CSV [N_PER_SET]
"""
import csv
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from leoan import Trace, offset_from_delays  # noqa: E402

zpath, out = sys.argv[1], sys.argv[2]
n_per_set = int(sys.argv[3]) if len(sys.argv) > 3 else 100
sets = [f"Anonymous_{s}_{d}" for d in ("downlink", "uplink") for s in "ABCD"]
z = zipfile.ZipFile(zpath)
names = set(z.namelist())

rows, skipped = [], {}
for s in sets:
    picks = sorted({1 + round(i * 600 / n_per_set) for i in range(n_per_set)} & set(range(1, 601)))
    used = 0
    for n in picks:
        bw_n, d_n = f"{s}/{n}/bw_{n}.txt", f"{s}/{n}/delay_{n}.txt"
        if bw_n not in names or d_n not in names:
            continue
        delay = [int(x) for x in z.read(d_n).split()]
        off, hits, possible = offset_from_delays(delay)
        if possible == 0 or hits / possible < 0.75:
            skipped[s] = skipped.get(s, 0) + 1
            continue
        slots = [int(x) for x in z.read(bw_n).split()]
        tr = Trace(slots=slots, delay=delay, offset_ms=off)
        for c in tr.changes():
            rows.append({"set": s, "trace": n, "boundary_s": round(c["boundary_s"], 2),
                         "d_bw": round(c["d_bw"], 4), "d_rtt": round(c["d_rtt"], 4),
                         "delta": round(c["delta"], 4)})
        used += 1
    print(f"{s}: used {used} traces, skipped {skipped.get(s, 0)} non-periodic", flush=True)

os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

# summary: share of boundaries in keep / blend / replace bands (10 % / 30 %)
print("\nset                     boundaries  keep(<10%)  blend(10-30%)  replace(>30%)  median dBW  median dRTT")
for s in sets:
    r = [x for x in rows if x["set"] == s]
    if not r:
        continue
    k = sum(x["delta"] < 0.10 for x in r) / len(r)
    rp = sum(x["delta"] > 0.30 for x in r) / len(r)
    mbw = sorted(x["d_bw"] for x in r)[len(r) // 2]
    mrt = sorted(x["d_rtt"] for x in r)[len(r) // 2]
    print(f"{s:24s} {len(r):10d}  {100*k:9.0f}%  {100*(1-k-rp):12.0f}%  {100*rp:12.0f}%  {100*mbw:9.1f}%  {100*mrt:10.1f}%")
