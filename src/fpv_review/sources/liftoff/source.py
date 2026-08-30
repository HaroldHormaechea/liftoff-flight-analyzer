#!/usr/bin/env python3
"""
source.py - Liftoff's entry point into the shared schema.

This is the seam. Above it, replay.py knows about base64 state blobs, 48-byte
records and Liftoff's XML; below it, nothing does. load_flight() is the one
function every stage calls to get a flight, and its return type is the contract
in common/schema.py rather than anything Liftoff-shaped.

A second sim is added by writing this file for it, not by touching the analysis.
"""

from fpv_review.common import kinematics
from fpv_review.common import schema
from fpv_review.sources.liftoff import replay

SIM_NAME = "liftoff"


def load_flight(path):
    """Decode one archived replay -> (SessionMeta, FlightSeries, LapSet, meta).

    FOUR values, not the three the schema alone would suggest. The fourth is the
    sim's raw metadata dict, and it travels because report.py writes it verbatim
    into analysis.json's `meta` key: that key is a PUBLISHED RECORD, read by a
    later machine, so reshaping it is a change to the output rather than to the
    architecture. SessionMeta is the typed view of the same data and is what a
    second sim should populate; the raw dict is Liftoff's own and downstream
    code other than that one key must not read it.

    The row list that replay.parse() and kinematics.add_velocity() pass between
    them stays exactly as it was - it is Liftoff's own decode buffer, laid out in
    COLUMNS order - and is converted to samples here, once, at the boundary.
    """
    meta, rows = replay.parse(path)
    rows = kinematics.add_velocity(rows)

    series = schema.FlightSeries(
        samples=[schema.FlightSample.from_row(r) for r in rows],
        source=SIM_NAME)

    session = schema.SessionMeta(
        name=meta.get("name"),
        track_id=meta.get("track_id"),
        race_id=meta.get("race_id"),
        environment=meta.get("environment"),
        gamemode=meta.get("gamemode"),
        drone=meta.get("drone"),
        created=meta.get("created"),
        total_time=meta.get("total_time") or 0.0,
        game_version=meta.get("game_version"),
        source_file=str(path))

    laps = schema.LapSet(times=list(meta.get("lap_times") or []),
                         start_indices=list(meta.get("lap_start_indices") or []))

    # The raw metadata dict travels alongside for now: report.py writes it into
    # analysis.json's `meta` key verbatim, and reshaping that output is a change
    # to the published record, not to the architecture. SessionMeta is the typed
    # view of the same thing.
    return session, series, laps, meta
