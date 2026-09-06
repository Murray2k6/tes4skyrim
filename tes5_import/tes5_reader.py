"""TES5 (Skyrim) plugin binary reader: the one copy of the record/GRUP layer.

Mirrors `tes4_export/tes4_reader.py` on the TES5 side.  Everything that reads
a converted ESM/ESP goes through here -- the header sizes, the compressed-body
path and the recursive GRUP walk were re-implemented in 40+ files before this
existed.

TES5 vs TES4 headers: records and GRUPs are 24 bytes (TES4: 20), gaining
timestamp+form_version; subrecord headers stay 6 bytes.

**Say WHAT you want and the walk does the rest.**  The signatures you ask for
decide which records are yielded, whose bodies are decompressed, and which
top-level GRUPs are entered at all -- there are no separate knobs to keep in
step, and asking for less is always faster:

    records(raw, b'CELL', b'REFR')   -> Record, only those types
    records(raw)                     -> Record, every type
    records(raw, headers=True)       -> no bodies read; sig/FormID/flags only
    walk(raw, ...)                   -> (Record, GroupStack) when you need the
                                        enclosing worldspace/cell
    subrecords(body) / sub_map(body) -> split one record body

A `Record`'s `body` is already decompressed.  Signatures and subrecord tags
are `bytes` throughout, matching the file; use `zstr` for the string ones.

See: docs/commentary/tes5_import_override.md#the-walk-is-flat-and-inline
"""

import struct
import zlib
from dataclasses import dataclass, field

#: Record and GRUP header size; subrecord header size.
REC_HDR = 24
GRP_HDR = 24
SUB_HDR = 6

#: Tag whose U32 payload is the real length of the NEXT subrecord.
XXXX = b'XXXX'

#: Whole record header: sig, size, flags, FormID, vcs1(u32), version, vcs2.
_REC = struct.Struct('<4s4IHH')

#: Whole GRUP header: sig, size, raw label, type.
_GRP = struct.Struct('<4sI4sI')

#: Record flag: body is zlib-compressed behind a 4-byte decompressed size.
FLAG_COMPRESSED = 0x00040000

#: Record flag: the record is deleted; an override carrying it removes it.
FLAG_DELETED = 0x00000020

#: Record flag set on REFR for a persistent reference.
FLAG_PERSISTENT = 0x00000400

#: GRUP type 0 labels are a 4-char record signature, not a FormID.
GRP_TOP = 0

#: GRUP type whose label is the owning worldspace's FormID.
GRP_WORLD_CHILDREN = 1

#: GRUP types whose label is the owning cell's FormID.
GRP_CELL_CHILDREN = (6, 8, 9, 10)

#: The cell-children GRUP the engine loads ON DEMAND, not at plugin load.
GRP_TEMPORARY_CHILDREN = 9

#: GRUP types for an exterior cell block and sub-block.
GRP_EXT_BLOCK = 4
GRP_EXT_SUBBLOCK = 5


def zstr(data: bytes) -> str:
    """A null-terminated latin-1 subrecord string."""
    return data.split(b'\x00', 1)[0].decode('latin-1', errors='replace')


def subrecords(body: bytes) -> list:
    """`[(tag, data), ...]` for one record body, in file order.

    A payload over 65535 bytes cannot state its own length, so an XXXX
    subrecord carries the real U32 size and the next header's length reads 0;
    the XXXX itself is consumed, not yielded.  A truncated trailing subrecord
    is dropped rather than raising: real plugins carry them and every caller
    wants the records it can read.
    See: docs/reference/tes5_binary_format.md#xxxx-subrecord-oversized-data
    """
    out = []
    pos, n = 0, len(body)
    pending = None
    while pos + SUB_HDR <= n:
        tag = body[pos:pos + 4]
        size = struct.unpack_from('<H', body, pos + 4)[0]
        pos += SUB_HDR
        if tag == XXXX and size >= 4:
            pending = struct.unpack_from('<I', body, pos)[0]
            pos += size
            continue
        if pending is not None:
            size, pending = pending, None
        if pos + size > n:
            break
        out.append((tag, body[pos:pos + size]))
        pos += size
    return out


def sub_map(body: bytes) -> dict:
    """`{tag: data}` for one body; a repeated tag keeps the LAST one."""
    return dict(subrecords(body))


def first_sub(body: bytes, tag: bytes):
    """The first subrecord body tagged `tag`, or None."""
    for got, data in subrecords(body):
        if got == tag:
            return data
    return None


def decompress(body: bytes, flags: int) -> bytes:
    """`body` inflated when the compressed flag is set; unchanged otherwise.

    A corrupt deflate stream yields b'' rather than raising, so one bad
    record cannot abort a whole-plugin scan.
    """
    if not (flags & FLAG_COMPRESSED) or len(body) < 4:
        return body
    try:
        return zlib.decompress(body[4:])
    except zlib.error:
        return b''


@dataclass
class Record:
    """One TES5 record: header fields plus its decompressed body."""

    sig: bytes
    flags: int
    form_id: int
    form_version: int
    body: bytes
    offset: int

    #: On-disk body size; `REC_HDR + size` is the record's total byte extent.
    size: int = 0

    #: Lazily parsed by `subs`; a record's body is split at most once.
    _subs: list = None

    @property
    def end(self) -> int:
        """Offset just past this record, i.e. `offset + REC_HDR + size`."""
        return self.offset + REC_HDR + self.size

    @property
    def deleted(self) -> bool:
        """True when the record carries the deleted flag."""
        return bool(self.flags & FLAG_DELETED)

    def subs(self) -> list:
        """`[(tag, data), ...]` for this record, parsed once and cached."""
        if self._subs is None:
            self._subs = subrecords(self.body)
        return self._subs

    def sub_map(self) -> dict:
        """`{tag: data}` for this record; a repeated tag keeps the last."""
        return dict(self.subs())

    def sub(self, tag: bytes):
        """The first subrecord tagged `tag`, or None."""
        for got, data in self.subs():
            if got == tag:
                return data
        return None

    def string(self, tag: bytes, default: str = '') -> str:
        """A null-terminated string subrecord, or `default` when absent."""
        data = self.sub(tag)
        return zstr(data) if data is not None else default


@dataclass
class Group:
    """One GRUP header: its type, raw label, and byte extent."""

    type: int
    label: bytes
    start: int
    end: int

    @property
    def label_fid(self) -> int:
        """The label read as a FormID, for types 1 and 6/8/9/10."""
        return struct.unpack_from('<I', self.label)[0]

    @property
    def label_sig(self) -> bytes:
        """The label read as a record signature, for type 0."""
        return self.label

    @property
    def label_grid(self) -> tuple:
        """The block label as `(y, x)`; exterior labels pack Y first."""
        y, x = struct.unpack_from('<2h', self.label)
        return y, x


@dataclass
class GroupStack:
    """The GRUP chain enclosing a record, outermost first."""

    groups: list = field(default_factory=list)

    #: Cached `path()`, dropped by `_walk` whenever the stack changes.
    _path: tuple = None

    #: Cached `of_type` answers for this stack, keyed by GRUP type.
    _found: dict = None

    def of_type(self, gtype: int):
        """The innermost enclosing GRUP of `gtype`, or None; cached per stack.

        See: docs/commentary/tes5_import_override.md#group-path-caching
        """
        if self._found is None:
            self._found = {}
        elif gtype in self._found:
            return self._found[gtype]
        hit = None
        for g in reversed(self.groups):
            if g.type == gtype:
                hit = g
                break
        self._found[gtype] = hit
        return hit

    def has_type(self, gtype: int) -> bool:
        """True when any enclosing GRUP has this type."""
        return any(g.type == gtype for g in self.groups)

    @property
    def worldspace(self):
        """FormID of the enclosing world-children GRUP, or None."""
        g = self.of_type(GRP_WORLD_CHILDREN)
        return g.label_fid if g is not None else None

    @property
    def cell(self):
        """FormID of the innermost enclosing cell-children GRUP, or None.

        One inward scan, not one `of_type` per cell type: the four-lookup
        form cost 4.3M calls over a 717k-record plugin.
        See: docs/commentary/tes5_import_override.md#group-path-caching
        """
        for g in reversed(self.groups):
            if g.type in GRP_CELL_CHILDREN:
                return g.label_fid
        return None

    @property
    def top(self):
        """Signature of the enclosing top-level GRUP, or None."""
        g = self.of_type(GRP_TOP)
        return g.label_sig if g is not None else None

    def path(self) -> tuple:
        """`((type, label), ...)` outermost first, cached per GRUP.

        See: docs/commentary/tes5_import_override.md#group-path-caching
        """
        if self._path is None:
            self._path = tuple((g.type, g.label) for g in self.groups)
        return self._path


def read_record(raw, pos: int, end: int = None, bodies: bool = True):
    """`(Record, next_pos)` at `pos`, or `(None, pos)` when unreadable.

    `bodies=False` leaves `body` empty and skips the slice and any inflate,
    for scans that only read signatures and FormIDs.
    """
    end = len(raw) if end is None else end
    if pos + REC_HDR > end:
        return None, pos
    (sig, size, flags, form_id,
     _vcs1, form_version, _vcs2) = _REC.unpack_from(raw, pos)
    stop = pos + REC_HDR + size
    if stop > end:
        return None, pos
    body = (decompress(bytes(raw[pos + REC_HDR:stop]), flags) if bodies
            else b'')
    return Record(sig, flags, form_id, form_version, body, pos, size), stop


def read_group(raw, pos: int):
    """`Group` header at `pos`, or None when it is not a GRUP."""
    if pos + GRP_HDR > len(raw):
        return None
    sig, size, label, gtype = _GRP.unpack_from(raw, pos)
    if sig != b'GRUP':
        return None
    return Group(gtype, label, pos, pos + size)


def header_end(raw) -> int:
    """Offset just past the TES4 file header, i.e. the first GRUP."""
    if len(raw) < REC_HDR:
        return len(raw)
    return REC_HDR + struct.unpack_from('<I', raw, 4)[0]


def masters(raw) -> list:
    """The plugin's MAST names, lowercased, in declaration order.

    Slot i is what index byte i means inside this file; the file itself owns
    index `len(masters)`.
    """
    if len(raw) < REC_HDR or raw[:4] != b'TES4':
        return []
    size = struct.unpack_from('<I', raw, 4)[0]
    body = bytes(raw[REC_HDR:REC_HDR + size])
    return [zstr(data).lower()
            for tag, data in subrecords(body) if tag == b'MAST']


#: Placed-reference types, which live under a CELL's children GRUP.
_PLACED = frozenset({b'REFR', b'ACHR', b'LAND', b'NAVM', b'PGRE', b'PHZD',
                     b'PMIS', b'PARW', b'PBAR', b'PBEA', b'PCON', b'PFLA'})

#: What each nesting top-level block can hold below it; see the module doc.
_NESTED_UNDER = {
    b'WRLD': _PLACED | {b'WRLD', b'CELL'},
    b'CELL': _PLACED | {b'CELL'},
    b'DIAL': frozenset({b'DIAL', b'INFO'}),
}

#: What a child GRUP holds, by type; 7 is topic children, the rest cells.
_CHILD_HOLDS = {
    1: _PLACED | {b'CELL'}, 4: _PLACED | {b'CELL'}, 5: _PLACED | {b'CELL'},
    6: _PLACED, 8: _PLACED, 9: _PLACED, 10: _PLACED,
    7: frozenset({b'INFO'}),
}


def walk(raw, *sigs: bytes, bodies=None, span=None, prune=None):
    """Yield `(Record, GroupStack)` for `sigs`, or all; the stack is reused.

    `bodies` narrows which of them are read in full, `()` for none.  `prune`
    skips a GRUP its `(group, stack)` cannot be judged by signature alone.
    See: docs/commentary/tes5_import_override.md#the-signatures-drive-everything
    """
    want = frozenset(sigs) or None
    start, end = span if span else (header_end(raw), len(raw))
    return _walk(raw, start, end, GroupStack(), want,
                 want if bodies is None else frozenset(bodies), prune)


def records(raw, *sigs: bytes, bodies=None, span=None, prune=None):
    """Yield the `Record`s of `sigs` (or all), ignoring the group context."""
    for record, _ in walk(raw, *sigs, bodies=bodies, span=span, prune=prune):
        yield record


def _skippable(gtype: int, label: bytes, want) -> bool:
    """True when this GRUP holds no signature the caller asked for."""
    if gtype == GRP_TOP:
        return not (want & _NESTED_UNDER.get(label, frozenset((label,))))
    return gtype in _CHILD_HOLDS and not (want & _CHILD_HOLDS[gtype])


def _enter(stack: GroupStack, group: Group, want, prune) -> bool:
    """Push `group` and say whether to walk it; pops again when not."""
    if want is not None and _skippable(group.type, group.label, want):
        return False
    stack.groups.append(group)
    stack._path = stack._found = None
    if prune is not None and prune(group, stack):
        stack.groups.pop()
        stack._path = stack._found = None
        return False
    return True


def _walk(raw, pos: int, end: int, stack: GroupStack, want, bodies, prune):
    """Yield records between `pos` and `end`, descending into nested GRUPs.

    Flat and iterative, with both headers unpacked inline.
    See: docs/commentary/tes5_import_override.md#the-walk-is-flat-and-inline
    """
    unpack_rec, unpack_grp = _REC.unpack_from, _GRP.unpack_from
    groups, limit = stack.groups, end
    while True:
        while pos + REC_HDR > limit:
            if not groups:
                return
            groups.pop()
            stack._path = stack._found = None
            limit = groups[-1].end if groups else end
        sig, size, flags, form_id, _v1, version, _v2 = unpack_rec(raw, pos)
        if sig == b'GRUP':
            gend = pos + size
            if size < GRP_HDR or gend > limit:
                return
            _sig, _gsize, label, gtype = unpack_grp(raw, pos)
            if _enter(stack, Group(gtype, label, pos, gend), want, prune):
                limit = gend
                pos += GRP_HDR
            else:
                pos = gend
            continue
        stop = pos + REC_HDR + size
        if stop > limit:
            return
        if want is None or sig in want:
            body = (decompress(bytes(raw[pos + REC_HDR:stop]), flags)
                    if bodies is None or sig in bodies else b'')
            yield Record(sig, flags, form_id, version, body, pos, size), stack
        pos = stop
