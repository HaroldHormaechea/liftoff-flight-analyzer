#!/usr/bin/env python3
"""
kinematics.py - deriving motion from a position series.

Extracted from liftoff_replay.py. A sim that records position but not velocity
is the normal case rather than a Liftoff quirk, so the derivation belongs to the
shared layer; a sim that *does* report measured velocity simply never calls
this, and says so in its capabilities declaration.
"""

import math


def add_velocity(rows):
    """Central-difference velocity from position.

    The replay stores no velocity, unlike the live feed. At 10 Hz a central
    difference is good enough for trajectory work; do not read fine control
    detail into it.
    """
    out = []
    for i, r in enumerate(rows):
        a = rows[max(0, i - 1)]
        b = rows[min(len(rows) - 1, i + 1)]
        dt = b[0] - a[0]
        if dt <= 0:
            vx = vy = vz = 0.0
        else:
            vx, vy, vz = (b[1] - a[1]) / dt, (b[2] - a[2]) / dt, (b[3] - a[3]) / dt
        sp = math.sqrt(vx * vx + vy * vy + vz * vz)
        out.append(r + [vx, vy, vz, sp, sp * 3.6])
    return out
