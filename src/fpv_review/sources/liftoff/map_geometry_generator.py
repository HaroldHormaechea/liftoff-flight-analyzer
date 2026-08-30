#!/usr/bin/env python3
"""
map_geometry_generator.py - the one geometry surface a sim must offer.

"The map" around an incident is assembled from three Liftoff sources: tracks.py
(gates, route and blueprint placements), scene.py (the environment's static
colliders) and props.py (each prop's collider shape). This module is the façade
over all three, and it is the module every future sim has to provide: give it a
window of flown points and it answers what is around them, in the shared frame.

It is deliberately not a rename of tracks.py. Naming tracks.py "the map
generator" would name a third of the job and leave the other two thirds
uncovered by the per-sim contract.

props_near() arrives here from liftoff_view.py, which could not keep it: it
reads Liftoff's Track XML, so a copy of it living under common/ would have made
the sim-agnostic layer import a sim. common/incident_view.build() now receives
the props it returns as plain data.
"""

import json
import math
from pathlib import Path

from fpv_review.sources.liftoff import tracks


def props_near(track_dir, track_meta, route, points, radius, shapes=None):
    """Track items within `radius` of the path, classified by what they ARE.

    Three different things live in a track's blueprint list and drawing them
    alike is actively misleading - it was the first thing the pilot questioned
    about this view. Around one crash on Mexican Wave: 79 solid props, 31
    pass-through trigger volumes, and 3 route checkpoints.

      gate     a checkpoint the race routes through - the path, not an obstacle
      trigger  a pit volume (charge battery, repair props) or a spawn point.
               NOT SOLID. You fly through these; drawing them as obstacles
               invents collisions that cannot happen.
      prop     everything else: barriers, ramps, lights, boards. Solid.

    Position and yaw are exact. Shape is not known yet - see the module note."""
    root = tracks.parse_xml(Path(track_dir) / track_meta["file"])
    on_route = set(route or ())
    out = []
    for item in tracks.blueprints(root).values():
        if item["type"] in ("Action", "Spawnpoint"):
            kind = "trigger"
        elif item["id"] in on_route:
            kind = "gate"
        else:
            kind = "prop"
        for _t, q in points:
            if math.dist(item["pos"], q) <= radius:
                shape = (shapes or {}).get(item["item"], {}).get("colliders", [])
                out.append({"p": [round(v, 3) for v in item["pos"]],
                            "yaw": round(item["yaw"], 2),
                            "n": item["item"] or "?",
                            "k": kind,
                            "ap": item["aperture"],
                            # solid parts only: a trigger volume is not an obstacle
                            "sh": [c for c in shape if not c.get("trig")]})
                break
    return out


def geometry_for(replay, track_dir, scenes_dir, props_path):
    """Whatever of the environment is cached -> (track, race, scene, shapes, note).

    Nothing here is fatal. `note` is the honest sentence the recording prints
    about what it could not draw, because a view that quietly omits the wall the
    quad hit is worse than one that says the wall is missing."""
    missing = []
    try:
        track, race, _tid, _rid = tracks.for_replay(track_dir, replay)
    except Exception:
        track = race = None
    if track is None:
        return (None, None, None, {},
                "no track data for this replay - the path, the attitude and the impacts "
                "are drawn, the environment is not")
    env = track.get("environment") or "?"
    scene = None
    sp = Path(scenes_dir) / ("%s.json" % env)
    if sp.exists():
        scene = json.loads(sp.read_text(encoding="utf-8"))
        if scene.get("skipped"):
            missing.append("%s has no %s geometry" % (env, ", ".join(scene["skipped"])))
    else:
        missing.append("the %s scene is not cached (build it with the `scene` "
                       "command)" % env)
    shapes = {}
    pp = Path(props_path)
    if pp.exists():
        shapes = json.loads(pp.read_text(encoding="utf-8"))["items"]
    else:
        missing.append("prop shapes are not cached (build them with the `props` "
                       "command)")
    return track, race, scene, shapes, ("; ".join(missing) if missing else "")
