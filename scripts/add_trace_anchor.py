#!/usr/bin/env python3
"""Anchor a LeoCC-family module's 15 s schedule to the trace start (t0_ms parameter).

LeoCC's simulation version measures time from init_stamp = when the congestion-control
state of the flow is initialised, and assumes that is trace time 0. With iperf3 -R the
sender socket is created ~210 ms after the emulator starts the trace, so every predicted
boundary is ~210 ms late (measured: init - shell_start = 207 / 219 ms).

New parameter t0_ms (wall-clock epoch ms of trace start, 0 = original behaviour). The run
harness writes it via /sys/module/<mod>/parameters/t0_ms when the emulator shell starts;
at init the module back-dates init_stamp by (now - t0_ms). Alignment only: the congestion
control algorithm is unchanged.

Usage: add_trace_anchor.py path/to/module.c   (idempotent)
"""
import sys

path = sys.argv[1]
src = open(path).read()
if "t0_ms" in src:
    print("already anchored:", path)
    sys.exit(0)

PARAM = """static u32 init_stamp = 0;

/* Alignment (LeoCC-G project): wall-clock ms of trace start; 0 = schedule starts at init. */
static unsigned long long t0_ms = 0;
module_param(t0_ms, ullong, 0644);
MODULE_PARM_DESC(t0_ms, "epoch ms of trace start (schedule anchor); 0 = flow init");

static u32 leocc_schedule_start(void)
{
	u64 now_ms = div_u64(ktime_get_real_ns(), NSEC_PER_MSEC);

	if (!t0_ms || now_ms <= t0_ms || now_ms - t0_ms > 60000)
		return tcp_jiffies32;
	pr_info("%s: schedule anchored to trace start, init at +%llu ms\\n",
		KBUILD_MODNAME, now_ms - t0_ms);
	return tcp_jiffies32 - msecs_to_jiffies((u32)(now_ms - t0_ms));
}
"""
old_decl = "static u32 init_stamp = 0;\n"
assert src.count(old_decl) == 1, "init_stamp declaration not found exactly once"
src = src.replace(old_decl, PARAM)
old_init = "\tinit_stamp = tcp_jiffies32;\n"
assert src.count(old_init) == 1, "init_stamp assignment not found exactly once"
src = src.replace(old_init, "\tinit_stamp = leocc_schedule_start();\n")
open(path, "w").write(src)
print("anchored:", path)
