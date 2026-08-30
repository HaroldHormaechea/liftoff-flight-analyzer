#!/usr/bin/env python3
"""
unityfs.py - a dependency-free reader for the Unity bundles Liftoff ships.

Extracted from liftoff_tracks.py, which had grown two jobs: unwrapping Unity's
container format, and knowing what Liftoff's Track and Race XML means. This file
is the first of those. It stays under sources/liftoff/ rather than moving to a
shared engine layer: hoisting it would be generalising ahead of a second Unity
sim whose bundles nobody has opened yet, which is exactly what PROJECT_BRIEF.md
rules out. When that sim arrives, this is the file to promote.

liftoff_scene.py reaches in here by private name for `_cstr` and `lz4_block` -
it reads the same container with a different object table in mind - so those two
are deliberately importable rather than folded into their callers.

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
"""

import re
import struct
from pathlib import Path

CLASS_TEXTASSET = 49
MAX_BUNDLE_MB = 64                    # the two we want are ~1 MB and ~0.1 MB


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
