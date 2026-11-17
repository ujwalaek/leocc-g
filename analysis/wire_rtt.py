#!/usr/bin/env python3
"""Wire-level RTT from a sender-side capture (run_one.sh -c), to check TCP's own RTT samples.

For each ACK that advances the cumulative ack to exactly the end of a data segment that was sent
once (never retransmitted), RTT = ack capture time - segment capture time. These are the times the
segment entered and the ACK left the emulator, so this RTT is what the emulated path really did.

Usage: wire_rtt.py RUN_DIR [T_FROM T_TO]   (times in s relative to trace start)
Prints min wire RTT per second, and every sample in [T_FROM, T_TO].
"""
import struct, sys, os, collections

def packets(path):
    with open(path, 'rb') as f:
        gh = f.read(24)
        magic = struct.unpack('<I', gh[:4])[0]
        en = '<' if magic in (0xa1b2c3d4, 0xa1b23c4d) else '>'
        nano = magic in (0xa1b23c4d, 0x4d3cb2a1)
        linktype = struct.unpack(en + 'I', gh[20:24])[0]
        while True:
            h = f.read(16)
            if len(h) < 16:
                return
            ts, tf, incl, _ = struct.unpack(en + 'IIII', h)
            data = f.read(incl)
            t = ts + tf / (1e9 if nano else 1e6)
            off = 14 if linktype == 1 else (16 if linktype == 113 else 0)
            ip = data[off:]
            if len(ip) < 20 or ip[0] >> 4 != 4 or ip[9] != 6:
                continue
            ihl = (ip[0] & 15) * 4
            tot = struct.unpack('>H', ip[2:4])[0]
            src, dst = ip[12:16], ip[16:20]
            tcp = ip[ihl:]
            if len(tcp) < 16:
                continue
            sport, dport, seq, ack = struct.unpack('>HHII', tcp[:12])
            doff = (tcp[12] >> 4) * 4
            flags = tcp[13]
            plen = tot - ihl - doff
            yield t, src, dst, sport, dport, seq, ack, flags, plen

def main():
    d = sys.argv[1]
    t_from = float(sys.argv[2]) if len(sys.argv) > 2 else None
    t_to = float(sys.argv[3]) if len(sys.argv) > 3 else None
    t0 = [int(l.split('=')[1]) / 1000 for l in open(os.path.join(d, 'times.txt'))
          if l.startswith('trace_start_ms=')][0]
    sent = {}            # end_seq -> first send time
    retx = set()         # end_seqs sent more than once
    # data flow = the direction carrying the most payload, found on the fly by port 5201 as source
    last_ack = None
    per_sec = collections.defaultdict(lambda: 1e9)
    window = []
    n_data = n_ack = 0
    for t, src, dst, sp, dp, seq, ack, fl, plen in packets(os.path.join(d, 'sender.pcap')):
        if sp == 5201 and plen > 0:
            n_data += 1
            end = (seq + plen) & 0xffffffff
            if end in sent:
                retx.add(end)
            else:
                sent[end] = t
        elif dp == 5201 and (fl & 0x10):
            n_ack += 1
            if last_ack is not None and ((ack - last_ack) & 0xffffffff) == 0:
                continue
            last_ack = ack
            ts = sent.get(ack)
            if ts is None or ack in retx:
                continue
            rtt = (t - ts) * 1000
            rel = t - t0
            per_sec[int(rel)] = min(per_sec[int(rel)], rtt)
            if t_from is not None and t_from <= rel <= t_to:
                window.append((rel, rtt))
    print('data packets %d, acks %d, retransmitted segments %d' % (n_data, n_ack, len(retx)))
    print('min wire RTT per second (ms):')
    secs = sorted(per_sec)
    for i in range(0, len(secs), 10):
        print('  ' + ' '.join('%3d:%5.1f' % (s, per_sec[s]) for s in secs[i:i + 10]))
    if window:
        print('samples in window:')
        for rel, rtt in window[:80]:
            print('  t=%.4f rtt=%.2f ms' % (rel, rtt))

if __name__ == '__main__':
    main()
