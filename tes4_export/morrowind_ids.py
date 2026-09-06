"""
Morrowind string IDs to Oblivion-form EditorIDs and FormIDs.

TES3 identifies every record by a case-insensitive string; TES4 needs a FormID
and an alphanumeric EditorID. Morroblivion already made that jump, so the
escape below reproduces its EditorIDs exactly and lets a converted Morrowind
mod resolve its references to Morroblivion's records instead of duplicating
them. Our own TES3 exports keep the raw ID as the EditorID, so the index
answers to both spellings.

The escape is `0` + the ID with each non-alphanumeric replaced by a letter.
It is deliberately used in ONE direction only: encode a Morrowind ID to get a
lookup key. Decoding back is ambiguous, because the substitute letters are
themselves legal ID characters.

See: docs/commentary/tes4_export_morrowind.md#morroblivion-editorid-escape
"""

import os

#: Non-alphanumeric -> the letter Morroblivion substitutes for it.
_ESCAPES = {
    '_': 'U', ' ': 'S', ',': 'V', "'": 'A', ':': 'X', '-': 'D',
    '.': 'P', '(': 'B', ')': 'C', '!': 'E', '/': 'F',
}

#: Indexed types: base objects a reference or record can name, plus cells, terrain and the worldspace.
BASE_TYPES = (
    'STAT', 'ACTI', 'DOOR', 'CONT', 'LIGH', 'MISC', 'WEAP', 'ARMO',
    'BOOK', 'ALCH', 'INGR', 'CLOT', 'KEYM', 'FURN', 'FLOR', 'SLGM',
    'AMMO', 'APPA', 'NPC_', 'CREA', 'LVLI', 'LVLC', 'SOUN', 'GLOB',
    'FACT', 'CLAS', 'SCPT', 'WRLD', 'CELL', 'LAND',
)

#: Export text delimiters the index scans between.
_RECORD_BEGIN = '---RECORD_BEGIN---'
_RECORD_END = '---RECORD_END---'

#: Lines the scan keeps from each record.
_INDEXED_KEYS = ('FormID', 'EditorID', 'XCLC.X', 'XCLC.Y', 'ParentCELL')


def encode_editor_id(record_id: str) -> str:
    """The Morroblivion EditorID for a Morrowind string ID.

    See: docs/commentary/tes4_export_morrowind.md#morroblivion-editorid-escape
    """
    return '0' + ''.join(
        ch if ch.isalnum() else _ESCAPES.get(ch, 'Q') for ch in record_id)


def interior_key(name: str) -> str:
    """The index and derivation key of an interior cell, by its name."""
    return 'cell:' + name.lower()


def exterior_key(grid: tuple) -> str:
    """The index and derivation key of an exterior cell, by its TES4 grid."""
    return 'cell:%d:%d' % grid


def land_key(cell_form_id: str) -> str:
    """The index key of the LAND under one exterior cell."""
    return 'land:' + cell_form_id.upper()


class IdIndex:
    """Morrowind string ID -> an already-converted FormID.

    Lookups are case-insensitive because Morrowind's own comparisons are
    (OpenMW `ciEqual`), so `Tel Mora` and `tel mora` are one object and must
    never become two records. A base object answers under its raw ID (our own
    TES3 exports) and under the Morroblivion escape; cells and terrain are
    keyed by `interior_key`, `exterior_key` and `land_key`.
    """

    def __init__(self):
        """Start empty; records are added as export dumps are scanned."""
        self._by_key = {}
        self._sig_by_key = {}

    def __len__(self):
        """How many converted records this index can resolve."""
        return len(self._by_key)

    def __contains__(self, record_id: str) -> bool:
        """Whether a converted plugin already supplies this Morrowind ID."""
        return self.lookup(record_id) is not None

    def add(self, editor_id: str, form_id: str, signature: str = '') -> None:
        """Register one converted record under its EditorID or cell key."""
        key = editor_id.lower()
        if key not in self._by_key:
            self._by_key[key] = form_id
            self._sig_by_key[key] = signature

    def _key_for(self, record_id: str):
        """The stored key a Morrowind ID answers under, or None."""
        for key in (encode_editor_id(record_id).lower(), record_id.lower()):
            if key in self._by_key:
                return key
        return None

    def lookup(self, record_id: str):
        """The FormID a converted plugin already gave this Morrowind ID."""
        key = self._key_for(record_id)
        return None if key is None else self._by_key[key]

    def lookup_signature(self, record_id: str) -> str:
        """The record type a converted plugin gave this Morrowind ID, or ''.

        See: docs/commentary/tes4_export_morrowind.md#actors-and-placements
        """
        key = self._key_for(record_id)
        return '' if key is None else self._sig_by_key[key]

    def lookup_editor_id(self, editor_id: str):
        """The FormID for a literal EditorID, with no Morrowind escape applied.

        See: docs/commentary/tes4_export_morrowind.md#the-synthetic-worldspace
        """
        return self._by_key.get(editor_id.lower())

    def lookup_interior(self, name: str):
        """The FormID of a master's interior cell, by name or escaped name."""
        return (self._by_key.get(interior_key(name))
                or self._by_key.get(interior_key(encode_editor_id(name))))

    def lookup_exterior(self, grid: tuple):
        """The FormID of a master's exterior cell at this TES4 grid."""
        return self._by_key.get(exterior_key(grid))

    def form_ids(self):
        """Every FormID this index hands out, so derivation can avoid them."""
        return self._by_key.values()

    def merge(self, other) -> None:
        """Fold another index in; existing entries keep priority."""
        for key, form_id in other._by_key.items():
            self.add(key, form_id, other._sig_by_key.get(key, ''))


def load_index(export_dir: str, types=BASE_TYPES, remap: dict = None) -> IdIndex:
    """Index an existing export dump so its records can be referenced.

    Reads only the id lines of each record, so indexing Morroblivion's 421 MB
    dump costs a scan and not a parse. An absent directory yields an empty
    index, which is what makes the Morroblivion tier optional.

    `remap` translates each FormID's load-order byte into the borrowing
    plugin's master list; a record whose byte it does not map names a file the
    borrower does not load and is left out.
    See: docs/commentary/tes4_export_morrowind.md#masters
    """
    index = IdIndex()
    if not export_dir or not os.path.isdir(export_dir):
        return index
    for sig in types:
        path = os.path.join(export_dir, f'{sig}.txt')
        if os.path.exists(path):
            _index_file(path, index, sig, remap)
    return index


def remap_form_id(form_id: str, remap: dict):
    """`form_id` re-keyed through `remap`, or None when unreachable."""
    try:
        raw = int(form_id, 16)
    except ValueError:
        return None
    if remap is None:
        return '%08X' % raw
    mapped = remap.get((raw >> 24) & 0xFF)
    if mapped is None:
        return None
    return '%08X' % ((mapped << 24) | (raw & 0x00FFFFFF))


def _index_file(path: str, index: IdIndex, signature: str, remap) -> None:
    """Register every record of one export file under its key."""
    fields = {}
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if line.startswith(_RECORD_BEGIN):
                fields = {}
            elif line.startswith(_RECORD_END):
                _add_record(fields, index, signature, remap)
            else:
                _keep_field(fields, line)


def _keep_field(fields: dict, line: str) -> None:
    """Store `line`'s value when it is one of the id lines the scan keeps."""
    key, sep, value = line.partition('=')
    if sep and key in _INDEXED_KEYS:
        fields[key] = value.strip()


def _add_record(fields: dict, index: IdIndex, signature: str, remap) -> None:
    """Add one scanned record: by EditorID, or by cell grid / parent cell."""
    form_id = remap_form_id(fields.get('FormID', ''), remap)
    if form_id is None:
        return
    if signature == 'LAND':
        parent = remap_form_id(fields.get('ParentCELL', ''), remap)
        if parent:
            index.add(land_key(parent), form_id, signature)
        return
    if signature == 'CELL' and 'XCLC.X' in fields:
        grid = (int(fields['XCLC.X']), int(fields['XCLC.Y']))
        index.add(exterior_key(grid), form_id, signature)
        return
    edid = fields.get('EditorID')
    if not edid:
        return
    if signature == 'CELL':
        edid = interior_key(edid)
    index.add(edid, form_id, signature)


#: Morrowind marker name -> the TES4 FormID for the same engine marker.
ENGINE_MARKERS = {
    'doormarker': 0x00000001,
    'travelmarker': 0x00000002,
    'northmarker': 0x00000003,
    'divinemarker': 0x00000005,
    'templemarker': 0x00000006,
    'prisonmarker': 0x0000003B,
}


def marker_formid(record_id: str):
    """The TES4 marker FormID this Morrowind ID names, or None."""
    return ENGINE_MARKERS.get(record_id.lower())
