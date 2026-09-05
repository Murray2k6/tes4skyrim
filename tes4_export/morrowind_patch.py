"""
The Morroblivion patch: one shared master holding every object Morroblivion
never converted.

Morroblivion resolves 89.3% of vanilla Morrowind's base records, so in
Morroblivion mode a dependent plugin routinely places objects its master
cannot supply. Dropping those placements loses authored content; minting them
in each plugin's own space makes every plugin needing the same object ship a
rival copy of it.

So the gap is filled ONCE, by a standalone plugin built from the vanilla ESMs
holding every base record Morroblivion lacks. Every Morroblivion-mode
conversion declares it as a master and borrows from it exactly as it borrows
from Morroblivion itself, and a conversion that cannot find it is refused like
any other missing master.

Only the assets those records name are extracted, so the patch ships the ~10%
of Morrowind's tree Morroblivion is missing rather than all of it.

See: docs/commentary/tes4_export_morrowind.md#morroblivion-gap-patch
"""

import hashlib
import os
import re

from output_layout import record_dir

from .morrowind_ids import BASE_TYPES, IdIndex, load_index
from .record_types.morrowind import as_dds
from .tes3_reader import get_string, get_subrecord, read_file

#: Derivation site for a gap fill; fixed so ids never move between builds.
PATCH_SITE = 'mwpatch'

#: The generated patch plugin, a master of every Morroblivion-mode conversion.
PATCH_NAME = 'Morrowind-Morroblivion-Compatibility.esp'

#: The vanilla ESMs the patch is built from, in load order.
PATCH_SOURCES = ('Morrowind.esm', 'Tribunal.esm', 'Bloodmoon.esm')

#: The BSAs holding the assets those ESMs name.
PATCH_ARCHIVES = ('Morrowind.bsa', 'Tribunal.bsa', 'Bloodmoon.bsa')

#: Base object types a placement can name; cells and terrain are never filled.
GAP_TYPES = frozenset(BASE_TYPES) - {'CELL', 'LAND', 'WRLD'}

#: The patch declares no converted master, so its own records take byte 0x00.
PATCH_INDEX = 0x00

#: Derived ids live above Morroblivion's blocks, matching the export's own span.
_DERIVED_BASE = 0x00200000
_DERIVED_SPAN = 0x00D00000


def patch_formid(key) -> str:
    """The FormID of one gap fill, hashed from its (type, id) authored key.

    Keyed on authored data alone, so an id survives a rebuild and a plugin
    exported against an earlier patch still resolves. The type is part of the
    key because Morrowind's ids are unique only within one.
    See: docs/commentary/tes4_export_morrowind.md#per-type-id-namespaces
    """
    signature, record_id = key
    payload = ('%s\x00%s\x00%s' % (PATCH_SITE, signature,
                                   record_id.lower())).encode('utf-8')
    offset = int.from_bytes(hashlib.md5(payload).digest()[:4], 'little')
    return '%08X' % ((PATCH_INDEX << 24)
                     | (_DERIVED_BASE + offset % _DERIVED_SPAN))


def patch_dir(export_dir: str) -> str:
    """Where the shared patch's export lives."""
    return str(record_dir(export_dir, PATCH_NAME))


def patch_exists(export_dir: str) -> bool:
    """Whether the shared patch has been built and can be borrowed from."""
    return os.path.isfile(os.path.join(patch_dir(export_dir), '_HEADER.txt'))


def source_paths(data_dir: str, names) -> tuple:
    """(present paths, missing names) for `names` in a Morrowind Data folder."""
    found, missing = [], []
    for name in names:
        path = os.path.join(data_dir or '', name)
        if os.path.isfile(path):
            found.append(path)
        else:
            missing.append(name)
    return found, missing


def supplied_index(export_dir: str, exports) -> IdIndex:
    """What the converted Morroblivion exports can already supply.

    Read unremapped: the patch asks only WHETHER an object exists, never
    under which load-order byte, so the borrower's own re-keying does not
    apply here.
    """
    index = IdIndex()
    for name in exports:
        index.merge(load_index(str(record_dir(export_dir, name))))
    return index


def collect_gap_records(sources, index: IdIndex) -> dict:
    """{(type, record_id): TES3 record} for every object `index` cannot supply.

    Judged against the same index a conversion resolves against. Earlier
    sources win, so Tribunal and Bloodmoon add only what Morrowind.esm lacks.
    Keyed by type as well as id because Morrowind's ids are unique only within
    a type, so a bare-name key drops one of the pair.
    See: docs/commentary/tes4_export_morrowind.md#per-type-id-namespaces
    """
    found = {}
    for path in sources:
        if not os.path.isfile(path):
            continue
        for rec in read_file(path)[1]:
            name = (rec.record_id or '').lower()
            key = (rec.type, name)
            if rec.deleted or not name or key in found:
                continue
            if rec.type in GAP_TYPES and index.lookup(rec.record_id) is None:
                found[key] = rec
    return found


def gap_assets(records) -> set:
    """Every archive path the gap records name, lowercased and backslashed.

    Meshes from MODL and a land texture from LTEX's DATA. Inventory icons are
    deliberately absent: Skyrim renders the 3D model in the inventory and has
    no ICON field, so an extracted icon would ship as a dead asset.
    """
    wanted = set()
    for rec in records:
        _add_asset(wanted, rec, 'MODL', 'meshes')
        if rec.type == 'LTEX':
            _add_asset(wanted, rec, 'DATA', 'textures', dds=True)
    return wanted


def _add_asset(wanted: set, rec, sig: str, subtree: str,
               dds: bool = False) -> None:
    """Add the archive path one subrecord names, if it names one."""
    sub = get_subrecord(rec, sig)
    if sub is None:
        return
    path = get_string(sub).replace('/', chr(92)).strip().lower()
    if not path:
        return
    if dds:
        path = as_dds(path)
    wanted.add('%s%s%s' % (subtree, chr(92), path.lstrip(chr(92))))


#: A texture path as a NIF stores it: printable ASCII ending in an image suffix.
_NIF_TEXTURE = re.compile(rb'[ -~]{3,120}\.(?:dds|tga|bmp)', re.IGNORECASE)


def nif_textures(nif_path: str) -> set:
    """Every texture an extracted NIF names, as an archive path under textures.

    Scanned rather than parsed: a texture path is a plain string in the block
    data, so the whole tree costs one pass per file instead of a full NIF
    parse. Looked up as .dds, which is what the archives ship.
    """
    try:
        data = open(nif_path, 'rb').read()
    except OSError:
        return set()
    found = set()
    for raw in _NIF_TEXTURE.findall(data):
        name = raw.decode('cp1252', errors='replace')
        name = as_dds(name.replace('/', chr(92)).strip().lower())
        if name:
            found.add('textures' + chr(92) + name.lstrip(chr(92)))
    return found
