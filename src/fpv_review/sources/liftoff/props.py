#!/usr/bin/env python3
"""
props.py - collider shapes for the items a track is built from.

A Track XML says a `GenericRamp01` sits at (x, y, z) turned 47 degrees. It does
not say what a GenericRamp01 IS. That shape lives in a prefab, and without it
every prop on every track is an anonymous box - which is exactly what the first
3D crash view looked like, and the first thing the pilot asked to fix.

This scans the game's prefab bundles once and writes `props.json`: for each
`itemID`, its colliders in the prefab's OWN frame. Placing one is then just the
Track XML's position and yaw applied to that shape.

    python "<clone>/src" props                      # build the table
    python "<clone>/src" props --show GenericRamp01 # what one item looks like
    python "<clone>/src" props --check              # is it present and current?

Prefabs are name-keyed, which is the whole reason this is cheap: a GameObject
literally called `ConradCrowdControlBarrier01` is the barrier the Track XML
names. No Addressables catalog parsing needed. They are spread over several
bundles - the eight items around one crash came from three different ones - so
the scan walks non-scene bundles smallest-first and stops when every wanted
name has been found.

LOCAL FRAME, NOT WORLD
----------------------
A prefab's colliders are stored down a Transform chain like anything else, so
they are composed to world and then pushed back into the prefab root's frame.
That is what makes the result reusable: one shape, placed hundreds of times
across 92 tracks, instead of geometry baked per instance.

WHAT IS SKIPPED
---------------
MeshColliders, as in `scene.py`. Most track furniture is boxes and
capsules, but a few shapes - some arches especially - are mesh-only and will
come out empty. An item with no primitive colliders is recorded with an empty
list rather than omitted, so a consumer can tell "known to have no box shape"
from "never looked at".
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from fpv_review.common import geometry
from fpv_review.common import toolkit
from fpv_review.sources.liftoff import scene
from fpv_review.sources.liftoff import tracks

FORMAT = 1
MAX_BUNDLE_MB = 250


def wanted_items(track_dir):
    """Every distinct itemID placed by any shipped track."""
    index = tracks.load_index(track_dir)
    names = set()
    for track in index["tracks"].values():
        root = tracks.parse_xml(Path(track_dir) / track["file"])
        for item in tracks.blueprints(root).values():
            if item["item"]:
                names.add(item["item"])
    return names


def cab_index(bundles):
    """{CAB node name: bundle filename} for the whole content folder.

    A prefab's MeshCollider points at a Mesh that usually lives in a DIFFERENT
    bundle, so resolving it means loading that bundle alongside. Node names come
    out of the blocks-info block, so the whole map is built in under a second
    without decompressing anything."""
    out = {}
    for path in Path(bundles).glob("*.bundle"):
        try:
            for name in scene._node_names(path):
                out[name.lower()] = path.name
        except Exception:
            continue
    return out


MAX_MESH_TRIS = 1200


def _resolve_mesh(collider, env, bundles, cabs, loaded):
    """The Mesh behind a MeshCollider, loading its bundle if it lives elsewhere."""
    ref = getattr(collider, "m_Mesh", None)
    if ref is None:
        return None
    try:
        return ref.read()
    except FileNotFoundError as exc:
        name = str(exc).split()[1].lower()
        bundle = cabs.get(name)
        if bundle is None or bundle in loaded:
            return None
        loaded.add(bundle)
        try:
            env.load_file(str(Path(bundles) / bundle))
            return ref.read()
        except Exception:
            return None
    except Exception:
        return None


def mesh_shape(collider, env, bundles, cabs, loaded):
    """A MeshCollider as real triangles, or a bounding box if that is not possible.

    THE BOUNDING BOX IS NOT GOOD ENOUGH and this is not a theoretical worry. A
    ramp's collision hull is literally two triangles - the game calls the objects
    `TriangleCollider02` and `TraingleCollider01`, typo and all - and the AABB of
    a right triangle is a rectangular slab. Drawn that way a ramp gains two
    vertical walls that do not exist in the game, which is exactly what the pilot
    spotted the first time these were rendered.

    Returns ("mesh", vertices, faces) or ("box", centre, extent), or None."""
    mesh = _resolve_mesh(collider, env, bundles, cabs, loaded)
    if mesh is None:
        return None
    try:
        from UnityPy.helpers.MeshHelper import MeshHandler
        handler = MeshHandler(mesh)
        handler.process()
        verts = handler.m_Vertices
        tris = handler.get_triangles()
        faces = [t for sub in tris for t in sub] if tris and isinstance(tris[0], list) else tris
        if verts and faces and len(faces) <= MAX_MESH_TRIS:
            return ("mesh", verts, faces)
    except Exception:
        pass
    aabb = getattr(mesh, "m_LocalAABB", None)      # last resort, and marked approx
    if aabb is None:
        return None
    return ("box",
            (aabb.m_Center.x, aabb.m_Center.y, aabb.m_Center.z),
            (aabb.m_Extent.x, aabb.m_Extent.y, aabb.m_Extent.z))


def qconj(q):
    return (-q[0], -q[1], -q[2], q[3])


def prefab_colliders(env, want, bundles=None, cabs=None):
    """{name: [collider, ...]} for every wanted prefab root in this bundle.

    Colliders come back in the prefab root's own frame, so placing the prefab is
    the Track XML's translate-and-yaw and nothing else."""
    transforms, owner_of, name_of, raw = {}, {}, {}, []
    loaded, cabs = set(), cabs or {}
    for obj in env.objects:
        kind = obj.type.name
        try:
            if kind == "GameObject":
                name_of[obj.path_id] = obj.read().m_Name
            elif kind == "Transform":
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
            elif kind == "MeshCollider" and bundles:
                data = obj.read()
                shape = mesh_shape(data, env, bundles, cabs, loaded)
                trig = bool(getattr(data, "m_IsTrigger", False))
                if shape and shape[0] == "mesh":
                    raw.append(("mesh", data.m_GameObject.path_id, shape[1], shape[2],
                                None, trig, False))
                elif shape:
                    _k, centre, extent = shape
                    raw.append(("box", data.m_GameObject.path_id, centre,
                                (extent[0] * 2, extent[1] * 2, extent[2] * 2), None,
                                trig, True))
            elif kind in ("BoxCollider", "SphereCollider", "CapsuleCollider"):
                data = obj.read()
                centre = data.m_Center
                trig = bool(getattr(data, "m_IsTrigger", False))
                if kind == "BoxCollider":
                    size = data.m_Size
                    raw.append(("box", data.m_GameObject.path_id,
                                (centre.x, centre.y, centre.z), (size.x, size.y, size.z), None, trig, False))
                elif kind == "SphereCollider":
                    raw.append(("sph", data.m_GameObject.path_id,
                                (centre.x, centre.y, centre.z), None, data.m_Radius, trig, False))
                else:
                    raw.append(("cap", data.m_GameObject.path_id,
                                (centre.x, centre.y, centre.z),
                                (data.m_Radius, data.m_Height, data.m_Direction), None, trig, False))
        except Exception:
            continue

    # A prefab name can appear on SEVERAL GameObjects in a bundle - variants,
    # nested copies, LOD holders - and only one of them actually owns the
    # colliders. Taking the first match silently produced an empty shape for the
    # commonest prop on the track, so every candidate is kept and the one with
    # the most collider descendants wins.
    roots = {}
    for go_id, name in name_of.items():
        if name in want and go_id in owner_of:
            roots.setdefault(name, []).append(owner_of[go_id])
    if not roots:
        return {}

    ancestry, cache = {}, {}

    def chain(tid, depth=0):
        if tid in ancestry:
            return ancestry[tid]
        node = transforms.get(tid)
        if node is None or depth > 128:
            out = ()
        else:
            parent = node["parent"]
            out = (tid,) + (chain(parent, depth + 1) if parent in transforms else ())
        ancestry[tid] = out
        return out

    per_root = {}
    root_ids = {tid: name for name, tids in roots.items() for tid in tids}
    for kind, go_id, centre, size, radius, is_trigger, approx in raw:
        tid = owner_of.get(go_id)
        if tid is None:
            continue
        root_tid = next((a for a in chain(tid) if a in root_ids), None)
        if root_tid is None:
            continue
        owner_root = root_ids[root_tid]
        wp, wq, ws = scene.compose(transforms, tid, cache)
        rp, rq, rs = scene.compose(transforms, root_tid, cache)
        inv = qconj(rq)
        delta = (wp[0] - rp[0], wp[1] - rp[1], wp[2] - rp[2])
        lp = geometry.qrot(inv, delta)
        lp = [lp[i] / (rs[i] if abs(rs[i]) > 1e-6 else 1.0) for i in range(3)]
        lq = geometry.qmul(inv, wq)
        ls = [ws[i] / (rs[i] if abs(rs[i]) > 1e-6 else 1.0) for i in range(3)]

        if kind == "mesh":
            # Bake the mesh straight into the prefab frame: one vertex list, one
            # face list, nothing for a consumer to compose at draw time.
            verts = []
            for v in centre:
                sv = (v[0] * ls[0], v[1] * ls[1], v[2] * ls[2])
                rv = geometry.qrot(lq, sv)
                verts.append([round(lp[i] + rv[i], 3) for i in range(3)])
            per_root.setdefault((owner_root, root_tid), []).append(
                {"t": "mesh", "v": verts, "f": [list(f) for f in size],
                 **({"trig": 1} if is_trigger else {})})
            continue

        offset = geometry.qrot(lq, (centre[0] * ls[0], centre[1] * ls[1], centre[2] * ls[2]))
        p = [round(lp[i] + offset[i], 3) for i in range(3)]
        if kind == "box":
            half = [round(abs(size[i] * ls[i]) / 2.0, 3) for i in range(3)]
            if max(half) < 0.02:
                continue
            per_root.setdefault((owner_root, root_tid), []).append({"t": "box", "p": p,
                                      "q": [round(v, 4) for v in lq], "s": half,
                                      **({"trig": 1} if is_trigger else {}),
                                      **({"approx": 1} if approx else {})})
        elif kind == "sph":
            r = abs(radius) * max(abs(v) for v in ls)
            if r < 0.02:
                continue
            per_root.setdefault((owner_root, root_tid), []).append({"t": "sph", "p": p, "r": round(r, 3),
                                      **({"trig": 1} if is_trigger else {})})
        else:
            r, h, axis = size
            lateral = ([abs(ls[1]), abs(ls[2])] if axis == 0 else
                       [abs(ls[0]), abs(ls[2])] if axis == 1 else [abs(ls[0]), abs(ls[1])])
            r = abs(r) * max(lateral)
            h = abs(h) * abs(ls[int(axis)])
            if r < 0.02:
                continue
            per_root.setdefault((owner_root, root_tid), []).append({"t": "cap", "p": p, "q": [round(v, 4) for v in lq],
                                      "r": round(r, 3), "h": round(h, 3), "a": int(axis),
                                      **({"trig": 1} if is_trigger else {}),
                                      **({"approx": 1} if approx else {})})

    best = {name: [] for name in roots}
    for (name, _root_tid), colliders in per_root.items():
        if len(colliders) > len(best[name]):
            best[name] = colliders
    return best


def build(track_dir, out_path, max_mb=MAX_BUNDLE_MB):
    UnityPy = scene.need_unitypy()
    game = tracks.find_game()
    if game is None:
        sys.exit("could not find the Liftoff install.")
    toolkit.refuse_inside_toolkit(Path(out_path).parent, "extracted prop geometry")

    want = wanted_items(track_dir)
    print("%d distinct items placed across all shipped tracks" % len(want))
    bundles = tracks.bundle_dir(game)
    scenes = {p.name for p in scene.scene_bundles(bundles)}
    candidates = sorted((p for p in bundles.glob("*.bundle")
                         if p.name not in scenes and p.stat().st_size <= max_mb * 1024 * 1024),
                        key=lambda p: p.stat().st_size)
    print("scanning %d non-scene bundles up to %d MB\n" % (len(candidates), max_mb))

    cabs = cab_index(bundles)
    print("  %d CAB nodes mapped for mesh lookups\n" % len(cabs))
    items, started = {}, time.time()
    for path in candidates:
        missing = want - set(items)
        if not missing:
            break
        try:
            env = UnityPy.load(str(path))
            found = prefab_colliders(env, missing, bundles, cabs)
        except Exception:
            continue
        if not found:
            continue
        shaped = sum(1 for v in found.values() if v)
        print("  %-16s %5.0f MB  %3d items (%d with primitive colliders)"
              % (path.name[:16], path.stat().st_size / 1e6, len(found), shaped))
        for name, colliders in found.items():
            items[name] = {"bundle": path.name, "colliders": colliders}
            solid = [c for c in colliders if not c.get("trig")]
            if solid:
                pts = [c["p"] for c in solid if "p" in c]
                pts += [v for c in solid for v in c.get("v", [])]
                lo, hi = geometry.bounds_of(pts) if pts else ([0,0,0],[0,0,0])
                items[name]["bounds"] = {"min": [round(v, 2) for v in lo],
                                         "max": [round(v, 2) for v in hi]}

    table = {
        "format": FORMAT,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "source": {"build_id": tracks.build_id(game), "unity_version": scene.unity_version()},
        "counts": {"wanted": len(want), "found": len(items),
                   "with_shape": sum(1 for v in items.values()
                                     if any(not c.get("trig") for c in v["colliders"]))},
        "items": items,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        json.dump(table, fh, separators=(",", ":"))
    print("\n%.0f s -> %s (%.1f MB)"
          % (time.time() - started, out_path, Path(out_path).stat().st_size / 1e6))
    print("  %d of %d items found, %d with primitive colliders"
          % (table["counts"]["found"], table["counts"]["wanted"], table["counts"]["with_shape"]))
    unshaped = sorted(n for n, v in items.items()
                      if not any(not c.get("trig") for c in v["colliders"]))
    if unshaped:
        print("  mesh-only (no box/capsule/sphere): %d, e.g. %s"
              % (len(unshaped), ", ".join(unshaped[:5])))
    return table


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_parser():
    """The CLI for this module, borrowed whole by cli.py.

    The parser lives here rather than in cli.py so that every flag, default
    and help string stays beside the code that reads it; cli.py adopts it
    with argparse's `parents=`, which copies rather than restates."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--track-dir", default="trackdata")
    ap.add_argument("-o", "--out", default=None, help="default: <track-dir>/props.json")
    ap.add_argument("--force", action="store_true", help="rebuild even if present")
    ap.add_argument("--check", action="store_true", help="present and current? exit 1 if not")
    ap.add_argument("--show", metavar="ITEM", help="print one item's collider shape")
    ap.add_argument("--max-bundle-mb", type=int, default=MAX_BUNDLE_MB)
    return ap


def run(args):
    out = Path(args.out) if args.out else Path(args.track_dir) / "props.json"

    if args.check:
        if not out.exists():
            print("prop shapes NOT READY: no %s" % out)
            sys.exit(1)
        table = load(out)
        game = tracks.find_game()
        now = tracks.build_id(game) if game else None
        stale = now and table["source"].get("build_id") != now
        print("prop shapes %s: %d items, %d with shape%s"
              % ("NOT READY" if stale else "READY", table["counts"]["found"],
                 table["counts"]["with_shape"],
                 "; built from build %s, installed is %s" % (table["source"]["build_id"], now)
                 if stale else ""))
        sys.exit(1 if stale else 0)

    if args.show:
        table = load(out)
        item = table["items"].get(args.show)
        if item is None:
            near = [n for n in table["items"] if args.show.lower() in n.lower()][:10]
            sys.exit("no such item%s" % (("; did you mean:\n  " + "\n  ".join(near)) if near else ""))
        print("%s  (from %s)" % (args.show, item["bundle"]))
        if not item["colliders"]:
            print("  no primitive colliders - mesh-only shape")
            return
        print("  bounds %s .. %s" % (item["bounds"]["min"], item["bounds"]["max"]))
        for c in item["colliders"]:
            tag = "  TRIGGER (not solid)" if c.get("trig") else ""
            if c.get("approx"):
                tag += "  [box approximation]"
            if c["t"] == "mesh":
                print("   mesh %4d triangles, %3d vertices%s" % (len(c["f"]), len(c["v"]), tag))
                continue
            if c["t"] == "box":
                print("   box  %6.2f x %6.2f x %6.2f m  at %s%s"
                      % (2*c["s"][0], 2*c["s"][1], 2*c["s"][2], c["p"], tag))
            elif c["t"] == "sph":
                print("   sph  r=%.2f  at %s%s" % (c["r"], c["p"], tag))
            else:
                print("   cap  r=%.2f h=%.2f axis=%d  at %s%s" % (c["r"], c["h"], c["a"], c["p"], tag))
        return

    if out.exists() and not args.force:
        table = load(out)
        print("already built: %s, %d items (%s)"
              % (out, table["counts"]["found"], table["generated"]))
        return
    build(args.track_dir, out, args.max_bundle_mb)
