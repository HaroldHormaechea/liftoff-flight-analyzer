#!/usr/bin/env python3
"""
schema.py - the artifacts that cross a stage boundary, and how they serialise.

COORDINATE FRAME, stated once for everything in this module: Unity world space,
LEFT-HANDED, +Y up, distances in METRES, times in SECONDS on the session clock.
That is the frame the replay and the track XML already share, so nothing is
re-projected on the way in. A sim whose native frame differs converts in its own
ingestion layer; nothing downstream of here ever asks which sim it came from.

These dataclasses are the contract a sim implements. A sim is pluggable when it
emits them, and the analysis, the report and the incident view are written
against them rather than against any sim's file format.

COLUMNS arrives here from liftoff_replay.py. In its old home it was Liftoff's
record layout; here it is the serialisation of a FlightSample, which is what
makes flight.csv a format a second sim can be asked to produce and this layer
can be asked to read back. Its order is the field order of to_row(), and the two
must not drift.
"""

import csv
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

COLUMNS = ["t", "pos_x", "pos_y", "pos_z", "quat_x", "quat_y", "quat_z", "quat_w",
           "in_throttle", "in_yaw", "in_pitch", "in_roll",
           "vel_x", "vel_y", "vel_z", "speed_ms", "speed_kmh"]


@dataclass
class FlightSample:
    """One instant of flight. Every field carries its unit.

    speed_ms and speed_kmh are STORED, not derived from `velocity` on demand.
    They are computed once where the velocity is (common/kinematics.py) and
    carried, because recomputing a magnitude with a different expression -
    math.hypot rather than sqrt of the sum of squares - can differ in the last
    bits, and this series is compared byte for byte against a previous run.
    """
    t: float                                    # s, session clock
    pos: Tuple[float, float, float]             # x, y, z, metres, +Y up
    attitude: Tuple[float, float, float, float]  # quaternion x, y, z, w
    throttle: float                             # 0..1
    yaw: float                                  # -1..+1, stick deflection
    pitch: float                                # -1..+1, stick deflection
    roll: float                                 # -1..+1, stick deflection
    velocity: Tuple[float, float, float]        # x, y, z, metres per second
    speed_ms: float                             # m/s, magnitude of velocity
    speed_kmh: float                            # km/h, speed_ms * 3.6

    def to_row(self):
        """The 17 values of COLUMNS, in COLUMNS order."""
        return [self.t, self.pos[0], self.pos[1], self.pos[2],
                self.attitude[0], self.attitude[1], self.attitude[2], self.attitude[3],
                self.throttle, self.yaw, self.pitch, self.roll,
                self.velocity[0], self.velocity[1], self.velocity[2],
                self.speed_ms, self.speed_kmh]

    @classmethod
    def from_row(cls, row):
        """Build one sample from 17 values in COLUMNS order."""
        v = [float(x) for x in row]
        return cls(t=v[0], pos=(v[1], v[2], v[3]),
                   attitude=(v[4], v[5], v[6], v[7]),
                   throttle=v[8], yaw=v[9], pitch=v[10], roll=v[11],
                   velocity=(v[12], v[13], v[14]),
                   speed_ms=v[15], speed_kmh=v[16])


@dataclass
class FlightSeries:
    """A whole flight, sampled. The unit of transport between every stage."""
    samples: List[FlightSample] = field(default_factory=list)
    # s, the MEASURED MEDIAN interval, never a first difference: Liftoff's
    # timestamps are irregular (0.003-0.197 s observed) and a first difference
    # once scaled every duration in the report by up to 1.9x.
    #
    # DECLARED BUT NOT POPULATED BY THE LIFTOFF SOURCE, deliberately. Liftoff's
    # interval is measured downstream by common/analysis.sample_dt(), which is
    # the authority and is unchanged by this migration; moving where that number
    # comes from would be a behaviour change, and this restructure is meant to
    # have none. A second sim that knows its own rate should set this, and
    # unifying the two is a follow-up rather than part of the move. There is
    # exactly one implementation of the median - never write a second.
    sample_dt: Optional[float] = None
    source: Optional[str] = None        # the sim this came from, e.g. "liftoff"

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i):
        """Indexing a series yields samples; slicing yields a list of them."""
        return self.samples[i]

    def __iter__(self):
        return iter(self.samples)


@dataclass
class SessionMeta:
    """What the sim recorded about the run itself, rather than about the flight."""
    name: Optional[str] = None
    track_id: Optional[str] = None
    race_id: Optional[str] = None
    environment: Optional[str] = None
    gamemode: Optional[str] = None
    drone: Optional[str] = None          # the craft configuration's name
    created: Optional[str] = None        # the sim's own creation stamp
    total_time: float = 0.0              # s
    game_version: Optional[str] = None
    source_file: Optional[str] = None    # where this was decoded from


@dataclass
class LapSet:
    """Lap boundaries, as the sim reported them - never inferred from geometry."""
    times: List[float] = field(default_factory=list)          # s, per completed lap
    start_indices: List[int] = field(default_factory=list)    # index into samples
    names: List[str] = field(default_factory=list)            # segment labels


# ---------------------------------------------------------------- geometry
# Every field below is traced to a reader that exists today in analysis.py,
# incident_view.py or report.py. Nothing is here because a hypothetical sim
# might have it. The first real second sim will change this contract, and that
# is expected rather than a failure.


@dataclass
class Gate:
    """One scoring checkpoint of a race, in the order it must be flown.

    A gate is a SCORING VOLUME, not a hole: the environment may obstruct any
    part of it, so anything drawing a racing line has to intersect the aperture
    against world geometry first."""
    pos: Tuple[float, float, float]              # metres
    yaw: float                                   # degrees, Euler Y
    aperture: Optional[Tuple[float, float]] = None   # width, height in metres,
                                                     # None when the prefab's
                                                     # opening is baked into it
    order: Optional[int] = None                  # position along the route


@dataclass
class TrackGeometry:
    """Where the track is: the route, and everything placed along it."""
    gates: List[Gate] = field(default_factory=list)
    items: List["PropPlacement"] = field(default_factory=list)
    provenance: Optional[str] = None    # which build/cache these came from


@dataclass
class Collider:
    """One primitive solid, in the frame stated at the top of this module.

    Boxes, spheres and capsules only: they are what the games author collision
    with, so nothing has to be decimated. `trigger` matters - a pit volume or a
    checkpoint is flown THROUGH, and drawing it as an obstacle invents
    collisions that cannot happen."""
    kind: str                                    # "box" | "sph" | "cap"
    pos: Tuple[float, float, float]              # metres
    rot: Tuple[float, float, float, float]       # quaternion x, y, z, w
    half_extents: Optional[Tuple[float, float, float]] = None   # metres, box
    radius: Optional[float] = None               # metres, sphere and capsule
    height: Optional[float] = None               # metres, capsule
    axis: Optional[int] = None                   # 0/1/2, capsule's long axis
    trigger: bool = False                        # not solid; do not draw as one


@dataclass
class PropPlacement:
    """An item the track places, with its shape if the sim can supply one.

    Position and rotation are exact; the shape often is not, because items are
    instantiated from prefabs at runtime and are not in the environment's own
    geometry. A placement with no colliders is drawn as a marker saying
    "something is here", never as a claim about what it looks like."""
    name: str
    kind: str                                    # "gate" | "trigger" | "prop"
    pos: Tuple[float, float, float]              # metres
    yaw: float                                   # degrees
    colliders: List[Collider] = field(default_factory=list)
    aperture: Optional[Tuple[float, float]] = None   # metres, gates only


@dataclass
class WorldGeometry:
    """The static environment: what the craft can actually hit."""
    colliders: List[Collider] = field(default_factory=list)
    bounds: Optional[Tuple[Tuple[float, float, float],
                           Tuple[float, float, float]]] = None   # lo, hi, metres
    provenance: Optional[str] = None
    missing: List[str] = field(default_factory=list)   # what could not be read,
                                                       # named so a degraded view
                                                       # can say what it lacks


@dataclass
class PbSnapshot:
    """Personal bests as they stood at one moment.

    Sims overwrite their own best-time files, so a beaten time is gone unless
    something snapshotted it. This is that record."""
    taken_at: Optional[str] = None               # ISO 8601
    best_race: Optional[float] = None            # s
    best_lap: Optional[float] = None             # s
    all_races: List[float] = field(default_factory=list)   # s
    all_laps: List[float] = field(default_factory=list)    # s


def read_csv(path):
    """A FlightSeries from a flight.csv, or from any CSV carrying these columns.

    This is what makes the CSV a genuine interchange format rather than an
    internal pipe: the standalone `analyse` command reads one, and so does any
    stage that was handed a file instead of a series.

    TOLERANT OF MISSING COLUMNS, because it has to be. A capture from
    a sim's telemetry capture carries no speed columns and may carry no velocity
    either, and analysing one has always been supported. The fallbacks below are
    the ones common/analysis.load() used to apply itself when it read the file
    directly: absent field -> 0.0, absent velocity -> central difference on
    position, speed -> the magnitude of whichever velocity resulted.
    """
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return FlightSeries()

    def f(r, k):
        return float(r[k]) if r.get(k) not in (None, "") else 0.0

    has_vel = "vel_x" in rows[0]
    has_speed = "speed_ms" in rows[0]
    out = []
    for i, r in enumerate(rows):
        if has_vel:
            vel = (f(r, "vel_x"), f(r, "vel_y"), f(r, "vel_z"))
        else:
            a, b = rows[max(0, i - 1)], rows[min(len(rows) - 1, i + 1)]
            dt = f(b, "t") - f(a, "t")
            vel = (((f(b, "pos_x") - f(a, "pos_x")) / dt,
                    (f(b, "pos_y") - f(a, "pos_y")) / dt,
                    (f(b, "pos_z") - f(a, "pos_z")) / dt) if dt > 0 else (0.0, 0.0, 0.0))
        if has_speed:
            speed_ms, speed_kmh = f(r, "speed_ms"), f(r, "speed_kmh")
        else:
            speed_ms = math.sqrt(vel[0] * vel[0] + vel[1] * vel[1] + vel[2] * vel[2])
            speed_kmh = speed_ms * 3.6
        out.append(FlightSample(
            t=f(r, "t"),
            pos=(f(r, "pos_x"), f(r, "pos_y"), f(r, "pos_z")),
            attitude=(f(r, "quat_x"), f(r, "quat_y"), f(r, "quat_z"), f(r, "quat_w")),
            throttle=f(r, "in_throttle"), yaw=f(r, "in_yaw"),
            pitch=f(r, "in_pitch"), roll=f(r, "in_roll"),
            velocity=vel, speed_ms=speed_ms, speed_kmh=speed_kmh))
    return FlightSeries(samples=out)


def write_csv(path, series, digits=6):
    """Serialise a FlightSeries to flight.csv.

    newline="" is REQUIRED, not stylistic: csv.writer already terminates rows
    with \\r\\n, and without it Windows text mode translates that into \\r\\r\\n.
    The file still parses and every number in it is still correct, so the only
    symptom is that it stops being byte-identical to the previous run - which is
    the one property the comparison depends on.

    `digits` keeps the CSV at six decimals. That is a deliberate property of the
    artifact, not of the analysis: it is the readable, diffable interchange copy.
    """
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for s in series:
            w.writerow([round(x, digits) for x in s.to_row()])
