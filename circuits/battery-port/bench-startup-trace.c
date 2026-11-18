/* Host fixture for the same portable scheduler intended for a timer backend. */
#include "bench-startup.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

static void check_interlocks(void)
{
    bench_startup state = {0};
    bench_frame frame;
    assert(!bench_next_frame(&state, true, true, 120, &frame));
    assert(!bench_next_frame(&state, true, false, 120, &frame));
    assert(bench_next_frame(&state, true, true, 120, &frame));
    assert(!bench_next_frame(&state, false, true, 120, &frame));
    assert(!bench_next_frame(&state, true, true, 120, &frame));
    assert(frame.pp.fall == 0 && frame.pn.fall == 0 &&
           frame.sp.fall == 0 && frame.sn.fall == 0);
    assert(!bench_next_frame(&state, true, false, 0, &frame));
    assert(!bench_next_frame(&state, true, true, 121, &frame));
    assert(!bench_next_frame(&state, true, false, 0, &frame));
    assert(bench_next_frame(&state, true, true, -30, &frame));
    assert(frame.pp.rise - frame.sp.rise == 30);
    assert(!bench_next_frame(&state, true, true, 30, &frame));
    assert(!bench_next_frame(&state, true, true, 30, &frame));
}

int main(int argc, char **argv)
{
    check_interlocks();
    if (argc != 3) return 1;
    int target = atoi(argv[1]), frames = atoi(argv[2]);
    bench_startup state = {0};
    bench_frame f;
    bench_next_frame(&state, true, false, target, &f);
    for (int i = 0; i < frames; ++i) {
        if (!bench_next_frame(&state, true, true, target, &f)) return 2;
        printf("%d %d %d %d %d %d %d %d\n", f.pp.rise, f.pp.fall,
               f.pn.rise, f.pn.fall, f.sp.rise, f.sp.fall, f.sn.rise, f.sn.fall);
    }
    return 0;
}
