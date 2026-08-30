#!/usr/bin/env python3
"""
scene.py - extract an environment's collision geometry, and cull it to
an incident.

`tracks.py` says where the gates are. This says where the WORLD is: the
containers, walls, arches, poles and floors the quad can actually hit. Without
it a crash renders as a drone stopping in mid-air for no visible reason.

Colliders are the right source, not the render meshes. They are already the
simplified solid geometry - boxes, capsules and spheres with a position, a
rotation and a size - authored by the game, so nothing has to be decimated. On
LiftoffArena 95% of the collision geometry is those three primitives.

Two commands:

  python "<clone>/src" scene --environment LiftoffArena
      Extract every collider in the environment to world space and cache it as
      scenes/<Environment>.json. Slow (seconds to a minute) and rarely needed:
      only on a first run or after the game patches.

  python "<clone>/src" scene --cull --environment LiftoffArena \
      --flight reports/<stem>/flight.csv --at 6.0 --pad 2.0 --radius 30
      Emit only the colliders near where the quad was between t-pad and t+pad.
      Fast, and the shape a report figure embeds.

WORLD SPACE IS NOT ON DISK
--------------------------
Every Transform is stored local to its parent, so a collider's position has to
be composed up the parent chain with full TRS - translate, rotate AND scale.
Accumulating positions alone gives wrong answers wherever a parent is rotated,
which is most of a race track. This was the single biggest source of error when
the format was first explored: the median LOCAL position of a scene's
transforms is about (0, 0), which makes every environment look identical and
identifies none of them.

Once composed, positions are in the same frame the replay records - Unity world
space, left-handed, +Y up, metres - so geometry and flight path compare with no
transformation at all.

FINDING THE SCENE BUNDLE
------------------------
Bundle filenames are content hashes and change on every patch, and the
environment name is not reliably inside the bundle either - matching on it
resolves about half of them and silently mismatches others. So identification
is geometric: a scene bundle IS the environment whose known gate positions fall
inside its collider cloud. `tracks.py` already has every gate position,
which makes this a cheap and unambiguous test, and the answer is cached.

Streamed scene bundles are told apart from the other 250-odd bundles by their
node table alone - a scene has a `.sharedAssets` node - which is readable
without decompressing anything, and narrows 274 candidates to 21 in about a
second.

WHAT IS NOT EXTRACTED YET
-------------------------
MeshColliders and TerrainColliders are counted and reported but not emitted.
They are 5% of the collider count in the indoor environments and carry the
ground in the outdoor ones, so a scene that reports a non-zero terrain count
will render its obstacles correctly over no floor. Reaching them means decoding
compressed vertex buffers and heightmaps, which is a bigger job than the
primitives and is deliberately deferred rather than half-done.

DEPENDENCY NOTE
---------------
This is the one script in the toolkit that needs a third-party package,
`UnityPy`, and it is needed only when a scene cache is being BUILT. Everything
on the analysis path - decoding replays, measuring flights, writing reports -
remains standard library, and a cached scene is plain JSON that anything can
read. The alternative was hand-rolling generic Unity object parsing plus, later,
mesh and heightmap decoding; that is disproportionate for a step that runs once
per environment per game patch.
"""

import argparse
import json
import math
import os
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

from fpv_review.common import geometry
from fpv_review.common import schema
from fpv_review.common import toolkit
from fpv_review.sources.liftoff import replay
from fpv_review.sources.liftoff import tracks
from fpv_review.sources.liftoff import unityfs

FORMAT = 1
DEFAULT_RADIUS = 30.0
DEFAULT_PAD = 2.0


def need_unitypy():
    try:
        import UnityPy                                    # noqa: F401
    except ImportError:
        sys.exit("building a scene cache needs UnityPy:\n"
                 "    pip install UnityPy\n"
                 "It is only needed to BUILD a cache. Reading one - which is what the\n"
                 "report does - is plain JSON and needs nothing.")
    import UnityPy
    UnityPy.config.FALLBACK_UNITY_VERSION = unity_version()
    return UnityPy


def unity_version(default="2022.3.62f3"):
    """The engine version, from Liftoff's own log.

    These bundles carry no usable version string, so UnityPy has to be told one.
    The log states it, and hard-coding it silently rots across engine upgrades."""
    log = (Path(os.environ.get("LOCALAPPDATA", "")).parent / "LocalLow" /
           "LuGus Studios" / "Liftoff" / "Player.log")
    try:
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if "Initialize engine version" in line:
                return line.split("Initialize engine version:")[1].strip().split()[0]
    except OSError:
        pass
    return default


# ------------------------------------------------------------ scene discovery

def scene_bundles(bundles):
    """Candidate streamed-scene bundles, from the node table alone.

    A streamed scene bundle carries a `.sharedAssets` node; an asset bundle does
    not. Reading the node table needs the blocks-info block only, not the scene
    data, so this sifts 274 bundles in about a second without decompressing any
    of the 20 GB behind them."""
    out = []
    for path in sorted(Path(bundles).glob("*.bundle"), key=lambda p: p.stat().st_size):
        try:
            if any(name.endswith(".sharedAssets") for name in _node_names(path)):
                out.append(path)
        except Exception:
            continue
    return out


def _node_names(path, cap=2_000_000):
    with open(path, "rb") as fh:
        raw = fh.read(cap)
    sig, at = unityfs._cstr(raw, 0)
    if sig != "UnityFS":
        return []
    version, = struct.unpack_from(">I", raw, at)
    at += 4
    _, at = unityfs._cstr(raw, at)
    _, at = unityfs._cstr(raw, at)
    _size, packed, unpacked, flags = struct.unpack_from(">qIII", raw, at)
    at += 20
    if flags & 0x80:
        return []                                    # info at the end; not seen in practice
    if version >= 7:
        at = (at + 15) // 16 * 16
    info = raw[at:at + packed]
    if flags & 0x3F in (2, 3):
        info = unityfs.lz4_block(info, unpacked)
    walk = 16
    count, = struct.unpack_from(">I", info, walk)
    walk += 4 + 10 * count
    count, = struct.unpack_from(">I", info, walk)
    walk += 4
    names = []
    for _ in range(count):
        walk += 20
        name, walk = unityfs._cstr(info, walk)
        names.append(name)
    return names


def gate_cloud(track_dir, environment):
    """Every gate position for an environment, as the fingerprint to match on."""
    index = tracks.load_index(track_dir)
    points = []
    for _guid, track in index["tracks"].items():
        if track["environment"] != environment:
            continue
        race = index["races"].get(track.get("race") or "")
        if not race:
            continue
        root = tracks.parse_xml(Path(track_dir) / track["file"])
        points += [g["pos"] for g in tracks.gates(root, race["route"]) if g]
    return points


# ------------------------------------------------------------ transform maths

def compose(transforms, tid, cache, depth=0):
    """World (position, rotation, scale) for a Transform, up the parent chain."""
    if tid in cache:
        return cache[tid]
    node = transforms.get(tid)
    if node is None or depth > 128:
        return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
    parent = node["parent"]
    if not parent or parent not in transforms:
        result = (node["p"], node["q"], node["s"])
    else:
        pp, pq, ps = compose(transforms, parent, cache, depth + 1)
        scaled = (node["p"][0] * ps[0], node["p"][1] * ps[1], node["p"][2] * ps[2])
        turned = geometry.qrot(pq, scaled)
        result = ((pp[0] + turned[0], pp[1] + turned[1], pp[2] + turned[2]),
                  geometry.qmul(pq, node["q"]),
                  (node["s"][0] * ps[0], node["s"][1] * ps[1], node["s"][2] * ps[2]))
    cache[tid] = result
    return result


# ----------------------------------------------------------------- extraction

def read_scene(path, verbose=True):
    """All primitive colliders in a bundle, in world space.

    Returns (colliders, counts). A collider is a dict small enough to ship
    thousands of into an HTML page:
        box     t=box  p=centre  q=rotation  s=half-extents
        capsule t=cap  p=centre  q=rotation  r=radius  h=height  a=axis(0/1/2)
        sphere  t=sph  p=centre  r=radius
    """
    UnityPy = need_unitypy()
    env = UnityPy.load(str(path))

    transforms, owner_of, colliders_raw = {}, {}, []
    counts = {"box": 0, "capsule": 0, "sphere": 0, "mesh": 0, "terrain": 0}
    for obj in env.objects:
        kind = obj.type.name
        try:
            if kind == "Transform":
                data = obj.read()
                pos, rot, scale = data.m_LocalPosition, data.m_LocalRotation, data.m_LocalScale
                transforms[obj.path_id] = {
                    "p": (pos.x, pos.y, pos.z),
                    "q": (rot.x, rot.y, rot.z, rot.w),
                    "s": (scale.x, scale.y, scale.z),
                    "parent": data.m_Father.path_id if data.m_Father else 0,
                }
                if data.m_GameObject:
                    owner_of[data.m_GameObject.path_id] = obj.path_id
            elif kind == "BoxCollider":
                data = obj.read()
                c, s = data.m_Center, data.m_Size
                colliders_raw.append(("box", data.m_GameObject.path_id,
                                      (c.x, c.y, c.z), (s.x, s.y, s.z), None,
                                      bool(getattr(data, "m_IsTrigger", False))))
                counts["box"] += 1
            elif kind == "SphereCollider":
                data = obj.read()
                c = data.m_Center
                colliders_raw.append(("sph", data.m_GameObject.path_id,
                                      (c.x, c.y, c.z), None, data.m_Radius,
                                      bool(getattr(data, "m_IsTrigger", False))))
                counts["sphere"] += 1
            elif kind == "CapsuleCollider":
                data = obj.read()
                c = data.m_Center
                colliders_raw.append(("cap", data.m_GameObject.path_id, (c.x, c.y, c.z),
                                      (data.m_Radius, data.m_Height, data.m_Direction), None,
                                      bool(getattr(data, "m_IsTrigger", False))))
                counts["capsule"] += 1
            elif kind == "MeshCollider":
                counts["mesh"] += 1
            elif kind == "TerrainCollider":
                counts["terrain"] += 1
        except Exception:
            continue

    cache, out = {}, []
    triggers = 0
    for kind, go_id, centre, size, radius, is_trigger in colliders_raw:
        if is_trigger:
            # A trigger volume is not solid. Keeping them would draw walls that
            # can be flown through, and - worse - would make the free-space test
            # that identifies the environment reject the correct scene.
            triggers += 1
            continue
        tid = owner_of.get(go_id)
        if tid is None:
            continue
        pos, rot, scale = compose(transforms, tid, cache)
        offset = geometry.qrot(rot, (centre[0] * scale[0], centre[1] * scale[1], centre[2] * scale[2]))
        world = [round(pos[i] + offset[i], 3) for i in range(3)]
        if kind == "box":
            half = [round(abs(size[i] * scale[i]) / 2.0, 3) for i in range(3)]
            if max(half) < 0.02:
                continue                              # degenerate; nothing to draw
            out.append({"t": "box", "p": world, "q": [round(v, 4) for v in rot], "s": half})
        elif kind == "sph":
            r = abs(radius) * max(abs(v) for v in scale)
            if r < 0.02:
                continue
            out.append({"t": "sph", "p": world, "r": round(r, 3)})
        else:
            r, h, axis = size
            lateral = [abs(scale[1]), abs(scale[2])] if axis == 0 else \
                      ([abs(scale[0]), abs(scale[2])] if axis == 1 else
                       [abs(scale[0]), abs(scale[1])])
            r = abs(r) * max(lateral)
            h = abs(h) * abs(scale[int(axis)])
            if r < 0.02:
                continue
            out.append({"t": "cap", "p": world, "q": [round(v, 4) for v in rot],
                        "r": round(r, 3), "h": round(h, 3), "a": int(axis)})
    counts["trigger"] = triggers
    if verbose:
        print("    %d transforms, %d primitives kept "
              "(box %d, capsule %d, sphere %d; skipped mesh %d, terrain %d)"
              % (len(transforms), len(out), counts["box"], counts["capsule"],
                 counts["sphere"], counts["mesh"], counts["terrain"]))
    return out, counts


MIN_COLLIDERS = 500
NEAR_GATE_M = 25.0
NEED_FRACTION = 0.7


def cloud_score(colliders, cloud):
    """Fraction of the environment's gates that have scene geometry near them.

    A bounding-box test is not enough: a handful of colliders spread wide has a
    box that contains anything, and several small bundles pass it. Racing gates
    are placed in and around scenery, so the honest question is whether most
    gates have actual geometry near them. An unrelated environment scores near
    zero on this; the right one scores near one."""
    if len(colliders) < MIN_COLLIDERS or not cloud:
        return 0.0
    near = 0
    for point in cloud:
        for c in colliders:
            p = c["p"]
            if (abs(p[0] - point[0]) <= NEAR_GATE_M and abs(p[2] - point[2]) <= NEAR_GATE_M
                    and math.dist(p, point) <= NEAR_GATE_M):
                near += 1
                break
    return near / float(len(cloud))


MAX_PATH_INSIDE = 0.005


def flight_path(replay_path, stride=15):
    """A thinned position track from a replay, for use as the free-space witness.

    The parameter is `replay_path` rather than `replay`, because this module now
    imports the `replay` module and a parameter of that name would hide it for
    the whole function body."""
    _meta, rows = replay.parse(replay_path)
    return [(r[1], r[2], r[3]) for r in rows][::stride]


def build(environment, track_dir, out_dir, witness=None, bundle=None,
          max_mb=None, verbose=True):
    """Find the environment's scene bundle, extract it and cache it.

    Identification needs BOTH signals. Gate proximity alone ranks the wrong
    bundle top for HangarC03, whose answer is known independently; the flight
    witness alone leaves a dozen scenes tied at zero because they are simply
    empty where the quad flew. Together - reject anything the flight passes
    through, then take the highest gate proximity among what survives - they
    pick the right bundle for both environments where the truth is known.

    `--bundle` skips all of it when the answer is already known."""
    game = tracks.find_game()
    if game is None:
        sys.exit("could not find the Liftoff install. Set LIFTOFF_DIR, or check "
                 "the `tracks --check` command.")
    cloud = gate_cloud(track_dir, environment)
    if not cloud:
        sys.exit("no gates known for environment %r - run the `tracks` command "
                 "first, and check the name with `tracks --list`." % environment)
    toolkit.refuse_inside_toolkit(out_dir, "extracted scene geometry")

    bundles = tracks.bundle_dir(game)
    if bundle:
        candidates = [bundles / bundle]
        if not candidates[0].exists():
            sys.exit("no such bundle: %s" % candidates[0])
    else:
        candidates = scene_bundles(bundles)
        if max_mb:
            candidates = [p for p in candidates if p.stat().st_size <= max_mb * 1024 * 1024]

    path = flight_path(witness) if witness else []
    if not bundle and not path:
        sys.exit("identifying a scene bundle needs a flight from that environment as a\n"
                 "free-space witness. Pass --witness <replay.xml>, or --bundle <name> if you\n"
                 "already know which bundle it is.")

    print("%d candidate scene bundles, %d gates, %d witness samples"
          % (len(candidates), len(cloud), len(path)))
    best = None
    for candidate in candidates:
        started = time.time()
        try:
            colliders, counts = read_scene(candidate, verbose=False)
        except MemoryError:
            print("  %-16s out of memory; skipped" % candidate.name[:16])
            continue
        except Exception as exc:
            print("  %-16s unreadable (%s); skipped" % (candidate.name[:16], str(exc)[:40]))
            continue
        if len(colliders) < MIN_COLLIDERS and not bundle:
            continue
        occupied = geometry.path_inside(colliders, path) if path else 0.0
        near = cloud_score(colliders, cloud) if not bundle else 1.0
        verdict = "flown through" if occupied > MAX_PATH_INSIDE else "%3.0f%% gates" % (100 * near)
        print("  %-16s %6d colliders  path-inside %5.2f%%  %s  (%.1f s)"
              % (candidate.name[:16], len(colliders), 100 * occupied, verdict,
                 time.time() - started))
        if occupied > MAX_PATH_INSIDE or near < NEED_FRACTION:
            continue
        if best is None or near > best[0]:
            best = (near, occupied, candidate, colliders, counts)

    if best is None:
        sys.exit("no scene bundle matched %s.\nRaise --max-bundle-mb, or pass --bundle if you "
                 "know which one it is." % environment)

    near, occupied, candidate, colliders, counts = best
    lo, hi = geometry.bounds_of([c["p"] for c in colliders])
    scene = {
        "format": FORMAT,
        "environment": environment,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "source": {
            "bundle": candidate.name,
            "size": candidate.stat().st_size,
            "build_id": tracks.build_id(game),
            "unity_version": unity_version(),
            "identified_by": "bundle given" if bundle else
                             "%.0f%% gates near, %.2f%% of witness path inside"
                             % (100 * near, 100 * occupied),
            "witness": str(witness) if witness else None,
        },
        "counts": counts,
        "skipped": {k: counts[k] for k in ("mesh", "terrain") if counts[k]},
        "bounds": {"min": [round(v, 2) for v in lo], "max": [round(v, 2) for v in hi]},
        "colliders": colliders,
    }
    target = Path(out_dir) / ("%s.json" % environment)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="") as fh:
        json.dump(scene, fh, separators=(",", ":"))
    print("\npicked %s -> %s (%.1f MB, %d colliders)"
          % (candidate.name, target, target.stat().st_size / 1e6, len(colliders)))
    if scene["skipped"]:
        print("NOTE: %s not extracted; this scene renders without them"
              % ", ".join("%d %s" % (v, k) for k, v in scene["skipped"].items()))
    return scene


# ---------------------------------------------------------------- the cull

def load_scene(out_dir, environment):
    path = Path(out_dir) / ("%s.json" % environment)
    if not path.exists():
        sys.exit("no cached scene for %s.\nBuild it: python %s --environment %s"
                 % (environment, Path(__file__).name, environment))
    return json.loads(path.read_text(encoding="utf-8"))


def path_window(flight_csv, at, pad):
    """The quad's positions between at-pad and at+pad, from a decoded flight.

    Reads through common/schema.py rather than opening the CSV with a third
    independent DictReader of its own. There was one here, one in the analysis
    and one in the report, each with its own idea of what a column meant."""
    series = schema.read_csv(flight_csv)
    if not len(series):
        return []
    t0 = series[0].t
    return [(s.t - t0, s.pos) for s in series if at - pad <= s.t - t0 <= at + pad]


# ----------------------------------------------------------------------- main

def build_parser():
    """The CLI for this module, borrowed whole by cli.py.

    The parser lives here rather than in cli.py so that every flag, default
    and help string stays beside the code that reads it; cli.py adopts it
    with argparse's `parents=`, which copies rather than restates."""
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--environment", help="environment name, e.g. LiftoffArena")
    parser.add_argument("--track-dir", default="trackdata",
                        help="where the `tracks` command wrote index.json (default: ./trackdata)")
    parser.add_argument("-o", "--out", default=None,
                        help="scene cache directory (default: <track-dir>/scenes)")
    parser.add_argument("--force", action="store_true", help="rebuild even if cached")
    parser.add_argument("--list", action="store_true", help="cached scenes, and what is missing")
    parser.add_argument("--max-bundle-mb", type=int, default=None,
                        help="skip scene bundles larger than this while searching")
    parser.add_argument("--witness", metavar="REPLAY",
                        help="a replay flown in this environment; its path is the free-space "
                             "test that rejects the wrong scene")
    parser.add_argument("--bundle", metavar="NAME",
                        help="use this scene bundle instead of identifying one")
    parser.add_argument("--cull", action="store_true", help="emit geometry around an incident")
    parser.add_argument("--flight", help="flight.csv to take the path from")
    parser.add_argument("--at", type=float, help="incident time, seconds into the flight")
    parser.add_argument("--pad", type=float, default=DEFAULT_PAD,
                        help="seconds either side of --at (default: %.1f)" % DEFAULT_PAD)
    parser.add_argument("--radius", type=float, default=DEFAULT_RADIUS,
                        help="metres around the path to keep (default: %.0f)" % DEFAULT_RADIUS)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def run(args):

    out_dir = Path(args.out) if args.out else Path(args.track_dir) / "scenes"

    if args.list:
        index = tracks.load_index(args.track_dir)
        wanted = sorted({t["environment"] for t in index["tracks"].values()})
        for environment in wanted:
            path = out_dir / ("%s.json" % environment)
            if path.exists():
                scene = json.loads(path.read_text(encoding="utf-8"))
                skipped = scene.get("skipped") or {}
                print("  %-24s %6d colliders  %5.1f MB  %s"
                      % (environment, len(scene["colliders"]), path.stat().st_size / 1e6,
                         ("no " + "/".join(skipped)) if skipped else "complete"))
            else:
                print("  %-24s not built" % environment)
        return

    if not args.environment:
        parser.error("--environment is required (or use --list)")

    if args.cull:
        if not args.flight or args.at is None:
            parser.error("--cull needs --flight and --at")
        scene = load_scene(out_dir, args.environment)
        points = path_window(args.flight, args.at, args.pad)
        keep = geometry.cull(scene, points, args.radius)
        payload = {
            "environment": args.environment,
            "at": args.at, "pad": args.pad, "radius": args.radius,
            "path": [{"t": round(t, 2), "p": [round(v, 3) for v in q]} for t, q in points],
            "counts": {"kept": len(keep), "of": len(scene["colliders"])},
            "skipped": scene.get("skipped") or {},
            "colliders": keep,
        }
        if args.json:
            json.dump(payload, sys.stdout, separators=(",", ":"))
            print()
        else:
            print("%s at t=%.1f +/- %.1f s, %.0f m radius" %
                  (args.environment, args.at, args.pad, args.radius))
            print("  %d path samples, %d of %d colliders kept"
                  % (len(points), len(keep), len(scene["colliders"])))
            if payload["skipped"]:
                print("  WARNING: this scene has no %s geometry"
                      % ", ".join(payload["skipped"]))
        return

    target = out_dir / ("%s.json" % args.environment)
    if target.exists() and not args.force:
        scene = json.loads(target.read_text(encoding="utf-8"))
        print("already cached: %s, %d colliders (built %s)"
              % (target, len(scene["colliders"]), scene["generated"]))
        return
    build(args.environment, args.track_dir, out_dir, witness=args.witness,
          bundle=args.bundle, max_mb=args.max_bundle_mb)
