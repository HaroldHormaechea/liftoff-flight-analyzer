#!/usr/bin/env python3
"""
manoeuvres.py - naming the acrobatic manoeuvres in a flight.

The toolkit ships eight manoeuvre cards in `manoeuvres/`, drawn with the same
figure code as the reports so a taught manoeuvre and a flown one are the same
picture. This module is the other half: it finds those eight in a real flight
and names them, so a debrief can say "three backflips, one fell out at 200
degrees" instead of the pilot having to remember.

WHAT SEPARATES THEM IS THE AXIS, NOT THE ATTITUDE
-------------------------------------------------
`tilt` - the angle between the mast and vertical - passes through 180 degrees in
a backflip and in an axial roll alike, so no threshold on it can tell a loop
from a barrel. The discriminator is which of the airframe's OWN axes the
rotation happened about, which is `kinematics.body_rotation`. From that, the
loop family separates on arithmetic:

    backflip     360 deg of pitch, no roll
    power loop   the same, but big enough to have gone round something
    axial roll   360 deg of roll, no pitch, and the path does not bend
    split-S      180 of roll THEN 180 of pitch - reverses, and loses height
    Immelmann    180 of pitch THEN 180 of roll - reverses, and gains height

The order of the two halves is what separates the last pair, and it is why this
module integrates the axes separately rather than only totalling them: a split-S
and an Immelmann have the same totals and opposite sequences.

The remaining three never leave upright, so attitude says nothing about them and
they are found in the PATH instead:

    orbit        a full circle with the nose pinned inward - so the tell is
                 sustained sideslip, which is exactly what a racing corner does
                 not have
    figure eight two full circles of OPPOSITE hand, joined
    dive         nose down, height traded for speed, pulled out level

CONFIDENCE IS REPORTED, NOT ASSUMED
-----------------------------------
Every detection carries `confidence`. "confirmed" means the defining arithmetic
is unambiguous - a full rotation about one axis and not the other. "probable"
means the shape fits but a race line could have produced it too. A partial
rotation is reported as the manoeuvre it was ATTEMPTING with `complete: false`,
because a backflip that fell out at 200 degrees is the most useful row in the
table, not something to hide.

The thresholds live here rather than in a sim's calibration file: a backflip is
360 degrees of pitch in every simulator, and in the real world. Only the sample
rate is a sim's business, and that arrives as `dt`.
"""

import math

from . import kinematics

# --- rotation, degrees --------------------------------------------------
FULL_ROT = 300.0      # a full turn about an axis, with room for a sloppy exit
HALF_ROT = 130.0      # a half turn - the split-S and Immelmann building block
IDLE_ROT = 120.0      # below this an axis was not being commanded at all
PARTIAL_ROT = 150.0   # a rotation worth reporting even though it did not finish

# --- attitude, degrees --------------------------------------------------
LEVEL_TILT = 40.0     # mast within this of vertical is "upright"
INVERTED_TILT = 100.0  # past this the quad is on its back
ACRO_TILT = 110.0     # a window must reach this to be acrobatic at all
NOSE_DOWN = 35.0      # nose below the horizon by this much is a dive attitude
NOSE_LEVEL = 12.0     # pulled out

# --- shape, metres and seconds ------------------------------------------
LOOP_CUT = 340.0      # a window is CUT here: past this, the next turn is a new manoeuvre
MERGE_GAP_S = 0.4     # two rotations closer than this are one manoeuvre
PAD_S = 0.4           # context kept either side of a detected window
POWER_LOOP_M = 6.0    # a loop this tall had room for an object inside it
POWER_LOOP_S = 3.5
REVERSAL_MAX_S = 6.0  # a split-S or Immelmann is over in a few seconds
PARTIAL_MAX_S = 5.0   # longer than this, an unfinished rotation is just flying
DIVE_DROP_M = 8.0
DIVE_GAIN_KMH = 12.0
DIVE_RATE_MS = 3.0    # a descent slower than this is a let-down, not a dive
DIVE_MAX_S = 6.0
STRAIGHT_HEADING = 50.0   # an axial roll does not turn the path
ORBIT_SWEEP = 330.0
LOBE_SWEEP = 260.0        # one lobe of a figure eight
ORBIT_HEIGHT_M = 3.5      # a circle is flown level
ORBIT_SLIP = 25.0         # nose pinned inward, not pointed along the path
EIGHT_HEIGHT_M = 5.0
EIGHT_JOIN_S = 2.0

TITLES = {
    "backflip": "Backflip",
    "power-loop": "Power loop",
    "axial-roll": "Axial roll",
    "split-s": "Split-S",
    "immelmann": "Immelmann",
    "orbit": "Orbit",
    "figure-eight": "Figure eight",
    "dive": "Dive and pull-out",
}

# Spelled out because none of the interesting ones are regular: "Split-Ses" and
# "dive and pull-outs" are what a rule produces, and both are wrong.
PLURALS = {
    "backflip": "backflips",
    "power-loop": "power loops",
    "axial-roll": "axial rolls",
    "split-s": "Split-S turns",
    "immelmann": "Immelmanns",
    "orbit": "orbits",
    "figure-eight": "figure eights",
    "dive": "dives",
}


# Mid-sentence forms. Most are common nouns and lowercase there; Split-S and
# Immelmann keep their capitals wherever they appear, so lowercasing the display
# title is not a substitute for spelling these out.
SENTENCE = {
    "backflip": "backflip",
    "power-loop": "power loop",
    "axial-roll": "axial roll",
    "split-s": "Split-S",
    "immelmann": "Immelmann",
    "orbit": "orbit",
    "figure-eight": "figure eight",
    "dive": "dive",
}


def name(slug, n=1):
    """The manoeuvre's name as it should read inside a sentence, singular or plural."""
    if n == 1:
        return SENTENCE.get(slug, slug)
    return PLURALS.get(slug, slug + "s")


def _pct(vals, q):
    if not vals:
        return 0.0
    v = sorted(vals)
    return v[min(len(v) - 1, int(len(v) * q / 100.0))]


def _runs(flags, min_len=1):
    """Maximal runs of True in a bool list, as [start, end) index pairs."""
    out, i = [], 0
    while i < len(flags):
        if not flags[i]:
            i += 1
            continue
        j = i
        while j < len(flags) and flags[j]:
            j += 1
        if j - i >= min_len:
            out.append([i, j])
        i = j
    return out


def _merge(spans, gap):
    out = []
    for a, b in spans:
        if out and a - out[-1][1] <= gap:
            out[-1][1] = b
        else:
            out.append([a, b])
    return out


def _crosses(cum, target):
    """First index at which |cum| reaches target, or None."""
    for i, v in enumerate(cum):
        if abs(v) >= target:
            return i
    return None


def _overlaps(taken, a, b):
    return any(a < e and s < b for s, e in taken)


def _heading_shift(data, i0, i1):
    """Net change of travel direction across a window, degrees, unwrapped."""
    before = next((data[i]["heading"] for i in range(i0, -1, -1)
                   if data[i]["heading"] is not None), None)
    after = next((data[i]["heading"] for i in range(i1 - 1, len(data))
                  if data[i]["heading"] is not None), None)
    if before is None or after is None:
        return None
    d = math.degrees(after - before)
    return (d + 180) % 360 - 180


def nose_elevation(series):
    """Angle of the nose above the horizon, per sample, degrees."""
    out = []
    for s in series:
        f = kinematics.rotate_vec(s.attitude, (0.0, 0.0, 1.0))
        out.append(math.degrees(math.asin(max(-1.0, min(1.0, f[1])))))
    return out


def _segment_of(i, ranges, names):
    for k, (a, b) in enumerate(ranges):
        if a <= i < b:
            return names[k]
    return names[-1] if names else "flight"


def _throttle_quarters(data, i0, i1):
    """Throttle by quarter of the manoeuvre.

    The quarters are not decoration. On a loop the first quarter is the entry
    punch that buys the height, and the third is where a ballistic flip coasts
    over the top - the two numbers a pilot is actually coached on.
    """
    n = i1 - i0
    if n < 4:
        return {}
    q = n // 4

    def part(a, b):
        return round(sum(d["thr"] for d in data[a:b]) / max(1, b - a), 2)

    return {"first_quarter": part(i0, i0 + q),
            "third_quarter": part(i0 + 2 * q, i0 + 3 * q),
            "median": round(_pct([d["thr"] for d in data[i0:i1]], 50), 2)}


def _base(data, i0, i1, ranges, names, n):
    seg = data[i0:i1]
    alts = [s["alt"] for s in seg]
    spds = [s["spd"] for s in seg]
    return {
        "n": n,
        "segment": _segment_of(i0, ranges, names),
        "t": round(data[i0]["t"] - data[0]["t"], 1),
        "duration_s": round(data[i1 - 1]["t"] - data[i0]["t"], 2),
        "index": [i0, i1],
        "focus": (i0 + i1) // 2,
        "height_entry_m": round(alts[0], 2),
        "height_peak_m": round(max(alts), 2),
        "height_exit_m": round(alts[-1], 2),
        "entry_kmh": round(spds[0], 1),
        "min_kmh": round(min(spds), 1),
        "exit_kmh": round(spds[-1], 1),
        "throttle": _throttle_quarters(data, i0, i1),
        "inverted_pct": round(100.0 * sum(1 for s in seg if s["tilt"] > INVERTED_TILT)
                              / max(1, len(seg))),
    }


# ---------------------------------------------------------------------------
# the rotation family
# ---------------------------------------------------------------------------

def _classify_rotation(m, dp, dr, heading, span_m, roll_first):
    """Name a window from its two rotation totals and its shape.

    Returns (slug, complete, confidence, note), or None to discard the window.
    """
    ap, ar = abs(dp), abs(dr)

    # A FULL turn of pitch is a loop, and it is tested first on purpose. A flip
    # flown with a hundred degrees of roll in it is still a flip; testing the
    # half-and-half case first would call it a split-S, which is a manoeuvre
    # that does not contain a full loop at all.
    if ap >= FULL_ROT:
        big = span_m >= POWER_LOOP_M and m["duration_s"] >= POWER_LOOP_S
        clean = ar < IDLE_ROT
        return (("power-loop" if big else "backflip"), True,
                "confirmed" if clean else "probable",
                "%.0f deg of pitch about the wing axis against %.0f deg of roll; "
                "a %s loop %.1f m tall%s"
                % (ap, ar, "large" if big else "tight", span_m,
                   "" if clean else " - it corkscrewed rather than staying in one plane"))

    if ar >= FULL_ROT and ap < IDLE_ROT:
        straight = heading is None or abs(heading) <= STRAIGHT_HEADING
        return ("axial-roll", True, "confirmed" if straight else "probable",
                "%.0f deg of roll about the nose axis against %.0f deg of pitch; "
                "the path %s"
                % (ar, ap, "held its line" if straight
                   else "bent %.0f deg, so this steered as much as it rolled"
                        % abs(heading)))

    # Half of each, and a full turn of neither: that is the reversal pair. The
    # duration cap matters as much as the angles - a window that took ten
    # seconds to gather 240 degrees on each axis is a stretch of ordinary flying
    # that happened to add up, not a manoeuvre anyone flew.
    if (HALF_ROT <= ap < FULL_ROT and HALF_ROT <= ar < FULL_ROT
            and m["duration_s"] <= REVERSAL_MAX_S):
        reversed_ = heading is not None and abs(heading) > 120
        climbed = m["height_exit_m"] - m["height_entry_m"]
        # Which half came FIRST is the whole difference between the two.
        slug = "split-s" if roll_first else "immelmann"
        agrees = (climbed < 0) if slug == "split-s" else (climbed > 0)
        return (slug, True, "confirmed" if (reversed_ and agrees) else "probable",
                "%s half came first (%.0f deg of roll, %.0f deg of pitch); "
                "height %+.1f m, heading %s"
                % ("the roll" if roll_first else "the pitch", ar, ap, climbed,
                   "reversed %.0f deg" % abs(heading) if reversed_
                   else "changed %.0f deg" % abs(heading or 0)))

    if m["duration_s"] <= PARTIAL_MAX_S:
        if ap >= PARTIAL_ROT and ar < IDLE_ROT:
            return ("backflip", False, "confirmed",
                    "the rotation stopped at %.0f deg of pitch - it did not come round"
                    % ap)
        if ar >= PARTIAL_ROT and ap < IDLE_ROT:
            return ("axial-roll", False, "confirmed",
                    "the rotation stopped at %.0f deg of roll - it did not come round"
                    % ar)

    return None


def _rotations(series, data, rot, ranges, names, dt):
    """Everything that left upright, named by the axis it turned about."""
    gap = max(1, int(round(MERGE_GAP_S / dt)))
    pad = max(1, int(round(PAD_S / dt)))
    spans = _merge(_runs([s["tilt"] > LEVEL_TILT for s in data], min_len=2), gap)

    out = []
    for a, b in spans:
        # THE GATE THAT KEEPS RACING OUT. A hard racing corner sits at 70-80
        # degrees of tilt for a second at a time and accumulates body-axis
        # rotation while it does, which is enough to look like a half loop. What
        # it never does is go past vertical. Every one of the five rotation
        # manoeuvres passes through inverted; a corner does not, so requiring the
        # window to reach 110 degrees separates them completely and cheaply.
        if max(data[i]["tilt"] for i in range(a, b)) < ACRO_TILT:
            continue
        for i0, i1 in _cut(rot, max(0, a - pad), min(len(data), b + pad)):
            got = _one_rotation(data, rot, ranges, names, i0, i1)
            if got is not None:
                out.append(got)
    return out


def _cut(rot, a, b):
    """Split one run of non-level flight into one window per rotation.

    Eleven backflips in ninety seconds are eleven manoeuvres, but the quad never
    settles back to upright for long between them, so a run of non-level samples
    covers several at once and totalling it reports 747 degrees of pitch as a
    single very large loop. Cutting whenever a full turn has accumulated about
    ONE axis restores the count without needing the quad to return to level.

    A split-S is 180 of roll and 180 of pitch, so neither axis reaches the cut
    and the pair stays in one window - which is what makes it recognisable.
    """
    out, start, dp, dr = [], a, 0.0, 0.0
    for i in range(a, b):
        dp += rot[i]["pitch"]
        dr += rot[i]["roll"]
        if abs(dp) >= LOOP_CUT or abs(dr) >= LOOP_CUT:
            out.append((start, i + 1))
            start, dp, dr = i + 1, 0.0, 0.0
    if b - start >= 2:
        out.append((start, b))
    return out


def _one_rotation(data, rot, ranges, names, i0, i1):
    """Classify a single already-cut window, or None if it is not a manoeuvre."""
    if i1 - i0 < 2:
        return None
    dp = sum(rot[i]["pitch"] for i in range(i0, i1))
    dr = sum(rot[i]["roll"] for i in range(i0, i1))
    if abs(dp) < PARTIAL_ROT and abs(dr) < PARTIAL_ROT:
        return None                        # a hard banked corner, not a manoeuvre

    cp, cr, sp, sr = [], [], 0.0, 0.0
    for i in range(i0, i1):
        sp += rot[i]["pitch"]
        sr += rot[i]["roll"]
        cp.append(sp)
        cr.append(sr)
    ip, ir = _crosses(cp, HALF_ROT), _crosses(cr, HALF_ROT)
    roll_first = ir is not None and (ip is None or ir < ip)

    if True:
        m = _base(data, i0, i1, ranges, names, 0)
        heading = _heading_shift(data, i0, i1)
        span_m = m["height_peak_m"] - min(s["alt"] for s in data[i0:i1])
        got = _classify_rotation(m, dp, dr, heading, span_m, roll_first)
        if got is None:
            return None
        slug, complete, conf, note = got
        m.update({"kind": slug, "title": TITLES[slug], "complete": complete,
                  "confidence": conf, "note": note,
                  "pitch_deg": round(dp), "roll_deg": round(dr),
                  "yaw_deg": round(sum(rot[i]["yaw"] for i in range(i0, i1))),
                  "heading_change_deg": None if heading is None else round(heading),
                  "found_by": "attitude"})
        return m


# ---------------------------------------------------------------------------
# the path family
# ---------------------------------------------------------------------------

def _sweeps(data, dt):
    """Maximal runs of consistently-signed turning, with their total sweep."""
    slack_cap = max(1, int(round(0.4 / dt)))
    sign = [0 if s["turn"] is None or abs(s["turn"]) < 8 else
            (1 if s["turn"] > 0 else -1) for s in data]
    out, i = [], 0
    while i < len(sign):
        if sign[i] == 0:
            i += 1
            continue
        j, want, slack = i, sign[i], 0
        while j < len(sign):
            if sign[j] == -want:
                break
            slack = 0 if sign[j] == want else slack + 1
            if slack > slack_cap:
                break
            j += 1
        total = sum(data[k]["turn"] * dt for k in range(i, j)
                    if data[k]["turn"] is not None)
        out.append((i, j, total))
        i = max(j, i + 1)
    return out


def _circles(data, ranges, names, dt, taken):
    """Orbits and figure eights: full circles, found in the path.

    Both are flown upright, so the attitude pass is blind to them. A racing lap
    also sweeps 360 degrees of heading eventually, which is why an orbit
    additionally has to show the nose pinned INWARD - sustained sideslip of one
    sign, which a coordinated racing corner never has.
    """
    out = []
    lobes = [(a, b, t) for a, b, t in _sweeps(data, dt) if abs(t) >= LOBE_SWEEP]
    used = set()

    # Figure eights first: two opposed lobes claim both, so a lone lobe cannot
    # then be reported a second time as an orbit.
    for k in range(len(lobes) - 1):
        if k in used or k + 1 in used:
            continue
        a0, b0, t0 = lobes[k]
        a1, b1, t1 = lobes[k + 1]
        if t0 * t1 >= 0:
            continue
        join = data[a1]["t"] - data[b0 - 1]["t"]
        if join > EIGHT_JOIN_S:
            continue
        alts = [s["alt"] for s in data[a0:b1]]
        if max(alts) - min(alts) > EIGHT_HEIGHT_M or _overlaps(taken, a0, b1):
            continue
        m = _base(data, a0, b1, ranges, names, 0)
        m.update({"kind": "figure-eight", "title": TITLES["figure-eight"],
                  "complete": True, "confidence": "confirmed",
                  "note": "two opposed circles of %.0f and %.0f deg joined %.1f s apart, "
                          "height held inside %.1f m"
                          % (abs(t0), abs(t1), join, max(alts) - min(alts)),
                  "sweep_deg": round(abs(t0) + abs(t1)), "found_by": "path"})
        out.append(m)
        used.update({k, k + 1})

    for k, (a, b, t) in enumerate(lobes):
        if k in used or abs(t) < ORBIT_SWEEP or _overlaps(taken, a, b):
            continue
        alts = [s["alt"] for s in data[a:b]]
        if max(alts) - min(alts) > ORBIT_HEIGHT_M:
            continue
        slips = [s["slip"] for s in data[a:b] if s["slip"] is not None]
        if not slips:
            continue
        inward = [s for s in slips if s * t > 0]     # nose turned into the circle
        med = _pct([abs(s) for s in slips], 50)
        if med < ORBIT_SLIP or len(inward) < 0.6 * len(slips):
            continue
        m = _base(data, a, b, ranges, names, 0)
        m.update({"kind": "orbit", "title": TITLES["orbit"], "complete": True,
                  "confidence": "confirmed",
                  "note": "%.0f deg of turn at a median %.0f deg of sideslip, so the nose "
                          "stayed pointed inward; height held inside %.1f m"
                          % (abs(t), med, max(alts) - min(alts)),
                  "sweep_deg": round(abs(t)), "found_by": "path"})
        out.append(m)
    return out


def _dives(data, series, ranges, names, dt, taken):
    """Nose over, accelerate down a face, pull out level.

    Deliberately strict about the ATTITUDE. Every race track descends somewhere,
    and a shallow descent flown fast is not a dive: the nose has to actually go
    down, and the speed has to be bought with the height.
    """
    elev = nose_elevation(series)
    steep = _runs([e <= -NOSE_DOWN and data[i]["tilt"] < INVERTED_TILT
                   for i, e in enumerate(elev)], min_len=max(2, int(round(0.3 / dt))))
    out = []
    for a, b in _merge(steep, max(1, int(round(0.5 / dt)))):
        i0, i1 = a, b
        while i0 > 0 and elev[i0 - 1] < -NOSE_LEVEL:
            i0 -= 1
        while i1 < len(elev) - 1 and elev[i1] < -NOSE_LEVEL:
            i1 += 1
        if _overlaps(taken, i0, i1):
            continue
        alts = [s["alt"] for s in data[i0:i1]]
        drop = max(alts) - min(alts)
        gain = max(s["spd"] for s in data[i0:i1]) - data[i0]["spd"]
        secs = data[i1 - 1]["t"] - data[i0]["t"]
        # Rate as well as depth. Letting the quad down six metres over eight
        # seconds satisfies any threshold on height alone, and it is not a dive.
        if drop < DIVE_DROP_M or gain < DIVE_GAIN_KMH:
            continue
        if secs > DIVE_MAX_S or drop / max(0.1, secs) < DIVE_RATE_MS:
            continue
        pulled = elev[min(i1, len(elev) - 1)] > -NOSE_LEVEL
        m = _base(data, i0, i1, ranges, names, 0)
        m.update({"kind": "dive", "title": TITLES["dive"], "complete": pulled,
                  "confidence": "confirmed" if pulled else "probable",
                  "note": "nose down to %.0f deg, %.1f m of height traded for %+.0f km/h%s"
                          % (min(elev[i0:i1]), drop, gain,
                             "" if pulled
                             else " - it did not level out inside the window"),
                  "nose_min_deg": round(min(elev[i0:i1])),
                  "drop_m": round(drop, 1), "found_by": "path"})
        out.append(m)
    return out


# ---------------------------------------------------------------------------

def detect(series, data, ranges, names, dt):
    """Every manoeuvre in one flight, in the order flown.

    `series` is the schema.FlightSeries, because attitude lives there; `data` is
    the per-sample working values from analysis.load(). Both are needed - the
    rotation axes come from the quaternions and everything else from the derived
    values - and neither alone is enough.

    The three passes run in decreasing order of certainty and each one claims
    the samples it used, so a loop is never also reported as the dive that its
    back half looks like.
    """
    if len(series) < 4 or len(data) < 4 or len(series) != len(data):
        return []
    rot = kinematics.body_rotation(series)

    found = _rotations(series, data, rot, ranges, names, dt)
    found += _circles(data, ranges, names, dt, [tuple(m["index"]) for m in found])
    found += _dives(data, series, ranges, names, dt,
                    [tuple(m["index"]) for m in found])

    found.sort(key=lambda m: m["index"][0])
    for i, m in enumerate(found, 1):
        m["n"] = i
    return found


def tally(found):
    """{slug: count}, in the order the manoeuvres were first flown."""
    out = {}
    for m in found:
        out[m["kind"]] = out.get(m["kind"], 0) + 1
    return out
