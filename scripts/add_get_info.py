#!/usr/bin/env python3
"""Add a read-only get_info() hook to a LeoCC-family module source file.

It reports, through the standard INET_DIAG_BBRINFO attribute (so `ss -ti` prints
it as "bbr:(bw:...,mrtt:...,pacing_gain:...,cwnd_gain:...)"):
  bw          the bandwidth estimate the sender is actually using: the max-filter
              value, or the Kalman estimate bw_hat_post when LeoCC switched to it
  mrtt        min_rtt_us
  pacing_gain / cwnd_gain   (these identify the mode: STARTUP 2.89/2.89,
              DRAIN <1/2.89, cruise ~1/2, PROBE_RTT 1/1)
  bbr_mode    raw mode number (read by tools that decode the full struct)
Instrumentation only: no congestion-control state is modified.

Usage: add_get_info.py path/to/leocc.c   (idempotent)
"""
import sys

FUNC = r'''
/* Instrumentation (LeoCC-G project): expose estimates via ss -ti. Read-only. */
static size_t leocc_get_info(struct sock *sk, u32 ext, int *attr,
			     union tcp_cc_info *info)
{
	if (ext & (1 << (INET_DIAG_BBRINFO - 1)) ||
	    ext & (1 << (INET_DIAG_VEGASINFO - 1))) {
		struct tcp_sock *tp = tcp_sk(sk);
		struct leocc *leocc = inet_csk_ca(sk);
		u32 bw_pkts = leocc->use_max_filter ? leocc_bw(sk) : leocc->bw_hat_post;
		u64 bw = (u64)bw_pkts * tp->mss_cache * USEC_PER_SEC >> BW_SCALE;
		struct tcp_bbr_info *bbr_info = &info->bbr;

		memset(bbr_info, 0, sizeof(*bbr_info));
		bbr_info->bbr_bw_lo		= (u32)bw;
		bbr_info->bbr_bw_hi		= (u32)(bw >> 32);
		bbr_info->bbr_min_rtt		= leocc->min_rtt_us;
		bbr_info->bbr_pacing_gain	= leocc->pacing_gain;
		bbr_info->bbr_cwnd_gain		= leocc->cwnd_gain;
		bbr_info->bbr_mode		= leocc->mode;
		*attr = INET_DIAG_BBRINFO;
		return sizeof(*bbr_info);
	}
	return 0;
}
'''

path = sys.argv[1]
src = open(path).read()
if "leocc_get_info" in src:
    print("already instrumented:", path)
    sys.exit(0)
anchor = "static struct tcp_congestion_ops leocc"
assert src.count(anchor) == 1, "ops struct anchor not found exactly once"
src = src.replace(anchor, FUNC.lstrip("\n") + "\n" + anchor)
ops_line = "\t.set_state\t= leocc_set_state,\n"
assert src.count(ops_line) == 1, ".set_state line not found exactly once"
src = src.replace(ops_line, ops_line + "\t.get_info\t= leocc_get_info,\n")
open(path, "w").write(src)
print("instrumented:", path)
