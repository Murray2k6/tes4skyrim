"""FO3/FNV marker base objects that have no Oblivion counterpart.

FO3/FNV reuse the low FormID space Oblivion fills with real content -- 0x21 is
FNV's CollisionMarker and Oblivion's FlameNode3, 0x15 is MultiBoundMarker and
JailPants -- so these substitutions must never reach a TES4 plugin. The table
is selected per source, not merged into TES4_MARKER_FORMID_TO_SKYRIM.

See: docs/commentary/tes4_export_falloutnv.md#marker-base-objects
"""

_XMARKER = 0x0000003B
_XMARKER_HEADING = 0x00000034

#: FO3/FNV marker base FormID -> the Skyrim.esm invisible marker to stand in.
FALLOUT_MARKER_FORMID_TO_SKYRIM = {
    0x00000015: _XMARKER,          # MultiBoundMarker
    0x0000001F: _XMARKER,          # RoomMarker
    0x00000021: _XMARKER,          # CollisionMarker
    0x00000023: _XMARKER,          # AudioMarker
    0x00000032: _XMARKER_HEADING,  # COCMarkerHeading
    0x00000033: _XMARKER,          # RadiationMarker
}

#: Record types only FO3/FNV emit; their presence identifies the source game.
FALLOUT_ONLY_SIGS = ('NAVM', 'TERM', 'MSTT', 'IDLM', 'PWAT', 'CCRD', 'REPU')

#: True while converting an FO3/FNV source; set once per plugin at import start.
_IS_FALLOUT_SOURCE = []


def register_fallout_source(by_type: dict):
    """Detect and record whether this run's source plugin is FO3/FNV."""
    _IS_FALLOUT_SOURCE.clear()
    if any(by_type.get(sig) for sig in FALLOUT_ONLY_SIGS):
        _IS_FALLOUT_SOURCE.append(True)


def is_fallout_source() -> bool:
    """True when this run's source plugin is FO3/FNV."""
    return bool(_IS_FALLOUT_SOURCE)


def marker_substitute(name_raw: int):
    """The Skyrim invisible marker standing in for an FO3/FNV marker base."""
    if not _IS_FALLOUT_SOURCE:
        return None
    return FALLOUT_MARKER_FORMID_TO_SKYRIM.get(name_raw)
