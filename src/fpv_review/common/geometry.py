#!/usr/bin/env python3
"""
geometry.py - quaternion maths, collider containment, and the cull.

Extracted from liftoff_scene.py. None of it knows what a Liftoff bundle is: it
operates on the collider dicts and world points that any sim's ingestion layer
can produce, in the frame documented in schema.py (Unity world space,
left-handed, +Y up, metres).

A collider is the small dict the scene cache stores, and it is the on-disk cache
shape as well as the in-memory one, so it does not change here:

    {"t": "box"|"sph"|"cap", "p": (x, y, z), "q": (x, y, z, w),
     "s": (hx, hy, hz),      # box half-extents, metres
     "r": radius, "h": height, "a": axis index}   # sphere / capsule
"""

import math


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def qrot(q, v):
    x, y, z, w = q
    cx = y * v[2] - z * v[1]
    cy = z * v[0] - x * v[2]
    cz = x * v[1] - y * v[0]
    dx = y * cz - z * cy
    dy = z * cx - x * cz
    dz = x * cy - y * cx
    return (v[0] + 2 * w * cx + 2 * dx,
            v[1] + 2 * w * cy + 2 * dy,
            v[2] + 2 * w * cz + 2 * dz)


def bounds_of(points):
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    return lo, hi


def contains_point(c, p):
    """Is a world point inside this collider? Exact for all three primitives."""
    d = (p[0] - c["p"][0], p[1] - c["p"][1], p[2] - c["p"][2])
    if c["t"] == "sph":
        return d[0] * d[0] + d[1] * d[1] + d[2] * d[2] <= c["r"] * c["r"]
    x, y, z, w = c["q"]
    local = qrot((-x, -y, -z, w), d)                 # world -> collider frame
    if c["t"] == "box":
        s = c["s"]
        return abs(local[0]) <= s[0] and abs(local[1]) <= s[1] and abs(local[2]) <= s[2]
    axis = c["a"]
    half = max(c["h"] / 2.0 - c["r"], 0.0)
    clamped = max(-half, min(half, local[axis]))
    off = list(local)
    off[axis] = local[axis] - clamped
    return off[0] * off[0] + off[1] * off[1] + off[2] * off[2] <= c["r"] * c["r"]



def inside_volume(p, vol):
    """Is a world point inside a trigger volume - a yaw-rotated box, or a sphere?

    Deliberately NOT `contains_point`. That one takes the scene cache's collider
    dict, which is a full quaternion and half-extents already halved; a trigger
    volume comes out of a track's blueprint list as a centre, a yaw in degrees
    and a FULL size in metres, and converting one into the other at every call
    site would put the halving and the degree conversion in three places.

    The volume: {"shape": "box"|"sphere", "pos": (x, y, z), "yaw": deg,
                 "size": (sx, sy, sz)}"""
    d = (p[0] - vol["pos"][0], p[1] - vol["pos"][1], p[2] - vol["pos"][2])
    if vol["shape"] == "sphere":
        r = vol["size"][0] / 2.0
        return d[0] * d[0] + d[1] * d[1] + d[2] * d[2] <= r * r
    # Yaw is a rotation about +Y, so the inverse is the same rotation negated,
    # and only the horizontal components move.
    a = math.radians(-vol["yaw"])
    ca, sa = math.cos(a), math.sin(a)
    lx = d[0] * ca + d[2] * sa
    lz = -d[0] * sa + d[2] * ca
    sx, sy, sz = vol["size"]
    return abs(lx) <= sx / 2.0 and abs(d[1]) <= sy / 2.0 and abs(lz) <= sz / 2.0


def path_inside(colliders, path):
    """Fraction of flown samples that fall inside solid geometry.

    A flight is a WITNESS to the environment's free space. The quad was there,
    so in the right scene essentially no sample is inside a collider; in the
    wrong scene the path drives through walls. This is the only test found that
    reliably rejects a wrong environment - every scene is authored around the
    world origin at similar scale, so gate positions alone match almost any of
    them, including, when tried, the wrong answer for an environment whose
    bundle was already known."""
    if not path:
        return 0.0
    quick = [(c, c["p"], (max(c["s"]) if c["t"] == "box"
                          else c["r"] if c["t"] == "sph"
                          else c["r"] + c["h"] / 2.0) ** 2 * 3.05) for c in colliders]
    hit = 0
    for q in path:
        for c, centre, reach2 in quick:
            dx = q[0] - centre[0]
            dy = q[1] - centre[1]
            dz = q[2] - centre[2]
            if dx * dx + dy * dy + dz * dz <= reach2 and contains_point(c, q):
                hit += 1
                break
    return hit / float(len(path))


def cull(scene, points, radius):
    """Colliders within `radius` of any sampled point on the path.

    Distance is measured to the collider's centre with its own size added, so a
    long wall counts as near when any part of it is near, not only its middle."""
    if not points:
        return []
    keep = []
    for c in scene["colliders"]:
        reach = radius
        if c["t"] == "box":
            reach += math.dist((0, 0, 0), c["s"])
        elif c["t"] == "sph":
            reach += c["r"]
        else:
            reach += c["r"] + c["h"] / 2.0
        for _t, q in points:
            if math.dist(q, c["p"]) <= reach:
                keep.append(c)
                break
    return keep
