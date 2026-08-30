#!/usr/bin/env python3
"""
cli.py - the wiring layer, and the only module allowed to import both trees.

common/ may import common/ and the stdlib. sources/<sim>/ may import common/ and
its own siblings, never another sim. This file imports both, and that is the
whole of the architecture: every place a sim-agnostic stage needs a sim-specific
value - a calibrated threshold, a track's geometry, a decoded flight - the
connection is made here rather than by common/ reaching downward.

The nine modules used to be nine front doors, each with its own argparse and its
own `main()`. They are one now:

    python "<clone>/src" <command> [options]

`build_parser()` / `main()` survive as the house convention; what changed is that
there is one of them instead of nine.
"""

import argparse
import json
import sys
from pathlib import Path

from fpv_review.common import analysis
from fpv_review.common import incident_view
from fpv_review.common import kinematics
from fpv_review.sources.liftoff import calibration
from fpv_review.sources.liftoff import map_geometry_generator
from fpv_review.sources.liftoff import replay
from fpv_review.sources.liftoff import scene
from fpv_review.sources.liftoff import tracks

SRC_DIR = Path(__file__).resolve().parent.parent
PROG = 'python "%s"' % SRC_DIR

DEFAULT_SIM = "liftoff"
SIMS = {"liftoff": {"calibration": calibration,
                    "map": map_geometry_generator,
                    "replay": replay}}


# ------------------------------------------------------------------------ view

def add_view(sub):
    ap = sub.add_parser("view", prog="%s view" % PROG,
                        description=incident_view.__doc__,
                        formatter_class=argparse.RawDescriptionHelpFormatter,
                        help="a 3D page for one incident")
    ap.add_argument("--replay", required=True, help="archived replay xml")
    ap.add_argument("--at", type=float, help="incident time; default is the first impact")
    ap.add_argument("--pad", type=float, default=3.0, help="seconds either side (default 3)")
    ap.add_argument("--radius", type=float, default=25.0, help="metres of geometry (default 25)")
    ap.add_argument("--track-dir", default="trackdata")
    ap.add_argument("--scenes", default=None, help="default: <track-dir>/scenes")
    ap.add_argument("--props", help="prop shape table (default: <track-dir>/props.json)")
    ap.add_argument("--hide-route", action="store_true",
                    help="start with the route checkpoints hidden")
    ap.add_argument("--show-triggers", action="store_true",
                    help="draw pit trigger volumes from the start "
                         "(off by default; they are not solid)")
    ap.add_argument("-o", "--out", default="incident3d.html")
    ap.set_defaults(run=cmd_view)


def cmd_view(args, sim):
    cal = sim["calibration"]
    meta, rows = sim["replay"].parse(args.replay)
    rows = kinematics.add_velocity(rows)
    hits = incident_view.impacts(rows, cal.IMPACT_DROP_KMH, cal.IMPACT_DEBOUNCE_SAMPLES)
    t0 = rows[0][0]
    at = args.at if args.at is not None else (rows[hits[0]][0] - t0 if hits else 0.0)

    span = incident_view.window_indices(rows, at, args.pad)
    if not span:
        sys.exit("no samples in that window; the flight is %.1f s long" % (rows[-1][0] - t0))
    i0, i1 = span

    track, race, _tid, _rid = tracks.for_replay(args.track_dir, args.replay)
    if track is None:
        sys.exit("this replay has no track, so there is no environment to draw")
    scenes = Path(args.scenes) if args.scenes else Path(args.track_dir) / "scenes"
    loaded = scene.load_scene(scenes, track["environment"])
    shapes = {}
    props_path = Path(args.props) if args.props else Path(args.track_dir) / "props.json"
    if props_path.exists():
        shapes = json.loads(props_path.read_text(encoding="utf-8"))["items"]

    points = incident_view.window_points(rows, i0, i1)
    props = sim["map"].props_near(args.track_dir, track, race["route"] if race else [],
                                  points, args.radius, shapes)

    focus = min(hits, key=lambda i: abs(rows[i][0] - t0 - at)) if hits else None
    data = incident_view.build(rows, i0, i1, focus=focus, radius=args.radius,
                               props=props, prop_size=cal.PROP_NOMINAL,
                               scene=loaded, hits=hits,
                               show_gates=not args.hide_route,
                               show_triggers=args.show_triggers)

    heading = "%s &mdash; %s, impact at t=%.1f s" % (track["environment"], track["name"], at)
    Path(args.out).write_text(
        incident_view.page(data, "%s crash %.1fs" % (track["environment"], at), heading),
        encoding="utf-8")
    print("%s  (%d colliders, %d props, %d samples, %d impacts)"
          % (args.out, len(data["colliders"]), len(data["props"]),
             len(data["path"]), len(data["impacts"])))
    if loaded.get("skipped"):
        print("  note: scene has no %s geometry; props are placeholder boxes"
              % ", ".join(loaded["skipped"]))
    print("  impacts in the whole flight at t = %s"
          % ", ".join("%.1f s" % (rows[i][0] - t0) for i in hits))


# --------------------------------------------------------------------- analyse

def add_analyse(sub, sim):
    """The analysis parser, borrowed whole from common/analysis.py.

    `parents=` copies every flag, type, default, group and help string rather
    than restating them here, so the subcommand and the embedded analysis can
    never drift apart. The defaults inside it come from the sim's calibration -
    that is why the parser has to be built with one in hand."""
    ap = sub.add_parser("analyse", prog="%s analyse" % PROG, add_help=False,
                        parents=[analysis.build_parser(sim["calibration"])],
                        description=analysis.__doc__,
                        formatter_class=argparse.RawDescriptionHelpFormatter,
                        help="flight geometry, corners and stalls from a flight csv")
    ap.set_defaults(run=cmd_analyse)


def cmd_analyse(args, sim):
    data = analysis.load(args.csv, args.speed_floor)
    dt = analysis.sample_dt(data)
    if args.laps:
        ranges = analysis.parse_laps(args.laps, len(data))
        names = ["lap %d" % (i + 1) for i in range(len(ranges))]
    else:
        ranges = [(0, len(data))]
        names = ["flight"]
    report = analysis.analyse(data, ranges, names, dt, args)

    if args.json:
        print(json.dumps(report, indent=2))
        return
    for e in report:
        print("%s  %.1fs" % (e["segment"].upper(), e["duration_s"]))
        print("  speed     median %3d  p90 %3d  max %3d km/h" %
              (e["speed_median"], e["speed_p90"], e["speed_max"]))
        print("  tilt      median %3d  p90 %3d deg" % (e["tilt_median"], e["tilt_p90"]))
        print("  sideslip  median %.1f  p90 %.1f deg" %
              (e["sideslip_median"], e["sideslip_p90"]))
        print("  under 10 km/h: %.1fs" % e["slow_seconds"])
        if e["corners"]:
            print("   #   t     entry  min  exit  tilt  slip  radius  thr   d_thr")
            for i, c in enumerate(e["corners"], 1):
                print("  %2d %6.1f %6d %5d %5d %5d %5.1f %7s %5.2f %+6.2f" %
                      (i, c["t"], c["entry_kmh"], c["min_kmh"], c["exit_kmh"],
                       c["tilt_deg"], c["sideslip_deg"],
                       c["radius_m"] if c["radius_m"] is not None else "-",
                       c["throttle_in"], c["throttle_delta"]))
        y = e["yaw_only"]
        if y["yaw_only_pct"] is not None:
            print("  yaw-only  %.1fs of %.1fs commanded yaw (%d%%) at mean %s km/h"
                  % (y["yaw_only_seconds"], y["yaw_seconds"], y["yaw_only_pct"],
                     y["yaw_only_mean_kmh"] if y["yaw_only_mean_kmh"] is not None else "-"))
            print("            " + "   ".join(
                "%s: roll p90 %.2f / yaw p90 %.2f" %
                (b["band"], b["roll_p90"], b["yaw_p90"]) for b in y["bands"]))
        if e["stalls"]:
            print("  stalls")
            print("   #   t     dur  min   turn  retrace   net  verdict      because")
            for i, s in enumerate(e["stalls"], 1):
                f = lambda v, w, d=1: (("%%%d.%df" % (w, d)) % v) if v is not None else "-".rjust(w)
                print("  %2d %6.1f %5.1f %5.1f %s %s %s  %-12s %s%s" %
                      (i, s["t"], s["duration_s"], s["min_kmh"],
                       ("%+6.0f" % s["turn_deg"]) if s["turn_deg"] is not None else "     -",
                       f(s["retrace_m"], 8), f(s["net_m"], 6),
                       s["verdict"], s["why"],
                       "  [OFF LINE by %.1f m]" % s["other_lap"]["dist_m"]
                       if s["off_line"] else ""))
            if not args.laps or len(report) < 2:
                print("   (single segment: no cross-lap evidence, verdicts marked ? "
                      "rest on the reversal test alone)")
        if args.trace and e["stalls"]:
            for i, s in enumerate(e["stalls"], 1):
                a2, b2 = s["index"]
                lo = max(0, a2 - int(round(args.pre_window / dt)))
                hi = min(len(data), b2 + int(round(args.post_window / dt)))
                print()
                print("  --- stall %d at t=%.1f (%s) ---" % (i, s["t"], s["verdict"]))
                print("      t    spd   alt  tilt  slip   thr    yaw   pitch   roll")
                step = max(1, int(round(0.3 / dt)))
                for j in range(lo, hi, step):
                    d = data[j]
                    print("  %7.1f %5.1f %5.1f %5.0f %5s %5.2f %+6.2f %+6.2f %+6.2f" %
                          (d["t"] - data[0]["t"], d["spd"], d["alt"], d["tilt"],
                           "%.0f" % abs(d["slip"]) if d["slip"] is not None else "-",
                           d["thr"], d["yaw"], d["pitch"], d["roll"]))
        print()


# ------------------------------------------------------------------ dispatch

def pick_sim(argv):
    """Resolve --sim before the real parser is built.

    The analyse subcommand's defaults ARE the sim's calibration, so the parser
    cannot be constructed until the sim is known, and argparse gives no way to
    learn it part-way through building one. One throwaway pass over argv is the
    entire cost of making --sim mean what it says."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--sim", default=DEFAULT_SIM, choices=sorted(SIMS))
    known, _rest = pre.parse_known_args(argv)
    return known.sim


def build_parser(sim_name=DEFAULT_SIM):
    sim = SIMS[sim_name]
    ap = argparse.ArgumentParser(
        prog=PROG, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", default=DEFAULT_SIM, choices=sorted(SIMS),
                    help="which sim's ingestion to use (default: %s)" % DEFAULT_SIM)
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    add_view(sub)
    add_analyse(sub, sim)
    return ap


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = build_parser(pick_sim(argv))
    args = ap.parse_args(argv)
    if not getattr(args, "run", None):
        ap.print_help()
        return 2
    return args.run(args, SIMS[args.sim])


if __name__ == "__main__":
    sys.exit(main())
