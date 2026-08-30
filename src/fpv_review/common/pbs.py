#!/usr/bin/env python3
"""
pbs.py - personal bests, the half of PB tracking that is not sim-specific.

A sim's own module knows where its time files live and how to read them; this
module holds what happens to the numbers afterwards - the snapshot history and
the question a report actually asks of it: was this run faster or slower than
usual?

pb_context() arrives here from fpv_report.py, which is where it grew rather than
where it belonged: it reads a snapshot history, not a replay, and nothing in it
is Liftoff-specific. fmt(), diff_line() and the history store arrive from
liftoff_pbs.py for the same reason: formatting a lap time and appending to a
JSON list are not things a sim knows about.
"""

# `float | None` below is a 3.10 spelling; this makes it legal on the 3.9 floor.
from __future__ import annotations

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


def load_history(path):
    """Every snapshot recorded so far, oldest first; [] when there is none yet."""
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else []


def append_snapshot(path, history, snap):
    """Add one snapshot to the history file. Returns the new total."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    history.append(snap)
    p.write_text(json.dumps(history, indent=2))
    return len(history)


def fmt(seconds: float) -> str:
    m, s = divmod(float(seconds), 60)
    return f"{int(m)}:{s:06.3f}"


def diff_line(cur: float | None, prev: float | None) -> str:
    if cur is None or prev is None:
        return "  (new)" if prev is None and cur is not None else ""
    d = cur - prev
    if abs(d) < 1e-6:
        return ""
    return f"  ({d:+.3f}s)"
