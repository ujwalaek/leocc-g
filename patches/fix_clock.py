#!/usr/bin/env python3
"""LeoReplayer: time packets with CLOCK_MONOTONIC instead of CLOCK_REALTIME (WORKLOG step 42).

raw_timestamp() used CLOCK_REALTIME. When the VM's wall clock is corrected (time sync), every packet
waiting in the delay/link queues is released early (forward step) or late (backward step), which
produces RTT samples below the trace's path delay. Now: monotonic time + one fixed offset
(realtime - monotonic), taken once by the first emulator process and passed to the nested shells in
LEOREPLAYER_CLOCK_OFFSET_US, so all three shells share one step-free timeline in the same units
(epoch ms) as before. LEOREPLAYER_REALTIME=1 restores the original behaviour.

Usage: fix_clock.py REPLAYER_SRC_DIR
"""
import sys, pathlib

src = pathlib.Path(sys.argv[1]) / 'src/util/timestamp.cc'
text = src.read_text()
if 'LEOREPLAYER_CLOCK_OFFSET_US' in text:
    print('already patched'); sys.exit(0)

old_head = '#include "timestamp.hh"\n#include "exception.hh"\n'
new_head = old_head + r'''
#include <cstdlib>
#include <string>

/* Step-free clock: CLOCK_MONOTONIC + a fixed offset to the epoch, shared by all nested shells
 * through LEOREPLAYER_CLOCK_OFFSET_US (see patches/fix_clock.py). */
static uint64_t now_us( void )
{
    static bool init = false, realtime = false;
    static int64_t offset_us = 0;
    timespec ts;

    if ( !init ) {
        const char *rt = getenv( "LEOREPLAYER_REALTIME" );
        realtime = rt && rt[0] == '1';
        const char *env = getenv( "LEOREPLAYER_CLOCK_OFFSET_US" );
        if ( env ) {
            offset_us = std::stoll( env );
        } else {
            timespec r, m;
            SystemCall( "clock_gettime", clock_gettime( CLOCK_REALTIME, &r ) );
            SystemCall( "clock_gettime", clock_gettime( CLOCK_MONOTONIC, &m ) );
            offset_us = ( int64_t( r.tv_sec ) - int64_t( m.tv_sec ) ) * 1000000
                        + ( int64_t( r.tv_nsec ) - int64_t( m.tv_nsec ) ) / 1000;
            setenv( "LEOREPLAYER_CLOCK_OFFSET_US", std::to_string( offset_us ).c_str(), 1 );
        }
        init = true;
    }
    SystemCall( "clock_gettime", clock_gettime( realtime ? CLOCK_REALTIME : CLOCK_MONOTONIC, &ts ) );
    int64_t us = int64_t( ts.tv_sec ) * 1000000 + ts.tv_nsec / 1000;
    return uint64_t( realtime ? us : us + offset_us );
}
'''
assert old_head in text
text = text.replace(old_head, new_head)

old_ms = '''    timespec ts;
    SystemCall( "clock_gettime", clock_gettime( CLOCK_REALTIME, &ts ) );

    uint64_t millis = ts.tv_nsec / 1000000;
    millis += uint64_t( ts.tv_sec ) * 1000;

    return millis;'''
old_us = '''    timespec ts;
    SystemCall( "clock_gettime", clock_gettime( CLOCK_REALTIME, &ts ) );
    uint64_t us = ts.tv_nsec / 1000 ;
    us += uint64_t( ts.tv_sec ) * 1000000;

    return us;'''
assert old_ms in text and old_us in text
text = text.replace(old_ms, '    return now_us() / 1000;')
text = text.replace(old_us, '    return now_us();')
src.write_text(text)
print('patched', src)
