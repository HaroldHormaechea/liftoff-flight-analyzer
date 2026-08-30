#!/usr/bin/env python3
"""
capabilities.py - what a Liftoff replay does and does not contain.

Every entry below is a statement about the SAVED REPLAY, which is the only
source the analysis path reads. Liftoff's live UDP feed carries more - gyro,
battery, motor RPM - but nothing on this path consumes it, so from the
analysis's point of view those fields do not exist.

Written as a declaration rather than discovered at runtime, so a stage can ask
before it computes rather than producing a confident number from a field that
was never there.
"""

from fpv_review.common import capabilities as caps


def declare():
    """Liftoff's capability declaration."""
    c = caps.Capabilities(sim="liftoff")
    f = c.fields

    f["position"] = caps.Capability(caps.AVAILABLE, "world-space metres at 10 Hz")
    f["attitude"] = caps.Capability(caps.AVAILABLE, "quaternion, confirmed against "
                                    "a simultaneous 100 Hz telemetry capture")
    f["stick_positions"] = caps.Capability(
        caps.AVAILABLE, "throttle 0..1 and three axes -1..+1; exact, not estimated")
    f["velocity"] = caps.Capability(
        caps.DERIVED, "central difference on position at 10 Hz - good for "
        "trajectory work, not for fine control detail; the replay stores none")
    f["sample_rate"] = caps.Capability(
        caps.AVAILABLE, "10 Hz nominal but irregular (0.003-0.197 s observed), so "
        "the interval is the measured MEDIAN, never a first difference")
    f["lap_boundaries"] = caps.Capability(
        caps.AVAILABLE, "lapTimes and lapStartIndices, from the replay itself")
    f["track_geometry"] = caps.Capability(
        caps.AVAILABLE, "gates and route from the game's own bundles",
        conditional_on="the trackdata cache")
    f["world_geometry"] = caps.Capability(
        caps.AVAILABLE, "static environment colliders",
        conditional_on="the scene cache")
    f["prop_shapes"] = caps.Capability(
        caps.AVAILABLE, "per-prop collider shapes",
        conditional_on="the prop table")
    f["personal_bests"] = caps.Capability(
        caps.AVAILABLE, "from snapshots of the game's own ratcheting time files")

    # Present in the live UDP feed, absent from every saved replay.
    for name in ("gyro", "battery", "motor_rpm"):
        f[name] = caps.Capability(
            caps.UNAVAILABLE,
            "a saved replay carries no %s; only the live UDP telemetry feed does"
            % name.replace("_", " "))

    return c
