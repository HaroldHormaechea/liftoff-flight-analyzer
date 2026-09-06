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


def rotate_vec(q, v):
    """Rotate vector v by quaternion q = (x, y, z, w).

    The same arithmetic analysis.rotate() uses; it lives here as well so a
    caller that needs a body axis does not have to import the analysis stage to
    get one.
    """
    x, y, z, w = q
    tx = 2 * (y * v[2] - z * v[1])
    ty = 2 * (z * v[0] - x * v[2])
    tz = 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + (y * tz - z * ty),
            v[1] + w * ty + (z * tx - x * tz),
            v[2] + w * tz + (x * ty - y * tx))


def _conj(q):
    x, y, z, w = q
    return (-x, -y, -z, w)


def _mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def body_rotation(series):
    """Per-sample rotation increment resolved onto the BODY axes, in degrees.

    Returns one dict per sample with `roll`, `pitch` and `yaw`: how far the
    airframe turned about its own nose, wing and mast axes since the previous
    sample. The last sample repeats the previous increment so the list is the
    same length as the series.

    This is the measurement that separates a flip from a roll, and nothing
    already derived can stand in for it. `tilt` - the angle between the mast and
    vertical - reaches 180 degrees in a backflip and in an axial roll alike, so
    a detector built on tilt cannot tell a loop from a barrel. Attitude Euler
    angles are no better: they gimbal-lock exactly at the vertical attitudes
    every one of these manoeuvres passes through.

    Taken as the relative quaternion conj(q_i) * q_(i+1), which expresses the
    step in the frame the airframe occupied at the START of it, so the axis
    components ARE the body-axis increments. Composing rotations in the world
    frame instead would attribute a roll flown while inverted to the wrong axis.

    Unity's frame is left-handed with +Y up and +Z forward, so body Z is the
    nose (roll), body X the right wing (pitch) and body Y the mast (yaw). Sign
    follows the frame; only the magnitude and the CONSISTENCY of the sign are
    read, never the handedness.
    """
    out = []
    for i in range(len(series)):
        j = min(len(series) - 1, i + 1)
        if j == i:
            out.append(dict(out[-1]) if out else {"roll": 0.0, "pitch": 0.0, "yaw": 0.0})
            continue
        d = _mul(_conj(series[i].attitude), series[j].attitude)
        x, y, z, w = d
        if w < 0:                      # shortest arc: q and -q are the same rotation
            x, y, z, w = -x, -y, -z, -w
        s = math.sqrt(x * x + y * y + z * z)
        if s < 1e-9:
            out.append({"roll": 0.0, "pitch": 0.0, "yaw": 0.0})
            continue
        ang = math.degrees(2.0 * math.atan2(s, max(-1.0, min(1.0, w))))
        out.append({"roll": ang * z / s, "pitch": ang * x / s, "yaw": ang * y / s})
    if len(out) > 1:
        out[-1] = dict(out[-2])
    return out
