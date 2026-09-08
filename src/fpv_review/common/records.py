#!/usr/bin/env python3
"""
records.py - the scores that make progress measurable ACROSS tracks.

A lap time answers "am I faster on this track". It cannot answer "am I a better
pilot than last week", because every track has its own clock and a new track
resets it. pbs.py already tracks the per-track clock and is the right tool for
that question. This module is the other one: three quantities that mean the same
thing on Bardwells Yard and on a stairwell in BandoCity, so a run on a track
never flown before can still beat something.

Why three, and not thirty
-------------------------
A scoreboard nobody reads is worse than none, because it makes every debrief
longer without making one of them sharper. Three is what fits in a table the
pilot actually looks at, and each of the three had to earn its place by being a
number that a real debrief had already reached for by hand:

  smallest_gate    the smallest opening flown cleanly at racing speed.
                   Asked for directly - "I was proud of fitting through the
                   small gates" - and there was no way to answer it except by
                   remeasuring old flights.
  gate_accuracy    the median share of the available margin used at a gate.
                   Metres alone are not comparable: 0.33 m through a 2.4 m arch
                   uses more of the gap than 0.31 m through a 2.0 m box, so the
                   raw number can say a flight got worse when it got better.
  route_overhead   how much longer the flown path was than the route it had to
                   cover. The one line-quality measure that is already
                   dimensionless, and the one a debrief kept quoting from
                   memory across four different tracks.

Every one of them is a per-FLIGHT number, not a per-lap one, except
route_overhead which takes the best lap: a score is what a saved recording is
worth, because the saved recording is the unit the pilot chose.

The store is append-only, and the bests are derived
---------------------------------------------------
`records.json` holds a log of entries, one per flight, and NOTHING ELSE. There
is no "bests" block in the file. `standing()` recomputes the leaders on every
read, in about a millisecond, and that is deliberate: a stored best is a second
copy of a fact, and the second copy is the one that goes stale. Recomputing also
means `standing(entries, before=t)` can answer "what was the record BEFORE this
flight", which is the question a debrief actually asks and which a single stored
best cannot answer at all.

Re-running a report must not inflate the log, so an entry is keyed by its replay
and a re-run replaces its own row in place. Every OTHER flight's row survives
untouched - that is what keeps the history.

What a missing measurement does
-------------------------------
Nothing is guessed. A flight with no track data scores no gates and no overhead;
a gate whose opening cannot be established scores no tightness. Each score comes
back as None with a `why`, and None never enters a ranking. The alternative -
falling back to a nominal aperture - would mint records out of an assumption,
and a record that is not true is worse than a blank.
"""

# `float | None` below is a 3.10 spelling; this makes it legal on the 3.9 floor.
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import median

FORMAT = 1

# Prefab names carry their own opening: CheckpointBox2mX4m01, CheckpointBox20mX5m01,
# MultiGPChampTrack8x10Frame. This is not a heuristic dressed up as a rule - the
# game names these prefabs after the hole in them, and for the fixed-size ones it
# is the ONLY place the size exists. Their colliders are a unit cube scaled at
# runtime, so props.json reports a 1 x 1 x 1 box for a 20 m gate.
#
# THE UNIT IS PART OF THE NAME AND MUST BE READ. LightGate300x220cmVarBlue01 is a
# 3.00 x 2.20 m gate, not a 300 x 220 m one. Dropping the `cm` inflated 23 gates
# of one route by a hundred, which did not merely mis-score them: `_plane_crossing`
# sizes its acceptance window off the aperture, so a 150 m half-width accepted a
# pass 142.7 m away as a crossing, the monotonic cursor jumped to it, and 15 of
# that route's 38 checkpoints then matched nothing at all. It also minted an
# all-time gate-accuracy record of 0.004 against a standing 0.112. One missing
# unit, three symptoms.
_NAMED = re.compile(
    r"(\d+(?:\.\d+)?)\s*(mm|cm|m)?\s*[xX]\s*(\d+(?:\.\d+)?)\s*(mm|cm|m)?", re.I)
_UNIT = {"mm": 0.001, "cm": 0.01, "m": 1.0, None: 1.0, "": 1.0}

# No checkpoint in the game is wider than this. An aperture beyond it is a parse
# that went wrong, and the honest answer is then None - a crossing with no
# aperture is still measured, it just sets no record. Liftoff's widest is the
# 45 x 30 m resizable box on Hannover's The Biggest Yet, which arrives by `scale`
# and is exact, so this only ever guards the inferred sources.
_MAX_APERTURE_M = 60.0


def aperture_of(gate, shapes=None):
    """The flyable opening of one checkpoint -> ((width, height, centre_y), source).

    THE CENTRE HEIGHT IS PART OF THE OPENING, and leaving it out is a silent,
    systematic error rather than a small one. A checkpoint box is centred on its
    placement origin, so its opening runs +/- h/2 about it. An arch STANDS ON
    THE GROUND: its origin is at the base and its opening runs 0 to h. Measuring
    an arch as if it were centred put a third of a clean 3-lap race outside its
    own gates - every one of them "too high", every one of them actually fine.

    Five sources, tried in the order of how much they are trusted, and the one
    used is RETURNED rather than assumed, because a record's credibility is the
    credibility of its aperture:

      "scale"      the track's own aperture. Resizable prefabs carry their size
                   as a scale on the placement, and it is exact.
      "trigger"    the prefab's own scoring volume, from props.py. This is the
                   game's answer to "did I pass through", so where it exists and
                   is real it beats every inference below it - and it is the only
                   source that carries the centre height for free.
      "name"       parsed from the prefab name for the fixed-size prefabs, unit
                   included. Exact, but the axis ORDER is not reliable, which is
                   why the trigger outranks it: GenericGate200x250cm01's trigger
                   is 2.70 x 2.20 m, i.e. 250 wide by 200 tall plus the usual
                   10 cm of slack, so the name reads height first there and width
                   first on LightGate300x220cm.
      "colliders"  the gap between the prop's solid parts, from props.py. Used
                   for frames and arches that are neither resizable, named, nor
                   carrying a box trigger.
      None         no opening could be established. The crossing is still
                   measured; it just cannot set a tightness record.
    """
    ap = gate.get("aperture")
    if ap and len(ap) == 2 and all(v and v > 0 for v in ap):
        return (float(ap[0]), float(ap[1]), 0.0), "scale"
    name = gate.get("item") or ""
    shape = (shapes or {}).get(name, {}).get("colliders", [])
    trig = _opening_from_trigger(shape)
    if trig[0]:
        return trig
    m = _NAMED.search(name)
    if m:
        # A unit written once governs both numbers: GenericGate200x250cm01 is
        # 2.00 x 2.50 m, not 200 m by 2.50 m. Only CheckpointBox20mX10m01 spells
        # it out on each. Where neither carries one - MultiGPChampTrack8x10Frame
        # - metres is the reading, and the guard below catches it if that is
        # wrong rather than letting it set a record.
        u1, u2 = (m.group(2) or "").lower(), (m.group(4) or "").lower()
        w = float(m.group(1)) * _UNIT.get(u1 or u2, 1.0)
        h = float(m.group(3)) * _UNIT.get(u2 or u1, 1.0)
        if 0 < w <= _MAX_APERTURE_M and 0 < h <= _MAX_APERTURE_M:
            return (w, h, 0.0), "name"
        return None, None
    return _opening_from_colliders(shape)


def _opening_from_trigger(shape):
    """The prefab's own scoring volume -> ((w, h, centre_y), "trigger") or (None, None).

    A checkpoint prefab carries a `trig` box: the volume the game itself tests
    the quad against. That makes it the best aperture there is - it needs no
    inference, and unlike the name it carries the centre height, which is what
    stops a gate whose opening sits 1.44 m off the ground reading as 1.6 m high
    on every single crossing.

    Two prefabs it must NOT be used for, and both are detectable rather than
    listed: the `CheckpointBox*` family, whose trigger is a unit cube scaled at
    runtime and so reports 1 x 1 x 1 m for a 20 m gate, and anything whose
    trigger is a mesh rather than a box.

    Picking the two axes out of three: y is always up, so the height is direct.
    For the width, the thin horizontal axis is the plane normal - 0.13 m on a
    light gate, 0.07 m on a truss finish - so the other one is the opening. Where
    neither horizontal is thin the trigger is a VOLUME rather than a plane (the
    truss cube, 1.70 x 1.70 m in plan), and the narrower horizontal is then the
    real constraint. Erring narrow is the safe direction: it makes `clean`
    stricter and `margin_used` larger, so it can never mint a record that is not
    there."""
    boxes = [c for c in shape
             if c.get("trig") and c.get("t") == "box" and len(c.get("s") or []) == 3]
    if not boxes:
        return None, None
    c = boxes[0]
    sx, sy, sz = (abs(v) for v in c["s"])
    cy = c["p"][1]
    # The runtime-scaled unit cube. Nothing real is a 1 m cube centred on its
    # own origin, so this identifies the CheckpointBox family without naming it.
    if abs(cy) < 1e-6 and all(abs(v - 0.5) < 1e-3 for v in (sx, sy, sz)):
        return None, None
    lo, hi = min(sx, sz), max(sx, sz)
    half_w = hi if lo < 0.5 * hi else lo
    w, h = 2.0 * half_w, 2.0 * sy
    if not (0 < w <= _MAX_APERTURE_M and 0 < h <= _MAX_APERTURE_M):
        return None, None
    return (round(w, 2), round(h, 2), round(cy, 2)), "trigger"


def _opening_from_colliders(shape):
    """The hole a frame leaves -> ((width, height), "colliders") or (None, None).

    For the arches and truss gates, which are neither resizable nor named after
    their size, this is the only source there is. It has to be structural rather
    than opportunistic, and the difference is not academic: a first version took
    the lowest collider above the ground as "the top of the opening" and read
    InflatableArchBrandless01 - a 6 x 3.5 m arch - as 4.87 x 1.08 m, because the
    SIDE uprights are centred at y=1.58. That 1.08 then beat a genuine 2.00 m
    box and stood as the tightest-gate record, which is the exact failure this
    module exists to avoid: a record that is not true is worse than a blank.

    So the parts are identified by what they are. A capsule's `a` is the axis it
    is long on: 1 is an upright, 0 or 2 a bar. The opening is bounded sideways
    by the innermost upright on each side and from above by the lowest bar that
    sits above them, each shrunk by its own radius because the frame has
    thickness. If that structure is not there, this returns nothing rather than
    a number - an arch with no identifiable uprights is a prop this function
    does not understand, and saying so is the whole point."""
    solid = [c for c in shape if not c.get("trig")]
    uprights, bars = [], []
    for c in solid:
        half = c.get("r") or max(c.get("s") or [0.0])
        if c.get("t") == "cap" and c.get("a") == 1:
            uprights.append((c["p"][0], abs(half)))
        elif c.get("t") == "cap":
            bars.append((c["p"][1], abs(half)))
    left = [x + r for x, r in uprights if x < 0]
    right = [x - r for x, r in uprights if x > 0]
    if not (left and right and bars):
        return None, None
    w = min(right) - max(left)
    floor = max(max(left), 0.0)
    above = [y - r for y, r in bars if y - r > floor]
    if w <= 0 or not above:
        return None, None
    # An arch stands on the ground: the opening runs from the base to the lowest
    # bar above the uprights, so its centre is half way up, not at the origin.
    top = min(above)
    return (round(w, 2), round(top, 2), round(top / 2.0, 2)), "colliders"




def crossings(series, gates, ranges, names, shapes=None, min_aperture_m=0.0,
              laps=1):
    """Every checkpoint crossing in a flight, with how far off centre it was.

    Offsets are decomposed in the gate's own frame: `lateral` across the
    opening, `vertical` up it. Both are signed, so a systematic bias - this
    pilot sits low - stays visible instead of being averaged away by taking
    magnitudes too early.

    A crossing counts as `clean` only when it is inside the opening on BOTH
    axes. A pass outside the frame is a miss that happened to intersect the
    plane, and letting one into an accuracy median would reward missing.

    HOW THE ROUTE IS WALKED, and the three shapes that were wrong first. Each
    of them looks right, so each is worth naming:

      Once per flight, one cursor. Finds the first crossing of every checkpoint
      and stops, so a three-lap race scores lap 1 and discards laps 2 and 3 -
      backwards, since the later laps are the fast ones.

      Repeat until a pass finds nothing. The finish plane is the last
      checkpoint, so the cursor ends sitting on it, the next pass re-finds that
      same crossing, and it never terminates. It produced 83 "crossings" for a
      2-lap race, 65 of them one instant repeated.

      Once per lap, each walk clamped to that lap's sample range. The start gate
      is crossed a sample or two BEFORE the recorded lap-1 boundary - the
      boundary is the crossing - so lap 1's walk misses it, runs on, and matches
      the lap-2 crossing of the same gate instead. Then its cursor is inside lap
      2 and the rest of lap 1 finds nothing. It scored 1 crossing for lap 1 and
      19 for lap 2.

    What works is a flat sequence with one monotonic cursor and a walk count
    that is KNOWN rather than discovered: the start gate once, then checkpoints
    1..finish once per timed lap. A lap is exactly one walk of the route, the
    replay says how many laps there were, and the finish of one lap is the start
    of the next - which is why the start gate is not repeated. There is no
    termination condition left to get wrong.

    Each crossing's segment is read off its sample index, not off which walk it
    belongs to, so a lap boundary landing mid-gate cannot mislabel it."""
    out = []
    if not gates:
        return out
    seg_of = {}
    for k, (a, b) in enumerate(ranges):
        for i in range(a, b):
            seg_of[i] = names[k]
    n = len(series)
    # Each walk carries its own sample window, and that is what makes a MISSED
    # checkpoint harmless. Without it one failed lookup runs the cursor on into
    # the next lap, matches that lap's crossing, and every checkpoint behind it
    # then finds nothing: a single 0.25 m trigger slab that lap 1 passed 2.3 m
    # wide cost eight of lap 1's crossings that way.
    #
    # The start gate gets a window of its own that ENDS at the lap-1 boundary,
    # because it is crossed a sample or two before that boundary - the crossing
    # is what starts the clock.
    laps = max(1, laps)
    lap_windows = [(ranges[k][0], min(ranges[k][1] + 15, n))
                   for k in range(min(laps, len(ranges)))]
    while len(lap_windows) < laps:
        lap_windows.append((0, n))
    plan = [(0, gates[0], 0, min(lap_windows[0][0] + 15, n))]
    for lo, hi in lap_windows:
        plan += [(order, g, lo, hi) for order, g in list(enumerate(gates))[1:]]
    cursor = 0
    for step, (order, gate, lo, hi) in enumerate(plan):
        ap, ap_src = aperture_of(gate, shapes)
        hit = _plane_crossing(series, gate, max(cursor, lo), hi, ap)
        # YOU CANNOT CROSS GATE 9 AFTER YOU HAVE ALREADY CROSSED GATE 10, and a
        # route that visits the same checkpoint twice is where that stops being
        # obvious. Hannover's Got Intel passes truss gate 595 as both gate 9 and
        # gate 19. He clipped the first pass 4.6 m wide, outside the acceptance
        # window, so the walk ran on and matched the SECOND pass instead - and
        # the monotonic cursor, now 33 s downstream, then found nothing for
        # gates 10 to 19. Ten checkpoints lost to one wide pass.
        #
        # One step of lookahead settles it without a cursor that can go
        # backwards: if the next checkpoint is already crossed by the time this
        # one supposedly was, this match belongs to a later visit and the honest
        # answer is that this crossing was not found.
        if hit is not None and step + 1 < len(plan):
            nxt_order, nxt_gate, nxt_lo, nxt_hi = plan[step + 1]
            nxt_ap, _ = aperture_of(nxt_gate, shapes)
            nxt = _plane_crossing(series, nxt_gate, max(cursor, nxt_lo), nxt_hi,
                                  nxt_ap)
            if nxt is not None and nxt[3] < hit[3]:
                hit = None
        if hit is None:
            continue
        lat, vert, spd, j = hit
        clean = _inside(lat, vert, ap, gate.get("item") or "")
        out.append({
            "segment": seg_of.get(j),
            "order": order,
            "item": gate.get("item"),
            "aperture": [ap[0], ap[1]] if ap else None,
            "aperture_centre_y": ap[2] if ap else None,
            "aperture_source": ap_src,
            "lateral_m": round(lat, 3),
            "vertical_m": round(vert, 3),
            "vertical_off_centre_m": round(vert - ap[2], 3) if ap else None,
            "margin_used": (round(abs(lat) / (ap[0] / 2), 3)
                            if ap and ap[0] > 0 else None),
            "speed_kmh": round(spd, 1),
            "clean": clean,
            "real_opening": bool(ap and min(ap[0], ap[1]) >= min_aperture_m),
            "index": j,
        })
        cursor = j + 1
    return out


def _inside(lat, vert, ap, item):
    """Is this crossing inside the opening on both axes?

    A sphere checkpoint is an ellipsoid, not a rectangle, so the corners of its
    bounding box are outside it. Romantic Boat Ride's are 25 x 7 m and Pipeline
    carries a 2 x 2 m one, which is small enough for the difference to decide a
    record."""
    if not ap:
        return False
    dv = vert - ap[2]
    if "Sphere" in (item or ""):
        return ((lat / (ap[0] / 2)) ** 2 + (dv / (ap[1] / 2)) ** 2) <= 1.0
    return abs(lat) <= ap[0] / 2 and abs(dv) <= ap[1] / 2


def _plane_crossing(series, gate, start, end, ap=None):
    """Where the path NEXT cuts this checkpoint's plane -> (lat, vert, kmh, index).

    Interpolated between the two samples that straddle the plane. At 10 Hz and
    65 km/h the samples are 1.8 m apart, so taking the nearest sample instead
    would carry up to 0.9 m of sampling error along the direction of travel -
    the same order as the offsets being measured.

    NEXT, not nearest. Picking the crossing closest to the gate centre sounds
    strictly better and is not: a checkpoint flown 0.69 m off centre on lap 1
    and 0.35 m off on lap 2 has its lap-1 crossing silently replaced by the
    lap-2 one, the cursor jumps a whole lap, and every checkpoint after it in
    lap 1 then finds nothing. That is exactly what happened - a 2-lap race came
    back with 19 crossings, all of them attributed to lap 2.

    The acceptance window is the opening plus 2 m rather than a flat radius,
    because a flat radius has to be wide enough for a 20 m gate and is then wide
    enough to catch an unrelated pass through a 2 m one's infinite plane."""
    gx, gy, gz = gate["pos"]
    th = math.radians(gate.get("yaw") or 0.0)
    nx, nz = math.sin(th), math.cos(th)          # gate normal, horizontal
    lx, lz = math.cos(th), -math.sin(th)         # across the opening
    lat_max = max(ap[0] / 2 + 2.0, 4.0) if ap else 8.0
    vert_max = max(ap[1] / 2 + 2.0, 4.0) if ap else 8.0
    cy = ap[2] if ap else 0.0
    for j in range(max(start, 1), end):
        p0, p1 = series[j - 1], series[j]
        d0 = (p0.pos[0] - gx) * nx + (p0.pos[2] - gz) * nz
        d1 = (p1.pos[0] - gx) * nx + (p1.pos[2] - gz) * nz
        if d0 == d1 or d0 * d1 > 0:
            continue
        f = d0 / (d0 - d1)
        px = p0.pos[0] + f * (p1.pos[0] - p0.pos[0])
        py = p0.pos[1] + f * (p1.pos[1] - p0.pos[1])
        pz = p0.pos[2] + f * (p1.pos[2] - p0.pos[2])
        lat = (px - gx) * lx + (pz - gz) * lz
        vert = py - gy
        if abs(lat) > lat_max or abs(vert - cy) > vert_max:
            continue          # some other part of the flight through this plane
        return lat, vert, p0.speed_kmh + f * (p1.speed_kmh - p0.speed_kmh), j
    return None


def path_length(series, a, b):
    """Metres flown between two sample indices."""
    return sum(math.dist(series[k].pos, series[k - 1].pos) for k in range(a + 1, b))


def route_length(gates):
    """Metres of the route itself, centre to centre in the order flown."""
    pts = [g["pos"] for g in gates if g]
    return sum(math.dist(pts[k], pts[k - 1]) for k in range(1, len(pts)))


# ---------------------------------------------------------------- the scores

# Direction matters more than it looks: every comparison in this module goes
# through it, so a score added later cannot get "better" backwards by accident.
SCORES = {
    "smallest_gate":  {"better": "lower", "unit": "m2",
                       "label": "smallest gate flown clean"},
    "gate_accuracy":  {"better": "lower", "unit": "share of margin",
                       "label": "median margin used at a gate"},
    "route_overhead": {"better": "lower", "unit": "%",
                       "label": "shortest line, best lap"},
}

MIN_CROSSINGS = 8        # below this a median is one good gate, not a flight


def score_flight(series, gates, ranges, names, meta, shapes=None,
                 min_kmh=30.0, min_aperture_m=0.8):
    """The three scores for one flight -> {name: {value, why, ...}}.

    `min_kmh` keeps a tightness record honest: easing a quad through a small
    gate at walking pace is a different skill from taking it at racing speed,
    and only the second one is what the score is for.

    `min_aperture_m` excludes openings too small to be openings. Some
    checkpoints are trigger SLABS rather than gates - A League Of Its Own
    carries two at 0.25 x 6.00 m - and their narrow axis is the thickness of a
    scoring volume, not a hole anyone flies through. Left in, one fluke pass
    would mint a 0.25 m record that could never be beaten and never meant
    anything."""
    xs = crossings(series, gates, ranges, names, shapes, min_aperture_m,
                   laps=len(meta.get("lap_times") or []) or 1)
    scored = {}

    # 1. tightest gate: the narrowest real opening crossed clean, at speed.
    # EXACT apertures only. `colliders` is an inference from the frame's solid
    # parts, and an inference that is 15% out sets a record 15% too good which
    # then stands forever. `scale` is the track's own number, `name` is what the
    # prefab is called, and `trigger` is the volume the game itself scores the
    # crossing against - all three are facts rather than inferences. An inferred
    # opening still measures the crossing and still counts towards gate_accuracy,
    # where being uniformly out on one prefab shifts every crossing through it
    # together.
    fast = [c for c in xs if c["clean"] and c["real_opening"]
            and c["aperture_source"] in ("scale", "name", "trigger")
            and c["speed_kmh"] >= min_kmh]
    if fast:
        # Tightest first, then fastest, then closest to centre. Several
        # crossings of the same gate tie on the score itself, and the one the
        # report names should be the one worth naming.
        # AREA, not the narrowest dimension. Ranking on min(w, h) sounds like
        # what "tightest" means and crowns letterboxes: a 4.85 x 1.65 m slot
        # beat a 2.00 x 4.00 m box, even though the two holes are the same 8 m2
        # and only one of them is a small gate. Worse, the record then flips
        # between a width record and a height record from flight to flight, so
        # the progression cannot be read. Area is one number for one question -
        # how small was the hole - and the dimensions are in `aperture` for the
        # debrief to name the tight axis.
        best = min(fast, key=lambda c: (c["aperture"][0] * c["aperture"][1],
                                        -c["speed_kmh"], c["margin_used"] or 0.0))
        scored["smallest_gate"] = {
            "value": round(best["aperture"][0] * best["aperture"][1], 2),
            "narrow_axis_m": round(min(best["aperture"]), 2),
            "aperture": best["aperture"],
            "aperture_source": best["aperture_source"],
            "item": best["item"],
            "checkpoint": best["order"],
            "speed_kmh": best["speed_kmh"],
            "lateral_m": best["lateral_m"],
            "vertical_m": best["vertical_m"],
            "margin_used": best["margin_used"],
        }
    else:
        scored["smallest_gate"] = {"value": None, "why": (
            "no checkpoint with an EXACT opening was crossed cleanly above "
            "%.0f km/h; an opening inferred from the frame's colliders is "
            "measured but cannot set a record" % min_kmh if xs else
            "no track data for this replay, so no checkpoint could be measured")}

    # 2. gate accuracy: how much of the available margin gets used, typically.
    # EVERY crossing with a known opening, not just the clean ones. Restricting
    # the median to clean crossings looks like the careful choice and is the
    # opposite: it drops exactly the worst passes, so a flight that misses gates
    # scores better than one that scrapes through them all. On a finished race
    # there is nothing to drop anyway - a lap that counted crossed its gates -
    # and a crossing far enough out to be a real miss is not found at all,
    # because _plane_crossing only accepts a cut near the opening.
    usable = [c for c in xs if c["margin_used"] is not None]
    if len(usable) >= MIN_CROSSINGS:
        scored["gate_accuracy"] = {
            "value": round(median(c["margin_used"] for c in usable), 3),
            "crossings": len(usable),
            "clean": sum(1 for c in usable if c["clean"]),
            "median_lateral_m": round(median(abs(c["lateral_m"]) for c in usable), 3),
            # off centre, not height above the placement origin: an arch's
            # origin is on the ground, so raw height reads ~1.9 m for a pilot
            # flying dead through the middle of it.
            "median_vertical_off_centre_m":
                round(median(abs(c["vertical_off_centre_m"]) for c in usable), 3),
            "worst_lateral_m": round(max(abs(c["lateral_m"]) for c in usable), 3),
        }
    else:
        scored["gate_accuracy"] = {"value": None, "why": (
            "%d crossings with a known opening; %d are needed for a median to "
            "describe a flight rather than a gate" % (len(usable), MIN_CROSSINGS))}

    # 3. route overhead: the best lap's path against the route it had to cover.
    rlen = route_length(gates) if gates else 0.0
    timed = [k for k, nm in enumerate(names)
             if nm.startswith("lap") and meta.get("lap_times")
             and k < len(meta["lap_times"])]
    if rlen > 0 and timed:
        per = [(100.0 * (path_length(series, *ranges[k]) / rlen - 1.0), k)
               for k in timed]
        ov, k = min(per)
        scored["route_overhead"] = {
            "value": round(ov, 1),
            "lap": names[k],
            "path_m": round(path_length(series, *ranges[k]), 1),
            "route_m": round(rlen, 1),
        }
    else:
        scored["route_overhead"] = {"value": None, "why": (
            "no timed lap to measure" if rlen > 0 else
            "no track data for this replay, so the route length is unknown")}
    return scored, xs


# ----------------------------------------------------------------- the store

def load(path):
    """Every entry recorded so far, oldest first; [] when there is none yet."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    return doc.get("entries", []) if isinstance(doc, dict) else list(doc)


def save(path, entries):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"format": FORMAT, "entries": entries}, indent=2),
                 encoding="utf-8")


def record(path, entry):
    """Append one flight's scores, or replace this flight's own earlier row.

    Keyed on the replay, so regenerating a report - which happens at least twice
    for every review, once before the Debrief is written and once after - does
    not enter the same flight twice and quietly double its weight in the
    history. Every other row is untouched: the log only ever grows by flights.

    Returns (entries, replaced)."""
    entries = load(path)
    key = entry.get("replay")
    replaced = False
    for i, e in enumerate(entries):
        if key and e.get("replay") == key:
            entries[i] = entry
            replaced = True
            break
    if not replaced:
        entries.append(entry)
    entries.sort(key=lambda e: e.get("flown_at") or "")
    save(path, entries)
    return entries, replaced


def standing(entries, before=None, exclude=None):
    """The leader for each score -> {name: entry-shaped dict}, or {} if none yet.

    `before` restricts to flights flown strictly earlier, which is what makes
    "this beat the 0.31 you set on Field Day" answerable. `exclude` drops one
    replay by name, so a re-run of the same flight does not end up being
    compared against itself and reporting that it tied its own record."""
    out = {}
    for e in entries:
        if exclude and e.get("replay") == exclude:
            continue
        if before and (e.get("flown_at") or "") >= before:
            continue
        for name, spec in SCORES.items():
            got = (e.get("scores") or {}).get(name) or {}
            v = got.get("value")
            if v is None:
                continue
            cur = out.get(name)
            if cur is None or (v < cur["value"] if spec["better"] == "lower"
                               else v > cur["value"]):
                out[name] = {"value": v, "replay": e.get("replay"),
                             "race": e.get("race"), "flown_at": e.get("flown_at"),
                             "detail": got}
    return out


def compare(scores, prior):
    """This flight's scores against the standing bests -> the debrief's table.

    Every score comes back with the same four keys whether it is a record, a
    miss or unmeasurable, because a caller that has to branch on shape is a
    caller that will forget one of the branches."""
    out = {}
    for name, spec in SCORES.items():
        got = scores.get(name) or {}
        v = got.get("value")
        was = (prior.get(name) or {}).get("value")
        row = {"value": v, "unit": spec["unit"], "label": spec["label"],
               "best_before": was, "is_record": False, "delta": None,
               "previous_holder": (prior.get(name) or {}).get("race"),
               "previous_flown_at": (prior.get(name) or {}).get("flown_at"),
               "why": got.get("why"), "detail":
                   {k: x for k, x in got.items() if k not in ("value", "why")}}
        if v is not None:
            if was is None:
                row["is_record"] = True
            else:
                row["delta"] = round(v - was, 3)
                row["is_record"] = (v < was if spec["better"] == "lower" else v > was)
        out[name] = row
    return out


def entry_for(meta, replay, scores):
    """One row of the log. Small on purpose: the report folder holds the detail."""
    created = meta.get("created") or ""
    flown = created
    if len(created) == 15 and created[8] == ".":       # Liftoff's 20260907.151259
        flown = "%s-%s-%sT%s:%s:%s" % (created[0:4], created[4:6], created[6:8],
                                       created[9:11], created[11:13], created[13:15])
    return {"replay": Path(replay).stem, "flown_at": flown,
            "race": meta.get("_race_name") or meta.get("name"),
            "environment": meta.get("environment"),
            "scores": scores}
