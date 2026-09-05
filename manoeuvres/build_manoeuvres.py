#!/usr/bin/env python3
"""
manoeuvres.py - synthetic freestyle manoeuvres, drawn with the fpv-review viewer.

Every flight report in this project renders its crashes and stalls with
common/incident_view.py: a path coloured by speed, the quad drawn at its true
attitude, orbitable in 3D. A training plan needs the same picture for a
manoeuvre the pilot has NOT flown yet, so this builds the same `series` the
viewer eats - position, attitude quaternion and speed at 10 Hz - from a
parametric definition instead of from a replay.

Frame, verified against a real replay: right-handed, Y up, body forward = +Z,
body up = +Y, body right = +X = cross(up, forward).

Speed is DERIVED from the path by finite difference, never asserted, so the
colour ramp on these pages means the same thing it means on a real recording.
Stick positions are left at zero: the viewer does not draw them, and a synthetic
throttle trace sitting in the same schema as a measured one is a trap.
"""
import math
import sys
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from fpv_review.common import incident_view
from fpv_review.common import report as R
from fpv_review.common.schema import FlightSample
from fpv_review.sources.liftoff import calibration

DT = 0.1
UP = (0.0, 1.0, 0.0)
FWD = (0.0, 0.0, 1.0)


def norm(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / n for c in v)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def rot(v, axis, ang):
    """Rodrigues: rotate v about a unit axis."""
    c, s = math.cos(ang), math.sin(ang)
    d = sum(a * b for a, b in zip(axis, v))
    cr = cross(axis, v)
    return tuple(v[i] * c + cr[i] * s + axis[i] * d * (1 - c) for i in range(3))


def quat(X, Y, Z):
    """Quaternion from the basis whose images are X (right), Y (up), Z (forward)."""
    m = [[X[0], Y[0], Z[0]], [X[1], Y[1], Z[1]], [X[2], Y[2], Z[2]]]
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x = (m[2][1] - m[1][2]) / s
        y = (m[0][2] - m[2][0]) / s
        z = (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        w = (m[2][1] - m[1][2]) / s
        x = 0.25 * s
        y = (m[0][1] + m[1][0]) / s
        z = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        w = (m[0][2] - m[2][0]) / s
        x = (m[0][1] + m[1][0]) / s
        y = 0.25 * s
        z = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        w = (m[1][0] - m[0][1]) / s
        x = (m[0][2] + m[2][0]) / s
        y = (m[1][2] + m[2][1]) / s
        z = 0.25 * s
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    return (x / n, y / n, z / n, w / n)


def series(frames):
    """frames: list of (pos, fwd, up) -> FlightSample list with derived speed."""
    out = []
    last = len(frames) - 1
    for i, (p, f, u) in enumerate(frames):
        f = norm(f)
        d = sum(a * b for a, b in zip(u, f))
        u = norm(tuple(u[k] - f[k] * d for k in range(3)))
        r = cross(u, f)
        j0 = max(0, i - 1)
        j1 = min(last, i + 1)
        span = DT * (j1 - j0)
        vel = tuple((frames[j1][0][k] - frames[j0][0][k]) / span for k in range(3))
        ms = math.sqrt(sum(c * c for c in vel))
        out.append(FlightSample(t=round(i * DT, 3), pos=tuple(p),
                                attitude=quat(r, u, f), velocity=vel,
                                speed_ms=ms, speed_kmh=ms * 3.6,
                                # Stick positions are NOT modelled. The viewer does
                                # not draw them, and inventing them here would put
                                # made-up numbers next to measured ones.
                                throttle=0.0, yaw=0.0, pitch=0.0, roll=0.0))
    return out


def tangent_frames(points, up_fn):
    """Forward from the path itself; caller decides which way is up."""
    out = []
    last = len(points) - 1
    for i, p in enumerate(points):
        j0, j1 = max(0, i - 1), min(last, i + 1)
        f = norm(tuple(points[j1][k] - points[j0][k] for k in range(3)))
        out.append((p, f, up_fn(i / last, f)))
    return out


# ------------------------------------------------------------------ manoeuvres

def orbit(radius=5.0, secs=8.0, height=2.0, speed=5.0):
    """Nose pinned to a point while the path bends around it."""
    frames = []
    n = int(secs / DT)
    bank = math.atan2(speed * speed, radius * 9.81)
    for i in range(n + 1):
        a = (speed / radius) * i * DT
        p = (radius * math.sin(a), height, radius * math.cos(a))
        inward = norm((-p[0], 0.0, -p[2]))
        frames.append((p, inward, rot(UP, inward, -bank)))
    return frames


def figure_eight(radius=4.0, height=2.0, speed=5.0):
    """Two opposed circles joined at the crossing: the roll reverses through zero."""
    n = int((2 * math.pi * radius * 2 / speed) / DT)
    pts, sign = [], []
    for i in range(n + 1):
        a = (speed / radius) * i * DT
        if a <= math.pi * 2:
            pts.append((radius - radius * math.cos(a), height, radius * math.sin(a)))
            sign.append(1)
        else:
            b = a - math.pi * 2
            pts.append((-radius + radius * math.cos(b), height, radius * math.sin(b)))
            sign.append(-1)
    bank = math.atan2(speed * speed, radius * 9.81)
    out = []
    last = len(pts) - 1
    for i, p in enumerate(pts):
        j0, j1 = max(0, i - 1), min(last, i + 1)
        f = norm(tuple(pts[j1][k] - pts[j0][k] for k in range(3)))
        out.append((p, f, rot(UP, f, bank * sign[i])))
    return out


def axial_roll(secs=4.0, height=3.0, speed=10.0):
    """360 degrees about the nose axis, in a straight line."""
    frames = []
    n = int(secs / DT)
    hold0, hold1 = 0.25, 0.75
    for i in range(n + 1):
        u = i / n
        p = (0.0, height, speed * i * DT)
        if u < hold0:
            ang = 0.0
        elif u > hold1:
            ang = 2 * math.pi
        else:
            ang = 2 * math.pi * (u - hold0) / (hold1 - hold0)
        frames.append((p, FWD, rot(UP, FWD, ang)))
    return frames


def loop_frames(radius, turns, start_angle, centre, drift=(0.0, 0.0, 0.0),
                secs=3.0, plane_fwd=FWD):
    """A circular arc in the vertical plane holding plane_fwd.

    Thrust points at the CENTRE of the loop the whole way round - that is what
    makes a loop a loop, and it is why the throttle goes up over the top.

    `turns` carries the direction. Positive sweeps the radial from UP toward
    plane_fwd (start at the top and pull DOWN through: a split-S). Negative
    sweeps it the other way (start at the bottom and pull BACK over: a flip or a
    power loop). The tangent is d(radial)/d(theta), so it flips sign with it -
    getting that wrong is what made the first backflip start inverted and the
    first split-S come out flying the way it went in."""
    frames = []
    n = int(secs / DT)
    right = cross(UP, plane_fwd)
    sense = 1.0 if turns >= 0 else -1.0
    for i in range(n + 1):
        th = start_angle + turns * 2 * math.pi * (i / n)
        radial = tuple(UP[k] * math.cos(th) + plane_fwd[k] * math.sin(th)
                       for k in range(3))
        p = tuple(centre[k] + radius * radial[k] + drift[k] * (i / n)
                  for k in range(3))
        f = norm(tuple(sense * c for c in cross(right, radial)))
        frames.append((p, f, tuple(-c for c in radial)))
    return frames


def backflip(radius=2.0, secs=2.6, height=5.0):
    """A full loop pulled backwards. Level in, level out, inverted halfway."""
    return loop_frames(radius, -1.0, math.pi, (0.0, height, 0.0),
                       drift=(0.0, -1.0, 3.0), secs=secs)


def split_s(radius=4.0, height=12.0, roll_secs=1.2, loop_secs=2.6, speed=9.0):
    """Half roll to inverted, then pull through. Reverses direction, costs height."""
    frames = []
    n = int(roll_secs / DT)
    for i in range(n + 1):
        p = (0.0, height, -speed * roll_secs + speed * i * DT)
        frames.append((p, FWD, rot(UP, FWD, math.pi * (i / n))))
    frames += loop_frames(radius, 0.5, 0.0, (0.0, height - radius, 0.0),
                          secs=loop_secs)[1:]
    return frames


def immelmann(radius=4.0, height=3.0, roll_secs=1.2, loop_secs=2.6, speed=9.0):
    """Half loop up, then half roll upright. Reverses direction, buys height."""
    frames = loop_frames(radius, -0.5, math.pi, (0.0, height + radius, 0.0),
                         secs=loop_secs)
    top = frames[-1][0]
    back = (0.0, 0.0, -1.0)
    n = int(roll_secs / DT)
    for i in range(1, n + 1):
        p = (top[0], top[1], top[2] - speed * i * DT)
        frames.append((p, back, rot((0.0, -1.0, 0.0), back, math.pi * (i / n))))
    return frames


def power_loop(radius=3.5, secs=3.4, base=1.5, approach=2.0, speed=11.0):
    """Up the near face of an obstacle, inverted over the top, down the far side."""
    frames = []
    n = int(approach / DT)
    for i in range(n):
        frames.append(((0.0, base, -speed * approach + speed * i * DT), FWD, UP))
    frames += loop_frames(radius, -1.0, math.pi, (0.0, base + radius, 0.0),
                          drift=(0.0, 0.0, 7.0), secs=secs)
    tail = frames[-1][0]
    for i in range(1, int(1.5 / DT)):
        frames.append(((0.0, tail[1], tail[2] + speed * i * DT), FWD, UP))
    return frames


def dive(secs=3.2, top=18.0, speed=8.0):
    """Nose over, accelerate down a face, pull out level."""
    pts = []
    n = int(secs / DT)
    for i in range(n + 1):
        u = i / n
        drop = top * (u * u * (3 - 2 * u))
        pts.append((0.0, top - drop, speed * secs * u * 0.55))
    return tangent_frames(pts, lambda u, f: UP)


MANOEUVRES = [
    # slug, projection for the flat figure, title, builder, note
    ("orbit", "top", "Orbit", orbit,
     "Nose pinned to one point while the path bends around it. Roll holds the bank, "
     "yaw keeps the nose on the object, throttle holds the height. Nothing here is new "
     "to you - it is the racing corner with the nose turned inward instead of forward."),
    ("figure-eight", "top", "Figure eight", figure_eight,
     "Two opposed circles joined at the crossing, flown nose-forward. The roll has to "
     "reverse through zero at the join without the height moving. This is the drill "
     "that finds a lazy throttle hand."),
    ("axial-roll", "side", "Axial roll", axial_roll,
     "360 degrees about the nose axis in a straight line. The path does not bend - if "
     "it does, you are steering with the roll instead of rolling around the line. "
     "Throttle comes off as the horizon goes over and back on as it comes round."),
    ("backflip", "side", "Backflip", backflip,
     "A full loop pulled backwards. Thrust points at the centre of the loop the whole "
     "way round, which is why the throttle goes UP over the top rather than off. Level "
     "in, level out, inverted halfway."),
    ("split-s", "side", "Split-S", split_s,
     "Half roll to inverted, then pull through. Reverses your direction and costs you "
     "height - about twice the loop radius. The way to turn round in a space too tight "
     "to bank in."),
    ("immelmann", "side", "Immelmann", immelmann,
     "The split-S backwards: half loop up, then half roll upright. Reverses direction "
     "and buys height. Pair it with the split-S and you can reverse either way without "
     "ever flying a flat turn."),
    ("power-loop", "side", "Power loop", power_loop,
     "Up the near face of an obstacle, inverted over the top, down the far side. The "
     "loop is just a loop; what makes it a power loop is that the object is inside it."),
    ("dive", "side", "Dive and pull-out", dive,
     "Nose over, let it accelerate down a face, pull out level. Pitch sets how steep, "
     "throttle sets how fast you arrive - the manoeuvre where 'throttle is height, "
     "pitch is speed' either has landed or has not."),
]


# ---------------------------------------------------------------- the figure
# Drawn with report.py's OWN primitives - ramp, poly, panel, txt, doc, Proj,
# speed_path, legend_speed - so a manoeuvre figure and a lap figure are the same
# picture in the same colours. The only thing chosen here is the PROJECTION: a
# loop seen from above is a straight line, so the vertical manoeuvres are drawn
# side-on and the flat ones from the top.

PROJECTIONS = {
    "top":  ("x", "z", "looking down"),
    "side": ("z", "y", "looking from the side"),
}


def _proj_dicts(samples, plane):
    """report.Proj eats dicts keyed x/z. Feed it whichever world axes we want."""
    a, b, _ = PROJECTIONS[plane]
    ix = {"x": 0, "y": 1, "z": 2}
    return [{"x": s.pos[ix[a]], "z": s.pos[ix[b]], "spd": s.speed_kmh} for s in samples]


def _proj_vec(v, plane):
    a, b, _ = PROJECTIONS[plane]
    ix = {"x": 0, "y": 1, "z": 2}
    return (v[ix[a]], v[ix[b]])


def attitude_tick(px, py, up2, scale=1.0):
    """The airframe seen edge-on: a bar across the body, a spike out of the top.

    This is the whole reason the figure is worth drawing. In a side view of a
    loop the spike rotates through 360 degrees, so 'where is the top of the quad'
    is answerable at a glance, which is exactly the question a pilot who has
    never flown inverted cannot yet answer in the air."""
    m = math.sqrt(up2[0] ** 2 + up2[1] ** 2)
    if m < 1e-6:
        return ""
    ux, uy = up2[0] / m, -up2[1] / m          # screen y grows downward
    ax, ay = -uy, ux                          # the airframe, across the body
    half = 6.5 * scale
    spike = 7.5 * scale
    inverted = uy > 0.15
    col = "var(--crash)" if inverted else "var(--fg)"
    return (R.poly([(px - ax * half, py - ay * half), (px + ax * half, py + ay * half)],
                   col, 2.0)
            + R.poly([(px, py), (px + ux * spike, py + uy * spike)], col, 1.6))


def figure(slug, title, samples, plane, note, out, ticks=13):
    W, H = 760, 360
    d = _proj_dicts(samples, plane)
    pr = R.Proj(d, 0, 44, W, H - 44 - 74)
    vref = max(8.0, sorted(x.speed_kmh for x in samples)[int(len(samples) * 0.9)])

    body = [R.txt(14, 26, title, 15, "ttl"),
            R.txt(W - 14, 26, PROJECTIONS[plane][2], 11, "mut", "end"),
            R.panel(5, 44, W - 10, H - 44 - 74)]

    if plane == "side":
        gy = pr({"x": d[0]["x"], "z": 0.0})[1]
        top = 44 + (H - 44 - 74)
        if 44 < gy < top:
            body.append('<line x1="14" y1="%s" x2="%s" y2="%s" class="axis" '
                        'stroke-dasharray="5 4"/>' % (R.n(gy), R.n(W - 14), R.n(gy)))
            body.append(R.txt(18, gy - 5, "ground", 9.5, "mut"))

    body.append(R.poly([pr(x) for x in d], "var(--grid)", 6.0))
    body.append(R.speed_path(d, pr, vref, 2.4))

    step = max(1, (len(samples) - 1) // (ticks - 1))
    for i in range(0, len(samples), step):
        px, py = pr(d[i])
        up = R.analysis.rotate(samples[i].attitude, (0, 1, 0))
        body.append(attitude_tick(px, py, _proj_vec(up, plane)))

    sx, sy = pr(d[0])
    ex, ey = pr(d[-1])
    body.append('<circle cx="%s" cy="%s" r="4.5" fill="var(--ok)"/>' % (R.n(sx), R.n(sy)))
    body.append(R.txt(sx + 9, sy + 4, "start", 10, "mut"))
    body.append('<circle cx="%s" cy="%s" r="4.5" fill="none" stroke="var(--fg)" '
                'stroke-width="2"/>' % (R.n(ex), R.n(ey)))
    body.append(R.txt(ex + 9, ey + 4, "end", 10, "mut"))

    body.append(R.legend_speed(14, H - 56, vref))
    body.append(R.txt(W - 14, H - 47, "red = inverted", 10, "mut", "end"))
    body.append(R.txt(W - 14, H - 32, "bar = airframe, spike = top of the quad",
                      10, "mut", "end"))
    # Deliberately no note text here: an SVG <text> does not wrap, so a sentence
    # longer than the viewBox is silently clipped at the right edge. The caption
    # belongs to whatever embeds the figure.

    Path(out).write_text(R.doc(W, H, "".join(body), title), encoding="utf-8")


# ------------------------------------------------------------- embeddable bits

FRAGMENT_CSS = """.fpv-man{background:#0e1116;color:#c9d1d9;border-radius:10px;overflow:hidden;
 font:13px/1.5 ui-sans-serif,system-ui,'Segoe UI',Roboto,sans-serif;margin:18px 0}
.fpv-man .fpv-head{padding:12px 14px 0}
.fpv-man .fpv-head b{color:#e6edf3;font-size:15px}
.fpv-man .fpv-head p{margin:6px 0 0;color:#8b949e;max-width:70ch}
.fpv-man .fpv-stage{position:relative;height:340px}
.fpv-man canvas{display:block;width:100%;height:100%;cursor:grab}
.fpv-man canvas.drag{cursor:grabbing}
.fpv-man .fpv-hint{position:absolute;top:10px;left:14px;color:#8b949e;
 pointer-events:none;text-shadow:0 1px 3px #000}
.fpv-man .fpv-bar{display:flex;gap:12px;align-items:center;padding:0 14px 12px}
.fpv-man .fpv-bar input[type=range]{flex:1;accent-color:#4dd0c7}
.fpv-man button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;
 border-radius:6px;padding:5px 12px;font:inherit;cursor:pointer}
.fpv-man button:hover{background:#30363d}
.fpv-man .fpv-t{font-variant-numeric:tabular-nums;min-width:104px;color:#8b949e}"""

FRAGMENT = """<section class="fpv-man" id="fpv-__SLUG__" data-manoeuvre="__SLUG__">
  <div class="fpv-head"><b>__TITLE__</b><p>__NOTE__</p></div>
  <div class="fpv-stage">
    <canvas data-fpv=canvas></canvas>
    <div class="fpv-hint">drag to orbit &middot; wheel to zoom<br>
      <span data-fpv=readout></span></div>
  </div>
  <div class="fpv-bar">
    <button data-fpv=play>Play</button>
    <input data-fpv=scrub type=range min=0 max=0 step=1 value=0>
    <span class="fpv-t" data-fpv=time></span>
  </div>
  <script type="application/json" data-fpv-data>__DATA__</script>__BOOT__
</section>"""

BOOT = """(function(){
  /* Look the host up by id rather than via document.currentScript.
     currentScript is null whenever a script is re-executed after insertion
     rather than run by the parser, which is what happens when a host re-injects
     the page body - and the symptom is a viewer that draws nothing and controls
     that do not respond. An id costs nothing and cannot go wrong. */
  var ID = "fpv-__SLUG__";
  function start(){
    var host = document.getElementById(ID);
    if (!host) return;
    var raw = host.querySelector("[data-fpv-data]");
    if (!raw || host.dataset.fpvReady) return;
    host.dataset.fpvReady = "1";
    /* The SECTION is the root, not the stage. fpvViewer looks up every control
       - play, scrub, time - with root.querySelector, and the buttons live in
       .fpv-bar, a sibling of .fpv-stage. Handing it the stage binds the canvas
       and the readout and silently leaves the transport dead. */
    window.fpvViewer(host, JSON.parse(raw.textContent));
  }
  function go(){
    if (window.fpvViewer) return start();
    (window.__fpvWaiting = window.__fpvWaiting || []).push(start);
    if (window.__fpvLoading) return;
    window.__fpvLoading = true;
    var s = document.createElement("script");
    s.src = window.__fpvViewerSrc || "viewer.js";
    s.onload = function(){
      (window.__fpvWaiting || []).splice(0).forEach(function(f){ f(); });
    };
    document.head.appendChild(s);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", go);
  } else {
    go();
  }
})();"""


def fragment(slug, title, note, data, boot=True):
    """`boot=False` emits the markup and the data with no script at all.

    A page holding several fragments is better off initialising them itself in
    one pass than relying on eight separate scripts firing in parse order - the
    data is right there in the `[data-fpv-data]` node either way."""
    body = ("\n  <script>" + BOOT.replace("__SLUG__", slug) + "</script>") if boot else ""
    return (FRAGMENT.replace("__BOOT__", body)
                    .replace("__SLUG__", slug)
                    .replace("__TITLE__", R.esc(title))
                    .replace("__NOTE__", R.esc(note))
                    .replace("__DATA__", json.dumps(data, separators=(",", ":"))))


def build_all(outdir):
    """Every manoeuvre, in four shapes, because they get used in four places.

      <slug>.svg            flat figure - the one that works inside a .md file
      <slug>.fragment.html  embeddable 3D section, needs viewer.js beside it
      <slug>.html           standalone page, self-contained, double-clickable
      <slug>.json           just the data, for anything that renders its own

    viewer.js is written once rather than inlined eight times, so a page holding
    the whole library carries one copy of it."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "viewer.js").write_text(incident_view.VIEWER_JS, encoding="utf-8")
    (outdir / "manoeuvres.css").write_text(FRAGMENT_CSS, encoding="utf-8")

    index = []
    for slug, plane, title, fn, note in MANOEUVRES:
        s = series(fn())
        data = incident_view.build(
            s, 0, len(s), props=[], prop_size=calibration.PROP_NOMINAL,
            radius=calibration.REC_RADIUS_M, scene=None, hits=None,
            show_gates=False, note=note)

        figure(slug, title, s, plane, note, outdir / (slug + ".svg"))
        (outdir / (slug + ".fragment.html")).write_text(
            fragment(slug, title, note, data), encoding="utf-8")
        (outdir / (slug + ".bare.html")).write_text(
            fragment(slug, title, note, data, boot=False), encoding="utf-8")
        (outdir / (slug + ".html")).write_text(
            incident_view.page(data, title + " - manoeuvre", title), encoding="utf-8")
        (outdir / (slug + ".json")).write_text(
            json.dumps(data, separators=(",", ":")), encoding="utf-8")

        inverted = sum(1 for x in s if rotate_up_y(x.attitude) < 0)
        index.append({
            "slug": slug, "title": title, "note": note, "plane": plane,
            "secs": round(s[-1].t, 1), "samples": len(s),
            "speed_max": round(max(x.speed_kmh for x in s), 1),
            "height": [round(min(x.pos[1] for x in s), 1),
                       round(max(x.pos[1] for x in s), 1)],
            "inverted_pct": round(100.0 * inverted / len(s)),
            "files": {k: slug + v for k, v in
                      (("svg", ".svg"), ("fragment", ".fragment.html"),
                       ("bare", ".bare.html"), ("page", ".html"),
                       ("data", ".json"))},
        })
    (outdir / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    (outdir / "README.md").write_text(readme(index), encoding="utf-8")
    return index


def rotate_up_y(q):
    x, y, z, w = q
    return 1 - 2 * (x * x + z * z)


def readme(index):
    rows = "\n".join(
        "| %s | %s | %.1f s | %d%% | %s |"
        % (m["title"], "`" + m["slug"] + "`", m["secs"], m["inverted_pct"],
           "%.0f-%.0f m" % tuple(m["height"]))
        for m in index)
    return """# Manoeuvre library

Pre-rendered freestyle manoeuvres, drawn with the same code the flight reports
use: `common/report.py` primitives for the flat figure, `common/incident_view.py`
for the 3D view. They are TEMPLATES - synthetic, parametric, not flown - so they
can be committed and reused, unlike anything under `reports/` or `replays/`.

Regenerate with `python manoeuvres/build_manoeuvres.py`. Nothing in this
folder is hand-edited - the next build overwrites it, this README included.
**The guidance lives in `docs/manoeuvres.md`;** this file is just the inventory.

| manoeuvre | slug | length | inverted | height |
|---|---|---|---|---|
%s

## Embedding

**In a report** copy the SVG into that report's own `assets/` and reference it
from there, so the report folder stays portable:

    python manoeuvres/build_manoeuvres.py --install <report-dir> split-s
    ![Split-S](assets/split-s.svg)

**In an HTML page** (report.html, a plan) use the fragment, and put one copy of
`viewer.js` and `manoeuvres.css` where the page can reach them:

    <link rel="stylesheet" href="manoeuvres.css">
    <script>window.__fpvViewerSrc = 'manoeuvres/viewer.js';</script>
    ...paste split-s.fragment.html...

Fragments are self-registering: the first one on a page loads `viewer.js`, the
rest wait for it. Any number can sit on one page.

Use `<slug>.bare.html` instead of the fragment when the page would rather
initialise every viewer itself in one pass - it is the same markup and data with
no script of its own.

**On their own** open `<slug>.html`. That one inlines everything.

## What the figure shows

Path coloured by speed, on the same ramp as every lap map in a report. The bar
across the path is the airframe and the spike is the top of the quad; both go
red once the quad is inverted. Loops are drawn side-on because a loop seen from
above is a straight line.

Speed is derived from the path by finite difference, so the colour means what it
means on a real recording. Stick positions are NOT modelled and are left at
zero - a synthetic throttle trace sitting in the same schema as a measured one
is a trap.
""" % rows


def install(report_dir, slugs):
    """Copy manoeuvre figures into a report's own assets/ folder.

    Reports do not live in this repo - when the toolkit is mounted as a skill
    they live in the host project - so a relative href from a report back to
    this library is different for every installation and long enough to get
    wrong. Copying the figure in instead keeps the report folder portable, which
    is what every other figure in it already is. Regenerating a report writes
    into assets/ but never clears it, so the copy survives."""
    out = Path(report_dir) / "assets"
    out.mkdir(parents=True, exist_ok=True)
    done = []
    for slug in slugs:
        src = HERE / (slug + ".svg")
        if not src.exists():
            raise SystemExit("no such manoeuvre: %s" % slug)
        (out / src.name).write_bytes(src.read_bytes())
        done.append("assets/" + src.name)
    return done


if __name__ == "__main__":
    import sys as _sys
    if "--install" in _sys.argv:
        i = _sys.argv.index("--install")
        for href in install(_sys.argv[i + 1], _sys.argv[i + 2:]):
            print(href)
        raise SystemExit(0)
    for m in build_all(HERE):
        print("%-14s %4.1f s  %3d samples  peak %5.1f km/h  height %s  inverted %d%%"
              % (m["slug"], m["secs"], m["samples"], m["speed_max"],
                 m["height"], m["inverted_pct"]))
