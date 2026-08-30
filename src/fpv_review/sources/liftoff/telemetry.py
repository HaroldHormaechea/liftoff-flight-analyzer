#!/usr/bin/env python3
"""
telemetry.py - record Liftoff's live UDP telemetry stream to CSV.

Liftoff streams real flight data over UDP if you ask it to. This is the good
source: true position, attitude, velocity, gyro and - the one that matters most
for coaching - the actual stick inputs, rather than a dot estimated off the
on-screen overlay. Prefer this over screen-scraping whenever the flight was
flown with telemetry enabled.

Enabling it (one-time)
----------------------
Create TelemetryConfiguration.json in the Liftoff data folder:

  Windows  %USERPROFILE%/AppData/LocalLow/LuGus Studios/Liftoff/
  macOS    ~/Library/Application Support/LuGus Studios/Liftoff/
  Linux    ~/.config/unity3d/LuGus Studios/Liftoff/

    {
      "EndPoint": "127.0.0.1:9001",
      "StreamFormat": ["Timestamp", "Position", "Attitude", "Velocity",
                       "Gyro", "Input", "Battery", "MotorRPM"]
    }

Liftoff re-reads that file every time the drone resets, so it can be changed
without restarting the game. Deleting the file turns telemetry off again.

Packet layout
-------------
One UDP datagram per physics frame, fields concatenated in exactly the order
listed in StreamFormat, little-endian:

    Timestamp   1 float    seconds since the flight started
    Position    3 floats   world metres
    Attitude    4 floats   quaternion
    Velocity    3 floats   m/s
    Gyro        3 floats   deg/s (pitch, roll, yaw)
    Input       4 floats   throttle, yaw, pitch, roll
    Battery     2 floats   charge (0-1), then volts -- NOT the order the guide
                           states; verified against a live capture
    Input       range -1..+1 per axis; throttle -1 is stick fully down
    MotorRPM    1 byte N + N floats

The full set is 97 bytes for a 4-motor quad. A different size means the running
config does not match the one being parsed.

Usage
-----
  python "<clone>/src" telemetry                      # record until Ctrl+C
  python "<clone>/src" telemetry -o flight.csv
  python "<clone>/src" telemetry --timeout 120        # stop after 120 s of silence
  python "<clone>/src" telemetry --probe              # show packet size and layout
"""

import argparse
import csv
import json
import os
import socket
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

DEFAULT_CONFIG = (Path(os.environ.get("LOCALAPPDATA", "")).parent / "LocalLow" /
                  "LuGus Studios" / "Liftoff" / "TelemetryConfiguration.json")

# name -> (float count, column names). MotorRPM is variable and handled apart.
FIELDS = {
    "Timestamp": (1, ["t"]),
    "Position":  (3, ["pos_x", "pos_y", "pos_z"]),
    "Attitude":  (4, ["quat_x", "quat_y", "quat_z", "quat_w"]),
    "Velocity":  (3, ["vel_x", "vel_y", "vel_z"]),
    "Gyro":      (3, ["gyro_pitch", "gyro_roll", "gyro_yaw"]),
    "Input":     (4, ["in_throttle", "in_yaw", "in_pitch", "in_roll"]),
    # The Steam guide documents Battery as "voltage, charge percent". It is the
    # other way round, and the charge is a 0-1 fraction: a live capture read
    # 0.9936 then 16.73, and 16.73 V matches the in-game OSD for a full pack.
    "Battery":   (2, ["batt_charge", "batt_volts"]),
}


def read_stream_format(path):
    return list(json.loads(path.read_text()).get("StreamFormat", []))


def expected_size(fmt, motors=4):
    n = sum(FIELDS[f][0] * 4 for f in fmt if f in FIELDS)
    if "MotorRPM" in fmt:
        n += 1 + motors * 4
    return n


def columns(fmt, motors=4):
    cols = []
    for f in fmt:
        if f in FIELDS:
            cols.extend(FIELDS[f][1])
    if "MotorRPM" in fmt:
        cols.extend(["rpm_%d" % i for i in range(motors)])
    return cols


def decode(packet, fmt, little=True):
    """Decode one datagram, or None if it does not match the declared format.

    Never returns a partial guess: a size mismatch means the game is streaming
    something other than what we think, and silently mis-slicing floats would
    poison every downstream number.
    """
    end = "<" if little else ">"
    off, out = 0, []
    for f in fmt:
        if f == "MotorRPM":
            if off + 1 > len(packet):
                return None
            n = packet[off]
            off += 1
            if off + 4 * n > len(packet):
                return None
            out.extend(struct.unpack_from("%s%df" % (end, n), packet, off))
            off += 4 * n
            continue
        count = FIELDS.get(f, (0, []))[0]
        if count == 0:
            continue
        if off + 4 * count > len(packet):
            return None
        out.extend(struct.unpack_from("%s%df" % (end, count), packet, off))
        off += 4 * count
    if off != len(packet):
        return None
    return out


def plausible(values, fmt):
    """Sanity check used to pick byte order automatically.

    Timestamp is a small non-negative number of seconds and battery voltage sits
    in single- to low-double-digit volts. Byte-swapped floats blow both up to
    absurd magnitudes, which separates them reliably.
    """
    d = dict(zip(columns(fmt), values))
    if "t" in d and not (0 <= d["t"] < 86400):
        return False
    if "batt_volts" in d and not (0 <= d["batt_volts"] < 60):
        return False
    return True


def build_parser():
    """The CLI for this module, borrowed whole by cli.py.

    The parser lives here rather than in cli.py so that every flag, default
    and help string stays beside the code that reads it; cli.py adopts it
    with argparse's `parents=`, which copies rather than restates."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", help="CSV to write (default: telemetry_<timestamp>.csv)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="TelemetryConfiguration.json to read StreamFormat from")
    ap.add_argument("--format", help="comma-separated StreamFormat, overrides the config file")
    ap.add_argument("--timeout", type=float, default=0,
                    help="stop after this many seconds with no packets (0 = never)")
    ap.add_argument("--probe", action="store_true", help="report packet size and layout, then quit")
    return ap


def run(args):

    if args.format:
        fmt = [s.strip() for s in args.format.split(",") if s.strip()]
    else:
        cfg = Path(args.config)
        if not cfg.exists():
            sys.exit("No telemetry config at %s. Create it (see the docstring) or pass --format."
                     % cfg)
        fmt = read_stream_format(cfg)
    if not fmt:
        sys.exit("StreamFormat is empty - nothing to record.")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((args.host, args.port))
    except OSError as e:
        sys.exit("Cannot bind %s:%d - %s. Something else is listening, or EndPoint points "
                 "elsewhere." % (args.host, args.port, e))
    sock.settimeout(args.timeout if args.timeout else None)

    print("listening on %s:%d" % (args.host, args.port))
    print("format: %s  (expect %d bytes/frame for a quad)" % (", ".join(fmt), expected_size(fmt)))
    print("fly in Liftoff - telemetry starts on the first drone reset. Ctrl+C to stop.")

    try:
        packet, _ = sock.recvfrom(4096)
    except socket.timeout:
        sys.exit("No packets received. Check the game is running, a flight is active, and "
                 "EndPoint matches --host/--port.")

    little = True
    values = decode(packet, fmt, True)
    if values is None or not plausible(values, fmt):
        alt = decode(packet, fmt, False)
        if alt is not None and plausible(alt, fmt):
            little, values = False, alt
        elif values is None:
            sys.exit("Packet is %d bytes but the declared format expects %d. The running config "
                     "does not match %s - Liftoff reloads it on drone reset, so reset once."
                     % (len(packet), expected_size(fmt), args.config))
    fixed = sum(FIELDS[f][0] for f in fmt if f in FIELDS)
    motors = (len(values) - fixed) if "MotorRPM" in fmt else 0
    cols = columns(fmt, motors)

    if args.probe:
        print("")
        print("packet %d bytes, %s-endian, %d motors" %
              (len(packet), "little" if little else "big", motors))
        for c, v in zip(cols, values):
            print("  %-14s % .4f" % (c, v))
        return

    out = Path(args.out) if args.out else Path(
        "telemetry_%s.csv" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    started = last = time.time()
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerow([round(v, 6) for v in values])
        n = 1
        try:
            while True:
                try:
                    packet, _ = sock.recvfrom(4096)
                except socket.timeout:
                    print("no packets for %gs - stopping" % args.timeout)
                    break
                vals = decode(packet, fmt, little)
                if vals is None:
                    continue
                w.writerow([round(v, 6) for v in vals])
                n += 1
                if time.time() - last > 1.0:
                    last = time.time()
                    sys.stdout.write("\r%d frames, %.0fs" % (n, time.time() - started))
                    sys.stdout.flush()
        except KeyboardInterrupt:
            print("stopped")

    dur = time.time() - started
    print("wrote %s - %d frames over %.0fs (%.0f Hz)" % (out, n, dur, n / max(dur, 1e-6)))
