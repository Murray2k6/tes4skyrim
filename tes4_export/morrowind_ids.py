"""
Morrowind string IDs to Oblivion-form EditorIDs and FormIDs.

TES3 identifies every record by a case-insensitive string; TES4 needs a FormID
and an alphanumeric EditorID. Morroblivion already made that jump, so the
escape below reproduces its EditorIDs exactly and lets a converted Morrowind
mod resolve its references to Morroblivion's records instead of duplicating
them.

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

#: Indexed types: base objects a reference can name, plus the worldspace.
BASE_TYPES = (
    'STAT', 'ACTI', 'DOOR', 'CONT', 'LIGH', 'MISC', 'WEAP', 'ARMO',
    'BOOK', 'ALCH', 'INGR', 'CLOT', 'KEYM', 'FURN', 'FLOR', 'SLGM',
    'WRLD',
)


def encode_editor_id(record_id: str) -> str:
    """The Morroblivion EditorID for a Morrowind string ID.

    See: docs/commentary/tes4_export_morrowind.md#morroblivion-editorid-escape
    """
    return '0' + ''.join(
        ch if ch.isalnum() else _ESCAPES.get(ch, 'Q') for ch in record_id)


class IdIndex:
    """Morrowind string ID -> an already-converted FormID.

    Lookups are case-insensitive because Morrowind's own comparisons are
    (OpenMW `ciEqual`), so `Tel Mora` and `tel mora` are one object and must
    never become two records.
    """

    def __init__(self):
        """Start empty; records are added as export dumps are scanned."""
        self._by_key = {}

    def __len__(self):
        """How many converted records this index can resolve."""
        return len(self._by_key)

    def __contains__(self, record_id: str) -> bool:
        """Whether a converted plugin already supplies this Morrowind ID."""
        return self.lookup(record_id) is not None

    def add(self, editor_id: str, form_id: str) -> None:
        """Register one converted record under its EditorID."""
        self._by_key.setdefault(editor_id.lower(), form_id)

    def lookup(self, record_id: str):
        """The FormID a converted plugin already gave this Morrowind ID."""
        return self._by_key.get(encode_editor_id(record_id).lower())

    def lookup_editor_id(self, editor_id: str):
        """The FormID for a literal EditorID, with no Morrowind escape applied.

        See: docs/commentary/tes4_export_morrowind.md#the-synthetic-worldspace
        """
        return self._by_key.get(editor_id.lower())

    def form_ids(self):
        """Every FormID this index hands out, so derivation can avoid them."""
        return self._by_key.values()

    def merge(self, other) -> None:
        """Fold another index in; existing entries keep priority."""
        for key, form_id in other._by_key.items():
            self._by_key.setdefault(key, form_id)


def load_index(export_dir: str, types=BASE_TYPES) -> IdIndex:
    """Index an existing export dump so its records can be referenced.

    Reads only `EditorID=` and `FormID=` lines, so indexing Morroblivion's
    421 MB dump costs a scan and not a parse. An absent directory yields an
    empty index, which is what makes the Morroblivion tier optional.
    """
    index = IdIndex()
    if not export_dir or not os.path.isdir(export_dir):
        return index
    for sig in types:
        path = os.path.join(export_dir, f'{sig}.txt')
        if os.path.exists(path):
            _index_file(path, index)
    return index


def _index_file(path: str, index: IdIndex) -> None:
    """Pair each record's FormID with its EditorID into the index."""
    form_id = None
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if line.startswith('FormID='):
                form_id = line[7:].strip()
            elif line.startswith('EditorID=') and form_id:
                index.add(line[9:].strip(), form_id)
                form_id = None


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
