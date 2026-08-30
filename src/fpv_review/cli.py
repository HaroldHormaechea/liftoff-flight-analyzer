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

from fpv_review.common import incident_view
from fpv_review.common import kinematics
from fpv_review.sources.liftoff import calibration
from fpv_review.sources.liftoff import map_geometry_generator
from fpv_review.sources.liftoff import replay
from fpv_review.sources.liftoff import scene
from fpv_review.sources.liftoff import tracks

SRC_DIR = Path(__file__).resolve().parent.parent
PROG = 'python "%s"' % SRC_DIR

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


# ------------------------------------------------------------------ dispatch

def build_parser():
    ap = argparse.ArgumentParser(
        prog=PROG, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", default="liftoff", choices=sorted(SIMS),
                    help="which sim's ingestion to use (default: liftoff)")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    add_view(sub)
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "run", None):
        ap.print_help()
        return 2
    return args.run(args, SIMS[args.sim])


if __name__ == "__main__":
    sys.exit(main())
