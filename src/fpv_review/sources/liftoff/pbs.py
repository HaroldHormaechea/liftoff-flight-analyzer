#!/usr/bin/env python3
"""
liftoff_pbs.py — read Liftoff's own personal-best records, and keep a history.

What Liftoff actually stores
----------------------------
Liftoff does NOT log per-flight telemetry. There is no position, attitude or
stick trace on disk anywhere. What it keeps is a *ratchet* of personal bests:

  <LocalLow>/LuGus Studios/Liftoff/RaceTimes/raceTimes.xml   best + average total
  <LocalLow>/LuGus Studios/Liftoff/LapTimes/lapTimes.xml     five best laps + avg

Both are keyed by track GUID and both are overwritten in place, so a time that
gets beaten is gone. That is why this script snapshots them: run it after every
session and the history file accumulates the progression the game throws away.

Track names come from Player.log, which prints `Name: / Type: / Local ID:`
blocks as it loads content.

Usage
-----
  python liftoff_pbs.py                       # show PBs and diff vs last snapshot
  python liftoff_pbs.py --save                # also append a snapshot to history
  python liftoff_pbs.py --history h.json      # use a specific history file
  python liftoff_pbs.py --root "<LocalLow>/LuGus Studios/Liftoff"
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

DEFAULT_ROOT = Path(os.environ.get("LOCALAPPDATA", "")).parent / "LocalLow" / "LuGus Studios" / "Liftoff"



def track_names(root: Path) -> dict:
    """GUID -> "name (type)", scraped from the Unity player logs.

    Blocks look like:
        Type: Race
        Name: 04 - Flop Shot
        Status: Internal
        Local ID: c470450a-...
    Field order varies, so collect a small window and pull what is there.
    """
    names: dict = {}
    for log in ("Player.log", "Player-prev.log"):
        p = root / log
        if not p.exists():
            continue
        lines = p.read_text(errors="replace").splitlines()
        for i, line in enumerate(lines):
            m = re.match(r"\s*Local ID:\s*([0-9a-fA-F-]{36})\s*$", line)
            if not m:
                continue
            guid = m.group(1)
            name = kind = None
            for j in range(max(0, i - 4), min(len(lines), i + 5)):
                mm = re.match(r"\s*Name:\s*(.+?)\s*$", lines[j])
                if mm and name is None:
                    name = mm.group(1)
                mk = re.match(r"\s*Type:\s*(.+?)\s*$", lines[j])
                if mk and kind is None:
                    kind = mk.group(1)
            if name:
                names.setdefault(guid, f"{name}" + (f" [{kind}]" if kind else ""))
    return names


def parse_times(path: Path, entry_tag: str) -> dict:
    """{guid: {"best": [floats], "average": float}} from one of the XML files."""
    if not path.exists():
        return {}
    out: dict = {}
    root = ET.parse(path).getroot()
    for e in root.iter(entry_tag):
        ident = e.find("./ID/str")
        if ident is None:
            continue
        best = [float(t.text) for t in e.findall("./bestTimes/Time") if t.text]
        avg = e.find("./average")
        out[ident.text] = {"best": best,
                           "average": float(avg.text) if avg is not None and avg.text else None}
    return out


def snapshot(root: Path) -> dict:
    return {
        "taken_at": datetime.now().isoformat(timespec="seconds"),
        "races": parse_times(root / "RaceTimes" / "raceTimes.xml", "raceTime"),
        "laps": parse_times(root / "LapTimes" / "lapTimes.xml", "lapTime"),
    }
