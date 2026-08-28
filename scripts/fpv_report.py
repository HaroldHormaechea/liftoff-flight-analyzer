#!/usr/bin/env python3
"""
fpv_report.py - turn a Liftoff replay into an illustrated Markdown debrief.

One command takes a saved replay to a folder holding the decoded CSV, a set of
SVG figures, animated SVG replays of the lap and of every stall, and a report.md
that embeds them all.

Why this exists
---------------
analyze_flight.py answers "what were the numbers". It cannot answer "where on
the track", and the numbers that matter most here are geometric: a line taken
wide, a corner entered flat, a nose that keeps rotating after the quad has
stopped moving. Those are pictures. This script draws them from the same samples
the numbers come from, so a figure and a table can never disagree.

It does NOT write the coaching. It writes what happened, and leaves a Debrief
section to fill in by hand, because the diagnosis depends on what the pilot has
already been told and the script does not know that.

Everything is standard library
------------------------------
Figures are hand-written SVG and the animations are SMIL, so there is no
matplotlib, no Pillow, no ffmpeg, and the output is diffable text that scales to
any size. Animated SVG plays in any browser and in the VS Code Markdown preview.
Where it does not play, every animation still reads as a static picture, because
the whole line and all the annotations are drawn underneath the animation.

Figures use CSS custom properties inside a prefers-color-scheme media query, so
one file is legible on a light and on a dark background.

Usage
-----
  python fpv_report.py --latest
  python fpv_report.py replays/<archived-replay>.xml
  python fpv_report.py <replay.xml> -o reports --no-anim
  python fpv_report.py <replay.xml> --laps "732:1879,1879:3056"
  python fpv_report.py --latest --no-open

Lap ranges come from the replay metadata automatically; --laps only overrides
them, for an abandoned attempt worth splitting by hand.

report.html opens in the default browser once it is written, because the report
is the deliverable and a path printed to a terminal is not one. --no-open
suppresses that, which is what a batch run wants, or an agent regenerating the
same report several times to hand-write the Debrief.
"""

import argparse
import csv
import json
import math
import os
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analyze_flight as AF
import liftoff_replay as LR

# ---------------------------------------------------------------------------
# palette
#
# The speed ramp is red -> amber -> teal, deliberately not red -> green: it
# stays separable for the common colour-vision deficiencies, and both ends hold
# their contrast on a white and on a dark page.
# ---------------------------------------------------------------------------

SPEED_STOPS = [(0.0, (209, 73, 91)), (0.5, (237, 174, 73)), (1.0, (42, 157, 143))]
SPEED_BANDS = 14
LAP_HUES = ["#4c78d8", "#e4572e", "#2a9d8f", "#9b5de5", "#f4a261", "#118ab2"]
SEP = "  ·  "          # runs of plain spaces collapse in SVG text

CSS = """
:root{--bg:#ffffff;--pan:#f4f6f8;--fg:#1b1d21;--mut:#6b7178;--grid:#dfe3e8;
--warn:#c8384b;--ok:#1f8a7d;--acc:#3f6fd0;--halo:#ffffff}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--pan:#1c1f25;--fg:#e7e9ec;
--mut:#8b9199;--grid:#2b3037;--warn:#ef6d7d;--ok:#4fbfae;--acc:#7aa2f7;--halo:#14161a}}
text{font-family:'DejaVu Sans','Segoe UI',Helvetica,Arial,sans-serif;fill:var(--fg)}
.mut{fill:var(--mut)}
.ttl{font-weight:600}
.grid{stroke:var(--grid);stroke-width:1;fill:none}
.axis{stroke:var(--mut);stroke-width:1;fill:none;opacity:.5}
.pan{fill:var(--pan)}
"""


def ramp(f):
    f = max(0.0, min(1.0, f))
    for i in range(len(SPEED_STOPS) - 1):
        a, ca = SPEED_STOPS[i]
        b, cb = SPEED_STOPS[i + 1]
        if a <= f <= b:
            k = (f - a) / (b - a) if b > a else 0.0
            return "#%02x%02x%02x" % tuple(round(ca[j] + k * (cb[j] - ca[j])) for j in range(3))
    return "#888888"


# ---------------------------------------------------------------------------
# svg plumbing
# ---------------------------------------------------------------------------


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def n(v, d=2):
    """Short fixed point. An SVG of a flight is almost entirely coordinates, and
    trimming them to what a screen can resolve roughly halves the file."""
    return ("%.*f" % (d, v)).rstrip("0").rstrip(".") or "0"


def doc(w, h, body, title=""):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
            'width="%d" height="%d" role="img"><title>%s</title><style>%s</style>'
            '<rect width="%d" height="%d" fill="var(--bg)"/>%s</svg>'
            % (w, h, w, h, esc(title), CSS, w, h, body))


def txt(x, y, s, size=12, cls="", anchor="start", extra="", body=None):
    """`body` injects child elements - an animation - into the text node. The
    label must stay the text content, so it cannot be smuggled in via extra."""
    return ('<text x="%s" y="%s" font-size="%s" text-anchor="%s" class="%s" %s>%s%s</text>'
            % (n(x), n(y), n(size, 1), anchor, cls, extra, esc(s), body or ""))


def poly(pts, stroke, width=2, extra=""):
    d = " ".join("%s,%s" % (n(p[0], 1), n(p[1], 1)) for p in pts)
    return ('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s" '
            'stroke-linecap="round" stroke-linejoin="round" %s/>'
            % (d, stroke, n(width, 2), extra))


def panel(x, y, w, h, r=6):
    return ('<rect x="%s" y="%s" width="%s" height="%s" rx="%d" class="pan"/>'
            % (n(x), n(y), n(w), n(h), r))


class Proj:
    """World XZ -> panel pixels. Equal aspect, +z up the screen."""

    def __init__(self, samples, x, y, w, h, pad=16, bounds=None):
        if bounds:
            self.x0, self.x1, self.z0, self.z1 = bounds
        else:
            xs = [s["x"] for s in samples]
            zs = [s["z"] for s in samples]
            self.x0, self.x1 = min(xs), max(xs)
            self.z0, self.z1 = min(zs), max(zs)
        self.s = min((w - 2 * pad) / max(1e-6, self.x1 - self.x0),
                     (h - 2 * pad) / max(1e-6, self.z1 - self.z0))
        self.ox = x + pad + ((w - 2 * pad) - self.s * (self.x1 - self.x0)) / 2
        self.oy = y + pad + ((h - 2 * pad) - self.s * (self.z1 - self.z0)) / 2

    def __call__(self, s):
        return (self.ox + (s["x"] - self.x0) * self.s,
                self.oy + (self.z1 - s["z"]) * self.s)


def bounds_of(samples):
    xs = [s["x"] for s in samples]
    zs = [s["z"] for s in samples]
    return (min(xs), max(xs), min(zs), max(zs))


def fit_height(bounds, w, pad=16, lo=190, hi=520):
    """Panel height that matches the track's own shape.

    A fixed square panel is what makes a map look like a doodle: this track is
    roughly five times wider than it is deep, so a square panel spends most of
    its area on nothing and shrinks the line to a thread."""
    dx, dz = max(1e-6, bounds[1] - bounds[0]), max(1e-6, bounds[3] - bounds[2])
    return max(lo, min(hi, (w - 2 * pad) * dz / dx + 2 * pad))


def scale_bar(pr, x, y):
    """A metre scale, because a track map without one is a drawing, not a map."""
    for m in (5, 10, 20, 25, 50, 100, 200, 500):
        px = m * pr.s
        if px >= 55:
            break
    return ('<path d="M%s %s h%s" class="axis" stroke-width="2"/>' % (n(x), n(y), n(px))
            + txt(x + px / 2, y - 5, "%d m" % m, 9.5, "mut", "middle"))


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------


def heading_deg(s):
    """Direction of travel, degrees clockwise from screen-up, or None when the
    quad is not moving. A velocity vector of length zero has no direction, and
    drawing one would invent the very thing the sideslip figures measure."""
    return None if s["heading"] is None else math.degrees(s["heading"])


def unwrap(seq):
    """Continuous angle series, gaps held at the last known value.

    Without this an animated rotation whips through a full turn every time the
    value crosses 180 - which, on a pirouette, is exactly where it lives."""
    out, off, prev = [], 0.0, None
    for v in seq:
        if v is None:
            out.append(None)
            continue
        if prev is not None:
            off -= 360.0 * round((v + off - prev) / 360.0)
        out.append(v + off)
        prev = out[-1]
    last = next((v for v in out if v is not None), 0.0)
    for i, v in enumerate(out):
        if v is None:
            out[i] = last
        else:
            last = v
    return out


def load_samples(csv_path, args):
    """analyze_flight.load, plus the nose bearing it computes and discards."""
    data = AF.load(csv_path, args.speed_floor)
    for s, r in zip(data, csv.DictReader(open(csv_path))):
        q = (float(r["quat_x"]), float(r["quat_y"]), float(r["quat_z"]), float(r["quat_w"]))
        f = AF.rotate(q, (0, 0, 1))
        s["nose"] = math.degrees(math.atan2(f[0], f[2]))
    return data


def decimate(idx, limit):
    idx = list(idx)
    if len(idx) <= limit:
        return idx
    step = len(idx) / float(limit)
    out = [idx[int(i * step)] for i in range(limit)]
    if out[-1] != idx[-1]:
        out.append(idx[-1])
    return out


def pctl(vals, q):
    v = sorted(vals)
    return v[min(len(v) - 1, int(len(v) * q / 100))] if v else 0.0


def cover_tail(ranges, names, data, dt, min_flying, stall_speed):
    """Add the untimed flying either side of the laps that finished.

    The test is TIME SPENT MOVING, not elapsed time. A duration test looks
    reasonable and is wrong: the 20:31 race sits on the grid for 73 s before the
    lights, of which 68.8 s is below 10 km/h, and admitting that as a segment
    puts a stationary quad on the track map and 68.8 s of grid time into the
    'below 10 km/h' total. Requiring real flying rejects it and still keeps the
    69 s of genuine flying after the last timed lap on the 20:12 replay - which
    is where that run's crash happened."""
    def flying(a, b):
        return sum(1 for s in data[a:b] if s["spd"] >= stall_speed) * dt

    ranges, names = list(ranges), list(names)
    end = ranges[-1][1]
    if flying(end, len(data)) >= min_flying:
        ranges.append((end, len(data)))
        names.append("after lap %d" % (len(ranges) - 1))
    start = ranges[0][0]
    if flying(0, start) >= min_flying:
        ranges.insert(0, (0, start))
        names.insert(0, "before lap 1")
    return ranges, names


def race_name(meta):
    """The track as Liftoff names it, minus the bookkeeping.

    `name` looks like "01 - Railline - 03_52_373 - 2026-08-26": the track, then
    the run's total time, then the date. Only the first part identifies the
    track, and it is worth surfacing because `environment` is the SCENERY name -
    "Rustline" - while the track inside it is "Railline". Two different words
    for two different things, and the notes have been conflating them."""
    raw = (meta.get("name") or "").strip()
    if not raw:
        return meta.get("environment") or "?"
    parts = []
    for p in [x.strip() for x in raw.split(" - ")]:
        if re.match(r"^\d{1,2}_\d{2}_\d{1,3}$", p) or re.match(r"^\d{4}-\d{2}-\d{2}$", p):
            break
        parts.append(p)
    return " - ".join(parts) or raw


def fmt_time(sec):
    m, s = divmod(float(sec), 60)
    return "%d:%06.3f" % (int(m), s)


# ---------------------------------------------------------------------------
# the line, coloured by speed
# ---------------------------------------------------------------------------


def speed_path(seg, pr, vref, width=2.6):
    """The line, coloured by speed.

    Not an SVG gradient: a gradient follows the bounding box, not the path, so
    on a track that doubles back it paints the wrong colour over half of it.
    Speed is quantised into SPEED_BANDS steps and each run of samples inside one
    band becomes a single polyline - which is also what keeps the file small,
    one polyline per run instead of one per sample pair.

    `vref` is the p90 speed, not the maximum. Against the maximum, a single fast
    straight pushes the whole working range of the flight into two shades and
    the slow sections - the ones the debrief is about - stop being visible."""
    out, run, band = [], [], None
    for s in seg:
        b = min(SPEED_BANDS - 1, int(SPEED_BANDS * min(1.0, s["spd"] / vref if vref else 0)))
        if band is not None and b != band:
            out.append(poly(run, ramp((band + 0.5) / SPEED_BANDS), width))
            run = run[-1:]
        run.append(pr(s))
        band = b
    if len(run) > 1:
        out.append(poly(run, ramp((band + 0.5) / SPEED_BANDS), width))
    return "".join(out)


def pin(x, y, label, colour="var(--warn)", r=8.5):
    return ('<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="var(--halo)" '
            'stroke-width="1.5"/>' % (n(x), n(y), n(r, 1), colour)
            + txt(x, y + 3.4, label, 9.5, "", "middle", 'fill="#ffffff" font-weight="700"'))


def quad_glyph(angle, scale=1.0, fill="var(--fg)"):
    return ('<g transform="rotate(%s) scale(%s)"><path d="M0,-13 L8,9 L0,4.5 L-8,9 Z" '
            'fill="%s" stroke="var(--halo)" stroke-width="1.4"/></g>'
            % (n(angle, 1), n(scale, 2), fill))


def legend_speed(x, y, vref, w=210):
    stops = "".join('<stop offset="%d%%" stop-color="%s"/>' % (100 * i // 8, ramp(i / 8.0))
                    for i in range(9))
    return ('<defs><linearGradient id="spd">%s</linearGradient></defs>'
            '<rect x="%s" y="%s" width="%d" height="9" rx="4.5" fill="url(#spd)"/>'
            % (stops, n(x), n(y), w)
            + txt(x, y - 5, "speed", 9.5, "mut")
            + txt(x, y + 20, "0", 9.5, "mut")
            + txt(x + w, y + 20, "%d+ km/h" % round(vref), 9.5, "mut", "end"))


def fig_track(data, ranges, names, report, vref, out, title):
    W = 960
    bounds = bounds_of(data)
    wide = (bounds[1] - bounds[0]) > 1.3 * (bounds[3] - bounds[2])
    cols = 1 if (wide or len(ranges) == 1) else 2
    pw = W // cols
    ph = fit_height(bounds, pw) + 46
    rows = (len(ranges) + cols - 1) // cols
    H = 44 + rows * ph + 56
    body = [txt(14, 26, title, 15, "ttl")]
    for k, (a, b) in enumerate(ranges):
        cx, cy = (k % cols) * pw, 44 + (k // cols) * ph
        pr = Proj(None, cx, cy + 40, pw, ph - 46, bounds=bounds)
        seg = data[a:b]
        e = report[k] if k < len(report) else {}
        body.append(panel(cx + 5, cy + 4, pw - 10, ph - 12))
        body.append(txt(cx + 16, cy + 24, names[k].upper(), 12, "ttl"))
        # SVG has no text metrics here, so the stats line is offset by an
        # estimated advance width. A fixed offset fitted "LAP 1" and collided
        # with "AFTER LAP 1" the moment untimed segments were added.
        body.append(txt(cx + 30 + 7.6 * len(names[k]), cy + 24, SEP.join(
            ["%.1f s" % e.get("duration_s", 0),
             "median %d km/h" % e.get("speed_median", 0),
             "%.1f s under 10" % e.get("slow_seconds", 0)]), 10.5, "mut"))
        body.append(poly([pr(s) for s in data], "var(--grid)", 1.4))   # rest of the flight
        body.append(speed_path(seg, pr, vref))
        sx, sy = pr(seg[0])
        body.append('<g transform="translate(%s,%s)">%s</g>'
                    % (n(sx, 1), n(sy, 1), quad_glyph(seg[0]["nose"], 0.85)))
        for i, st in enumerate(e.get("stalls", []), 1):
            s0, s1 = st["index"]
            deep = min(range(s0, s1 + 1), key=lambda j: data[j]["spd"])
            dx, dy = pr(data[deep])
            body.append(pin(dx, dy, str(i)))
        body.append(scale_bar(pr, cx + 24, cy + ph - 24))
    body.append(legend_speed(16, H - 36, vref))
    body.append(txt(W - 14, H - 20, SEP.join(
        ["arrow = start", "numbered pins = stalls", "grey = the rest of the flight"]),
        10, "mut", "end"))
    write(out, doc(W, H, "".join(body), title))


def fig_line(data, ranges, names, out, title):
    W = 960
    bounds = bounds_of(data)
    ph = fit_height(bounds, W, lo=240, hi=560)
    H = 46 + ph + 58
    pr = Proj(None, 0, 46, W, ph, bounds=bounds)
    body = [txt(14, 26, title, 15, "ttl"), panel(5, 46, W - 10, ph)]
    for k, (a, b) in enumerate(ranges):
        c = LAP_HUES[k % len(LAP_HUES)]
        body.append(poly([pr(s) for s in data[a:b]], c, 2.2, extra='opacity="0.82"'))
        body.append('<rect x="%d" y="%s" width="14" height="4" rx="2" fill="%s"/>'
                    % (18 + k * 100, n(46 + ph + 16), c))
        body.append(txt(38 + k * 100, 46 + ph + 24, names[k], 11))
    body.append(scale_bar(pr, W - 140, 46 + ph - 16))
    body.append(txt(14, H - 14, "Where the laps separate is a LINE difference. No change of "
                                "stick technique moves a line - only knowing the track does.",
                    10, "mut"))
    write(out, doc(W, H, "".join(body), title))


# ---------------------------------------------------------------------------
# stacked time traces
# ---------------------------------------------------------------------------


class Strip:
    """One time-series panel. `head` reserves room for the label so the trace
    never runs underneath its own title."""

    def __init__(self, x, y, w, h, t0, t1, lo, hi, head=18):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.py, self.ph = y + head, h - head - 4
        self.t0, self.t1, self.lo, self.hi = t0, t1, lo, hi

    def tx(self, t):
        return self.x + (t - self.t0) / max(1e-6, self.t1 - self.t0) * self.w

    def vy(self, v):
        v = max(self.lo, min(self.hi, v))
        return self.py + self.ph - (v - self.lo) / max(1e-6, self.hi - self.lo) * self.ph

    def frame(self, label, guides=()):
        out = [panel(self.x, self.y, self.w, self.h, 4)]
        if label:
            out.append(txt(self.x + 8, self.y + 14, label, 11, "ttl"))
        for g, gl in guides:
            yy = self.vy(g)
            out.append('<path d="M%s %s H%s" class="grid" stroke-dasharray="3 3"/>'
                       % (n(self.x + 4), n(yy), n(self.x + self.w - 4)))
            if gl:
                out.append(txt(self.x + self.w - 8, yy - 4, gl, 9, "mut", "end"))
        return "".join(out)

    def series(self, seg, key, colour, width=1.6, absolute=False, extra=""):
        runs, run = [], []
        for s in seg:
            v = s.get(key)
            if v is None:
                if len(run) > 1:
                    runs.append(run)
                run = []
                continue
            run.append((self.tx(s["t"]), self.vy(abs(v) if absolute else v)))
        if len(run) > 1:
            runs.append(run)
        return "".join(poly(r, colour, width, extra) for r in runs)

    def band(self, ta, tb, colour, op=0.18):
        return ('<rect x="%s" y="%s" width="%s" height="%s" fill="%s" opacity="%s"/>'
                % (n(self.tx(ta)), n(self.y), n(max(1.5, self.tx(tb) - self.tx(ta))),
                   n(self.h), colour, n(op)))


def fig_traces(data, ranges, names, report, out, title, order=None):
    t0, t1 = data[ranges[0][0]]["t"], data[ranges[-1][1] - 1]["t"]
    W, pads, gap = 980, 50, 10
    order = order or ["speed", "sideslip", "tilt", "sticks", "throttle"]
    spec = {
        "speed": (0, math.ceil(max(10, max(s["spd"] for s in data)) / 10) * 10,
                  "speed   km/h", 104, ((10, "10 - stalled"),)),
        # 180, not 90: a pirouette runs the nose right past sideways, and a panel
        # clipped at 90 would flatten the very fault the panel exists to show. The
        # panel is taller than the others to pay for the range, so the 10 and 30
        # guides that matter on a normal corner stay apart.
        "sideslip": (0, 180, "sideslip   |deg|", 150,
                     ((10, "10 coordinated"), (30, "30 skid"), (90, "90 - sideways"))),
        "tilt": (0, math.ceil(max(20, max(s["tilt"] for s in data)) / 10) * 10,
                 "tilt   deg", 104, ((30, "30"),)),
        "sticks": (-1, 1, "sticks   roll solid, yaw dashed", 104, ((0, ""),)),
        "throttle": (0, 1, "throttle", 90, ((0.5, "0.5"),)),
    }
    H = 46 + sum(spec[p][3] + gap for p in order) + 40
    body = [txt(14, 26, title, 15, "ttl")]
    strips, y = {}, 46
    for p in order:
        lo, hi, label, ph, guides = spec[p]
        st = Strip(pads, y, W - pads - 14, ph, t0, t1, lo, hi)
        strips[p] = st
        body.append(st.frame(label, guides))
        body.append(txt(pads - 6, st.vy(hi) + 4, "%g" % hi, 9, "mut", "end"))
        body.append(txt(pads - 6, st.vy(lo), "%g" % lo, 9, "mut", "end"))
        y += ph + gap
    for k, (a, b) in enumerate(ranges):
        for st in (report[k].get("stalls", []) if k < len(report) else []):
            i0, i1 = st["index"]
            for p in order:
                body.append(strips[p].band(data[i0]["t"], data[i1]["t"], "var(--warn)"))
        if k:
            for p in order:
                s = strips[p]
                body.append('<path d="M%s %s V%s" class="axis" stroke-dasharray="4 3"/>'
                            % (n(s.tx(data[a]["t"])), n(s.y), n(s.y + s.h)))
        first = strips[order[0]]
        body.append(txt(first.tx(data[a]["t"]) + 5, 42, names[k], 10.5, "mut"))
    seg = data[ranges[0][0]:ranges[-1][1]]
    if "speed" in strips:
        body.append(strips["speed"].series(seg, "spd", ramp(0.95)))
    if "sideslip" in strips:
        body.append(strips["sideslip"].series(seg, "slip", "var(--warn)", absolute=True))
    if "tilt" in strips:
        body.append(strips["tilt"].series(seg, "tilt", "var(--acc)"))
    if "sticks" in strips:
        body.append(strips["sticks"].series(seg, "roll", "var(--acc)", 1.7))
        body.append(strips["sticks"].series(seg, "yaw", "var(--warn)", 1.7,
                                            extra='stroke-dasharray="4 3"'))
    if "throttle" in strips:
        body.append(strips["throttle"].series(seg, "thr", "var(--ok)"))
    s = strips[order[-1]]
    step = 10 if (t1 - t0) < 120 else 20
    tt = t0
    while tt <= t1 + 0.5:
        body.append('<path d="M%s %s v5" class="axis"/>' % (n(s.tx(tt)), n(s.y + s.h)))
        body.append(txt(s.tx(tt), s.y + s.h + 17, "%d" % round(tt - t0), 9.5, "mut", "middle"))
        tt += step
    body.append(txt(pads, H - 8, SEP.join(["seconds from the start", "red bands = stalls",
                                           "dashed vertical = lap boundary"]), 10, "mut"))
    write(out, doc(W, H, "".join(body), title))


# ---------------------------------------------------------------------------
# corner scorecard
# ---------------------------------------------------------------------------


def fig_corners(report, names, out, title):
    corners = [(k, i, c) for k, e in enumerate(report) for i, c in enumerate(e["corners"], 1)]
    if not corners:
        return False
    W = 980
    px, py, pw = 58, 62, 420
    ph = max(300, min(560, 22 * len(corners) + 40))
    H = py + ph + 62
    body = [txt(14, 26, title, 15, "ttl")]
    tmax = max(50, max(c["tilt_deg"] for _, _, c in corners) + 6)
    smax = max(45, max(c["sideslip_deg"] for _, _, c in corners) + 6)
    X = lambda v: px + v / tmax * pw
    Y = lambda v: py + ph - v / smax * ph
    body.append(panel(px, py, pw, ph, 5))
    body.append('<rect x="%d" y="%s" width="%d" height="%s" fill="var(--ok)" opacity="0.12"/>'
                % (px, n(Y(10)), pw, n(py + ph - Y(10))))
    body.append('<rect x="%d" y="%d" width="%d" height="%s" fill="var(--warn)" opacity="0.12"/>'
                % (px, py, pw, n(Y(30) - py)))
    body.append(txt(px + 10, Y(10) - 7, "coordinated, under 10 deg", 10, "mut"))
    body.append(txt(px + 10, py + 15, "skidding, over 30 deg", 10, "mut"))
    for v in range(0, int(tmax) + 1, 10):
        body.append('<path d="M%s %d V%d" class="grid"/>' % (n(X(v)), py, py + ph))
        body.append(txt(X(v), py + ph + 16, str(v), 9.5, "mut", "middle"))
    for v in range(0, int(smax) + 1, 15):
        body.append('<path d="M%d %s H%d" class="grid"/>' % (px, n(Y(v)), px + pw))
        body.append(txt(px - 8, Y(v) + 3.5, str(v), 9.5, "mut", "end"))
    for k, i, c in corners:
        r = 5 + 9 * min(1.0, c["entry_kmh"] / 70.0)
        body.append('<circle cx="%s" cy="%s" r="%s" fill="%s" opacity="0.72" '
                    'stroke="var(--halo)" stroke-width="1.2"/>'
                    % (n(X(c["tilt_deg"])), n(Y(c["sideslip_deg"])), n(r, 1),
                       LAP_HUES[k % len(LAP_HUES)]))
        body.append(txt(X(c["tilt_deg"]), Y(c["sideslip_deg"]) - r - 4, str(i), 9, "mut", "middle"))
    body.append(txt(px + pw / 2, py + ph + 36, "tilt through the corner   (deg)", 11, "mut", "middle"))
    body.append(txt(16, py + ph / 2, "sideslip (deg)", 11, "mut", "middle",
                    'transform="rotate(-90 16 %s)"' % n(py + ph / 2)))
    body.append(txt(px, 44, "Bubble size is entry speed. Down and to the right is a "
                            "committed, coordinated corner.", 10, "mut"))
    for k in range(len(report)):
        body.append('<circle cx="%d" cy="52" r="5" fill="%s"/>'
                    % (px + 6 + k * 84, LAP_HUES[k % len(LAP_HUES)]))
        body.append(txt(px + 16 + k * 84, 55.5, names[k], 10, "mut"))

    bx, zero, span = 540, 700, 190
    body.append(txt(bx, 44, "throttle added through the corner", 11, "ttl"))
    rowh = min(24, (ph - 16) / max(1, len(corners)))
    dmax = max(0.25, max(abs(c["throttle_delta"]) for _, _, c in corners))
    body.append('<path d="M%d %d V%s" class="axis"/>' % (zero, py, n(py + len(corners) * rowh + 8)))
    for j, (k, i, c) in enumerate(corners):
        yy = py + 14 + j * rowh
        d = c["throttle_delta"]
        w = abs(d) / dmax * span
        col = "var(--ok)" if d > 0.01 else ("var(--warn)" if d < -0.01 else "var(--mut)")
        body.append('<rect x="%s" y="%s" width="%s" height="%s" rx="2" fill="%s" opacity="0.85"/>'
                    % (n(zero if d >= 0 else zero - w), n(yy - rowh * 0.34), n(max(1.5, w)),
                       n(rowh * 0.68), col))
        body.append(txt(bx, yy + 3.5, "%s c%d%s%d→%d km/h"
                        % (names[k], i, SEP, c["entry_kmh"], c["exit_kmh"]), 9.5, "mut"))
        body.append(txt(zero + (w + 6 if d >= 0 else -w - 6), yy + 3.5, "%+.2f" % d, 9.5,
                        "", "start" if d >= 0 else "end"))
    body.append(txt(bx, H - 22, "Bank sets the DIRECTION of the turning force;", 10, "mut"))
    body.append(txt(bx, H - 9, "throttle sets its MAGNITUDE. A flat corner goes wide and sinks.",
                    10, "mut"))
    write(out, doc(W, H, "".join(body), title))
    return True


# ---------------------------------------------------------------------------
# where the time went
# ---------------------------------------------------------------------------


def fig_timeline(data, ranges, names, report, out, title, best_lap=None, lap_times=None):
    W = 980
    rows = len(ranges) + (1 if best_lap else 0)
    H = 58 + rows * 58 + 40
    longest = max([e["duration_s"] for e in report] + [best_lap or 0])
    px, pw = 104, W - 104 - 96
    body = [txt(14, 26, title, 15, "ttl")]
    y = 56
    if best_lap:
        w = best_lap / longest * pw
        body.append('<rect x="%d" y="%s" width="%s" height="22" rx="4" fill="var(--ok)" '
                    'opacity="0.45"/>' % (px, n(y), n(w)))
        body.append(txt(px - 10, y + 15.5, "best ever", 11, "mut", "end"))
        body.append(txt(px + w + 10, y + 15.5, fmt_time(best_lap), 10.5, "mut"))
        y += 58
    for k, e in enumerate(report):
        dur = e["duration_s"]
        # The bar is scaled by the measured duration, but the LABEL is the lap
        # time Liftoff recorded, to the millisecond. duration_s is rounded to a
        # tenth for the tables, and printing that turned 1:54.708 into 1:54.700
        # - a wrong number sitting next to the right one in the header.
        shown = lap_times[k] if lap_times and k < len(lap_times) else dur
        w = dur / longest * pw
        body.append(panel(px, y, w, 26, 4))
        body.append('<rect x="%d" y="%s" width="%s" height="26" rx="4" fill="var(--acc)" '
                    'opacity="0.32"/>' % (px, n(y), n(w)))
        t0 = data[ranges[k][0]]["t"]
        for i, st in enumerate(e.get("stalls", []), 1):
            # st["t"] is measured from the start of the RECORDING, and this bar
            # starts at the start of this LAP. Using it raw drew lap 1's stalls
            # past the end of its own bar and lap 2's off the figure entirely.
            off = data[st["index"][0]]["t"] - t0
            sx = px + off / longest * pw
            sw = max(2.5, st["duration_s"] / longest * pw)
            body.append('<rect x="%s" y="%s" width="%s" height="26" fill="var(--warn)"/>'
                        % (n(sx), n(y), n(sw)))
            body.append(txt(sx + sw / 2, y - 6, str(i), 9.5, "mut", "middle"))
        body.append(txt(px - 10, y + 17.5, names[k], 11, "", "end"))
        body.append(txt(px + w + 10, y + 17.5, fmt_time(shown), 10.5))
        body.append(txt(px, y + 44, "%.1f s under 10 km/h in %d stall%s"
                        % (e["slow_seconds"], len(e.get("stalls", [])),
                           "" if len(e.get("stalls", [])) == 1 else "s"), 10, "mut"))
        y += 58
    body.append(txt(14, H - 12, "Red is time spent below 10 km/h. It is the cheapest time on "
                                "the track to get back.", 10, "mut"))
    write(out, doc(W, H, "".join(body), title))


# ---------------------------------------------------------------------------
# animation
#
# SMIL, so it needs no JavaScript and plays inside an <img>. Position is an
# animateTransform translate and not an animateMotion path, because
# animateMotion distributes frames by path LENGTH, which plays the slow parts
# fast - the exact opposite of what a debrief has to show.
#
# The static line and every annotation are drawn underneath, so a renderer that
# ignores SMIL still shows a picture worth reading.
# ---------------------------------------------------------------------------


def keytimes(times, values):
    """SMIL requires exactly one keyTime per value, starting at 0, ending at 1
    and never decreasing. A mismatch makes the whole animation a no-op in every
    renderer, silently, so it is asserted rather than hoped for."""
    assert len(times) == len(values), "%d keyTimes for %d values" % (len(times), len(values))
    return ";".join(n(t, 5) for t in times)


def animate(attr, values, times, dur, calc="linear"):
    return ('<animate attributeName="%s" dur="%ss" repeatCount="indefinite" '
            'calcMode="%s" keyTimes="%s" values="%s"/>'
            % (attr, n(dur, 3), calc, keytimes(times, values), ";".join(values)))


def animate_tf(typ, values, times, dur):
    return ('<animateTransform attributeName="transform" type="%s" dur="%ss" '
            'repeatCount="indefinite" calcMode="linear" keyTimes="%s" values="%s"/>'
            % (typ, n(dur, 3), keytimes(times, values), ";".join(values)))


def marker(nose, vel, vis, skid, times, dur, scale=1.0):
    """Nose arrow and direction-of-travel ray, sharing one origin.

    The angle between them IS the sideslip, so the fault is visible rather than
    tabulated, and the arrow turns red once that angle passes 30 degrees.

    The colour change is done by cross-fading two arrows on OPACITY rather than
    by animating `fill`. SMIL animates presentation attributes and does not
    resolve a CSS var() inside an animation value, so animating fill would have
    to hard-code hex and give up on the theme; two theme-coloured arrows and a
    numeric opacity keep both.

    The ray is HIDDEN while the quad is stationary rather than frozen at its
    last bearing. A stopped quad has no direction of travel, and drawing one
    would be a lie at the exact moment the figure matters most."""
    arrow = "M0,%s L%s,%s L0,%s L%s,%s Z" % (
        n(-14 * scale), n(8.6 * scale), n(9.6 * scale), n(4.8 * scale),
        n(-8.6 * scale), n(9.6 * scale))
    return ('<g opacity="0.9">%s<path d="M0,0 L0,%s" stroke="var(--mut)" stroke-width="%s" '
            'stroke-dasharray="6 5"/><circle cx="0" cy="%s" r="%s" fill="var(--mut)"/>%s</g>'
            '<g>%s'
            '<path d="%s" fill="var(--fg)" stroke="var(--halo)" stroke-width="1.4">%s</path>'
            '<path d="%s" fill="var(--warn)" stroke="var(--halo)" stroke-width="1.4" '
            'opacity="0">%s</path></g>'
            % (animate_tf("rotate", vel, times, dur),
               n(-52 * scale), n(2.6 * scale), n(-52 * scale), n(3.4 * scale),
               animate("opacity", vis, times, dur, calc="discrete"),
               animate_tf("rotate", nose, times, dur),
               arrow, animate("opacity", ["0" if k == "1" else "1" for k in skid],
                              times, dur, calc="discrete"),
               arrow, animate("opacity", skid, times, dur, calc="discrete")))


def fig_anim(data, a, b, out, title, caption, vref, dur_cap=40.0, frames=380,
             cam_span_m=45.0):
    """Overview map with a moving quad, plus a follow-cam that keeps the quad
    centred and magnified.

    The follow-cam exists because a whole lap drawn to fit a page shrinks the
    quad to a few pixels, and the thing worth watching - the nose separating
    from the direction of travel - is a few pixels wide at that scale."""
    seg = data[a:b]
    if len(seg) < 4:
        return None
    idx = decimate(range(a, b), frames)
    t0, t1 = data[idx[0]]["t"], data[idx[-1]]["t"]
    real = t1 - t0
    if real <= 0:
        return None
    dur = min(real, dur_cap)
    rate = real / dur
    times = [(data[i]["t"] - t0) / real for i in idx]
    times[0] = 0.0
    for i in range(1, len(times)):
        times[i] = min(1.0, max(times[i - 1] + 1e-5, times[i]))
    times[-1] = 1.0

    W = 900
    bounds = bounds_of(seg)
    mh = fit_height(bounds, W, lo=230, hi=440)
    cam = 300
    H = 46 + mh + 34 + cam + 44
    pr = Proj(None, 0, 46, W, mh, bounds=bounds)

    body = [txt(14, 26, title, 15, "ttl"), panel(5, 46, W - 10, mh)]
    body.append(poly([pr(s) for s in seg], "var(--grid)", 5.5))
    body.append(speed_path(seg, pr, vref, 1.8))

    pts = [pr(data[i]) for i in idx]
    nose = [n(v, 1) for v in unwrap([data[i]["nose"] for i in idx])]
    vel = [n(v, 1) for v in unwrap([heading_deg(data[i]) for i in idx])]
    vis = ["1" if data[i]["heading"] is not None else "0" for i in idx]
    # The arrow's red flag is computed here rather than read from data["slip"].
    # analyze_flight leaves slip undefined below --speed-floor (15 km/h) because
    # the STATISTIC is meaningless down there, and that is right for a median.
    # But the pirouette lives below that floor, so reusing the field would grey
    # out the arrow at the exact moment it should be shouting. Whenever there is
    # a direction of travel at all, the angle between it and the nose is real
    # and worth colouring.
    skid = []
    for i in idx:
        h = heading_deg(data[i])
        skid.append("1" if h is not None
                    and abs((data[i]["nose"] - h + 180) % 360 - 180) > 30 else "0")
    xs = ["%s,%s" % (n(p[0], 1), n(p[1], 1)) for p in pts]

    # progressive trail, driven by cumulative LENGTH against time, so the trail
    # keeps pace with the marker even where the samples bunch up
    cum, tot = [0.0], 0.0
    for i in range(1, len(pts)):
        tot += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        cum.append(tot)
    if tot > 0:
        d = " ".join(("M" if i == 0 else "L") + "%s %s" % (n(p[0], 1), n(p[1], 1))
                     for i, p in enumerate(pts))
        body.append('<path d="%s" fill="none" stroke="var(--fg)" stroke-width="2.6" '
                    'stroke-linecap="round" opacity="0.7" stroke-dasharray="%s %s">%s</path>'
                    % (d, n(tot, 1), n(tot, 1),
                       animate("stroke-dashoffset", [n(tot - c, 1) for c in cum], times, dur)))
    body.append('<g>%s%s</g>' % (animate_tf("translate", xs, times, dur),
                                marker(nose, vel, vis, skid, times, dur, 0.8)))
    body.append(scale_bar(pr, W - 150, 46 + mh - 16))

    # follow-cam: same pixels, magnified, panned so the quad stays centred
    cy = 46 + mh + 34
    zoom = max(1.0, cam / max(1e-6, cam_span_m * pr.s))
    ccx, ccy = 8 + cam / 2, cy + cam / 2
    inner = (poly([pr(s) for s in seg], "var(--grid)", 5.5 / zoom)
             + speed_path(seg, pr, vref, 3.0 / zoom))
    pan = ["%s,%s" % (n(-p[0] * zoom, 1), n(-p[1] * zoom, 1)) for p in pts]
    body.append('<defs><clipPath id="cam"><rect x="8" y="%s" width="%d" height="%d" rx="6"/>'
                '</clipPath></defs>' % (n(cy), cam, cam))
    body.append(panel(8, cy, cam, cam))
    body.append('<g clip-path="url(#cam)"><g transform="translate(%s,%s)"><g>%s'
                '<g transform="scale(%s)">%s</g></g></g>%s</g>'
                % (n(ccx, 1), n(ccy, 1), animate_tf("translate", pan, times, dur),
                   n(zoom, 3), inner,
                   '<g transform="translate(%s,%s)">%s</g>'
                   % (n(ccx, 1), n(ccy, 1), marker(nose, vel, vis, skid, times, dur, 1.25))))
    body.append(txt(8, cy - 6, "follow cam" + SEP + "about %d m across" % round(cam_span_m),
                    10.5, "mut"))

    # readouts
    rx, ry = cam + 32, cy + 26
    body.append(txt(rx, ry, "speed", 10.5, "mut"))
    body.append('<rect x="%s" y="%s" width="300" height="13" rx="6.5" class="pan"/>'
                % (n(rx + 48), n(ry - 11)))
    body.append('<rect x="%s" y="%s" height="13" rx="6.5" width="0" fill="%s">%s%s</rect>'
                % (n(rx + 48), n(ry - 11), ramp(0.95),
                   animate("width", [n(300.0 * min(1.0, data[i]["spd"] / vref), 1) for i in idx],
                           times, dur),
                   animate("fill", [ramp(data[i]["spd"] / vref) for i in idx], times, dur,
                           calc="discrete")))
    body.append(txt(rx + 356, ry, "0-%d+ km/h" % round(vref), 10, "mut"))
    for k in range(int(real) + 1):          # a one-second clock, one label per second
        f0, f1 = k / real, min(1.0, (k + 1) / real)
        body.append(txt(rx, ry + 34, "%d s" % k, 20, "", "start", 'opacity="0"',
                        body='<animate attributeName="opacity" dur="%ss" '
                             'repeatCount="indefinite" calcMode="discrete" '
                             'keyTimes="0;%s;%s" values="0;1;0"/>'
                             % (n(dur, 3), n(max(1e-4, f0), 4), n(min(0.9999, f1), 4))))
    body.append(txt(rx + 60, ry + 34, "of %.1f s" % real, 11, "mut"))
    strip = Strip(rx, ry + 52, W - rx - 16, cam - 84, t0, t1, 0, max(1.0, max(s["spd"] for s in seg)))
    body.append(strip.frame("speed over the segment"))
    body.append(strip.series([data[i] for i in idx], "spd", ramp(0.95), 1.5))
    body.append('<path d="M%s %s V%s" stroke="var(--fg)" stroke-width="1.5">%s</path>'
                % (n(strip.x), n(strip.py), n(strip.py + strip.ph),
                   animate_tf("translate",
                              ["%s,0" % n(strip.tx(data[i]["t"]) - strip.x, 1) for i in idx],
                              times, dur)))
    foot = [caption, "nose = arrow", "direction of travel = dashed ray"]
    if rate > 1.01:
        foot.append("playback %.1f× real time" % rate)
    body.append(txt(14, H - 14, SEP.join(foot), 10, "mut"))
    write(out, doc(W, H, "".join(body), title))
    return rate


# ---------------------------------------------------------------------------
# report assembly
# ---------------------------------------------------------------------------


def write(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def pb_context(meta, history_path):
    """Best race and best lap for this track, from the PB snapshots.

    Liftoff overwrites its own PB files, so a snapshot history is the only place
    a superseded time still exists. It is what makes "faster or slower than
    usual" answerable at all."""
    p = Path(history_path)
    if not p.exists():
        return {}
    try:
        hist = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not hist:
        return {}
    last = hist[-1]
    out = {"taken_at": last.get("taken_at")}
    for key, field in (("races", "race"), ("laps", "lap")):
        for guid in (meta.get("race_id"), meta.get("track_id")):
            rec = last.get(key, {}).get(guid) if guid else None
            if rec and rec.get("best"):
                out["best_" + field] = rec["best"][0]
                out["all_" + field] = rec["best"]
                break
    return out


def findings(meta, report, names, pb):
    """Mechanical observations: true by arithmetic, no judgement.

    Kept separate from the Debrief on purpose. A generated sentence can say a
    number is large; only a person knows whether the pilot was already told
    about it last session, which is the whole difference between coaching and
    nagging."""
    out = []
    slow = sum(e["slow_seconds"] for e in report)
    dur = sum(e["duration_s"] for e in report)
    stalls = [s for e in report for s in e["stalls"]]
    if dur:
        out.append("**%.1f s below 10 km/h** across %.1f s of flying, %.0f%% of the run."
                   % (slow, dur, 100 * slow / dur))
    if stalls:
        kinds = {}
        for s in stalls:
            k = s["verdict"].rstrip("?")
            kinds[k] = kinds.get(k, 0) + 1
        out.append("**%d stall%s**: %s."
                   % (len(stalls), "" if len(stalls) == 1 else "s",
                      ", ".join("%d %s" % (v, k) for k, v in sorted(kinds.items()))))
        off = [s for s in stalls if s["off_line"]]
        if off:
            out.append("**%d of them started off the racing line.** That is a line error, "
                       "not a stick error, and no change of technique fixes it." % len(off))
    for k, e in enumerate(report):
        y = e["yaw_only"]
        if y["yaw_only_pct"] is not None and y["yaw_only_pct"] >= 30:
            out.append("**%s: %d%% of commanded yaw came with no roll at all** "
                       "(%.1f s of %.1f s, mean %s km/h). Yaw with no roll rotates the "
                       "airframe; it does not bend the path."
                       % (names[k], y["yaw_only_pct"], y["yaw_only_seconds"],
                          y["yaw_seconds"], y["yaw_only_mean_kmh"]))
    corners = [c for e in report for c in e["corners"]]
    if corners:
        pos = sum(1 for c in corners if c["throttle_delta"] > 0)
        fast = sum(1 for c in corners if c["exit_kmh"] > c["entry_kmh"])
        out.append("**Throttle was added in %d of %d corners**, and **%d of %d exited faster "
                   "than they entered**." % (pos, len(corners), fast, len(corners)))
        skid = [c for c in corners if c["sideslip_deg"] > 30]
        if skid:
            out.append("**%d corner%s skidded** (over 30 deg of sideslip)."
                       % (len(skid), "" if len(skid) == 1 else "s"))
    if len(report) > 1:
        a, b = report[0], report[-1]
        if b["speed_median"] < a["speed_median"] * 0.92:
            out.append("**%s decayed against %s**: median speed %d vs %d km/h, median tilt "
                       "%d vs %d deg, slow time %.1f vs %.1f s."
                       % (names[-1], names[0], b["speed_median"], a["speed_median"],
                          b["tilt_median"], a["tilt_median"], b["slow_seconds"],
                          a["slow_seconds"]))
    laps = meta.get("lap_times") or []
    if laps and pb.get("best_lap"):
        best = min(laps)
        d = best - pb["best_lap"]
        if d < -0.2:
            out.append("**New best lap on this track: %s**, %.3f s under the previous %s."
                       % (fmt_time(best), -d, fmt_time(pb["best_lap"])))
        elif d > 0.2:
            out.append("**Best lap here was %s, against a personal best of %s** on the same "
                       "geometry (+%.1f s)." % (fmt_time(best), fmt_time(pb["best_lap"]), d))
        else:
            out.append("**Best lap here matched the personal best**, %s." % fmt_time(best))
    return out


DEBRIEF_STUB = ("<!-- Written by hand after reading the figures. One fault, one drill, "
                "no stacking. Read the pilot's notes file first, so this does not "
                "repeat advice already given and absorbed. Delete this comment when "
                "filled in. -->\n\n_TO BE WRITTEN._")


def existing_debrief(path):
    """The hand-written Debrief from a previous run of this report, if any.

    Regenerating a report is routine - a new figure, a fixed threshold, a
    segment that was being missed - and every regeneration would otherwise
    destroy the only part of the file a person wrote. The Debrief is carried
    forward silently; `--reset-debrief` puts the stub back deliberately."""
    p = Path(path)
    if not p.exists():
        return None
    # Stop at the NEXT HEADING, not at the footer rule. Debrief used to be the
    # last section, so "up to ---" meant the same thing; the moment it moved to
    # the top, that swallowed the entire report into the Debrief and re-inserted
    # it on every regeneration, doubling the document each time. The heading
    # guard below is a second line of defence, because a silently duplicated
    # document looks like a rendering glitch rather than the data bug it is.
    m = re.search(r"^## Debrief\s*\n+(.*?)\n+(?=^## |^---\s*$)",
                  p.read_text(encoding="utf-8"), re.S | re.M)
    if not m:
        return None
    body = m.group(1).strip()
    if not body or "_TO BE WRITTEN._" in body:
        return None
    if re.search(r"^## ", body, re.M):
        print("  warning: the Debrief in %s carries a section heading; not "
              "carrying it forward" % p, file=sys.stderr)
        return None
    return body


def md_table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    return "\n".join(out)


def details(summary, lines, open_=False):
    """A collapsed block.

    <details> is part of GitHub-flavoured Markdown and is honoured by the VS Code
    preview, so one construct gives a working disclosure in the .md, in the
    generated .html and on GitHub, with no JavaScript anywhere. The blank lines
    around the body are required: without them the Markdown inside is not parsed.
    """
    return (["<details%s>" % (" open" if open_ else ""),
             "<summary>%s</summary>" % summary, ""] + lines + ["</details>", ""])


def build_report(meta, data, ranges, names, report, pb, figs, anims, rel, debrief=None):
    """The reader's order, which is not the analysis order.

    The debrief comes first because it is the answer; everything after it is the
    evidence for the answer, and evidence is only read when the answer provokes
    a question. Anything that is reference rather than narrative is collapsed, so
    the page stays the length of the argument and not the length of the data."""
    L = []
    when = meta.get("created") or ""
    if re.match(r"^\d{8}\.\d{6}$", when):
        when = datetime.strptime(when, "%Y%m%d.%H%M%S").strftime("%Y-%m-%d %H:%M")
    laps = meta.get("lap_times") or []
    total = meta.get("total_time") or (data[-1]["t"] - data[0]["t"])
    lap_word = "%d lap%s" % (len(laps), "" if len(laps) == 1 else "s") if laps else "no timed lap"

    # Compact header. Raw HTML rather than Markdown because the date has to sit
    # against the right edge, and Markdown has no way to say that.
    L += ['<div class="rhead">',
          '<div class="rmeta">',
          '<span class="k">Race:</span> <b>%s</b> &nbsp;·&nbsp; %s, %s<br>'
          % (esc(race_name(meta)), esc(meta.get("gamemode") or "?"), lap_word),
          '<span class="k">Drone:</span> <b>%s</b>%s' % (esc(meta.get("drone") or "?"),
                                                         "  &nbsp;·&nbsp; <b>CRASHED</b>"
                                                         if meta.get("crashed") else ""),
          '</div>',
          '<div class="rwhen">%s<br><b>%s</b></div>' % (esc(when), fmt_time(total)),
          '</div>', ""]

    L += ["## Debrief", "", debrief or DEBRIEF_STUB, ""]

    L += ["## Data analysis", ""]
    L += ["- " + f for f in findings(meta, report, names, pb)]
    L += [""]

    L += ["## Lap times", "", "![Lap times](%s)" % rel(figs["timeline"]), ""]

    # One entry per lap and nothing called "all". A combined figure sitting as a
    # sibling of the laps it combines reads as a fourth lap; the way to see
    # everything is the expand-all control on the heading, which the HTML adds
    # automatically to any section holding more than one disclosure.
    L += ["## Circuit path", ""]
    for k, p in sorted(figs.get("track_each", {}).items()):
        L += details(names[k].capitalize(), ["![%s](%s)" % (names[k], rel(p)), ""])
    if "line" in figs:
        L += details("Laps overlaid",
                     ["![Laps overlaid](%s)" % rel(figs["line"]), "",
                      "Where the laps separate is a LINE difference. No change of stick "
                      "technique moves a line - only knowing the track does.", ""])

    if anims.get("laps"):
        L += ["## Flight playback", "",
              "The dashed ray is where the quad is *going*. The arrow is where it is "
              "*pointing*. When they separate, that gap is sideslip: the quad is "
              "travelling sideways and the camera is not saying so. The follow cam is "
              "the same flight magnified, because at whole-lap scale the gap is a few "
              "pixels wide.", ""]
        for k, (path, rate) in enumerate(anims["laps"]):
            L += details(names[k].capitalize(),
                         ["![%s](%s)" % (names[k], rel(path)), ""])

    L += ["## Numbers", ""]
    rows = [[names[k], "%.1f" % e["duration_s"], e["speed_median"], e["speed_p90"],
             e["speed_max"], e["tilt_median"], "%.1f" % e["sideslip_median"],
             "%.1f" % e["sideslip_p90"], "%.2f" % e["throttle_median"],
             "%.1f" % e["slow_seconds"]] for k, e in enumerate(report)]
    L += [md_table(["Segment", "s", "spd med", "spd p90", "spd max", "tilt med", "slip med",
                    "slip p90", "thr med", "under 10 km/h"], rows), ""]
    rows = []
    for k, e in enumerate(report):
        y = e["yaw_only"]
        rows.append([names[k], "%.1f" % y["yaw_seconds"], "%.1f" % y["yaw_only_seconds"],
                     "%s%%" % y["yaw_only_pct"] if y["yaw_only_pct"] is not None else "-",
                     y["yaw_only_mean_kmh"],
                     " / ".join("%s: roll %.2f, yaw %.2f"
                                % (b["band"], b["roll_p90"], b["yaw_p90"]) for b in y["bands"])])
    L += ["**Yaw without roll.** A turn flown on yaw alone is a pirouette: the airframe "
          "rotates, the path does not bend.", ""]
    L += [md_table(["Segment", "yaw held (s)", "roll at zero (s)", "share", "mean km/h",
                    "p90 by speed band"], rows), ""]
    L += ["![Speed, sideslip and throttle](%s)" % rel(figs["traces"]), ""]

    if "traces_extra" in figs:
        L += details("Tilt and stick traces",
                     ["![Tilt and sticks](%s)" % rel(figs["traces_extra"]), ""])

    corners = [(k, i, c) for k, e in enumerate(report) for i, c in enumerate(e["corners"], 1)]
    if corners and "corners" in figs:
        body = ["![Corner scorecard](%s)" % rel(figs["corners"]), ""]
        body += [md_table(["Segment", "#", "t", "entry", "min", "exit", "tilt", "slip",
                           "radius m", "thr in", "d thr"],
                          [[names[k], i, "%.1f" % c["t"], c["entry_kmh"], c["min_kmh"],
                            c["exit_kmh"], c["tilt_deg"], "%.1f" % c["sideslip_deg"],
                            c["radius_m"], "%.2f" % c["throttle_in"],
                            "%+.2f" % c["throttle_delta"]] for k, i, c in corners]), ""]
        L += details("Corners (%d)" % len(corners), body)

    stalls = [(k, i, st) for k, e in enumerate(report) for i, st in enumerate(e["stalls"], 1)]
    if stalls:
        body = [md_table(["Segment", "#", "t", "dur", "min km/h", "turn", "retrace", "net",
                          "verdict", "because", "line"],
                         [[names[k], i, "%.1f" % st["t"], "%.1f" % st["duration_s"],
                           "%.1f" % st["min_kmh"],
                           "%+d" % st["turn_deg"] if st["turn_deg"] is not None else "-",
                           "%.1f" % st["retrace_m"] if st["retrace_m"] is not None else "-",
                           "%.1f" % st["net_m"] if st["net_m"] is not None else "-",
                           "**%s**" % st["verdict"], st["why"],
                           "off line by %.1f m" % st["other_lap"]["dist_m"]
                           if st["off_line"] else ""] for k, i, st in stalls]), "",
                "`overrun` - the path reverses and retraces itself. `corner` - another lap "
                "turns hard at the same coordinates, so the track asked for it. "
                "`hesitation` - another lap goes straight through there at speed, so "
                "nothing there needed a stop. A trailing `?` means there was only one lap: "
                "no cross-lap evidence, and the verdict rests on the reversal test alone.", ""]
        for label, path, rate in anims.get("stalls", []):
            body += ["**%s**" % label, "", "![%s](%s)" % (label, rel(path)), ""]
        L += details("Stalls (%d)" % len(stalls), body)

    # A real no-break space, not &nbsp;. This line is Markdown prose, so it goes
    # through md_inline, and esc() would turn the entity into visible text. The
    # character is correct in the .md and in the .html alike.
    L += ["---", "",
          "Replay `%s`\u00a0·\u00a0samples in `%s`\u00a0·\u00a0**full analysis, "
          "including everything not drawn above, in `analysis.json`**\u00a0·\u00a0"
          "generated %s by `fpv_report.py`"
          % (Path(meta.get("_source", "?")).name, rel(figs["csv"]),
             datetime.now().strftime("%Y-%m-%d %H:%M"))]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# a viewable copy
#
# report.md is the source of truth and the thing that gets edited. But Markdown
# in a browser is plain text, and the animations are the whole point, so a
# report you cannot simply double-click is a report that does not get read.
#
# This converts the SUBSET OF MARKDOWN THIS FILE EMITS - nothing more. That is
# not a limitation to apologise for, it is why 60 lines are enough and correct:
# the input is generated three functions up, so the grammar is closed and known.
# If build_report() ever emits something new, extend this with it.
#
# Figures stay as <img src="assets/..."> rather than being inlined. A browser
# loads them over file:// perfectly well, SMIL animates inside an <img>, and it
# keeps the page a few kilobytes instead of a megabyte and a half.
# ---------------------------------------------------------------------------

HTML_CSS = """
:root{color-scheme:light dark;--bg:#ffffff;--fg:#1b1d21;--mut:#6b7178;--line:#e2e5e9;
--pan:#f7f8fa;--acc:#2f5fbf}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--fg:#e7e9ec;--mut:#9aa1a9;
--line:#2b3037;--pan:#1c1f25;--acc:#7aa2f7}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.65 -apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
main{max-width:1040px;margin:0 auto;padding:48px 24px 96px}
h1{font-size:30px;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:21px;margin:52px 0 14px;padding-top:22px;border-top:1px solid var(--line)}
main>h2:first-of-type{border-top:0;padding-top:0;margin-top:26px}
h3{font-size:16px;margin:32px 0 10px;color:var(--mut);text-transform:uppercase;
letter-spacing:.06em}
p{margin:14px 0}
img{max-width:100%;height:auto;display:block;margin:18px 0;
border:1px solid var(--line);border-radius:8px}
code{background:var(--pan);padding:2px 6px;border-radius:4px;font-size:.88em;
font-family:'Cascadia Mono',Consolas,monospace}
hr{border:0;border-top:1px solid var(--line);margin:48px 0 20px}
.tw{overflow-x:auto;margin:18px 0}
table{border-collapse:collapse;font-size:13.5px;width:100%}
th,td{padding:7px 11px;text-align:left;border-bottom:1px solid var(--line);
white-space:nowrap}
th{color:var(--mut);font-weight:600;text-transform:uppercase;font-size:11px;
letter-spacing:.05em}
tr:hover td{background:var(--pan)}
blockquote,.lede{color:var(--mut)}
footer{color:var(--mut);font-size:13px}
.rhead{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;
padding:0 0 18px;border-bottom:1px solid var(--line);margin-bottom:8px;flex-wrap:wrap}
.rmeta{font-size:19px;line-height:1.5}
.rwhen{text-align:right;color:var(--mut);font-size:14px;line-height:1.5;
white-space:nowrap;padding-top:3px}
.rwhen b{color:var(--fg);font-size:19px}
.k{color:var(--mut);font-weight:600;font-size:13px;text-transform:uppercase;
letter-spacing:.06em}
details{border:1px solid var(--line);border-radius:8px;margin:12px 0;
background:var(--pan)}
details[open]{background:transparent}
summary{cursor:pointer;padding:11px 15px;font-weight:600;font-size:14.5px;
list-style:none;user-select:none}
summary::-webkit-details-marker{display:none}
/* the marker is drawn with borders, not a glyph: U+25B8 is missing from the
   default Windows UI font and fell back to a tofu box overlapping the label */
summary::before{content:"";display:inline-block;width:0;height:0;margin-right:10px;
vertical-align:2px;border:5px solid transparent;border-left-color:var(--mut);
transition:transform .12s}
details[open]>summary::before{transform:rotate(90deg) translateX(1px)}
summary:hover{color:var(--acc)}
details>*:not(summary){margin-left:15px;margin-right:15px}
details>*:last-child{margin-bottom:14px}
h2 .xall{margin-left:14px;vertical-align:3px;display:inline-flex;align-items:center;
gap:5px;padding:4px 10px;border:1px solid var(--line);border-radius:999px;
background:transparent;color:var(--mut);cursor:pointer;font:inherit;font-size:12px;
font-weight:500;letter-spacing:.01em}
h2 .xall:hover{color:var(--acc);border-color:var(--acc)}
h2 .xall svg{transition:transform .12s}
h2 .xall[data-open="1"] svg{transform:rotate(180deg)}
/* Tabs. Everything here is gated on .js, set by an inline script in <head>, so
   a page opened without JavaScript keeps the old single scroll and never shows
   a control that cannot work. Gating in CSS rather than hiding panels from
   JavaScript on load also means there is no flash of the whole report first. */
.tabs{display:none;gap:4px;flex-wrap:wrap;position:sticky;top:0;z-index:5;
margin:0 0 30px;padding:10px 0;background:var(--bg);border-bottom:1px solid var(--line)}
.js .tabs{display:flex}
.tab{appearance:none;-webkit-appearance:none;border:1px solid transparent;
border-radius:8px;background:transparent;color:var(--mut);font:inherit;font-size:14px;
font-weight:600;padding:7px 14px;cursor:pointer;white-space:nowrap;
transition:color .12s,background .12s,border-color .12s}
.tab:hover{color:var(--fg);background:var(--pan)}
.tab.on{color:var(--acc);border-color:var(--line);background:var(--pan)}
.tab:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.js .panel{display:none}
.js .panel.on{display:block}
.panel>h2:first-child{border-top:0;padding-top:0;margin-top:0}
/* Paper has no tabs: print every panel, in order, and drop the nav. */
@media print{.tabs{display:none!important}.js .panel{display:block!important}
.panel>h2:first-child{border-top:1px solid var(--line);padding-top:22px;margin-top:52px}}
"""


def md_inline(t):
    """Inline Markdown, in the order the constructs bind.

    Code spans and images are lifted out into placeholders before emphasis runs,
    and put back afterwards. Emphasis is a text construct and has no business
    reaching inside generated markup: without this, the underscores in a replay
    name - `20260828-140705_BardwellsYard_Race_3lap.xml` - and in image paths
    are read as italics, and the tags come out interleaved.

    The placeholder uses NUL, which cannot appear in a report: the text is built
    from XML attributes and formatted numbers."""
    held = []

    def hold(html):
        held.append(html)
        return "\x00%d\x00" % (len(held) - 1)

    t = esc(t)
    t = re.sub(r"`([^`]+)`", lambda m: hold("<code>%s</code>" % m.group(1)), t)
    t = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
               lambda m: hold('<img src="%s" alt="%s">' % (m.group(2), m.group(1))), t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"_([^_]+)_", r"<em>\1</em>", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], t)


EXPAND_ICON = ('<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">'
               '<path d="M4 6.5 8 10.5 12 6.5" fill="none" stroke="currentColor" '
               'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')

EXPAND_JS = """
for (const b of document.querySelectorAll('.xall')) {
  b.addEventListener('click', () => {
    const want = b.getAttribute('data-open') !== '1';
    let n = b.closest('h2').nextElementSibling;
    while (n && n.tagName !== 'H2') {
      if (n.tagName === 'DETAILS') n.open = want;
      for (const d of n.querySelectorAll('details')) d.open = want;
      n = n.nextElementSibling;
    }
    b.setAttribute('data-open', want ? '1' : '0');
    b.lastChild.textContent = want ? 'collapse all' : 'expand all';
  });
}
"""


def add_expand_all(out):
    """Give every section with more than one disclosure a control to open them.

    Done here rather than in build_report so report.md stays clean Markdown: the
    affordance belongs to the rendered page, and the source should not carry a
    button that only one of its two renderings can use.

    Sections are delimited by <h2>, and the button walks its own section at click
    time, so nothing has to be numbered or cross-referenced."""
    heads = [i for i, ln in enumerate(out) if ln.startswith("<h2>")]
    for j, i in enumerate(heads):
        stop = heads[j + 1] if j + 1 < len(heads) else len(out)
        if sum(1 for ln in out[i:stop] if ln.startswith("<details")) < 2:
            continue
        label = out[i][4:-5]
        out[i] = ('<h2>%s<button class="xall" type="button" data-open="0">%s'
                  "<span>expand all</span></button></h2>" % (label, EXPAND_ICON))
    return out


TAB_JS = """
(function () {
  const nav = document.querySelector('.tabs');
  if (!nav) return;
  const tabs = [...nav.querySelectorAll('.tab')];
  const panels = [...document.querySelectorAll('.panel')];
  function show(id, remember) {
    for (const t of tabs) {
      const on = t.dataset.panel === id;
      t.classList.toggle('on', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    }
    for (const p of panels) p.classList.toggle('on', p.id === id);
    // replaceState rather than assigning location.hash: the tab row is
    // navigation inside one document, and every click landing in the back
    // stack would make the back button useless for leaving the report.
    if (remember && history.replaceState) history.replaceState(null, '', '#' + id);
  }
  nav.addEventListener('click', e => {
    const t = e.target.closest('.tab');
    if (t) { show(t.dataset.panel, true); scrollTo(0, 0); }
  });
  nav.addEventListener('keydown', e => {
    const i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    const j = {ArrowRight: (i + 1) % tabs.length,
               ArrowLeft: (i - 1 + tabs.length) % tabs.length,
               Home: 0, End: tabs.length - 1}[e.key];
    if (j === undefined) return;
    e.preventDefault();
    tabs[j].focus();
    show(tabs[j].dataset.panel, true);
  });
  const wanted = () => decodeURIComponent(location.hash.slice(1));
  show(panels.some(p => p.id === wanted()) ? wanted() : panels[0].id, false);
  addEventListener('hashchange', () => {
    if (panels.some(p => p.id === wanted())) show(wanted(), false);
  });
})();
"""


def slugify(text, taken):
    """A readable id for a section, unique within the page."""
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
    s, n = base, 1
    while s in taken:
        n += 1
        s = "%s-%d" % (base, n)
    taken.add(s)
    return s


def add_tabs(out):
    """Put the <h2> sections behind a tab row sitting under the race header.

    Like add_expand_all, this belongs to the rendered page and not to report.md,
    which stays one linear Markdown document that GitHub and the VS Code preview
    render correctly. Only the browser copy is paginated, and the Debrief is
    still the first thing open, because it is still the first section.

    The trailing rule and provenance line are lifted out of the last section
    first. They describe the whole report, so a reader should not have to guess
    which tab to open to find out which replay it came from.

    Sections are delimited by <h2>, the same delimiter add_expand_all uses, so
    the two agree about what a section is by construction. Run this AFTER it:
    the label is taken from the text before the expand-all button, which leaves
    the button in the panel with the disclosures it opens.
    """
    heads = [i for i, ln in enumerate(out) if ln.startswith("<h2>")]
    if len(heads) < 2:
        return out                       # one section is not a set of tabs

    end = len(out)
    for i in range(len(out) - 1, heads[-1], -1):
        if out[i] == "<hr>":
            end = i
            break

    labels, ids, taken = [], [], set()
    for i in heads:
        inner = out[i][len("<h2>"):out[i].rindex("</h2>")].split("<button")[0]
        # Already escaped upstream by md_inline, so strip tags and the one
        # entity that would otherwise read as a word, and do not escape twice.
        label = re.sub(r"<[^>]+>", "", inner).replace("&nbsp;", " ").strip()
        labels.append(label)
        ids.append(slugify(re.sub(r"&[a-z]+;", " ", label), taken))

    nav = ['<nav class="tabs" role="tablist" aria-label="Report sections">']
    nav += ['<button class="tab" type="button" role="tab" id="tab-%s" data-panel="%s" '
            'aria-controls="%s" aria-selected="false" tabindex="-1">%s</button>'
            % (i, i, i, lb) for i, lb in zip(ids, labels)]
    nav += ["</nav>"]

    new = out[:heads[0]] + nav
    for j, i in enumerate(heads):
        stop = heads[j + 1] if j + 1 < len(heads) else end
        new += ['<section class="panel" id="%s" role="tabpanel" aria-labelledby="tab-%s">'
                % (ids[j], ids[j])]
        new += out[i:stop]
        new += ["</section>"]
    return new + out[end:]


ALIGN_RE = re.compile(r"^:?-{3,}:?$")


def md_to_html(md, title):
    out, rows, para = [], [], []
    align = []

    def flush_para():
        if para:
            out.append("<p>%s</p>" % md_inline(" ".join(para)))
            para.clear()

    def flush_table():
        if not rows:
            return
        head, body = rows[0], rows[2:]          # rows[1] is the |---| separator
        al = [(' style="text-align:right"' if c.endswith(":") and not c.startswith(":")
               else "") for c in rows[1]] if len(rows) > 1 else []
        pad = lambda i: al[i] if i < len(al) else ""
        out.append('<div class="tw"><table><thead><tr>%s</tr></thead><tbody>%s'
                   "</tbody></table></div>"
                   % ("".join("<th%s>%s</th>" % (pad(i), md_inline(c))
                              for i, c in enumerate(head)),
                      "".join("<tr>%s</tr>" % "".join("<td%s>%s</td>" % (pad(i), md_inline(c))
                                                      for i, c in enumerate(r))
                              for r in body)))
        rows.clear()

    for line in md.splitlines():
        if line.startswith("|"):
            flush_para()
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
            continue
        flush_table()
        st = line.strip()
        if not st:
            flush_para()
        elif st.startswith("<!--"):
            continue                             # editing notes are not for the page
        elif st.startswith("<") and not st.startswith("<http"):
            # Raw HTML passes straight through. build_report emits exactly two
            # kinds - the compact header and <details> disclosures - and both
            # are also honoured by GitHub and the VS Code Markdown preview, so
            # one construct serves the .md and the .html without divergence.
            flush_para()
            out.append(st)
        elif st == "---":
            flush_para()
            out.append("<hr>")
        elif st.startswith("### "):
            flush_para()
            out.append("<h3>%s</h3>" % md_inline(st[4:]))
        elif st.startswith("## "):
            flush_para()
            out.append("<h2>%s</h2>" % md_inline(st[3:]))
        elif st.startswith("# "):
            flush_para()
            out.append("<h1>%s</h1>" % md_inline(st[2:]))
        elif st.startswith("- "):
            flush_para()
            out.append("<p>&bull;&nbsp; %s</p>" % md_inline(st[2:]))
        elif st.startswith("!["):
            flush_para()
            out.append(md_inline(st))
        else:
            para.append(st)
    flush_para()
    flush_table()
    out = add_tabs(add_expand_all(out))
    # The .js flag is set in <head>, before the body paints, so the browser
    # never shows the whole report for a frame and then collapses it to one tab.
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>%s</title><script>document.documentElement.className='js'</script>"
            "<style>%s</style></head><body><main>%s</main>"
            "<script>%s</script><script>%s</script></body></html>"
            % (esc(title), HTML_CSS, "\n".join(out), EXPAND_JS, TAB_JS))

# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("replay", nargs="?", help="replay XML; omit with --latest")
    ap.add_argument("--latest", action="store_true",
                    help="take the newest replay from the Liftoff Recordings folder")
    ap.add_argument("--root", default=str(LR.DEFAULT_ROOT), help="Recordings folder")
    ap.add_argument("--archive-dir", default="replays",
                    help="where the safety copy of a --latest replay goes")
    ap.add_argument("-o", "--out", default="reports",
                    help="parent folder for the report (default reports)")
    ap.add_argument("--name", help="report folder name (default: the replay's)")
    ap.add_argument("--laps", help='override lap ranges, "732:1879,1879:3056"')
    ap.add_argument("--history", default="data/liftoff_history.json",
                    help="PB snapshot history, from liftoff_pbs.py --save (default "
                         "data/liftoff_history.json, relative to the working "
                         "directory)")
    ap.add_argument("--reset-debrief", action="store_true",
                    help="discard the hand-written Debrief and put the stub back; "
                         "without it, an existing Debrief is carried forward")
    ap.add_argument("--no-html", action="store_true",
                    help="skip report.html, the double-clickable copy of report.md")
    ap.add_argument("--no-open", action="store_true",
                    help="do not open report.html in the default browser")
    ap.add_argument("--no-anim", action="store_true", help="skip the animated figures")
    ap.add_argument("--anim-max", type=float, default=40.0,
                    help="longest animation loop, seconds; anything longer is sped up and "
                         "the factor is printed on the figure (default 40)")
    ap.add_argument("--anim-frames", type=int, default=380, help="frames per animation")
    ap.add_argument("--cam-span", type=float, default=45.0,
                    help="metres across the follow cam on a lap animation (default 45)")
    ap.add_argument("--tail-min", type=float, default=5.0,
                    help="seconds of actual FLYING (above the stall speed) that "
                         "untimed time either side of the laps must contain to "
                         "earn its own segment (default 5). Grid time fails this.")
    ap.add_argument("--stall-pad", type=float, default=4.0,
                    help="seconds of context either side of a stall animation (default 4)")
    args = ap.parse_args()

    path = Path(args.replay) if args.replay else None
    if args.latest or path is None:
        found = LR.find_replays(args.root)
        if not found:
            sys.exit("No replays under %s. Save one from the finish or pause screen." % args.root)
        LR.refuse_inside_toolkit(args.archive_dir, "archived replays")
        path, _ = LR.archive(found[0], args.archive_dir)
        print("replay: %s" % path)

    meta, rows = LR.parse(path)
    rows = LR.add_velocity(rows)
    meta["_source"] = str(path)

    outdir = Path(args.out) / (args.name or Path(path).stem)
    LR.refuse_inside_toolkit(args.out, "reports")
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / "flight.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(LR.COLUMNS)
        for r in rows:
            w.writerow([round(x, 6) for x in r])

    aargs = AF.default_args(str(csv_path))
    data = load_samples(str(csv_path), aargs)
    dt = AF.sample_dt(data)

    # lap boundaries come from the replay itself; --laps only overrides them
    if args.laps:
        ranges = AF.parse_laps(args.laps, len(data))
    elif meta["lap_start_indices"] and meta["lap_times"]:
        starts = meta["lap_start_indices"]
        ranges = [(max(0, a), min(len(data), starts[i + 1] if i + 1 < len(starts)
                                  else a + int(round(meta["lap_times"][i] / dt))))
                  for i, a in enumerate(starts)]
    else:
        ranges = [(0, len(data))]
    names = (["lap %d" % (i + 1) for i in range(len(ranges))]
             if len(ranges) > 1 or meta["lap_times"] else ["flight"])

    # A run that ends in a crash records a completed lap and then keeps
    # recording, and lapTimes only describes the laps that FINISHED. Left alone,
    # the flying after the last timed lap - which on a fatal run is the whole
    # point - is analysed nowhere and silently disappears from the report. The
    # 20:12 Rustline replay lost 69 s that way, the crash included.
    #
    # The tail is also treated as a segment for the cross-lap stall probe, which
    # is legitimate: it crosses the same coordinates, so it is real evidence
    # about what the track asked for there.
    if not args.laps:
        ranges, names = cover_tail(ranges, names, data, dt, args.tail_min,
                                   aargs.stall_speed)

    report = AF.analyse(data, ranges, names, dt, aargs)
    if not report:
        sys.exit("no moving samples in %s" % path)
    pb = pb_context(meta, args.history)

    assets = outdir / "assets"
    # Clear the figures before redrawing. Every SVG in here is written by this
    # run, so anything left from a previous one is stale by definition - and a
    # stale figure is worse than a missing one, because it looks current. The
    # 2026-08-27 grid-segment fix left anim_beforelap1.svg and five orphaned
    # stall clips sitting in the folder describing a segment that no longer
    # exists.
    if assets.exists():
        for old_svg in assets.glob("*.svg"):
            old_svg.unlink()
    rel = lambda p: str(Path(p).relative_to(outdir)).replace("\\", "/")
    vref = max(1.0, pctl([s["spd"] for s in data], 90))
    figs = {"csv": csv_path, "timeline": assets / "timeline.svg",
            "traces": assets / "traces.svg"}

    fig_timeline(data, ranges, names, report, figs["timeline"], "Lap times",
                 best_lap=pb.get("best_lap"), lap_times=meta.get("lap_times"))
    # One figure per segment, never a combined multi-panel one: the report shows
    # them one disclosure at a time, and a panel grid nobody embeds is a file
    # that goes stale without anyone noticing.
    figs["track_each"] = {}
    for k in range(len(ranges)):
        p = assets / ("track_%s.svg" % names[k].replace(" ", ""))
        fig_track(data, [ranges[k]], [names[k]], [report[k]], vref, p,
                  "%s - circuit path, coloured by speed" % names[k].capitalize())
        figs["track_each"][k] = p
    if len(ranges) > 1:
        figs["line"] = assets / "line.svg"
        fig_line(data, ranges, names, figs["line"], "Laps overlaid")
    # the headline traces and the reference traces are separate figures, so the
    # three that get read every time are not buried under the two that do not
    fig_traces(data, ranges, names, report, figs["traces"],
               "Speed, sideslip and throttle", ["speed", "sideslip", "throttle"])
    figs["traces_extra"] = assets / "traces_extra.svg"
    fig_traces(data, ranges, names, report, figs["traces_extra"],
               "Tilt and stick inputs", ["tilt", "sticks"])
    cf = assets / "corners.svg"
    if fig_corners(report, names, cf, "Corner scorecard"):
        figs["corners"] = cf

    anims = {"laps": [], "stalls": []}
    if not args.no_anim:
        for k, (a, b) in enumerate(ranges):
            p = assets / ("anim_%s.svg" % names[k].replace(" ", ""))
            rate = fig_anim(data, a, b, p, "%s, played back" % names[k],
                            meta.get("environment") or "the track", vref,
                            args.anim_max, args.anim_frames, args.cam_span)
            if rate:
                anims["laps"].append((p, rate))
        pad = max(1, int(round(args.stall_pad / dt)))
        for k, e in enumerate(report):
            for i, st in enumerate(e["stalls"], 1):
                s0, s1 = st["index"]
                p = assets / ("anim_stall_%d_%d.svg" % (k + 1, i))
                label = "%s, stall %d at %.1f s - %s" % (names[k], i, st["t"], st["verdict"])
                rate = fig_anim(data, max(0, s0 - pad), min(len(data), s1 + pad), p,
                                label, st["why"], vref, args.anim_max, args.anim_frames,
                                cam_span_m=22.0)
                if rate:
                    anims["stalls"].append((label, p, rate))

    md_path = outdir / "report.md"
    kept = None if args.reset_debrief else existing_debrief(md_path)
    write(md_path, build_report(meta, data, ranges, names, report, pb, figs, anims, rel, kept))
    if kept:
        print("  kept the existing Debrief section")
    html_path = outdir / "report.html"
    if not args.no_html:
        write(html_path, md_to_html(md_path.read_text(encoding="utf-8"),
                                    "%s - %s" % (meta.get("environment") or "?",
                                                 meta.get("gamemode") or "?")))
    # The full analysis, deliberately a superset of the report.
    #
    # report.md and report.html are an argument made to a person, so they leave
    # things out on purpose - collapsed sections, dropped panels, rounded
    # figures. This file leaves nothing out, so a later reader (usually an LLM
    # picking the session back up) never has to re-derive what was already
    # computed, and never has to guess which thresholds produced a number.
    full = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "source_replay": str(path),
        "race_name": race_name(meta),
        "meta": {k: v for k, v in meta.items() if not k.startswith("_")},
        "sample_rate_hz": round(1.0 / dt, 3),
        "sample_interval_s": round(dt, 6),
        "speed_ref_kmh": round(vref, 2),
        "speed_ref_note": "p90 speed; the figures' colour ramp saturates here",
        "thresholds": {k: v for k, v in vars(aargs).items() if k != "csv"},
        "segments_index": [
            {"name": names[k], "start_index": a, "end_index": b,
             "start_t": round(data[a]["t"], 3), "end_t": round(data[b - 1]["t"], 3),
             "lap_time": (meta["lap_times"][k]
                          if meta.get("lap_times") and k < len(meta["lap_times"])
                          and names[k].startswith("lap") else None),
             "timed_lap": bool(meta.get("lap_times") and k < len(meta["lap_times"])
                               and names[k].startswith("lap"))}
            for k, (a, b) in enumerate(ranges)],
        "segments": report,
        "findings": findings(meta, report, names, pb),
        "personal_bests": pb,
        "figures": {k: (rel(v) if isinstance(v, Path)
                        else {str(i): rel(p) for i, p in v.items()})
                    for k, v in figs.items()},
        "animations": {"laps": [rel(p) for p, _ in anims["laps"]],
                       "stalls": [{"label": lb, "file": rel(p)}
                                  for lb, p, _ in anims["stalls"]]},
        "not_in_report": [
            "per-sample trajectory, attitude and stick positions: flight.csv",
            "tilt and stick traces are collapsed in the report; the numbers are "
            "in segments[].tilt_* and segments[].yaw_only",
            "corner and stall tables are collapsed in the report; full detail in "
            "segments[].corners and segments[].stalls",
        ],
    }
    with open(outdir / "analysis.json", "w", encoding="utf-8") as fh:
        json.dump(full, fh, indent=2)

    print("report: %s" % md_path)
    print("        %s" % (outdir / "analysis.json"))
    if not args.no_html:
        print("        %s" % html_path)
    print("  %d figures, %d animations, %d segment(s)"
          % (len(figs) - 1, len(anims["laps"]) + len(anims["stalls"]), len(ranges)))

    # The report is the deliverable, so show it rather than printing a path and
    # trusting someone to follow it. Failure here is never worth aborting on:
    # the files are already written, and a machine with no browser - a CI box, a
    # headless container - must still exit 0.
    if not (args.no_html or args.no_open):
        try:
            opened = webbrowser.open(html_path.resolve().as_uri())
        except Exception:
            opened = False
        if not opened:
            print("  (could not open a browser; open the file above by hand)")


if __name__ == "__main__":
    main()
