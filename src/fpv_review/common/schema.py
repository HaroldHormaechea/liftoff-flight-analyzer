#!/usr/bin/env python3
"""
schema.py - the artifacts that cross a stage boundary, and how they serialise.

Coordinate frame, stated once for everything in this module: Unity world space,
left-handed, +Y up, distances in metres. That is the frame the replay and the
track XML already share, so nothing is re-projected on the way in.

COLUMNS arrives here from liftoff_replay.py. In its old home it was Liftoff's
record layout; here it is the serialisation of a flight sample, which is what
makes flight.csv a format a second sim can be asked to produce and this layer
can be asked to read back.
"""

COLUMNS = ["t", "pos_x", "pos_y", "pos_z", "quat_x", "quat_y", "quat_z", "quat_w",
           "in_throttle", "in_yaw", "in_pitch", "in_roll",
           "vel_x", "vel_y", "vel_z", "speed_ms", "speed_kmh"]
