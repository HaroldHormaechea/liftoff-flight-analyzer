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
