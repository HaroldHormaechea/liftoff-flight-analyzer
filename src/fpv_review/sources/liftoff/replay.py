#!/usr/bin/env python3
"""
replay.py - decode a saved Liftoff replay into CSV.

Liftoff's in-game "save recording" writes an XML file per attempt. It is not a
video and not an opaque blob: the flight itself is a base64 block of fixed-size
records, and the surrounding XML carries the track, the race, the drone setup
and the lap times.

    <LocalGhostStatesRecording>
      <environment>Rustline</environment>
      <gamemode>Race</gamemode>
      <trackID><str>7aafe2b2-...</str></trackID>
      <lapTimes />  <lapStartIndices />
      <droneConfiguration> ... rates, expo, PIDs ... </droneConfiguration>
      <stateLayout>POSITION_STICKS</stateLayout>
      <statesByte>base64...</statesByte>

Record format (stateLayout POSITION_STICKS), reverse-engineered and verified
against a 2026-08-26 capture: 48 bytes, 12 little-endian floats.

    [0:3]   position x, y, z      world metres, y up
    [3:7]   attitude quaternion   x, y, z, w
    [7:11]  sticks                throttle 0..1, then three axes -1..+1
    [11]    timestamp             seconds on the session clock, 10 Hz

Sample rate is 10 Hz, against 100 Hz for the live UDP telemetry feed. That is
enough for trajectory work - line, turn radius, braking points, sideslip - and
too coarse for fine input analysis such as throttle sawing.

Stick order is CONFIRMED, not assumed: one flight was captured as both a replay
and a live UDP telemetry stream on 2026-08-26, and across 1575 moving samples
with exact position matches the yaw/pitch/roll channels agreed to within 0.04
(the 10 Hz vs 100 Hz sampling offset). Throttle is the same signal on a
different scale: telemetry = 2 * replay - 1, i.e. replay 0..1, telemetry -1..+1.

Replays live in:
  <LocalLow>/LuGus Studios/Liftoff/Recordings/<GameMode>/<name>.xml

ARCHIVING IS AUTOMATIC AND HAPPENS FIRST. Liftoff names a replay after its track
and total time, so two abandoned attempts are both "<track> - 00_00_000 - <date>"
and the second save silently destroys the first. This script therefore copies the
replay to a timestamped filename BEFORE decoding it, and then decodes the copy,
so an analysis always refers to a file that still exists. Pass --no-archive only
when re-running against a file already archived.

Usage
-----
  python "<clone>/src" replay --list
  python "<clone>/src" replay "path/to/replay.xml" -o flight.csv
  python "<clone>/src" replay --latest -o flight.csv
"""

import argparse
import base64
import csv
import json
import os
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from fpv_review.common import kinematics
from fpv_review.common import schema

DEFAULT_ROOT = (Path(os.environ.get("LOCALAPPDATA", "")).parent / "LocalLow" /
                "LuGus Studios" / "Liftoff" / "Recordings")

RECORD_BYTES = 48
RECORD_FLOATS = 12


def find_replays(root):
    root = Path(root)
    if not root.exists():
        return []
    return sorted(root.rglob("*.xml"), key=lambda p: p.stat().st_mtime, reverse=True)


def text(node, tag, default=None):
    el = node.find(tag)
    return el.text if el is not None and el.text else default


def safe_name(text):
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in (text or "")]
    out = "".join(keep)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "replay"


def archive(src, archive_dir):
    """Copy a replay to a timestamped filename before anything reads it.

    Liftoff names a replay after its track and TOTAL TIME, so every abandoned
    attempt on a track lands on the same filename and each save destroys the
    last. The stamp comes from the file's own <creationTime> (format
    YYYYMMDD.hhmmss) so re-archiving the same replay is idempotent; if that field
    is missing, the file's mtime is used instead.
    """
    src = Path(src)
    root = ET.parse(str(src)).getroot()
    created = text(root, "creationTime")
    if created and "." in created:
        d, t = created.split(".", 1)
        stamp = "%s-%s" % (d, t)
    else:
        stamp = datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
    laps = len(root.findall("./lapTimes/float"))
    tag = "%dlap" % laps if laps else "nolap"
    name = "%s_%s_%s_%s.xml" % (stamp, safe_name(text(root, "environment")),
                                safe_name(text(root, "gamemode")), tag)
    dest = Path(archive_dir) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == src.stat().st_size:
        return dest, False
    shutil.copy2(str(src), str(dest))
    return dest, True


def parse(path):
    """Return (metadata dict, list of sample rows)."""
    root = ET.parse(str(path)).getroot()
    blob = text(root, "statesByte", "")
    layout = text(root, "stateLayout", "?")
    if layout != "POSITION_STICKS":
        print("warning: stateLayout is %r, not POSITION_STICKS - the record format "
              "may differ and the columns below may be wrong." % layout, file=sys.stderr)
    raw = base64.b64decode(blob) if blob else b""
    if len(raw) % RECORD_BYTES:
        raise SystemExit("state blob is %d bytes, not a multiple of %d - unknown format"
                         % (len(raw), RECORD_BYTES))
    n = len(raw) // RECORD_BYTES

    lap_times = [float(t.text) for t in root.findall("./lapTimes/float") if t.text]
    lap_idx = [int(t.text) for t in root.findall("./lapStartIndices/int") if t.text]
    meta = {
        "name": text(root, "name"),
        "environment": text(root, "environment"),
        "gamemode": text(root, "gamemode"),
        "modifiers": text(root, "gameModifiers"),
        "crashed": text(root, "isCrashed") == "true",
        "created": text(root, "creationTime"),
        "total_time": float(text(root, "totalTime", "0") or 0),
        "lap_times": lap_times,
        "lap_start_indices": lap_idx,
        "track_id": text(root, "./trackID/str"),
        "race_id": text(root, "./raceID/str"),
        "drone": text(root, "./droneConfiguration/name"),
        "samples": n,
        "game_version": text(root, "gameVersion"),
    }

    rows = []
    for i in range(n):
        v = struct.unpack_from("<%df" % RECORD_FLOATS, raw, i * RECORD_BYTES)
        rows.append(list(v[11:12]) + list(v[0:11]))   # t first, then pos/quat/sticks
    return meta, rows


def build_parser():
    """The CLI for this module, borrowed whole by cli.py.

    The parser lives here rather than in cli.py so that every flag, default
    and help string stays beside the code that reads it; cli.py adopts it
    with argparse's `parents=`, which copies rather than restates."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("replay", nargs="?", help="replay xml to decode")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="Recordings folder")
    ap.add_argument("--list", action="store_true", help="list saved replays, newest first")
    ap.add_argument("--latest", action="store_true", help="use the newest replay")
    ap.add_argument("-o", "--out", help="CSV to write")
    ap.add_argument("--json", action="store_true", help="print metadata as JSON")
    ap.add_argument("--archive-dir", default="replays",
                    help="where timestamped copies are kept (default: ./replays)")
    ap.add_argument("--no-archive", action="store_true",
                    help="skip the safety copy; only for a file already archived")
    return ap


def run(args):

    if args.list:
        found = find_replays(args.root)
        if not found:
            sys.exit("No replays under %s. Save one from the finish or pause screen."
                     % args.root)
        for p in found:
            print(p)
        return

    path = Path(args.replay) if args.replay else None
    if args.latest or path is None:
        found = find_replays(args.root)
        if not found:
            sys.exit("No replays under %s." % args.root)
        path = found[0]

    if not args.no_archive:
        archived, copied = archive(path, args.archive_dir)
        print("%s %s" % ("archived ->" if copied else "already archived:", archived))
        path = archived            # decode the copy, never the volatile original

    meta, rows = parse(path)
    rows = kinematics.add_velocity(rows)

    if args.json:
        print(json.dumps(meta, indent=2))
    else:
        print("%s" % meta["name"])
        print("  %s / %s  [%s]%s" % (meta["environment"], meta["gamemode"],
                                     meta["drone"] or "?",
                                     "  CRASHED" if meta["crashed"] else ""))
        print("  %d samples, %.1f s at %.0f Hz" %
              (meta["samples"],
               rows[-1][0] - rows[0][0] if rows else 0,
               (len(rows) - 1) / (rows[-1][0] - rows[0][0]) if len(rows) > 1 else 0))
        if meta["lap_times"]:
            print("  laps: %s" % ", ".join("%.3f" % t for t in meta["lap_times"]))
        else:
            print("  no completed laps recorded (total time %.3f)" % meta["total_time"])
        sp = [r[16] for r in rows]
        alt = [r[2] for r in rows]
        thr = [r[8] for r in rows]
        print("  speed  median %.0f  max %.0f km/h" %
              (sorted(sp)[len(sp) // 2], max(sp)))
        print("  height range %.1f to %.1f m (relative to world origin)" % (min(alt), max(alt)))
        print("  throttle  median %.2f  range %.2f-%.2f" %
              (sorted(thr)[len(thr) // 2], min(thr), max(thr)))

    if args.out:
        with open(args.out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(schema.COLUMNS)
            for r in rows:
                w.writerow([round(x, 6) for x in r])
        print("wrote %s" % args.out)
