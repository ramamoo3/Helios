#ifndef HELIOS_BENCH_STARTUP_H
#define HELIOS_BENCH_STARTUP_H

/* Call once per complete 50 kHz frame. Times are 10 ns ticks from its origin.
 * The delayed negative pulse can end in the following frame. A timer backend
 * must queue that edge and asynchronously mask all outputs on loss of permit.
 */
#include <stdbool.h>

enum {
    BENCH_HALF = 1000, BENCH_PERIOD = 2000, BENCH_BLANK = 20,
    BENCH_INITIAL_SHIFT = 60, BENCH_MAX_SHIFT = 120,
    BENCH_HOLD_FRAMES = 10, BENCH_STEP = 1
};

typedef struct {
    bool ready, active;
    int target, magnitude, hold_remaining;
} bench_startup;

typedef struct { int rise, fall; } bench_pulse;
typedef struct { bench_pulse pp, pn, sp, sn; } bench_frame;

static inline bench_pulse bench_window(int offset)
{
    bench_pulse pulse = {offset + BENCH_BLANK / 2,
                         offset + BENCH_HALF - BENCH_BLANK / 2};
    return pulse;
}

/* A false return requests all gates off and invalidates previous pending edges.
 * Each run has one fixed signed target, in thousandths of a half-period.
 * Initialize state to zero at reset. The hardware trip latch owns permission.
 */
static inline bool bench_next_frame(bench_startup *state, bool permit, bool run,
                                    int target, bench_frame *frame)
{
    *frame = (bench_frame){0};
    if (!permit || !run || target == 0 || target < -BENCH_MAX_SHIFT ||
        target > BENCH_MAX_SHIFT || (state->active && state->target != target)) {
        *state = (bench_startup){0};
        state->ready = permit && !run;
        return false;
    }
    int limit = target < 0 ? -target : target;
    if (!state->active) {
        if (!state->ready)
            return false;
        state->active = true;
        state->ready = false;
        state->target = target;
        state->magnitude = limit < BENCH_INITIAL_SHIFT ? limit : BENCH_INITIAL_SHIFT;
        state->hold_remaining = BENCH_HOLD_FRAMES;
    }
    if (state->hold_remaining > 0)
        --state->hold_remaining;
    else if (state->magnitude < limit)
        state->magnitude += BENCH_STEP;

    int primary = target < 0 ? state->magnitude : 0;
    int secondary = target > 0 ? state->magnitude : 0;
    frame->pp = bench_window(primary);
    frame->pn = bench_window(primary + BENCH_HALF);
    frame->sp = bench_window(secondary);
    frame->sn = bench_window(secondary + BENCH_HALF);
    return true;
}
#endif
