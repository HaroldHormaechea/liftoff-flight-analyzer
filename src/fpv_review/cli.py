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
import csv
import json
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from fpv_review.common import analysis
from fpv_review.common import incident_view
from fpv_review.common import kinematics
from fpv_review.common import pbs
from fpv_review.common import report
from fpv_review.common import schema
from fpv_review.common import toolkit
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


# ------------------------------------------------------------------- report

def add_report(sub, sim):
    ap = sub.add_parser("report", prog="%s report" % PROG,
                        description=report.__doc__,
                        formatter_class=argparse.RawDescriptionHelpFormatter,
                        help="the full illustrated review of one replay")
    ap.add_argument("replay", nargs="?", help="replay XML; omit with --latest")
    ap.add_argument("--latest", action="store_true",
                    help="take the newest replay from the Liftoff Recordings folder")
    ap.add_argument("--root", default=str(sim["replay"].DEFAULT_ROOT),
                    help="Recordings folder")
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
    ap.add_argument("--no-auto-open", "--no-open", action="store_true", dest="no_open",
                    help="do not open report.html; pass this when you will open the "
                         "finished report yourself, after the Debrief is written "
                         "(--no-open is the older spelling of the same flag)")
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
                    help="seconds of context either side of a stall recording (default 4)")
    ap.add_argument("--track-dir", default="trackdata",
                    help="track, scene and prop caches for the recordings "
                         "(default trackdata, relative to the working directory)")
    ap.add_argument("--scenes", help="scene cache folder (default: <track-dir>/scenes)")
    ap.add_argument("--props", help="prop shape table (default: <track-dir>/props.json)")
    ap.add_argument("--rec-radius", type=float, default=25.0,
                    help="metres of environment geometry around a recording (default 25)")
    ap.add_argument("--no-rec", action="store_true",
                    help="skip the crash and stall recordings; the tables stay, the "
                         "play controls do not")
    ap.set_defaults(run=cmd_report)


def cmd_report(args, sim):
    cal = sim["calibration"]
    # The props guard, kept explicit. build_recordings() cannot look props up
    # itself - that means reading the sim's track files - so it is handed a
    # callable. When there is no track data, or no cache directory to read it
    # from, that callable returns nothing and the recordings degrade to path,
    # attitude and impacts, exactly as they did when build() made this test
    # internally. Dropping it would crash every report for a replay with no
    # track data, and every replay in the verification set has track data.
    def props_for_window(track, race, shapes):
        if not (track and args.track_dir):
            return lambda _points: []
        route = race["route"] if race else []
        return lambda points: sim["map"].props_near(
            args.track_dir, track, route, points, args.rec_radius, shapes)


    path = Path(args.replay) if args.replay else None
    if args.latest or path is None:
        found = sim["replay"].find_replays(args.root)
        if not found:
            sys.exit("No replays under %s. Save one from the finish or pause screen." % args.root)
        toolkit.refuse_inside_toolkit(args.archive_dir, "archived replays")
        path, _ = sim["replay"].archive(found[0], args.archive_dir)
        print("replay: %s" % path)

    meta, rows = sim["replay"].parse(path)
    rows = kinematics.add_velocity(rows)
    meta["_source"] = str(path)

    outdir = Path(args.out) / (args.name or Path(path).stem)
    toolkit.refuse_inside_toolkit(args.out, "reports")
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / "flight.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(schema.COLUMNS)
        for r in rows:
            w.writerow([round(x, 6) for x in r])

    aargs = analysis.default_args(str(csv_path), cal)
    data = report.load_samples(str(csv_path), aargs)
    dt = analysis.sample_dt(data)

    # lap boundaries come from the replay itself; --laps only overrides them
    if args.laps:
        ranges = analysis.parse_laps(args.laps, len(data))
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
        ranges, names = report.cover_tail(ranges, names, data, dt, args.tail_min,
                                          aargs.stall_speed)

    analysed = analysis.analyse(data, ranges, names, dt, aargs)
    if not analysed:
        sys.exit("no moving samples in %s" % path)
    pb = pbs.pb_context(meta, args.history)

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
    vref = max(1.0, report.pctl([s["spd"] for s in data], 90))
    figs = {"csv": csv_path, "timeline": assets / "timeline.svg",
            "traces": assets / "traces.svg"}

    report.fig_timeline(data, ranges, names, analysed, figs["timeline"], "Lap times",
                        best_lap=pb.get("best_lap"),
                        lap_times=meta.get("lap_times"))
    # There is no per-lap track figure. It drew the same path, in the same speed
    # colours, as the overview map inside that lap's own playback animation, and
    # a report that shows one flight twice teaches the reader to skim.
    if len(ranges) > 1:
        figs["line"] = assets / "line.svg"
        report.fig_line(data, ranges, names, figs["line"], "Laps overlaid")
    # the headline traces and the reference traces are separate figures, so the
    # three that get read every time are not buried under the two that do not
    report.fig_traces(data, ranges, names, analysed, figs["traces"],
               "Speed, sideslip and throttle", ["speed", "sideslip", "throttle"])
    figs["traces_extra"] = assets / "traces_extra.svg"
    report.fig_traces(data, ranges, names, analysed, figs["traces_extra"],
               "Tilt and stick inputs", ["tilt", "sticks"])
    cf = assets / "corners.svg"
    if report.fig_corners(analysed, names, cf, "Corner scorecard"):
        figs["corners"] = cf

    anims = {"laps": []}
    if not args.no_anim:
        for k, (a, b) in enumerate(ranges):
            p = assets / ("anim_%s.svg" % names[k].replace(" ", ""))
            rate = report.fig_anim(data, a, b, p, "%s, played back" % names[k],
                                   meta.get("environment") or "the track", vref,
                                   args.anim_max, args.anim_frames, args.cam_span)
            if rate:
                anims["laps"].append((p, rate))

    # The two moments worth watching again, each recorded from its own row.
    # A stall used to get a flat SVG clip printed under the table; the recording
    # answers the same question in the place the reader asks it, and answers the
    # one the clip could not - what was actually around the quad.
    hits = incident_view.impacts(rows, cal.IMPACT_DROP_KMH,
                                 cal.IMPACT_DEBOUNCE_SAMPLES)
    crashes = report.find_crashes(rows, hits, ranges, names)
    recs = {"geo": [], "props": [], "items": {}}
    if not args.no_rec and (crashes or any(e["stalls"] for e in analysed)):
        scenes = args.scenes or str(Path(args.track_dir) / "scenes")
        props = args.props or str(Path(args.track_dir) / "props.json")
        geo_track, geo_race, geo_scene, geo_shapes, geo_note = (
            sim["map"].geometry_for(path, args.track_dir, scenes, props))
        recs = report.build_recordings(
            rows, hits, crashes, analysed, names, geo_scene, geo_note,
            props_for_window(geo_track, geo_race, geo_shapes), cal.PROP_NOMINAL,
            dt, args.rec_radius, args.stall_pad)
        if geo_note:
            print("  recordings: %s" % geo_note)

    md_path = outdir / "report.md"
    kept = None if args.reset_debrief else report.existing_debrief(md_path)
    report.write(md_path,
                 report.build_report(meta, data, ranges, names, analysed, pb,
                                     figs, anims, rel, kept, crashes,
                                     set(recs["items"])))
    if kept:
        print("  kept the existing Debrief section")
    html_path = outdir / "report.html"
    if not args.no_html:
        report.write(html_path,
                     report.md_to_html(md_path.read_text(encoding="utf-8"),
                                       "%s - %s" % (meta.get("environment") or "?",
                                                    meta.get("gamemode") or "?"),
                                       recs))
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
        "race_name": report.race_name(meta),
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
        "segments": analysed,
        "findings": report.findings(meta, analysed, names, pb, crashes),
        "crashes": crashes,
        "crash_detection": ("speed lost inside one 0.1 s sample, >= %.0f km/h; the "
                            "replay's isCrashed flag is not used, it reads false on "
                            "flights that ended pinned against the ground"
                            % cal.IMPACT_DROP_KMH),
        "recordings": {"in": "report.html, opened from the crash and stall tables",
                       "ids": sorted(recs["items"]),
                       "titles": {i: d.get("title") for i, d in recs["items"].items()}},
        "personal_bests": pb,
        "figures": {k: (rel(v) if isinstance(v, Path)
                        else {str(i): rel(p) for i, p in v.items()})
                    for k, v in figs.items()},
        "animations": {"laps": [rel(p) for p, _ in anims["laps"]]},
        "not_in_report": [
            "per-sample trajectory, attitude and stick positions: flight.csv",
            "tilt and stick traces are collapsed in the report; the numbers are "
            "in segments[].tilt_* and segments[].yaw_only",
            "the corner table is collapsed in the report; full detail in "
            "segments[].corners, and every stall in segments[].stalls",
            "the recordings are in report.html only; the windows they cut are "
            "described by crashes[] and segments[].stalls",
        ],
    }
    with open(outdir / "analysis.json", "w", encoding="utf-8") as fh:
        json.dump(full, fh, indent=2)

    print("report: %s" % md_path)
    print("        %s" % (outdir / "analysis.json"))
    if not args.no_html:
        print("        %s" % html_path)
    print("  %d figures, %d animations, %d segment(s), %d recording(s)"
          % (len(figs) - 1, len(anims["laps"]), len(ranges), len(recs["items"])))

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
    add_report(sub, sim)
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
