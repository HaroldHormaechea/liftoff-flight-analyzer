#!/usr/bin/env python3
"""
liftoff_tracks.py - extract Liftoff's track and race geometry from the game.

A saved replay says WHERE the quad went. It does not say where the track was.
Without the gates, "he went wide" is an opinion; with them it is a number - the
lateral offset through a 2.45 m aperture. This script is what turns the second
one on, and it is the first thing to run before any analysis that talks about
the racing line.

Liftoff ships every official track as plain XML inside Unity Addressable
bundles. Nothing is encrypted; the bundle container just has to be unwrapped.
This writes those XMLs out to a directory, plus an `index.json` that joins them
to a replay and records exactly which build they came from.

    trackdata/
      index.json                     the join table + the source fingerprint
      HangarC03Track02_0001.xml      one Track per official track
      HangarC03Race02_0001.xml       its Race: the route through the gates

The XMLs are game assets. They are not committed here and not redistributed;
they are re-extracted from the local install whenever they are missing or the
game has been patched.

Usage
-----
  python liftoff_tracks.py --check         # is the data present and current?
  python liftoff_tracks.py                 # extract if not; no-op if current
  python liftoff_tracks.py --force         # re-extract regardless
  python liftoff_tracks.py --list          # what was extracted
  python liftoff_tracks.py --gates TRACK   # gate geometry for one track
  python liftoff_tracks.py --for-replay X  # which track a replay was flown on

WHY A READINESS CHECK EXISTS
----------------------------
Bundle filenames are content hashes, so they change on every patch, and the
extracted XMLs then describe a track layout the game no longer has. Silently
analysing a flight against stale gates is worse than having no gates at all: it
produces confident, wrong numbers. `--check` compares the recorded bundle
fingerprint and Steam build id against what is installed now and exits non-zero
the moment they disagree, so a caller can rebuild before it reads anything.

WHY THIS PARSES UNITY BUNDLES BY HAND
-------------------------------------
UnityPy does this in ten lines. It is also a heavy dependency with an unstable
API, and it needs FALLBACK_UNITY_VERSION set by hand because these bundles carry
no usable version string of their own. The rest of this toolkit is standard
library and portable as a folder copy, and the one moment this script is needed
- the game just updated and the gates are stale - is the worst possible moment
to discover a dependency is missing. So the UnityFS reader below is the price of
keeping that property. It handles exactly what Liftoff ships: UnityFS v6-8,
LZ4/LZ4HC or uncompressed blocks, SerializedFile v17-22.

FORMAT NOTES
------------
Track XML holds every item's world-space position, rotation (Euler degrees)
and, on the resizable subtypes only, scale in metres. Unity world space is
left-handed with +Y up, which is the same frame a replay records positions in,
so track geometry and a flight path compare directly with no transformation.

TrackBlueprint is polymorphic via xsi:type, and only the resizable subtypes
carry `scale` - which, on unit-sized prefabs, IS the aperture in metres. Parsing
by tag name alone silently drops it.

Race XML holds the route as a linked list of passages: start at
passageType = Start and follow nextPassageIDs to Finish. Every shipped race has
one successor per node, but the field is a list with capacity for 4, so
community tracks may branch.

WHICH ITEMS ARE GATES IS THE RACE'S DECISION, NOT THE TRACK'S. A checkpoint is
any blueprint the route names by instanceID, of any subtype: on Bardwells Yard
all ten are plain inflatable arches, on HangarC03 the route mixes truss gates, a
fixed 5x5 box and three resizable checkpoints. Filtering a track's blueprints by
xsi:type to enumerate "the gates" finds three of the ten. Resolve the route.
The route is a lap, so it ends back on the checkpoint it started from.

A checkpoint is a SCORING VOLUME, NOT A HOLE. The environment can obstruct any
part of it - on HangarC03 gate 31 the checkpoint centre sits half a metre inside
a closed container door. Anything that emits a racing line has to intersect the
aperture against scene colliders first.
"""

import argparse
import json
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import liftoff_replay as LR          # refuse_inside_toolkit, and nothing else

FORMAT = 1                            # bump when index.json's shape changes
STEAM_APPID = "410340"
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
CLASS_TEXTASSET = 49
MAX_BUNDLE_MB = 64                    # the two we want are ~1 MB and ~0.1 MB


# ---------------------------------------------------------------- game lookup

def steam_libraries():
    """Every Steam library folder, from the registry and libraryfolders.vdf.

    Games do not have to live under the Steam install - a second library on a
    different drive is the normal case once one drive fills up - so the install
    path is only the starting point for finding the library list."""
    roots = []
    try:
        import winreg
        for hive, key, name in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    roots.append(Path(winreg.QueryValueEx(handle, name)[0]))
            except OSError:
                pass
    except ImportError:
        pass
    for guess in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam",
                  os.path.expanduser("~/.steam/steam"),
                  os.path.expanduser("~/.local/share/Steam"),
                  os.path.expanduser("~/Library/Application Support/Steam")):
        roots.append(Path(guess))

    libs, seen = [], set()
    for root in roots:
        for lib in [root] + vdf_paths(root / "steamapps" / "libraryfolders.vdf"):
            key = os.path.normcase(str(lib))
            if key in seen:
                continue
            seen.add(key)
            if (lib / "steamapps").is_dir():
                libs.append(lib)
    return libs


def vdf_paths(vdf):
    """The "path" values out of libraryfolders.vdf.

    A regex rather than a VDF parser: this file's only interesting content is a
    flat list of quoted paths, and the parser would be more code than the thing
    it parses."""
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', text)]


def find_game(explicit=None):
    """Locate the Liftoff install. Returns a Path, or None."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("LIFTOFF_DIR"):
        candidates.append(Path(os.environ["LIFTOFF_DIR"]))
    for lib in steam_libraries():
        candidates.append(lib / "steamapps" / "common" / "Liftoff")
    for cand in candidates:
        if (cand / "Liftoff_Data" / "StreamingAssets" / "aa" / "StandaloneWindows64").is_dir():
            return cand
    return None


def bundle_dir(game):
    return game / "Liftoff_Data" / "StreamingAssets" / "aa" / "StandaloneWindows64"


def build_id(game):
    """Steam's build id for the install, from the app manifest beside it.

    This is the cheapest honest answer to "has the game changed since we
    extracted?", and unlike a version string it moves on every patch."""
    acf = game.parent.parent / ("appmanifest_%s.acf" % STEAM_APPID)
    try:
        found = re.search(r'"buildid"\s+"(\d+)"',
                          acf.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return found.group(1) if found else None


# ------------------------------------------------------------ UnityFS reading

def lz4_block(src, out_size):
    """Decompress one LZ4 block - the format Unity uses for bundle blocks.

    LZ4HC compresses differently but decompresses identically, so bundle
    compression flags 2 and 3 both land here."""
    dst = bytearray(out_size)
    src_at = dst_at = 0
    end = len(src)
    while src_at < end:
        token = src[src_at]
        src_at += 1
        literals = token >> 4
        if literals == 15:
            while True:
                more = src[src_at]
                src_at += 1
                literals += more
                if more != 255:
                    break
        dst[dst_at:dst_at + literals] = src[src_at:src_at + literals]
        src_at += literals
        dst_at += literals
        if src_at >= end:
            break                      # the last sequence is literals only
        offset = src[src_at] | (src[src_at + 1] << 8)
        src_at += 2
        match = token & 15
        if match == 15:
            while True:
                more = src[src_at]
                src_at += 1
                match += more
                if more != 255:
                    break
        match += 4
        from_at = dst_at - offset
        if offset >= match:
            dst[dst_at:dst_at + match] = dst[from_at:from_at + match]
            dst_at += match
        else:
            for _ in range(match):     # overlapping run; must copy byte by byte
                dst[dst_at] = dst[from_at]
                dst_at += 1
                from_at += 1
    return bytes(dst)


def _cstr(buf, pos):
    end = buf.index(b"\x00", pos)
    return buf[pos:end].decode("utf-8", "replace"), end + 1


def bundle_payload(path):
    """Decompress a UnityFS bundle; returns (data, [(offset, size, name), ...])."""
    raw = Path(path).read_bytes()
    signature, at = _cstr(raw, 0)
    if signature != "UnityFS":
        raise ValueError("%s is not a UnityFS bundle (signature %r)" % (path, signature))
    version, = struct.unpack_from(">I", raw, at)
    at += 4
    _, at = _cstr(raw, at)             # engine version, always "5.x.x" here
    _, at = _cstr(raw, at)             # engine revision, always "0.0.0" here
    _size, info_packed, info_size, flags = struct.unpack_from(">qIII", raw, at)
    at += 20

    if version >= 7:
        at = (at + 15) // 16 * 16
    if flags & 0x80:                   # blocks info parked at the end of the file
        info_at = len(raw) - info_packed
    else:
        info_at = at
        at += info_packed
    info = raw[info_at:info_at + info_packed]
    if flags & 0x3F in (2, 3):
        info = lz4_block(info, info_size)
    elif flags & 0x3F:
        raise ValueError("%s uses compression %d; only none and LZ4 are handled"
                         % (path, flags & 0x3F))
    if flags & 0x200:                  # blockInfoNeedPaddingAtStart
        at = (at + 15) // 16 * 16

    walk = 16                          # skip the uncompressed-data hash
    count, = struct.unpack_from(">I", info, walk)
    walk += 4
    blocks = [struct.unpack_from(">IIH", info, walk + 10 * i) for i in range(count)]
    walk += 10 * count
    count, = struct.unpack_from(">I", info, walk)
    walk += 4
    nodes = []
    for _ in range(count):
        offset, size, _node_flags = struct.unpack_from(">qqI", info, walk)
        walk += 20
        name, walk = _cstr(info, walk)
        nodes.append((offset, size, name))

    data = bytearray()
    for unpacked, packed, block_flags in blocks:
        chunk = raw[at:at + packed]
        at += packed
        data += lz4_block(chunk, unpacked) if block_flags & 0x3F in (2, 3) else chunk
    return bytes(data), nodes


def text_assets(path):
    """Every TextAsset in a bundle, as {name: bytes}.

    Walks the SerializedFile object table rather than scanning the payload for
    markers, so the names and lengths are the ones Unity recorded rather than
    ones inferred from the bytes around them."""
    data, nodes = bundle_payload(path)
    out = {}
    for offset, size, _name in nodes:
        try:
            out.update(_serialized_text_assets(data[offset:offset + size]))
        except (struct.error, IndexError, ValueError):
            continue                   # not a SerializedFile, or a shape we do not read
    return out


def _serialized_text_assets(blob):
    version, = struct.unpack_from(">I", blob, 8)
    if not 17 <= version <= 22:
        raise ValueError("SerializedFile version %d is outside the handled range" % version)
    at = 16
    endian = "<" if blob[at] == 0 else ">"
    at += 4                            # endianness byte plus 3 reserved
    if version >= 22:
        at += 4                        # metadata size; we index from data_offset instead
        _file_size, data_offset, _unknown = struct.unpack_from(">qqq", blob, at)
        at += 24
    else:
        _meta, _file_size, _version, data_offset = struct.unpack_from(">IIII", blob, 0)
        at = 20
    _unity_version, at = _cstr(blob, at)
    at += 4                            # target platform
    has_type_tree = blob[at]
    at += 1

    count, = struct.unpack_from(endian + "i", blob, at)
    at += 4
    class_ids = []
    for _ in range(count):
        class_id, = struct.unpack_from(endian + "i", blob, at)
        at += 4 + 1 + 2                # class id, stripped flag, script type index
        if class_id == 114:            # MonoBehaviour carries an extra script hash
            at += 16
        at += 16                       # old type hash
        if has_type_tree:
            nodes, strings = struct.unpack_from(endian + "II", blob, at)
            at += 8 + nodes * 32 + strings
            if version >= 21:
                deps, = struct.unpack_from(endian + "i", blob, at)
                at += 4 + 4 * deps
        class_ids.append(class_id)

    count, = struct.unpack_from(endian + "i", blob, at)
    at += 4
    out = {}
    for _ in range(count):
        at = (at + 3) // 4 * 4
        _path_id, byte_start, _byte_size, type_index = struct.unpack_from(
            endian + "qqIi", blob, at)
        at += 24
        if class_ids[type_index] != CLASS_TEXTASSET:
            continue
        base = data_offset + byte_start
        walk = base
        size, = struct.unpack_from(endian + "i", blob, walk)
        walk += 4
        name = blob[walk:walk + size].decode("utf-8", "replace")
        walk = base + ((walk + size - base) + 3) // 4 * 4   # strings are 4-byte aligned
        size, = struct.unpack_from(endian + "i", blob, walk)
        walk += 4
        out[name] = blob[walk:walk + size]
    return out


# ---------------------------------------------------- finding the two bundles

def normalise_xml(blob):
    """Decode a Track/Race asset and make its prolog tell the truth.

    Three shipped assets declare utf-16 in the prolog and then hold UTF-8 bytes,
    which a strict parser refuses. Rewriting the declaration on the way out means
    every consumer downstream can just call ET.parse()."""
    if blob[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = blob.decode("utf-16")
    else:
        text = blob.decode("utf-8-sig")
    return re.sub(r"encoding=[\"'][^\"']+[\"']", 'encoding="utf-8"', text, count=1)


def _root_tag(blob):
    head = blob[:400].decode("utf-8", "replace").lstrip("\ufeff")
    found = re.search(r"<(Track|Race)[\s>]", head)
    return found.group(1) if found else None


def locate(bundles, max_mb=MAX_BUNDLE_MB, verbose=True):
    """Find the Track and Race bundles by their contents.

    Bundle filenames are content hashes and change on every patch, so they can
    never be hard-coded. Smallest first, because both are around a megabyte in a
    20 GB directory and that ordering finds them in a couple of seconds."""
    files = sorted((p for p in Path(bundles).glob("*.bundle")
                    if p.stat().st_size <= max_mb * 1024 * 1024),
                   key=lambda p: p.stat().st_size)
    found = {}
    for i, path in enumerate(files):
        try:
            assets = text_assets(path)
        except Exception:
            continue
        for blob in assets.values():
            kind = _root_tag(blob)
            if kind:
                found.setdefault(kind.lower(), (path, assets))
            break                      # one asset is enough to classify a bundle
        if "track" in found and "race" in found:
            if verbose:
                print("  found both in the %d smallest of %d bundles" % (i + 1, len(files)))
            break
    return found


# ----------------------------------------------------------------- track data

def parse_xml(path):
    return ET.fromstring(normalise_xml(Path(path).read_bytes()).encode("utf-8"))


def _text(node, path, default=None):
    found = node.find(path)
    return found.text if found is not None and found.text else default


def blueprints(track_root):
    """Every item on the track, keyed by instanceID.

    instanceID is what a Race refers to when it names a checkpoint, so this is
    the table the route is resolved through.

    yaw is the Euler Y rotation in degrees. For an item at yaw r the normal -
    the direction of travel through it - is (sin r, 0, cos r), and the width
    axis is (cos r, 0, -sin r).

    `aperture` is [width, height] in metres, and is None for most items. Only
    the resizable subtypes carry `scale`, and because those prefabs are
    unit-sized their scale IS the aperture; components can be negative to mirror
    an item, so it is taken as absolute. Everything else is a fixed prefab whose
    opening is baked into the model - `CheckpointBox5mX5m01` says so in its
    name, `InflatableArchBrandless01` does not - and the only way to size one is
    to measure its collider in the scene bundle."""
    axis = lambda node, name: float(_text(node, name, "0"))
    out = {}
    listed = track_root.find("blueprints")
    for item in listed if listed is not None else []:
        pos, rot, scale = item.find("position"), item.find("rotation"), item.find("scale")
        instance = int(_text(item, "instanceID", "0"))
        out[instance] = {
            "id": instance,
            "type": (item.get(XSI_TYPE) or "").replace("TrackBlueprint", "") or "?",
            "item": _text(item, "itemID"),
            "pos": [axis(pos, "x"), axis(pos, "y"), axis(pos, "z")],
            "yaw": axis(rot, "y"),
            "aperture": ([abs(axis(scale, "x")), abs(axis(scale, "y"))]
                         if scale is not None else None),
        }
    return out


def gates(track_root, order):
    """The checkpoints of one race, resolved to geometry, in the order flown.

    A checkpoint is NOT necessarily a resizable one. On Bardwells Yard every
    checkpoint in the route is a plain inflatable arch; on HangarC03 the route
    mixes truss gates, a fixed 5x5 box and three resizable ones. Filtering the
    blueprints by xsi:type to find "the gates" therefore misses most of them -
    the race route is the only thing that says which items score.

    An id the track does not define comes back as None, so a caller sees the
    hole rather than a silently shorter route."""
    table = blueprints(track_root)
    return [table.get(cid) for cid in order]


def route(race_root):
    """Checkpoint IDs in the order they must be flown, Start to Finish.

    Follows nextPassageIDs. Every shipped race is a linked list, but the field is
    a list with room for four, so a branching community track stops the walk
    instead of having a successor picked for it arbitrarily."""
    passages, start = {}, None
    listed = race_root.find("checkPointPassages")
    for passage in listed if listed is not None else []:
        uid = _text(passage, "uniqueId")
        passages[uid] = passage
        if _text(passage, "passageType") == "Start":
            start = uid
    order, seen, uid = [], set(), start
    while uid and uid in passages and uid not in seen:
        seen.add(uid)
        passage = passages[uid]
        order.append(int(_text(passage, "checkPointID", "0")))
        following = [s.text for s in passage.findall("./nextPassageIDs/string") if s.text]
        uid = following[0] if len(following) == 1 else None
    return order


def build_index(out_dir, source):
    """Read every extracted XML back and write the join table.

    Keyed by localID, because that is the GUID a replay records - which makes
    "which track was this flight on" a dictionary lookup rather than a guess from
    the environment name, and an environment holds five or six tracks."""
    tracks, races = {}, {}
    for path in sorted(Path(out_dir).glob("*.xml")):
        root = parse_xml(path)
        guid = _text(root, "./localID/str")
        if not guid:
            continue
        if root.tag == "Track":
            tracks[guid] = {
                "file": path.name,
                "name": _text(root, "name"),
                "environment": _text(root, "environment"),
                "blueprints": len(blueprints(root)),
            }
        elif root.tag == "Race":
            order = route(root)
            races[guid] = {
                "file": path.name,
                "name": _text(root, "name"),
                "track": _text(root, "./dependencies/dependency/str"),
                "laps": int(_text(root, "requiredLaps", "0")),
                # The route is a lap: it ends back on the checkpoint it starts
                # from, so the number of gates flown is one less than its length.
                "checkpoints": max(len(order) - 1, 0),
                "route": order,
            }
    for guid, race in races.items():
        track = tracks.get(race["track"])
        if track:
            race["environment"] = track["environment"]
            track["race"] = guid
    return {
        "format": FORMAT,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "counts": {"tracks": len(tracks), "races": len(races)},
        "tracks": tracks,
        "races": races,
    }


# ------------------------------------------------------------------- the work

def fingerprint(path):
    stat = Path(path).stat()
    return {"name": Path(path).name, "size": stat.st_size, "mtime": int(stat.st_mtime)}


def extract(out_dir, game, max_mb=MAX_BUNDLE_MB):
    LR.refuse_inside_toolkit(out_dir, "extracted track data")
    bundles = bundle_dir(game)
    print("game:    %s" % game)
    print("bundles: %s" % bundles)
    found = locate(bundles, max_mb)
    missing = [kind for kind in ("track", "race") if kind not in found]
    if missing:
        sys.exit("could not find the %s bundle under %s.\n"
                 "Bundle names are content hashes, so this looks for them by content; if the\n"
                 "game moved them into a bundle larger than %d MB, raise --max-bundle-mb."
                 % (" and ".join(missing), bundles, max_mb))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stale = {p.name for p in out.glob("*.xml")}
    written = 0
    for kind in ("track", "race"):
        path, assets = found[kind]
        for name, blob in sorted(assets.items()):
            target = out / ("%s.xml" % name)
            # newline="" so the assets' own CRLFs survive instead of becoming CR CRLF
            with open(target, "w", encoding="utf-8", newline="") as fh:
                fh.write(normalise_xml(blob))
            stale.discard(target.name)
            written += 1
        print("  %-5s %-36s %3d assets" % (kind, path.name, len(assets)))
    for name in sorted(stale):         # a track this build no longer ships
        (out / name).unlink()
        print("  removed %s (no longer shipped)" % name)

    source = {
        "game_dir": str(game),
        "app_id": STEAM_APPID,
        "build_id": build_id(game),
        "bundles": {kind: fingerprint(path) for kind, (path, _assets) in found.items()},
    }
    index = build_index(out, source)
    with open(out / "index.json", "w", encoding="utf-8", newline="") as fh:
        json.dump(index, fh, indent=2)
    print("wrote %d XMLs and index.json to %s" % (written, out))
    print("  %d tracks, %d races, build %s"
          % (index["counts"]["tracks"], index["counts"]["races"], source["build_id"]))
    return index


def check(out_dir, game):
    """Is the extracted data present, complete and current? -> (ok, reason)

    Cheap on purpose - one JSON read and a handful of stat calls - so a caller
    can run it before every analysis without thinking about the cost."""
    index_path = Path(out_dir) / "index.json"
    if not index_path.exists():
        return False, "no index.json in %s" % out_dir
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return False, "index.json is unreadable (%s)" % exc
    if index.get("format") != FORMAT:
        return False, ("index.json is format %s, this tool writes %d"
                       % (index.get("format"), FORMAT))

    referenced = {t["file"] for t in index["tracks"].values()}
    referenced |= {r["file"] for r in index["races"].values()}
    absent = [name for name in sorted(referenced) if not (Path(out_dir) / name).exists()]
    if absent:
        return False, ("%d XMLs listed in index.json are missing (%s%s)"
                       % (len(absent), ", ".join(absent[:3]), ", ..." if len(absent) > 3 else ""))

    counts = "%d tracks, %d races" % (index["counts"]["tracks"], index["counts"]["races"])
    if game is None:
        return True, counts + "; game not found, so the build could not be verified"

    source = index.get("source", {})
    installed = build_id(game)
    if source.get("build_id") and installed and source["build_id"] != installed:
        return False, ("extracted from build %s, installed build is %s"
                       % (source["build_id"], installed))
    bundles = bundle_dir(game)
    for kind, was in source.get("bundles", {}).items():
        path = bundles / was["name"]
        if not path.exists():
            return False, ("the %s bundle %s is gone - the game has been patched"
                           % (kind, was["name"]))
        if path.stat().st_size != was["size"]:
            return False, "the %s bundle changed size since extraction" % kind
    return True, "%s, build %s" % (counts, source.get("build_id") or "?")


# ------------------------------------------------------------------ accessors

def load_index(out_dir):
    return json.loads((Path(out_dir) / "index.json").read_text(encoding="utf-8"))


def for_replay(out_dir, replay):
    """The track and race a replay was flown on -> (track, race, track_id, race_id).

    Matched on the GUIDs the replay records. A replay also names its environment,
    but an environment holds five or six tracks that all share it, so the name
    alone identifies nothing. Either dict is None for a community track, or for
    track data extracted from a different build."""
    root = ET.parse(str(replay)).getroot()
    index = load_index(out_dir)
    track_id = _text(root, "./trackID/str")
    race_id = _text(root, "./raceID/str")
    return index["tracks"].get(track_id), index["races"].get(race_id), track_id, race_id


# ----------------------------------------------------------------------- main

def cmd_for_replay(args, index_dir):
    track, race, track_id, race_id = for_replay(index_dir, args.for_replay)
    if args.json:
        print(json.dumps({"track": track, "race": race,
                          "track_id": track_id, "race_id": race_id}, indent=2))
        return
    if track_id is None:
        print("this replay records no track - Stunt Mode and some free flights have none, "
              "so there is no geometry to compare against")
        return
    if track is None:
        print("unknown track %s - a community track, or data extracted from another build"
              % track_id)
        return
    print("%s / %s  (%s)" % (track["environment"], track["name"], track["file"]))
    if race is None:
        print("  no race: free flight over the track, so there is no route")
        return
    print("  %d checkpoints, %d laps" % (race["checkpoints"], race["laps"]))
    print("  route %s" % " -> ".join(str(i) for i in race["route"]))
    print("  geometry: python %s --gates %r -o %s"
          % (Path(__file__).name, track["name"], index_dir))


def cmd_gates(args, index_dir):
    index = load_index(index_dir)
    wanted = args.gates.lower()
    hits = [(guid, meta) for guid, meta in index["tracks"].items()
            if wanted in (guid.lower(), (meta["name"] or "").lower(),
                          meta["file"].lower(), meta["file"].lower()[:-4])]
    if not hits:
        hits = [(guid, meta) for guid, meta in index["tracks"].items()
                if wanted in ("%s %s" % (meta["environment"], meta["name"])).lower()]
    if len(hits) != 1:
        listing = sorted("%s / %s" % (meta["environment"], meta["name"])
                         for _guid, meta in (hits or list(index["tracks"].items())))
        sys.exit("%s matches for %r. Name one of:\n  %s%s"
                 % (len(hits) or "No", args.gates, "\n  ".join(listing[:20]),
                    "\n  ..." if len(listing) > 20 else ""))
    _guid, meta = hits[0]
    race = index["races"].get(meta.get("race") or "")
    if race is None:
        sys.exit("%s / %s has no race, so there is no route to resolve"
                 % (meta["environment"], meta["name"]))
    found = gates(parse_xml(Path(index_dir) / meta["file"]), race["route"])
    if args.json:
        print(json.dumps({"track": meta, "race": race, "gates": found}, indent=2))
        return
    print("%s / %s  -  %d checkpoints, %d laps"
          % (meta["environment"], meta["name"], race["checkpoints"], race["laps"]))
    print("%-6s %-4s %-26s %-27s %-7s %s"
          % ("#", "id", "item", "position x/y/z", "yaw", "aperture"))
    for i, (cid, gate) in enumerate(zip(race["route"], found)):
        if gate is None:
            print("%-6d %-4d not defined by the track" % (i, cid))
            continue
        aperture = ("%5.2f x %5.2f m" % tuple(gate["aperture"])) if gate["aperture"] else "fixed"
        label = "finish" if i == len(found) - 1 else ("start" if i == 0 else str(i))
        print("%-6s %-4d %-26s (%7.2f,%6.2f,%7.2f) %6.1f  %s"
              % (label, gate["id"], (gate["item"] or "?")[:26],
                 gate["pos"][0], gate["pos"][1], gate["pos"][2], gate["yaw"], aperture))


def cmd_list(args, index_dir):
    index = load_index(index_dir)
    if args.json:
        print(json.dumps(index, indent=2))
        return
    by_environment = {}
    for guid, meta in index["tracks"].items():
        by_environment.setdefault(meta["environment"], []).append((guid, meta))
    for environment in sorted(by_environment):
        print(environment)
        for _guid, meta in sorted(by_environment[environment],
                                  key=lambda pair: pair[1]["name"] or ""):
            race = index["races"].get(meta.get("race") or "", {})
            print("  %-36s %2s checkpoints  %s laps  %s"
                  % (meta["name"], race.get("checkpoints", "?"), race.get("laps", "?"),
                     meta["file"]))
    print("\n%d tracks, %d races  (build %s)"
          % (index["counts"]["tracks"], index["counts"]["races"],
             index.get("source", {}).get("build_id") or "?"))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--out", default="trackdata",
                        help="where the XMLs and index.json live (default: ./trackdata)")
    parser.add_argument("--game-dir",
                        help="Liftoff install root; found automatically if omitted")
    parser.add_argument("--check", action="store_true",
                        help="report whether the data is present and current; exit 1 if not")
    parser.add_argument("--force", action="store_true", help="re-extract even if current")
    parser.add_argument("--list", action="store_true", help="list the extracted tracks")
    parser.add_argument("--gates", metavar="TRACK",
                        help="gate geometry for one track, by name, file or GUID")
    parser.add_argument("--for-replay", metavar="XML",
                        help="which track and race a replay was flown on")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--max-bundle-mb", type=int, default=MAX_BUNDLE_MB,
                        help="largest bundle to open while searching (default: %d)"
                             % MAX_BUNDLE_MB)
    args = parser.parse_args()

    game = find_game(args.game_dir)

    if args.check:
        ok, why = check(args.out, game)
        if args.json:
            print(json.dumps({"ready": ok, "reason": why, "dir": str(args.out)}))
        else:
            print("track data %s: %s" % ("READY" if ok else "NOT READY", why))
            if not ok:
                print("rebuild with: python %s -o %s" % (Path(__file__).name, args.out))
        sys.exit(0 if ok else 1)

    if args.for_replay or args.gates or args.list:
        ok, why = check(args.out, game)
        if not ok:
            sys.exit("track data not ready: %s\nrun: python %s -o %s"
                     % (why, Path(__file__).name, args.out))
        if args.for_replay:
            return cmd_for_replay(args, args.out)
        if args.gates:
            return cmd_gates(args, args.out)
        return cmd_list(args, args.out)

    if not args.force:
        ok, why = check(args.out, game)
        if ok:
            print("track data already current: %s" % why)
            return
        print("rebuilding: %s" % why)
    if game is None:
        sys.exit("could not find the Liftoff install.\n"
                 "Looked in every Steam library named by the registry and libraryfolders.vdf.\n"
                 "Pass --game-dir, or set LIFTOFF_DIR, pointing at the folder that holds "
                 "Liftoff_Data.")
    extract(args.out, game, max_mb=args.max_bundle_mb)


if __name__ == "__main__":
    main()
