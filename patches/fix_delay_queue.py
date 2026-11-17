#!/usr/bin/env python3
"""Patch LeoReplayer's DelayQueue so packets with equal release times keep arrival order.

Bug: DelayQueue stores packets in a std::priority_queue keyed only on the release time
in whole milliseconds. std::priority_queue is not stable, so the ~33 packets that arrive
in the same millisecond at 400 Mbit/s leave in arbitrary heap order -> constant packet
reordering (ss: reord_seen ~500k per 120 s run, ~85% of BBRv3 retransmissions spurious
per DSACK).

Fix: add a monotonically increasing sequence number as a tie-breaker. Packets are still
released at arrival + delay(arrival slot), so reordering caused by the trace's delay
decreasing between 10 ms slots (the intended time-varying-delay behaviour) is unchanged.

Second change (FIFO path): even with stable ties, the trace's one-way delay changes every
10 ms, and each 1 ms decrease lets the next packets overtake the ~33 packets sent in the
previous millisecond (still ~540 reordering events/s, ~77% of BBRv3 retransmissions
spurious). By default a packet now never leaves before the packet ahead of it
(release = max(arrival + delay, previous release)), as on a single FIFO path and as in
upstream Mahimahi's constant-delay queue. Set LEOREPLAYER_ALLOW_REORDER=1 in the
environment to get the original (reordering) behaviour.

Usage: fix_delay_queue.py <replayer>/src/frontend   (idempotent)
"""
import os
import sys


def sub(text, old, new):
    assert text.count(old) == 1, f"pattern not found exactly once: {old!r}"
    return text.replace(old, new)


def fifo_patch(hh_p, cc_p):
    hh, cc = open(hh_p).read(), open(cc_p).read()
    if "last_release_" in hh:
        print("already patched (FIFO)")
        return
    hh = sub(hh, "    uint64_t seq_ = 0;",
             "    uint64_t last_release_ = 0;  /* FIFO: no packet leaves before the one ahead */\n"
             "    bool allow_reorder_ = false; /* LEOREPLAYER_ALLOW_REORDER=1 restores original */\n"
             "    uint64_t seq_ = 0;")
    cc = sub(cc, "    base_timestamp_ = std::stoull(getenv(\"BASE_TIMESTAMP\"));\n",
             "    base_timestamp_ = std::stoull(getenv(\"BASE_TIMESTAMP\"));\n"
             "    const char *ar = getenv(\"LEOREPLAYER_ALLOW_REORDER\");\n"
             "    allow_reorder_ = ar && ar[0] == '1';\n")
    cc = sub(cc, "    packet_queue_.emplace( now + delays_ms_[delay_idx], seq_++, contents );",
             "    uint64_t release = now + delays_ms_[delay_idx];\n"
             "    if ( !allow_reorder_ && release < last_release_ ) {\n"
             "        release = last_release_;\n"
             "    }\n"
             "    last_release_ = release;\n"
             "    packet_queue_.emplace( release, seq_++, contents );")
    open(hh_p, "w").write(hh)
    open(cc_p, "w").write(cc)
    print("patched (FIFO)", hh_p, cc_p)


d = sys.argv[1]
hh_p, cc_p = os.path.join(d, "delay_queue.hh"), os.path.join(d, "delay_queue.cc")
hh, cc = open(hh_p).read(), open(cc_p).read()
if "seq_" in hh:
    print("already patched (stable order)")
    fifo_patch(hh_p, cc_p)
    sys.exit(0)


# header: element = (release_ms, seq, contents)
hh = sub(hh, "#include <fstream>\n", "#include <fstream>\n#include <tuple>\n")
hh = sub(hh, "bool operator()(std::pair<uint64_t, std::string> &a, std::pair<uint64_t, std::string> &b);",
         "bool operator()(const std::tuple<uint64_t, uint64_t, std::string> &a,\n"
         "                        const std::tuple<uint64_t, uint64_t, std::string> &b) const;")
hh = sub(hh, "        std::pair<uint64_t, std::string>,\n        std::vector<std::pair<uint64_t, std::string>>,",
         "        std::tuple<uint64_t, uint64_t, std::string>,\n"
         "        std::vector<std::tuple<uint64_t, uint64_t, std::string>>,")
hh = sub(hh, "    std::vector<uint64_t> delays_ms_;\n",
         "    std::vector<uint64_t> delays_ms_;\n    uint64_t seq_ = 0;  /* tie-breaker: keeps FIFO order for equal release times */\n")

cc = sub(cc, "bool DelayQueue::cmp::operator()(pair<uint64_t, string> &a, pair<uint64_t, string> &b) {\n    return a.first > b.first;\n}",
         "bool DelayQueue::cmp::operator()(const tuple<uint64_t, uint64_t, string> &a,\n"
         "                                 const tuple<uint64_t, uint64_t, string> &b) const {\n"
         "    if (get<0>(a) != get<0>(b)) return get<0>(a) > get<0>(b);\n"
         "    return get<1>(a) > get<1>(b);\n}")
cc = sub(cc, "packet_queue_.emplace( now + delays_ms_[delay_idx], contents );",
         "packet_queue_.emplace( now + delays_ms_[delay_idx], seq_++, contents );")
cc = sub(cc, "&& (packet_queue_.top().first <= raw_timestamp()) ) {\n        fd.write( packet_queue_.top().second );",
         "&& (get<0>(packet_queue_.top()) <= raw_timestamp()) ) {\n        fd.write( get<2>(packet_queue_.top()) );")
cc = sub(cc, "    if ( packet_queue_.top().first <= now ) {\n        return 0;\n    } else {\n        return packet_queue_.top().first - now;",
         "    if ( get<0>(packet_queue_.top()) <= now ) {\n        return 0;\n    } else {\n        return get<0>(packet_queue_.top()) - now;")
open(hh_p, "w").write(hh)
open(cc_p, "w").write(cc)
print("patched (stable order)", hh_p, cc_p)
fifo_patch(hh_p, cc_p)
