/* Host fixture for the same portable scheduler intended for a timer backend. */
#include "bench-startup.h"
#include "bench-hrtim.h"
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

static void check_hrtim(void)
{
    bench_hrtim timer = {0};
    bench_hrtim_frame f;
    assert(!bench_hrtim_next(&timer, true, true, 120, &f));
    assert(!bench_hrtim_next(&timer, false, true, 120, &f));
    assert(!bench_hrtim_next(&timer, true, true, 120, &f));
    assert(!bench_hrtim_next(&timer, false, false, 120, &f));
    assert(!bench_hrtim_next(&timer, true, false, 120, &f));
    for (int i = 0; i < 75; ++i) {
        assert(bench_hrtim_next(&timer, true, true, 120, &f));
        int offset = i < 10 ? 60 : (i < 70 ? i + 51 : 120);
        int previous = offset > 60 && i <= 69 ? offset - 1 : offset;
        assert(f.primary.cmp4 == 25472 && f.primary.cmp1 == 128);
        assert(f.secondary.cmp4 == bench_hrtim_counts(previous - 10));
        assert(f.secondary.cmp1 == bench_hrtim_counts(offset + 10));
        assert(f.secondary.cmp1 - f.secondary.cmp4 >= 256);
        assert(f.secondary.cmp3 - f.secondary.cmp2 == 256);
    }
    assert(!bench_hrtim_next(&timer, true, false, 120, &f));
    assert(!bench_hrtim_next(&timer, true, true, 120, &f));
    assert(f.primary.cmp1 == 0 && f.secondary.cmp4 == 0);
    assert(!bench_hrtim_next(&timer, false, false, -120, &f));
    assert(bench_hrtim_next(&timer, true, true, -120, &f));
    assert(f.primary.cmp4 == 640 && f.secondary.cmp4 == 25472);
    bench_hrtim_abort(&timer);
    assert(!bench_hrtim_next(&timer, true, true, -120, &f));
    assert(!bench_hrtim_next(&timer, false, false, 59, &f));
    assert(!bench_hrtim_next(&timer, true, true, 59, &f));
}

int main(int argc, char **argv)
{
    check_interlocks();
    check_hrtim();
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
