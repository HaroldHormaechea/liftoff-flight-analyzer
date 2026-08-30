#!/usr/bin/env python3
"""
fpv_report.py - turn a Liftoff replay into an illustrated Markdown debrief.

One command takes a saved replay to a folder holding the decoded CSV, a set of
SVG figures, an animated SVG replay of every lap, a playable 3D recording of
every crash and every stall, and a report.md that embeds them all.

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

Recordings
----------
Crashes and stalls each get a recording: the 3D incident view from
liftoff_view.py, opened from the event's own row in its table and played back in
a window inside the page. Environment geometry is drawn when the caches for that
environment exist and is honestly reported as missing when they do not - the
path, the attitude and the impacts come from the replay either way. `--no-rec`
skips them.

Usage
-----
  python fpv_report.py --latest
  python fpv_report.py replays/<archived-replay>.xml
  python fpv_report.py <replay.xml> -o reports --no-anim
  python fpv_report.py <replay.xml> --laps "732:1879,1879:3056"
  python fpv_report.py --latest --no-auto-open

Lap ranges come from the replay metadata automatically; --laps only overrides
them, for an abandoned attempt worth splitting by hand.

report.html opens in the default browser once it is written, because the report
is the deliverable and a path printed to a terminal is not one.

--no-auto-open suppresses that. Pass it whenever the Debrief is going to be
written after this run - which is every run a coach or an agent makes - and open
the report yourself once it says something. The automatic open fires when the
file is WRITTEN, so on a fresh report it puts a page reading "TO BE WRITTEN" in
front of the reader, and the regeneration that fills the Debrief in does not
refresh that tab. A batch run wants the flag too. --no-open is the older
spelling and still works.
"""

import csv
import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analyze_flight as AF
import liftoff_replay as LR
import liftoff_tracks as LT
import liftoff_view as LV

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


def legend_speed(x, y, vref, w=210, label="speed"):
    """The key for the speed ramp the paths are drawn with.

    `label` exists because the animation already has a live speed readout, and
    two things both captioned "speed" leave the reader guessing which one the
    coloured line belongs to."""
    stops = "".join('<stop offset="%d%%" stop-color="%s"/>' % (100 * i // 8, ramp(i / 8.0))
                    for i in range(9))
    return ('<defs><linearGradient id="spd">%s</linearGradient></defs>'
            '<rect x="%s" y="%s" width="%d" height="9" rx="4.5" fill="url(#spd)"/>'
            % (stops, n(x), n(y), w)
            + txt(x, y - 5, label, 9.5, "mut")
            + txt(x, y + 20, "0", 9.5, "mut")
            + txt(x + w, y + 20, "%d+ km/h" % round(vref), 9.5, "mut", "end"))


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
    # 74, not 44, at the foot: the speed ramp key sits above the caption. The
    # path is coloured by speed in both the overview and the follow cam, and
    # until this was drawn there was nothing anywhere saying so.
    H = 46 + mh + 34 + cam + 74
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
    body.append(legend_speed(14, H - 52, vref, label="path colour"))
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




# ---------------------------------------------------------------------------
# recordings
#
# A crash and a stall are the two moments a pilot actually wants to look at
# again, and a table row describing one is not a look at it. So each of them
# gets a recording: the 3D incident view - environment geometry, track props,
# the flown path coloured by speed, the quad at its true attitude, every impact
# marked - opened from its own row in the table and played back in a modal on
# the page.
#
# The renderer is imported from liftoff_view.py, never copied. That file owns
# the projection and the playback; this one owns where the windows are cut and
# what the page around them looks like.
#
# Geometry is best-effort BY DESIGN. An environment's colliders exist only once
# its scene bundle has been cached (liftoff_scene.py) and prop shapes only once
# the prefabs have been (liftoff_props.py) - two of five environments flown so
# far. Neither is needed for the part that matters most: where the quad went,
# how it was pointing and where it stopped all come from the replay itself. A
# recording with no geometry says so in its own footer rather than not existing.
# ---------------------------------------------------------------------------

CRASH_PAD = 3.0          # seconds either side of an impact
NEAR_HIT_M = 6.0         # a prop further than this was not what the quad hit


class Pool:
    """A shared table of geometry so two recordings of one corner ship it once.

    Every recording is culled independently, and incidents cluster - two impacts
    0.7 s apart, a stall and a crash at the same hairpin - so the same few
    hundred colliders come back again and again. Identical entries collapse to
    one index here, which is the difference between a report of a bad session
    weighing two megabytes and weighing six."""

    def __init__(self):
        self.items = []
        self.index = {}

    def add(self, obj):
        key = json.dumps(obj, separators=(",", ":"), sort_keys=True)
        if key not in self.index:
            self.index[key] = len(self.items)
            self.items.append(obj)
        return self.index[key]




def find_crashes(rows, hits, ranges, names):
    """One record per impact: when, how hard, where in the run, and how high.

    `hits` comes from the trajectory, not from the replay's isCrashed flag,
    which reads false on flights that ended pinned against the ground - see
    liftoff_view.impacts()."""
    t0 = rows[0][0]
    out = []
    for n, i in enumerate(hits, 1):
        seg = next((names[k] for k, (a, b) in enumerate(ranges) if a <= i < b), "-")
        out.append({
            "n": n,
            "index": i,
            "t": round(rows[i][0] - t0, 1),
            "segment": seg,
            "entry_kmh": round(rows[max(0, i - 1)][16], 1),
            "min_kmh": round(rows[i][16], 1),
            "drop_kmh": round(rows[max(0, i - 1)][16] - rows[i][16], 1),
            "height_m": round(rows[i][2], 2),
            # Two seconds later. The number that separates a clip that cost a
            # moment from one that ended the run.
            "after_kmh": round(rows[min(len(rows) - 1, i + 20)][16], 1),
            "hit": None,
        })
    return out


def crash_id(c):
    return "crash-%d" % c["n"]


def stall_id(k, i):
    return "stall-%d-%d" % (k + 1, i)


def build_recordings(rows, hits, crashes, report, names, scene, note,
                     props_for, prop_size, dt, radius, stall_pad,
                     crash_pad=CRASH_PAD):
    """A payload per crash and per stall, all sharing one pool of geometry.

    `props_for` is a callable the caller supplies: hand it the points of one
    window and it answers what the sim's map has near them. It is injected
    rather than imported because finding props means reading a sim's own track
    files, and this module may not know that a sim exists. A caller with no
    track data passes one that returns nothing, and every recording still draws
    its path, its attitude and its impacts."""
    colliders, props = Pool(), Pool()
    items = {}

    def add(rec_id, title, i0, i1, focus):
        data = LV.build(rows, i0, i1, focus=focus, radius=radius,
                        props=props_for(LV.window_points(rows, i0, i1)),
                        prop_size=prop_size, scene=scene, hits=hits, note=note)
        found = data["props"]
        data["title"] = title
        data["colliders"] = [colliders.add(c) for c in data["colliders"]]
        data["props"] = [props.add(p) for p in found]
        items[rec_id] = data
        return found

    half = max(1, int(round(crash_pad / dt)))
    for c in crashes:
        i = c["index"]
        found = add(crash_id(c),
                    "%s - impact at %.1f s, %.0f to %.0f km/h"
                    % (c["segment"], c["t"], c["entry_kmh"], c["min_kmh"]),
                    max(0, i - half), min(len(rows), i + half + 1), i)
        # What it hit, when the track data says anything at all. Solid props
        # only: a checkpoint volume and a pit trigger are flown through.
        near = [(math.dist(p["p"], rows[i][1:4]), p) for p in found if p["k"] == "prop"]
        if near:
            d, p = min(near, key=lambda pair: pair[0])
            if d <= NEAR_HIT_M:
                c["hit"] = {"item": p["n"], "dist_m": round(d, 1)}

    pad = max(1, int(round(stall_pad / dt)))
    for k, e in enumerate(report):
        for i, st in enumerate(e["stalls"], 1):
            s0, s1 = st["index"]
            add(stall_id(k, i),
                "%s, stall %d at %.1f s - %s" % (names[k], i, st["t"], st["verdict"]),
                max(0, s0 - pad), min(len(rows), s1 + pad + 1), (s0 + s1) // 2)

    return {"geo": colliders.items, "props": props.items, "items": items}


def findings(meta, report, names, pb, crashes=()):
    """Mechanical observations: true by arithmetic, no judgement.

    Kept separate from the Debrief on purpose. A generated sentence can say a
    number is large; only a person knows whether the pilot was already told
    about it last session, which is the whole difference between coaching and
    nagging."""
    out = []
    if crashes:
        worst = max(crashes, key=lambda c: c["drop_kmh"])
        what = (", into %s %.1f m away" % (worst["hit"]["item"], worst["hit"]["dist_m"])
                if worst["hit"] else "")
        out.append("**%d impact%s**, at %s. The hardest took %.0f km/h out in a tenth of "
                   "a second - %.0f to %.0f km/h, %.1f m up%s."
                   % (len(crashes), "" if len(crashes) == 1 else "s",
                      ", ".join("%.1f s" % c["t"] for c in crashes), worst["drop_kmh"],
                      worst["entry_kmh"], worst["min_kmh"], worst["height_m"], what))
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


DEBRIEF_STUB = ("<!-- Written by hand after reading the figures. Read the pilot's notes "
                "file first, so this does not repeat advice already given and absorbed. "
                "Above the Recommendations heading goes the assessment: what happened, "
                "what it means, and what is still wrong - a result that went well is "
                "reported in the same register as one that did not. Below it go the "
                "instructions, numbered. One fault, one drill, no stacking. Delete this "
                "comment when filled in. -->"
                "\n\n_TO BE WRITTEN._"
                "\n\n### Recommendations\n\n_TO BE WRITTEN._")


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


def rec_cell(rec_id, rec_ids):
    """The recording link that sits on an event's own row.

    A plain Markdown link, so report.md stays Markdown and stays honest: the
    recording lives in the HTML copy and the link says so. md_inline turns the
    same link into the control that opens the modal."""
    return ("[▶ View recording](report.html#rec-%s)" % rec_id
            if rec_id in rec_ids else "-")


def build_report(meta, data, ranges, names, report, pb, figs, anims, rel, debrief=None,
                 crashes=(), rec_ids=()):
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
    L += ["- " + f for f in findings(meta, report, names, pb, crashes)]
    L += [""]

    L += ["## Lap times", "", "![Lap times](%s)" % rel(figs["timeline"]), ""]

    # One entry per lap and nothing called "all". A combined figure sitting as a
    # sibling of the laps it combines reads as one more lap; the way to see
    # everything is the expand-all control on the heading, which the HTML adds
    # automatically to any section holding more than one disclosure.
    #
    # The overlay is the exception, and it earns it by answering a different
    # question: not "how did this lap go" but "where did the LINE move between
    # laps". It sits here because a static map of every lap at once is the one
    # thing the playback cannot show - the playback is always one lap.
    if anims.get("laps") or "line" in figs:
        L += ["## Flight playback", ""]
        if anims.get("laps"):
            L += ["The dashed ray is where the quad is *going*. The arrow is where it is "
                  "*pointing*. When they separate, that gap is sideslip: the quad is "
                  "travelling sideways and the camera is not saying so. The follow cam is "
                  "the same flight magnified, because at whole-lap scale the gap is a few "
                  "pixels wide.", ""]
        for k, (path, rate) in enumerate(anims.get("laps", [])):
            L += details(names[k].capitalize(),
                         ["![%s](%s)" % (names[k], rel(path)), ""])
        if "line" in figs:
            L += details("Laps overlaid",
                         ["![Laps overlaid](%s)" % rel(figs["line"]), "",
                          "Every lap on one map, each a different colour. Where the laps "
                          "separate is a LINE difference. No change of stick technique "
                          "moves a line - only knowing the track does.", ""])

    # The section leads with the moments and ends with the reference tables, in
    # the order a pilot asks for them: what went wrong, then where it went
    # slowly, then the numbers behind both. The crashes and the stalls open on
    # arrival - they are the point of the section, and each row carries the
    # control that plays it - while everything below them stays collapsed.
    L += ["## Highlights and recordings", ""]

    if crashes:
        body = [md_table(["Segment", "#", "t", "km/h in", "km/h after", "lost", "height m",
                          "2 s later", "hit", "recording"],
                         [[c["segment"], c["n"], "%.1f" % c["t"], "%.1f" % c["entry_kmh"],
                           "%.1f" % c["min_kmh"], "**%.0f**" % c["drop_kmh"],
                           "%.2f" % c["height_m"], "%.1f" % c["after_kmh"],
                           ("%s, %.1f m" % (c["hit"]["item"], c["hit"]["dist_m"]))
                           if c["hit"] else "-",
                           rec_cell(crash_id(c), rec_ids)] for c in crashes]), "",
                "An impact is read from the trajectory, not from the replay's `isCrashed` "
                "flag: a run that ends pinned against the ground at full throttle records "
                "that flag as false. Losing 20 km/h or more inside one 0.1 s sample is not "
                "something braking can do. `hit` is the nearest SOLID track prop, and is "
                "blank when the track data for this environment has not been extracted - "
                "not a claim that the quad hit nothing.", ""]
        L += details("Crashes (%d)" % len(crashes), body, open_=True)

    stalls = [(k, i, st) for k, e in enumerate(report) for i, st in enumerate(e["stalls"], 1)]
    if stalls:
        body = [md_table(["Segment", "#", "t", "dur", "min km/h", "turn", "retrace", "net",
                          "verdict", "because", "line", "recording"],
                         [[names[k], i, "%.1f" % st["t"], "%.1f" % st["duration_s"],
                           "%.1f" % st["min_kmh"],
                           "%+d" % st["turn_deg"] if st["turn_deg"] is not None else "-",
                           "%.1f" % st["retrace_m"] if st["retrace_m"] is not None else "-",
                           "%.1f" % st["net_m"] if st["net_m"] is not None else "-",
                           "**%s**" % st["verdict"], st["why"],
                           "off line by %.1f m" % st["other_lap"]["dist_m"]
                           if st["off_line"] else "",
                           rec_cell(stall_id(k, i), rec_ids)] for k, i, st in stalls]), "",
                "`overrun` - the path reverses and retraces itself. `corner` - another lap "
                "turns hard at the same coordinates, so the track asked for it. "
                "`hesitation` - another lap goes straight through there at speed, so "
                "nothing there needed a stop. A trailing `?` means there was only one lap: "
                "no cross-lap evidence, and the verdict rests on the reversal test alone.", ""]
        L += details("Stalls (%d)" % len(stalls), body, open_=True)

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

/* Recordings. The control sits in the event's own row - the moment and the way
   to watch it on one line - and opens a window inside the page rather than a
   browser one: a real pop-up loses the report's palette, its scroll position
   and, in most browsers, the click that asked for it. */
a.rec{display:inline-flex;flex-direction:column;align-items:center;gap:2px;
text-decoration:none;color:var(--acc);padding:3px 8px;border-radius:7px;line-height:1.15}
a.rec:hover{background:var(--pan)}
a.rec svg{display:block}
a.rec span{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;
color:var(--mut)}
a.rec:hover span{color:var(--acc)}
a.rec:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
th.rc,td.rc{position:sticky;right:0;text-align:center;background:var(--bg);
box-shadow:-9px 0 9px -9px rgba(0,0,0,.35)}
tr:hover td.rc{background:var(--pan)}
.recwrap{position:fixed;inset:0;z-index:50;display:flex;align-items:center;
justify-content:center;padding:24px}
.recwrap[hidden]{display:none}
.recdim{position:absolute;inset:0;background:rgba(9,11,14,.62)}
.recwin{position:relative;display:flex;flex-direction:column;width:min(1080px,100%);
max-height:100%;background:var(--bg);border:1px solid var(--line);border-radius:12px;
box-shadow:0 24px 64px rgba(0,0,0,.45);overflow:hidden}
.recbar{display:flex;align-items:center;gap:10px;padding:9px 10px 9px 14px;
background:var(--pan);border-bottom:1px solid var(--line)}
.recbar h3{flex:1;margin:0;font-size:14px;font-weight:600;color:var(--fg);
text-transform:none;letter-spacing:0;white-space:nowrap;overflow:hidden;
text-overflow:ellipsis}
.recx{appearance:none;-webkit-appearance:none;border:1px solid transparent;
background:transparent;color:var(--mut);font:inherit;font-size:15px;line-height:1;
padding:5px 9px;border-radius:7px;cursor:pointer}
.recx:hover{background:var(--bg);border-color:var(--line);color:var(--fg)}
/* The stage keeps its own dark ground in both themes. It is a view through a
   camera, not a panel of the document, and the geometry colours were chosen
   against this background. */
.recstage{position:relative;background:#0e1116;height:min(60vh,560px)}
.recstage canvas{display:block;width:100%;height:100%;cursor:grab}
.recstage canvas.drag{cursor:grabbing}
.rechud,.reclegend{position:absolute;top:10px;pointer-events:none;color:#c9d1d9;
text-shadow:0 1px 3px #000}
.rechud{left:13px;font-size:12px}
.reclegend{right:13px;text-align:right;font-size:11px;line-height:1.65}
.reclegend i{display:inline-block;width:9px;height:9px;margin-right:5px;
border-radius:2px;vertical-align:middle}
.recctl{display:flex;align-items:center;gap:10px;padding:10px 14px;
border-top:1px solid var(--line);background:var(--pan)}
.recctl input[type=range]{flex:1;min-width:120px;accent-color:var(--acc)}
.recbtn{appearance:none;-webkit-appearance:none;border:1px solid var(--line);
background:var(--bg);color:var(--fg);font:inherit;font-size:13px;padding:5px 12px;
border-radius:7px;cursor:pointer}
.recbtn:hover{border-color:var(--acc);color:var(--acc)}
.rectime{font-variant-numeric:tabular-nums;color:var(--mut);font-size:13px;min-width:92px}
.recnote{margin:0;padding:9px 14px 12px;background:var(--pan);color:var(--mut);
font-size:12px;border-top:1px solid var(--line)}
.recnote[hidden]{display:none}
@media (max-width:640px){.recctl{flex-wrap:wrap}.recstage{height:46vh}
.reclegend{display:none}}
@media print{.recwrap{display:none!important}}
"""


REC_ICON = ('<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">'
            '<circle cx="10" cy="10" r="8.5" fill="none" stroke="currentColor" '
            'stroke-width="1.5"/><path d="M8.3 6.4 14 10l-5.7 3.6Z" fill="currentColor"/>'
            "</svg>")

REC_HREF = re.compile(r"^(?:report\.html)?#rec-(.+)$")


def md_link(text, href):
    """A Markdown link. A link to a recording becomes the control that plays it.

    The .md and the .html carry the same construct, which is the rule the whole
    renderer follows: report.md keeps a link that says the recording is in the
    HTML copy, and the HTML copy turns that link into the play control on the
    event's row."""
    m = REC_HREF.match(href)
    if not m:
        return '<a href="%s">%s</a>' % (href, text)
    label = text.lstrip("▶ ").strip() or "View recording"
    return ('<a class="rec" href="#rec-%s" data-rec="%s" title="Play this recording">'
            "%s<span>%s</span></a>" % (m.group(1), m.group(1), REC_ICON, label))


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
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
               lambda m: hold(md_link(m.group(1), m.group(2))), t)
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


# One window, reused. Only one recording is ever being watched, and a page that
# builds a canvas per incident pays for every incident on load - a bad session
# has six - to show at most one of them.
REC_MODAL = """
<div class="recwrap" id="recmodal" hidden>
  <div class="recdim" data-close></div>
  <div class="recwin" role="dialog" aria-modal="true" aria-labelledby="rectitle">
    <div class="recbar">
      <h3 id="rectitle"></h3>
      <button class="recx" type="button" data-close aria-label="Close recording"
              title="Close">&#10005;</button>
    </div>
    <div class="recstage">
      <canvas data-fpv="canvas"></canvas>
      <div class="rechud">drag to orbit &middot; wheel to zoom<br>
        <span data-fpv="readout"></span></div>
      <div class="reclegend">
        <i style="background:#5b6b7f"></i>scene collider<br>
        <i style="background:#e3b341"></i>solid track prop<br>
        <i style="background:#4dd0c7"></i>route checkpoint<br>
        <i style="background:#3a4a5c"></i>pit trigger (not solid)<br>
        <i style="background:#f0524d"></i>impact
      </div>
    </div>
    <div class="recctl">
      <button class="recbtn" type="button" data-fpv="play">Play</button>
      <input data-fpv="scrub" type="range" min="0" max="0" step="1" value="0"
             aria-label="Playback position">
      <span class="rectime" data-fpv="time"></span>
      <button class="recbtn" type="button" data-fpv="gates">Show route</button>
      <button class="recbtn" type="button" data-fpv="triggers">Show triggers</button>
    </div>
    <p class="recnote" hidden></p>
  </div>
</div>
"""

REC_JS = """
(function () {
  const modal = document.getElementById('recmodal');
  if (!modal || typeof FPV_REC === 'undefined') return;
  const title = document.getElementById('rectitle');
  const note = modal.querySelector('.recnote');
  let viewer = null, opener = null;

  /* Geometry is pooled across recordings and referenced by index, so the
     payload is rebuilt into the shape the viewer expects on the way in. */
  function payload(id) {
    const it = FPV_REC.items[id];
    if (!it) return null;
    const D = Object.assign({}, it);
    D.colliders = it.colliders.map(i => FPV_REC.geo[i]);
    D.props = it.props.map(i => FPV_REC.props[i]);
    return D;
  }
  function teardown() {
    if (viewer) { viewer.destroy(); viewer = null; }
    modal.hidden = true;
    document.body.style.overflow = '';
  }
  function close() {
    teardown();
    if (opener) { opener.focus(); opener = null; }
  }
  function open(id, from) {
    const D = payload(id);
    if (!D) return;
    teardown();
    opener = from || null;
    title.textContent = D.title || 'Recording';
    note.textContent = D.note ? 'Not drawn: ' + D.note + '.' : '';
    note.hidden = !D.note;
    modal.hidden = false;
    // The page behind must not scroll under the window.
    document.body.style.overflow = 'hidden';
    viewer = fpvViewer(modal, D);
    modal.querySelector('.recx').focus();
  }

  document.addEventListener('click', e => {
    const a = e.target.closest('a[data-rec]');
    if (a) { e.preventDefault(); open(a.dataset.rec, a); return; }
    if (!modal.hidden && e.target.closest('[data-close]')) close();
  });
  addEventListener('keydown', e => {
    if (e.key === 'Escape' && !modal.hidden) { e.preventDefault(); close(); }
  });
})();
"""


ALIGN_RE = re.compile(r"^:?-{3,}:?$")


def md_to_html(md, title, recs=None):
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
        # An incident table is a dozen columns wide and scrolls sideways inside
        # its own box, so a recording column left to sit at the far end of it is
        # a control the reader has to go looking for. It is pinned to the right
        # edge instead, and stays on the event's row wherever the row is scrolled
        # to. Found by column, not by cell, so an event with no recording keeps
        # the same pinned cell rather than punching a hole in it.
        rc = next((i for i, c in enumerate(head) if c.strip().lower() == "recording"), None)
        attrs = lambda i: (' class="rc"' if i == rc else "") + (al[i] if i < len(al) else "")
        out.append('<div class="tw"><table><thead><tr>%s</tr></thead><tbody>%s'
                   "</tbody></table></div>"
                   % ("".join("<th%s>%s</th>" % (attrs(i), md_inline(c))
                              for i, c in enumerate(head)),
                      "".join("<tr>%s</tr>" % "".join("<td%s>%s</td>" % (attrs(i), md_inline(c))
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

    # The recordings ride in the page rather than in files beside it. A report
    # is opened over file://, where fetch() of a sibling JSON is blocked, so
    # anything the page needs on click has to already be in the page.
    #
    # Built by concatenation, not by %-formatting: the viewer's playback loop
    # contains a modulo, and one stray %d in a script is a silent MISSING
    # renderer rather than an error anyone would see.
    body = ["<main>", "\n".join(out), "</main>"]
    scripts = ["<script>" + EXPAND_JS + "</script>", "<script>" + TAB_JS + "</script>"]
    if recs and recs.get("items"):
        body.append(REC_MODAL)
        scripts.append("<script>const FPV_REC = "
                       + json.dumps(recs, separators=(",", ":")) + ";</script>")
        scripts.append("<script>" + LV.VIEWER_JS + "</script>")
        scripts.append("<script>" + REC_JS + "</script>")
    # The .js flag is set in <head>, before the body paints, so the browser
    # never shows the whole report for a frame and then collapses it to one tab.
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>" + esc(title) + "</title>"
            "<script>document.documentElement.className='js'</script>"
            "<style>" + HTML_CSS + "</style></head><body>"
            + "".join(body) + "".join(scripts) + "</body></html>")

