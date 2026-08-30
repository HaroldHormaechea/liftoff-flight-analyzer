#!/usr/bin/env python3
"""
calibration.py - the constants that were tuned against Liftoff, and only Liftoff.

Every value here was fixed by measuring Liftoff flights. None of them is a
property of FPV flight in general, so none of them may sit in common/, where it
would silently apply to a sim it was never calibrated against.

The line, so a later reader knows where a new constant belongs: physical
constants are calibration; presentational ones are not. A speed in km/h, a
distance in metres, a count of samples at this sim's rate - calibration. Seconds
of animation, frames of SVG, pixels - properties of the report, and they stay in
common/.
"""

# --------------------------------------------------------- incident detection
# Both are tied to Liftoff's 10 Hz replay rate: a sim sampling at 100 Hz spreads
# the same collision over ten samples and would never see this drop in one.

IMPACT_DROP_KMH = 20.0          # speed lost inside one 0.1 s sample
IMPACT_DEBOUNCE_SAMPLES = 3     # a two-sample collapse is one impact, not two

# ------------------------------------------------------------------ prop scale
# Liftoff track props are placed by the Track XML and instantiated from prefabs
# at runtime, so their position is exact and their shape is not. This is the
# placeholder size, in metres.

PROP_NOMINAL = (0.6, 1.0, 0.6)  # half-extents for a prop whose shape is unknown

# -------------------------------------------------------- analysis thresholds
# Every numeric default in common/analysis.py's parser, keyed by its argparse
# `dest`. These were fixed empirically against one Liftoff flight - the Rustline
# 2-lap race of 2026-08-26 - where the two populations separated cleanly, and
# each value sits in the gap between them. That measurement is the whole reason
# they may not stay in common/: they are evidence about Liftoff, not about
# flying.
#
# The literals are reproduced exactly as they were written, ints included.
# argparse applies `type` only to a STRING default, so a `type=float` argument
# with `default=25` yields the int 25; writing 25.0 here would change what lands
# in analysis.json.

THRESHOLDS = {
    # flight geometry
    "turn_threshold": 25,        # deg/s
    "speed_floor": 15,           # km/h, below which sideslip is not meaningful
    "min_samples": 5,

    # stall detection
    "stall_speed": 10,           # km/h
    "stall_min": 0.5,            # s
    "stall_gap": 1.0,            # s
    "idle_throttle": 0.05,

    # stall geometry, all seconds
    "lead": 1.5,
    "pre_window": 4.0,
    "post_window": 4.5,
    "history_window": 15.0,
    "retrace_exclude": 3.0,
    "probe_half_window": 2.5,

    # stall classification - the decision table
    "retrace_m": 3.0,            # overruns measured 0.3-0.4 m, everything else 7.1+
    "reversal_deg": 120,         # overruns measured 172-174 deg, everything else <=105
    "near_m": 15.0,
    "corner_deg": 30,
    "offline_m": 8.0,

    # yaw-only detection, stick deflection
    "yaw_on": 0.20,
    "roll_off": 0.05,
}
