"""Minimal TES5 plugin reader: records, masters, and global FormID identity.

Nothing here knows about LOD.  `parse_esm` walks a converted ESM/ESP once and
returns the worldspaces, cells, LOD-capable base objects and placed references
the LOD stages need.

Every FormID it returns is NORMALISED: the index byte is rewritten to a global
one that names the same file in every plugin.  Raw ids cannot be compared
across plugins -- the index byte is per file -- so without this an overlay
merge treats numeric coincidences as overrides.
See: docs/commentary/tes5_import_override.md#cross-plugin-formid-identity
"""

import math
import struct
import zlib
from pathlib import Path

#: TES5 record, group and subrecord header sizes.
REC_HDR = 24
GRP_HDR = 24
SUB_HDR = 6

#: Record flag: the record body is zlib-compressed after a 4-byte size.
_FLAG_COMP = 0x00040000

#: Has Distant LOD -- SSELodGen bakes LOD for this object.
FLAG_DISTANT_LOD = 0x00008000

#: Show in World Map -- the object appears on the world map.
FLAG_WORLD_MAP = 0x10000000

#: Placement values beyond this are junk, not geometry.
_PLACEMENT_LIMIT = 1e9

#: Base-object signatures that can carry a LOD model.
_LOD_BASE_SIGS = ('STAT', 'ACTI', 'MSTT', 'TREE')

_MASTERS_CACHE: dict = {}

#: Every plugin name seen while normalising, in first-seen order; append-only.
_GLOBAL_FILES: list = []
_GLOBAL_FILE_IDX: dict = {}

_PARSED_ESM_CACHE: dict = {}


def sub(subrecords, tag):
    """The first subrecord body tagged `tag`, or None."""
    for s in subrecords:
        if s[0] == tag:
            return s[1]
    return None


def parse_subrecords(data: bytes):
    """Split a record body into `(tag, body)` pairs."""
    subs = []
    pos = 0
    while pos + SUB_HDR <= len(data):
        tag = data[pos:pos + 4].decode('ascii', errors='replace')
        size = struct.unpack_from('<H', data, pos + 4)[0]
        pos += SUB_HDR
        subs.append((tag, data[pos:pos + size]))
        pos += size
    return subs


def read_record(data: bytes, pos: int):
    """`({sig, flags, form_id, subs}, end_pos)`, decompressing when flagged."""
    if pos + REC_HDR > len(data):
        return None, pos
    sig = data[pos:pos + 4].decode('ascii', errors='replace')
    data_size = struct.unpack_from('<I', data, pos + 4)[0]
    flags = struct.unpack_from('<I', data, pos + 8)[0]
    form_id = struct.unpack_from('<I', data, pos + 12)[0]
    end = pos + REC_HDR + data_size

    raw = data[pos + REC_HDR:end]
    if flags & _FLAG_COMP and len(raw) >= 4:
        try:
            raw = zlib.decompress(raw[4:])
        except zlib.error:
            pass
    return {'sig': sig, 'flags': flags, 'form_id': form_id,
            'subs': parse_subrecords(raw)}, end


def zstr(b: bytes) -> str:
    """A null-terminated latin-1 subrecord string."""
    return b.rstrip(b'\x00').decode('latin-1', errors='replace')


def _mast_names(body: bytes) -> list:
    """Every MAST value in a TES4 header body, lowercased, in order."""
    names = []
    p = 0
    while p + SUB_HDR <= len(body):
        tag = body[p:p + 4]
        sz = struct.unpack_from('<H', body, p + 4)[0]
        if tag == b'MAST':
            names.append(zstr(body[p + SUB_HDR:p + SUB_HDR + sz]).lower())
        p += SUB_HDR + sz
    return names


def _read_header_body(esm_path: Path) -> bytes:
    """The plugin's TES4 header body, or empty when it has none."""
    try:
        with open(esm_path, 'rb') as fh:
            head = fh.read(24)
            if len(head) != 24 or head[:4] != b'TES4':
                return b''
            return fh.read(struct.unpack_from('<I', head, 4)[0])
    except OSError:
        return b''


def plugin_masters(esm_path: Path) -> list:
    """The plugin's MAST list, lowercased, in declaration order.

    Slot i of the returned list is what index byte i means inside this file;
    the file itself owns index `len(masters)`.
    """
    key = str(esm_path).lower()
    hit = _MASTERS_CACHE.get(key)
    if hit is None:
        hit = _mast_names(_read_header_body(esm_path))
        _MASTERS_CACHE[key] = hit
    return hit


def global_file_index(name: str) -> int:
    """Stable small integer for a plugin name, assigned on first sight.

    Process-wide and append-only: an id normalised for one worldspace must
    mean the same thing in the next.
    """
    name = name.lower()
    idx = _GLOBAL_FILE_IDX.get(name)
    if idx is None:
        idx = len(_GLOBAL_FILES)
        _GLOBAL_FILES.append(name)
        _GLOBAL_FILE_IDX[name] = idx
    return idx


def formid_remap_table(esm_path: Path):
    """256-entry table mapping this file's index bytes to GLOBAL index bytes.

    Slot i of the plugin's master list names the file its index byte i refers
    to; anything past the list is the plugin itself.  A local id is only ever
    24 bits, so the high byte is free to re-stamp, and
    `(global_byte << 24) | local_id` is comparable across the load order.
    """
    masters = plugin_masters(esm_path)
    own = esm_path.name.lower()
    return tuple(
        global_file_index(masters[i] if i < len(masters) else own) << 24
        for i in range(256)
    )


def finite(v: float, default: float = 0.0) -> float:
    """Clamp a placement float; NaN and out-of-range both become `default`.

    See: docs/commentary/asset_convert_terrain.md#lodgen-poisoned-floats
    """
    if not math.isfinite(v) or abs(v) > _PLACEMENT_LIMIT:
        return default
    return v


def _worldspace_bounds(mnam: bytes):
    """`(sw_x, sw_y, ne_x, ne_y)` cell corners from a WRLD MNAM."""
    if not mnam or len(mnam) < 16:
        return 0, 0, 0, 0
    nw_x, nw_y, se_x, se_y = struct.unpack_from('<4h', mnam, 8)
    return (min(nw_x, se_x), min(nw_y, se_y),
            max(nw_x, se_x), max(nw_y, se_y))


def _read_worldspace(subs) -> dict:
    """The WRLD fields the LOD stages read."""
    sw_x, sw_y, ne_x, ne_y = _worldspace_bounds(sub(subs, 'MNAM'))
    return {'edid': zstr(sub(subs, 'EDID') or b''),
            'sw_x': sw_x, 'sw_y': sw_y, 'ne_x': ne_x, 'ne_y': ne_y}


def _read_cell(subs, parent_wrld: int) -> dict:
    """The CELL grid position, or None coordinates for an interior."""
    grid_x = grid_y = None
    xclc = sub(subs, 'XCLC')
    if xclc and len(xclc) >= 8:
        grid_x, grid_y = struct.unpack_from('<2i', xclc)
    return {'parent_wrld': parent_wrld, 'grid_x': grid_x, 'grid_y': grid_y}


def _read_base_object(rec, subs) -> dict:
    """A LOD-capable base object: model, the three LOD meshes, and bounds."""
    modl = sub(subs, 'MODL')
    lods = [zstr(s[1]) for s in subs if s[0] == 'MNAM'][:3] + [''] * 3
    obnd = sub(subs, 'OBND')
    return {
        'edid': zstr(sub(subs, 'EDID') or b''),
        'sig': rec['sig'],
        'flags': rec['flags'],
        'model': zstr(modl) if modl else '',
        'obnd': (struct.unpack_from('<6h', obnd)
                 if obnd and len(obnd) >= 12 else None),
        'lod4': lods[0], 'lod8': lods[1], 'lod16': lods[2],
    }


def _read_ref(rec, subs, fid: int, pw: int, pc: int, g) -> dict:
    """One placed reference, with every float clamped by `finite`.

    NAME points at the placed base object, which very often lives in a MASTER
    -- the most collision-prone field in the merge, and the one deciding which
    mesh a distant object draws.
    """
    name = sub(subs, 'NAME')
    data_sub = sub(subs, 'DATA')
    xscl = sub(subs, 'XSCL')
    x, y, z, rx, ry, rz = (
        tuple(finite(v) for v in struct.unpack_from('<6f', data_sub))
        if data_sub and len(data_sub) >= 24 else (0.0,) * 6)
    return {
        'form_id': fid, 'flags': rec['flags'],
        'base_fid': (g(struct.unpack_from('<I', name)[0])
                     if name and len(name) >= 4 else 0),
        'parent_wrld': pw, 'parent_cell': pc,
        'x': x, 'y': y, 'z': z, 'rx': rx, 'ry': ry, 'rz': rz,
        'scale': (finite(struct.unpack_from('<f', xscl)[0], 1.0)
                  if xscl and len(xscl) >= 4 else 1.0),
    }


class _Scan:
    """One linear pass over a plugin, accumulating the four output tables."""

    def __init__(self, raw: bytes, gmap):
        """Bind the file bytes and its index-byte remap table."""
        self.raw = raw
        self.n = len(raw)
        self.gmap = gmap
        self.worldspaces: dict = {}
        self.cells: dict = {}
        self.stats: dict = {}
        self.refs: list = []

    def g(self, fid: int) -> int:
        """Normalise one FormID into the global space."""
        return self.gmap[fid >> 24] | (fid & 0x00FFFFFF)

    def dispatch(self, rec, pw: int, pc: int) -> None:
        """Route one record into whichever table it belongs to."""
        sig, subs = rec['sig'], rec['subs']
        fid = self.g(rec['form_id'])
        if sig == 'WRLD':
            self.worldspaces[fid] = _read_worldspace(subs)
        elif sig == 'CELL':
            self.cells[fid] = _read_cell(subs, pw)
        elif sig in _LOD_BASE_SIGS:
            self.stats[fid] = _read_base_object(rec, subs)
        elif sig == 'REFR':
            self.refs.append(_read_ref(rec, subs, fid, pw, pc, self.g))

    def _group_parents(self, start: int, pw: int, pc: int):
        """`(parent_wrld, parent_cell)` this GRUP's label establishes.

        GRUP labels are FormIDs in this file's own space, exactly like the
        record ids they point at, so they normalise the same way.
        """
        grp_type = struct.unpack_from('<I', self.raw, start + 12)[0]
        label = struct.unpack_from('<I', self.raw, start + 8)[0]
        if grp_type == 1:
            return self.g(label), pc
        if grp_type in (6, 8, 9, 10):
            return pw, self.g(label)
        return pw, pc

    def group(self, start: int, end: int, parent_wrld: int,
              parent_cell: int) -> None:
        """Walk one GRUP, recursing into nested groups."""
        pw, pc = self._group_parents(start, parent_wrld, parent_cell)
        p = start + GRP_HDR
        while p < end and p + 4 <= self.n:
            if self.raw[p:p + 4] == b'GRUP':
                if p + GRP_HDR > self.n:
                    break
                g_size = struct.unpack_from('<I', self.raw, p + 4)[0]
                self.group(p, p + g_size, pw, pc)
                p += g_size
                continue
            rec, next_p = read_record(self.raw, p)
            if rec is None:
                break
            self.dispatch(rec, pw, pc)
            if rec['sig'] == 'CELL':
                pc = self.g(rec['form_id'])
            elif rec['sig'] == 'WRLD':
                pw = self.g(rec['form_id'])
            p = next_p

    def run(self, pos: int) -> None:
        """Walk every top-level GRUP from `pos`."""
        p = pos
        while p + 4 <= self.n and self.raw[p:p + 4] == b'GRUP':
            if p + GRP_HDR > self.n:
                break
            g_size = struct.unpack_from('<I', self.raw, p + 4)[0]
            self.group(p, p + g_size, 0, 0)
            p += g_size


def parse_esm(esm_path: Path):
    """Scan a plugin into `(worldspaces, cells, stats, refs)`.

    worldspaces: {fid: {edid, sw_x, sw_y, ne_x, ne_y}}
    cells:       {fid: {parent_wrld, grid_x, grid_y}}
    stats:       {fid: {edid, sig, flags, model, obnd, lod4, lod8, lod16}}
    refs:        [{form_id, flags, base_fid, parent_wrld, parent_cell,
                   x, y, z, rx, ry, rz, scale}]

    Every FormID is normalised into the global index space.
    """
    raw = esm_path.read_bytes()
    if len(raw) < REC_HDR:
        return {}, {}, {}, []
    scan = _Scan(raw, formid_remap_table(esm_path))
    scan.run(REC_HDR + struct.unpack_from('<I', raw, 4)[0])
    return scan.worldspaces, scan.cells, scan.stats, scan.refs


def parse_esm_cached(esm_path: Path):
    """`parse_esm` memoised on (path, mtime, size).

    The returned structures are treated as READ-ONLY by callers.
    See: docs/commentary/asset_convert_terrain.md#parsed-esm-cache
    """
    try:
        st = esm_path.stat()
        key = (str(esm_path).lower(), st.st_mtime_ns, st.st_size)
    except OSError:
        return parse_esm(esm_path)
    hit = _PARSED_ESM_CACHE.get(key)
    if hit is None:
        hit = parse_esm(esm_path)
        for k in [k for k in _PARSED_ESM_CACHE if k[0] == key[0]]:
            del _PARSED_ESM_CACHE[k]
        _PARSED_ESM_CACHE[key] = hit
    return hit
