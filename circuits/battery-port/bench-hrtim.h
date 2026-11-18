#ifndef HELIOS_BENCH_HRTIM_H
#define HELIOS_BENCH_HRTIM_H

#include <stdint.h>
#include "bench-startup.h"

/* Bench target is STM32G474 HRTIM at 160 MHz with the x8 timer prescaler. */
enum { BENCH_HRTIM_PERIOD = 25600 };

typedef struct {
    uint16_t cmp1, cmp2, cmp3, cmp4;
} bench_hrtim_compares;

typedef struct {
    bench_hrtim_compares primary, secondary;
} bench_hrtim_frame;

typedef struct {
    bench_startup ramp;
    int primary_carry, secondary_carry;
    bool start_allowed;
} bench_hrtim;

static inline uint16_t bench_hrtim_counts(int ticks)
{
    /* Round 12.8 counter counts per 10 ns scheduler tick to the nearest count. */
    return (uint16_t)((64 * ticks + 2) / 5);
}

static inline bench_hrtim_compares bench_hrtim_bridge(bench_pulse positive,
                                                       bench_pulse negative,
                                                       int *carry)
{
    /* For either sign, the lagging bridge holds its negative output through
     * rollover. CMP4 must end the previous frame's pulse at its old offset.
     */
    int fall = *carry;
    *carry = negative.fall >= BENCH_PERIOD ? negative.fall - BENCH_PERIOD : 0;
    if (!fall)
        fall = negative.fall - (*carry ? BENCH_PERIOD : 0);
    return (bench_hrtim_compares){
        bench_hrtim_counts(positive.rise), bench_hrtim_counts(positive.fall),
        bench_hrtim_counts(negative.rise), bench_hrtim_counts(fall)
    };
}

static inline void bench_hrtim_abort(bench_hrtim *state)
{
    *state = (bench_hrtim){0};
}

/* Plan one complete frame before its timer reload. Request is the operator's
 * run command. Permit is J5.10, which can only rise after ARM and RUN.
 * A false result calls for no new frame and disabled timer outputs.
 * A FLT1 event or missed preload deadline also requires bench_hrtim_abort().
 */
static inline bool bench_hrtim_next(bench_hrtim *state, bool request, bool permit,
                                    int target, bench_hrtim_frame *frame)
{
    *frame = (bench_hrtim_frame){0};
    if (!request) {
        bench_hrtim_abort(state);
        state->start_allowed = !permit;
        return false;
    }
    if (!state->start_allowed)
        return false;
    if ((target > -BENCH_INITIAL_SHIFT && target < BENCH_INITIAL_SHIFT) ||
        target < -BENCH_MAX_SHIFT || target > BENCH_MAX_SHIFT ||
        (state->ramp.active && (!permit || state->ramp.target != target))) {
        bench_hrtim_abort(state);
        return false;
    }
    if (!permit)
        return false;

    bench_frame logical;
    if (!state->ramp.active)
        bench_next_frame(&state->ramp, true, false, target, &logical);
    if (!bench_next_frame(&state->ramp, true, true, target, &logical))
        return false;
    frame->primary = bench_hrtim_bridge(logical.pp, logical.pn, &state->primary_carry);
    frame->secondary = bench_hrtim_bridge(logical.sp, logical.sn, &state->secondary_carry);
    return true;
}
#endif
