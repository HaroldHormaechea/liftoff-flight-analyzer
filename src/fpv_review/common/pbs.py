#!/usr/bin/env python3
"""
pbs.py - personal bests, the half of PB tracking that is not sim-specific.

A sim's own module knows where its time files live and how to read them; this
module holds what happens to the numbers afterwards - the snapshot history and
the question a report actually asks of it: was this run faster or slower than
usual?

pb_context() arrives here from fpv_report.py, which is where it grew rather than
where it belonged: it reads a snapshot history, not a replay, and nothing in it
is Liftoff-specific.
"""

import json
from pathlib import Path


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
