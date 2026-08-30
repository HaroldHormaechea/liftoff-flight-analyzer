#!/usr/bin/env python3
"""
analysis.py - flight-geometry analysis of a decoded flight.

Consumes a FlightSeries decoded by a sim's source.py (Liftoff: 10 Hz) or a CSV
written by its telemetry capture
(100 Hz). Both carry position, attitude quaternion and stick positions, which is
everything this needs.

What it computes, and why each one earns its place
--------------------------------------------------
* SIDESLIP - the signed angle between where the nose points and where the quad
  is actually travelling. This is THE diagnostic for the yaw-lead skid: yawing
  faster than bank-plus-throttle curves the path means pointing into the turn
  while still moving outward. Under about 10 degrees is coordinated; 30+ is a
  skid; near 90 means travelling sideways with no lift authority left.
* TILT - the angle of the thrust axis off vertical. On a quad this is the whole
  turning force, so it is the honest measure of commitment in a corner.
* TURN RADIUS - speed divided by turn rate. Separates a committed arc from a
  flat yaw-around.
* THROTTLE DELTA THROUGH THE CORNER - bank sets the DIRECTION of the turning
  force, throttle sets its MAGNITUDE. A corner flown with no throttle increase
  is a corner that will go wide and sink. Positive delta means the coaching
  landed.

Corners are runs of sustained turn rate above a threshold, measured only above a
speed floor, because sideslip is meaningless when nearly stationary.

* YAW-ONLY TIME - time with meaningful yaw held while roll stays at zero. A turn
  flown on yaw alone is a pirouette: the airframe rotates, the path does not
  bend. Reported whole-segment and split by speed band, because the fault shows
  up as yaw authority rising while roll authority stays flat as speed drops.

STALLS AND WHY EACH ONE HAPPENED
--------------------------------
A stall is a run of samples below --stall-speed. Finding them is easy; the value
is in saying WHY, and that is a deterministic decision table, not a judgement:

  overrun     the path REVERSES and retraces itself - heading swings at least
              --reversal-deg and the recovery passes within --retrace-m of
              ground already covered. The pilot went past the point, stopped,
              spun and came back.
  corner      another lap of the same flight turns hard at the same coordinates,
              so the direction change was the track asking for it.
  hesitation  another lap passes the same coordinates going essentially straight.
              Nothing there needed a stop.

The cross-lap probe is the decisive test and it needs no gate data: if a
different lap flies the same coordinates straight through at speed, the event
belongs to the pilot, not the track. It requires --laps with two or more laps.
With one lap only, classification falls back to the reversal test plus the
flight's own turn angle, and the report says so.

Defaults were fixed against the Rustline 2-lap race of 2026-08-26, in which the
five hand-analysed events measured: overruns at retrace 0.3 and 0.4 m with 174
and 172 deg of reversal; non-overruns at retrace 7.1, 15.7 and 18.2 m with 100,
105 and 34 deg. Every threshold below sits in the gap between those two groups,
and every one is a CLI flag, so a default can be moved without touching code.

Usage
-----
  python "<clone>/src" analyse flight.csv
  python "<clone>/src" analyse flight.csv --laps "73:1077,1077:1768"  # sample indices
  python "<clone>/src" analyse flight.csv --laps "..." --trace        # stick traces
  python "<clone>/src" analyse flight.csv --json
"""

import argparse
import json
import math
import sys


def rotate(q, v):
    """Rotate vector v by quaternion q = (x, y, z, w)."""
    x, y, z, w = q
    tx = 2 * (y * v[2] - z * v[1])
    ty = 2 * (z * v[0] - x * v[2])
    tz = 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + (y * tz - z * ty),
            v[1] + w * ty + (z * tx - x * tz),
            v[2] + w * tz + (x * ty - y * tx))


def pct(vals, q):
    if not vals:
        return float("nan")
    v = sorted(vals)
    return v[min(len(v) - 1, int(len(v) * q / 100))]


def load(series, speed_floor_kmh):
    """The per-sample working values the rest of this module reads.

    Takes a common.schema.FlightSeries. It used to take a path and parse
    flight.csv itself; the CSV is now a side output rather than the pipe between
    stages, so the series arrives directly and is never serialised in between.
    """
    if not len(series):
        sys.exit("no samples to analyse")
    out = []
    for i, s in enumerate(series):
        q = s.attitude
        vel = s.velocity
        t = s.t
        px, py, pz = s.pos
        thr, yaw = s.throttle, s.yaw
        pit, rol = s.pitch, s.roll

        fwd = rotate(q, (0, 0, 1))
        up = rotate(q, (0, 1, 0))
        vh = math.hypot(vel[0], vel[2])
        spd = math.sqrt(sum(c * c for c in vel)) * 3.6
        heading = math.atan2(vel[0], vel[2]) if vh > 0.5 else None
        slip = None
        if heading is not None and spd >= speed_floor_kmh:
            d = math.degrees(math.atan2(fwd[0], fwd[2]) - heading)
            slip = (d + 180) % 360 - 180
        out.append({
            "i": i, "t": t, "alt": py,
            "x": px, "z": pz,
            "spd": spd, "vh": vh, "vy": vel[1], "heading": heading, "slip": slip,
            "tilt": math.degrees(math.acos(max(-1.0, min(1.0, up[1])))),
            "thr": thr, "yaw": yaw,
            "pitch": pit, "roll": rol,
        })
    for i, s in enumerate(out):
        a, b = out[max(0, i - 1)], out[min(len(out) - 1, i + 1)]
        if a["heading"] is None or b["heading"] is None or b["t"] <= a["t"]:
            s["turn"] = s["radius"] = None
            continue
        d = math.degrees(b["heading"] - a["heading"])
        d = (d + 180) % 360 - 180
        s["turn"] = d / (b["t"] - a["t"])
        s["radius"] = s["vh"] / abs(math.radians(s["turn"])) if abs(s["turn"]) > 3 else None
    return out


def find_corners(seg, turn_thresh, speed_floor, min_samples):
    fast = [s for s in seg if s["spd"] > speed_floor and s["turn"] is not None]
    out, cur = [], []
    for s in fast:
        if abs(s["turn"]) > turn_thresh:
            cur.append(s)
        else:
            if len(cur) >= min_samples:
                out.append(cur)
            cur = []
    if len(cur) >= min_samples:
        out.append(cur)
    return out


def corner_stats(c, t0):
    rad = [s["radius"] for s in c if s["radius"]]
    return {
        "t": round(c[0]["t"] - t0, 1),
        "entry_kmh": round(c[0]["spd"]),
        "min_kmh": round(min(s["spd"] for s in c)),
        "exit_kmh": round(c[-1]["spd"]),
        "tilt_deg": round(sum(s["tilt"] for s in c) / len(c)),
        "sideslip_deg": round(sum(abs(s["slip"]) for s in c if s["slip"] is not None)
                              / max(1, sum(1 for s in c if s["slip"] is not None)), 1),
        "radius_m": round(sum(rad) / len(rad), 1) if rad else None,
        "throttle_in": round(c[0]["thr"], 2),
        "throttle_mid": round(sum(s["thr"] for s in c) / len(c), 2),
        "throttle_delta": round(sum(s["thr"] for s in c) / len(c) - c[0]["thr"], 2),
    }


def sample_dt(data):
    """Median sample interval. Median, not first-difference, so one dropped
    sample cannot rescale every window in the report."""
    d = sorted(data[i + 1]["t"] - data[i]["t"] for i in range(len(data) - 1))
    return d[len(d) // 2] if d else 0.1


def bearing(p, q):
    """Ground-plane bearing from point p to point q, degrees."""
    return math.degrees(math.atan2(q[0] - p[0], q[1] - p[1]))


def wrap(deg):
    return (deg + 180) % 360 - 180


def xz(s):
    return (s["x"], s["z"])


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def find_stalls(data, a, b, speed, min_s, gap_s, idle_thr, dt):
    """Maximal runs below `speed`, bridging gaps up to `gap_s`.

    Two deterministic rejections: runs shorter than `min_s`, and runs whose
    MEDIAN throttle is under `idle_thr` - motors idle for most of the run means
    sitting on the grid or lying crashed, not a stall in flight.

    Median, not peak: the grid wait ends with the pilot spooling up to launch, so a
    peak test passes the one episode it most needs to reject. The margin is
    wide either way - the 2026-08-26 grid wait sat at 0.00 median throttle and
    every real stall in that flight was between 0.43 and 0.51.
    """
    idx = [i for i in range(a, b) if data[i]["spd"] < speed]
    if not idx:
        return []
    gap_n = max(1, int(round(gap_s / dt)))
    groups, cur = [], [idx[0]]
    for i in idx[1:]:
        if i - cur[-1] <= gap_n:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    out = []
    for g in groups:
        s, e = g[0], g[-1]
        if s == 0:
            continue  # recording starts before launch; that is not a stall
        if (e - s + 1) * dt < min_s:
            continue
        thr = sorted(data[j]["thr"] for j in range(s, e + 1))
        if thr[len(thr) // 2] < idle_thr:
            continue
        out.append((s, e))
    return out


def stall_geometry(data, s, e, dt, args, prev_end=None, next_start=None):
    """Heading reversal, path retrace and net progress across one stall.

    Windows are specified in seconds and converted through the measured sample
    interval, so a 10 Hz replay and a 100 Hz telemetry capture give the same
    answer.

    Windows are clamped THREE ways, in this order:
      1. to the bounds of the data;
      2. to the neighbouring stalls - `prev_end` and `next_start`. Two stalls
         four seconds apart would otherwise each measure their heading across
         the other one, and the answer would depend on how far apart they
         happened to fall. Stalls come in clusters on a bad lap, so this is the
         normal case, not an edge case;
      3. to a minimum of two samples. A window that cannot meet that yields
         None rather than a fabricated number, and the verdict degrades to the
         evidence that survives.

    `net_m` is progress ACROSS the event: how far the quad actually got between
    entering the stall and leaving it. Small net with a large turn is the
    signature of stopping and coming back.
    """
    n = len(data)
    ns = lambda sec: max(1, int(round(sec / dt)))
    lead = ns(args.lead)
    floor = 0 if prev_end is None else prev_end + 1
    ceil = n if next_start is None else next_start
    pre_a, pre_b = max(floor, s - ns(args.pre_window)), max(floor, s - lead)
    post_a = min(ceil - 1, e + lead)
    post_b = min(ceil, e + ns(args.post_window))
    g = {"turn_deg": None, "retrace_m": None, "net_m": None}
    if pre_b - pre_a >= 2 and post_b - post_a >= 2:
        h_in = bearing(xz(data[pre_a]), xz(data[pre_b]))
        h_out = bearing(xz(data[post_a]), xz(data[post_b - 1]))
        g["turn_deg"] = wrap(h_out - h_in)
        g["net_m"] = dist(xz(data[pre_b]), xz(data[post_a]))
    hist_a = max(0, s - ns(args.history_window))
    hist_b = max(0, s - ns(args.retrace_exclude))
    if hist_b - hist_a >= 2 and post_b - post_a >= 1:
        hist = [xz(data[j]) for j in range(hist_a, hist_b)]
        g["retrace_m"] = min(min(dist(xz(data[j]), h) for h in hist)
                             for j in range(post_a, post_b))
    return g


def probe_other_laps(data, ranges, own, point, dt, half_s):
    """What every OTHER lap was doing at the same coordinates.

    Returns the single closest pass across all other laps. Ties on distance
    resolve to the lower sample index, so the result never depends on dict or
    iteration order.
    """
    half = max(1, int(round(half_s / dt)))
    best = None
    for k, (a, b) in enumerate(ranges):
        if k == own or b - a < 2 * half + 2:
            continue
        j = min(range(a + half, b - half),
                key=lambda i: (dist(xz(data[i]), point), i))
        w = range(j - half, j + half + 1)
        mid = max(1, half // 2)
        h_in = bearing(xz(data[j - half]), xz(data[j - mid]))
        h_out = bearing(xz(data[j + mid]), xz(data[j + half]))
        cand = {
            "lap": k + 1,
            "dist_m": dist(xz(data[j]), point),
            "speed_kmh": sum(data[i]["spd"] for i in w) / len(w),
            "turn_deg": wrap(h_out - h_in),
        }
        if best is None or (cand["dist_m"], j) < (best["dist_m"], best["_j"]):
            cand["_j"] = j
            best = cand
    if best:
        best.pop("_j", None)
    return best


def classify_stall(g, other, args):
    """Ordered decision table. First rule that matches wins; no rule is skipped
    on a hunch and none of them look at anything but the numbers above.

    The reversal test is checked FIRST and deliberately outranks the cross-lap
    probe: doubling back on your own track is an overrun even when a real corner
    happens to sit at the same place. That is exactly the 236.6 s case, where the pilot
    missed a genuine 93-degree corner and reversed to re-take it.
    """
    turn = abs(g["turn_deg"]) if g["turn_deg"] is not None else None
    if (g["retrace_m"] is not None and turn is not None
            and g["retrace_m"] <= args.retrace_m and turn >= args.reversal_deg):
        return "overrun", "reversed %.0f deg, retraced to %.1f m" % (turn, g["retrace_m"])
    if other is not None and other["dist_m"] <= args.near_m:
        if abs(other["turn_deg"]) >= args.corner_deg:
            return "corner", "lap %d turns %+.0f deg here" % (other["lap"], other["turn_deg"])
        return "hesitation", "lap %d goes straight here at %.0f km/h" % (
            other["lap"], other["speed_kmh"])
    if turn is not None and turn >= args.corner_deg:
        return "corner?", "no cross-lap evidence; own turn %.0f deg" % turn
    return "hesitation?", "no cross-lap evidence"


def yaw_only_stats(seg, dt, args):
    """Time spent rotating the airframe without banking the path.

    Sample counts are converted to seconds through the measured interval, so the
    numbers mean the same thing at 10 Hz and at 100 Hz.
    """
    yaw_on = [s for s in seg if abs(s["yaw"]) > args.yaw_on]
    only = [s for s in yaw_on if abs(s["roll"]) < args.roll_off]
    bands = []
    for lo, hi in ((0, 20), (20, 35), (35, 10 ** 6)):
        b = [s for s in seg if lo <= s["spd"] < hi]
        if not b:
            continue
        bands.append({
            "band": "%d-%s" % (lo, "max" if hi > 10 ** 5 else hi),
            "seconds": round(len(b) * dt, 1),
            "roll_p90": round(pct([abs(s["roll"]) for s in b], 90), 2),
            "yaw_p90": round(pct([abs(s["yaw"]) for s in b], 90), 2),
        })
    return {
        "yaw_seconds": round(len(yaw_on) * dt, 1),
        "yaw_only_seconds": round(len(only) * dt, 1),
        "yaw_only_pct": round(100 * len(only) / len(yaw_on)) if yaw_on else None,
        "yaw_only_mean_kmh": round(sum(s["spd"] for s in only) / len(only), 1) if only else None,
        "bands": bands,
    }


def segment_stats(seg, dt, stall_speed):
    """Whole-segment summary.

    Speed, tilt and throttle are measured over EVERY sample. Sideslip is the one
    statistic restricted to moving samples, because the angle between nose and
    velocity is undefined when there is no velocity. Restricting the rest would
    silently delete the stalled time from the medians and undercount the very
    thing the stall section exists to find.
    """
    sp = [s["spd"] for s in seg]
    sl = [abs(s["slip"]) for s in seg if s["slip"] is not None]
    return {
        "duration_s": round(seg[-1]["t"] - seg[0]["t"], 1),
        "speed_median": round(pct(sp, 50)), "speed_p90": round(pct(sp, 90)),
        "speed_max": round(max(sp)),
        "tilt_median": round(pct([s["tilt"] for s in seg], 50)),
        "tilt_p90": round(pct([s["tilt"] for s in seg], 90)),
        "sideslip_median": round(pct(sl, 50), 1), "sideslip_p90": round(pct(sl, 90), 1),
        "sideslip_samples": len(sl),
        "throttle_median": round(pct([s["thr"] for s in seg], 50), 2),
        "slow_seconds": round(sum(1 for s in seg if s["spd"] < stall_speed) * dt, 1),
    }


def build_parser(calibration):
    """The CLI, exposed so other tools can borrow the thresholds.

    common/report.py embeds this analysis rather than re-deriving it, so the
    numbers in a written report and the numbers on the terminal come from one
    implementation and one set of defaults. Adding a threshold here reaches
    both.

    `calibration` is the sim's calibration module. Every default below is read
    from its THRESHOLDS table instead of being written here, because every one
    of them was measured on one sim's flights: a literal in this file would
    apply Liftoff's numbers to a sim they were never measured against, silently
    and with nothing to tell a reader it had happened.

    The help text still quotes the Liftoff figures. That is deliberate - it is
    the evidence for a value, not a second copy of it - but a sim supplying its
    own thresholds will want to supply its own wording with them."""
    T = calibration.THRESHOLDS
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--laps", help='sample-index ranges, "73:1077,1077:1768"')
    ap.add_argument("--turn-threshold", type=float, default=T["turn_threshold"], help="deg/s")
    ap.add_argument("--speed-floor", type=float, default=T["speed_floor"],
                    help="km/h below which sideslip is not meaningful")
    ap.add_argument("--min-samples", type=int, default=T["min_samples"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--trace", action="store_true",
                    help="print the sample-by-sample stick trace around each stall")
    ap.add_argument("--no-stalls", action="store_true", help="skip the stall section")

    g = ap.add_argument_group(
        "stall detection",
        "What counts as a stall. All windows are seconds and are converted "
        "through the measured sample interval.")
    g.add_argument("--stall-speed", type=float, default=T["stall_speed"],
                   help="km/h below which the quad is not making progress (default 10)")
    g.add_argument("--stall-min", type=float, default=T["stall_min"],
                   help="shortest run worth reporting, seconds (default 0.5)")
    g.add_argument("--stall-gap", type=float, default=T["stall_gap"],
                   help="bridge sub-runs separated by less than this, seconds "
                        "(default 1.0; one bounce back over the threshold is "
                        "still the same event)")
    g.add_argument("--idle-throttle", type=float, default=T["idle_throttle"],
                   help="median throttle below which the run is grid time or a "
                        "dead quad, not a stall (default 0.05)")

    g = ap.add_argument_group(
        "stall geometry",
        "Windows used to measure what happened around a stall.")
    g.add_argument("--lead", type=float, default=T["lead"],
                   help="seconds skipped either side of the stall before "
                        "measuring heading, so the brake and the recovery do not "
                        "contaminate it (default 1.5)")
    g.add_argument("--pre-window", type=float, default=T["pre_window"],
                   help="seconds before the stall used for inbound heading (default 4.0)")
    g.add_argument("--post-window", type=float, default=T["post_window"],
                   help="seconds after the stall used for outbound heading (default 4.5)")
    g.add_argument("--history-window", type=float, default=T["history_window"],
                   help="how far back the retrace test looks for ground already "
                        "covered, seconds (default 15.0)")
    g.add_argument("--retrace-exclude", type=float, default=T["retrace_exclude"],
                   help="seconds immediately before the stall excluded from the "
                        "retrace test, so the approach itself cannot count as a "
                        "retrace (default 3.0)")
    g.add_argument("--probe-half-window", type=float, default=T["probe_half_window"],
                   help="half-width of the window measured on the other lap "
                        "at the same coordinates, seconds (default 2.5)")

    g = ap.add_argument_group(
        "stall classification thresholds",
        "The decision table. Each default sits in the gap between the two "
        "groups measured on 2026-08-26; see the module docstring.")
    g.add_argument("--retrace-m", type=float, default=T["retrace_m"],
                   help="recovery passing within this of earlier ground counts "
                        "as retracing (default 3.0; overruns measured 0.3-0.4 m, "
                        "everything else 7.1 m or more)")
    g.add_argument("--reversal-deg", type=float, default=T["reversal_deg"],
                   help="heading change that counts as doubling back (default "
                        "120; overruns measured 172-174 deg, everything else 105 or less)")
    g.add_argument("--near-m", type=float, default=T["near_m"],
                   help="how close another lap must pass for its behaviour to "
                        "be evidence about this spot (default 15.0)")
    g.add_argument("--corner-deg", type=float, default=T["corner_deg"],
                   help="heading change that counts as a real corner rather "
                        "than a straight (default 30)")
    g.add_argument("--offline-m", type=float, default=T["offline_m"],
                   help="distance from the other lap's line that is flagged as "
                        "a line error rather than a stick error (default 8.0)")

    g = ap.add_argument_group("yaw-only detection")
    g.add_argument("--yaw-on", type=float, default=T["yaw_on"],
                   help="stick deflection that counts as commanded yaw (default 0.20)")
    g.add_argument("--roll-off", type=float, default=T["roll_off"],
                   help="stick deflection below which roll counts as absent "
                        "(default 0.05)")
    return ap


def default_args(csv_path, calibration):
    """Every threshold at its default, for callers that embed the analysis."""
    return build_parser(calibration).parse_args([csv_path])


def parse_laps(spec, n):
    """"a:b,c:d" of sample indices -> [(a, b), ...] clamped to the data."""
    out = []
    for part in spec.split(","):
        a, b = (int(x) for x in part.split(":"))
        out.append((max(0, a), min(n, b)))
    return out


def analyse(data, ranges, names, dt, args):
    """The whole analysis, as data. the `analyse` command prints it; report.py draws it."""
    report = []
    for k, (a, b) in enumerate(ranges):
        raw = data[a:b]
        moving = [s for s in raw if s["heading"] is not None]
        if not moving:
            continue
        entry = {"segment": names[k]}
        entry.update(segment_stats(raw, dt, args.stall_speed))
        entry["corners"] = [corner_stats(c, moving[0]["t"]) for c in
                            find_corners(moving, args.turn_threshold, args.speed_floor,
                                         args.min_samples)]
        entry["yaw_only"] = yaw_only_stats(raw, dt, args)
        entry["stalls"] = []
        if not args.no_stalls:
            found = find_stalls(data, a, b, args.stall_speed, args.stall_min,
                                args.stall_gap, args.idle_throttle, dt)
            for n_i, (s, e) in enumerate(found):
                deep = min(range(s, e + 1), key=lambda i: (data[i]["spd"], i))
                geo = stall_geometry(
                    data, s, e, dt, args,
                    prev_end=found[n_i - 1][1] if n_i > 0 else None,
                    next_start=found[n_i + 1][0] if n_i + 1 < len(found) else None)
                other = probe_other_laps(data, ranges, k, xz(data[deep]), dt,
                                         args.probe_half_window)
                verdict, why = classify_stall(geo, other, args)
                entry["stalls"].append({
                    "t": round(data[s]["t"] - data[0]["t"], 1),
                    "index": [s, e],
                    "duration_s": round((e - s + 1) * dt, 1),
                    "min_kmh": round(data[deep]["spd"], 1),
                    "turn_deg": round(geo["turn_deg"]) if geo["turn_deg"] is not None else None,
                    "retrace_m": round(geo["retrace_m"], 1) if geo["retrace_m"] is not None else None,
                    "net_m": round(geo["net_m"], 1) if geo["net_m"] is not None else None,
                    "peak_yaw": round(max(abs(data[j]["yaw"]) for j in range(s, e + 1)), 2),
                    "peak_roll": round(max(abs(data[j]["roll"]) for j in range(s, e + 1)), 2),
                    "verdict": verdict,
                    "why": why,
                    "other_lap": ({"lap": other["lap"],
                                   "dist_m": round(other["dist_m"], 1),
                                   "speed_kmh": round(other["speed_kmh"], 1),
                                   "turn_deg": round(other["turn_deg"])}
                                  if other else None),
                    "off_line": bool(other and other["dist_m"] > args.offline_m),
                })
        report.append(entry)
    return report


