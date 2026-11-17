#!/usr/bin/env python3
"""Find the first periodic (15 s) reconfiguration time in a LeoReplayer delay trace.

Same method as LeoCC/traces/extract_reconfiguration.py (the LeoCC authors' script),
refactored to work on one file and to report how well the 15 s period fits.

delay_N.txt: line i = one-way delay (ms) during the i-th 10 ms interval.

Usage: find_offset.py DELAY_FILE [DELAY_FILE ...]
Prints: file  offset_ms  hits/possible   (hits = later 15 s boundaries that also
        land on a top-100 delay spike, within +-100 ms)
"""
import sys

SLOT_MS = 10
PERIOD_SLOTS = 1500          # 15 s / 10 ms
TOL_SLOTS = 10               # +-100 ms
TOP_N = 100


def read_delays(path):
    vals = []
    with open(path) as f:
        for i, line in enumerate(f):
            try:
                vals.append((int(line.strip()), i))
            except ValueError:
                continue
    return vals


def find_offset(path):
    delays = read_delays(path)
    n_slots = len(delays)
    first15 = sorted(delays[:PERIOD_SLOTS], key=lambda x: x[0], reverse=True)[:TOP_N]
    spikes = {pos for _, pos in sorted(delays, key=lambda x: x[0], reverse=True)[:TOP_N]}

    hits = []
    for _, pos in first15:
        h, i = 0, pos
        while i + PERIOD_SLOTS < n_slots:
            i += PERIOD_SLOTS
            if any(i + j in spikes for j in range(-TOL_SLOTS, TOL_SLOTS + 1)):
                h += 1
        hits.append(h)

    best = max(hits)
    cands = [k for k, h in enumerate(hits) if h == best]
    top_delay = max(first15[k][0] for k in cands)
    cands = [k for k in cands if first15[k][0] == top_delay]
    k = cands[0] if len(cands) == 1 else round(sum(cands) / len(cands))
    pos = first15[k][1]
    possible = (n_slots - 1 - pos) // PERIOD_SLOTS
    return pos * SLOT_MS, best, possible


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in sys.argv[1:]:
        off, h, n = find_offset(p)
        print(f"{p}\t{off}\t{h}/{n}")
