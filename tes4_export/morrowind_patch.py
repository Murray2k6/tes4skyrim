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

`build_patch` runs that whole pass when the user asks for a build -- export,
assets AND the plugin itself, because one user action has to leave something
installable -- and the rest answers where the patch is and what it supplies.

See: docs/commentary/tes4_export_morrowind.md#morroblivion-gap-patch
"""

import hashlib
import os
import time

from asset_convert.sources.bsa_extract_morrowind import (is_morrowind_bsa,
                                                         iter_bsa)
from asset_convert.sources.source_registry import asset_root
from output_layout import DEFAULT_OUTPUT, plugin_esm, record_dir

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


def build_patch(data_dir: str, export_dir: str, morroblivion_exports,
                progress=print, out_root=None) -> dict:
    """Build the shared patch from a Morrowind Data folder; report what it made.

    `morroblivion_exports` are the converted Morroblivion plugins whose records
    define the gap: anything they already supply is not filled. `out_root` is
    the output directory the finished plugin and its assets land in.

    `ok` means the plugin FILE exists: a build that wrote records and assets
    but no plugin is a failure, not a success.
    """
    start = time.time()
    out_root = out_root or DEFAULT_OUTPUT
    esms, missing = source_paths(data_dir, PATCH_SOURCES)
    if missing:
        return {'ok': False, 'error': _missing_message(data_dir, missing)}
    if not morroblivion_exports:
        return {'ok': False, 'error': _no_morroblivion_message()}

    progress(f'Indexing {len(morroblivion_exports)} converted Morroblivion '
             f'plugin(s)...')
    index = supplied_index(export_dir, morroblivion_exports)
    progress(f'  {len(index)} objects already supplied')

    progress(f'Scanning {len(esms)} vanilla master(s) for gaps...')
    gaps = collect_gap_records(esms, index)
    progress(f'  {len(gaps)} base records Morroblivion does not supply')
    if not gaps:
        return {'ok': True, 'records': 0, 'assets': 0, 'output': '',
                'plugin': '', 'seconds': time.time() - start}

    out_dir = _write_records(gaps, export_dir, progress)
    assets = _extract_assets(gaps.values(), data_dir, export_dir, progress)
    _convert_assets(export_dir, out_root, progress)
    plugin, error = _import_records(export_dir, out_root, progress)
    return {'ok': bool(plugin), 'records': len(gaps), 'assets': assets,
            'output': out_dir, 'plugin': plugin, 'error': error,
            'seconds': time.time() - start}


def _import_records(export_dir: str, out_root, progress) -> tuple:
    """Build the patch plugin itself from the records just exported.

    Returns (path, '') on success and ('', refusal) otherwise. An ESP, not an
    ESM: it declares no TES4 master, and the export it reads carries no
    `Master[N]=` line, so the importer's own reconciliation leaves the list at
    Skyrim.esm alone.

    Imported inside the function to keep the export package from loading the
    whole import stage just to answer where the patch lives.
    """
    from tes5_import.import_main import import_plugin

    dest = plugin_esm(out_root, PATCH_NAME)
    dest.parent.mkdir(parents=True, exist_ok=True)
    progress(f'  Building {PATCH_NAME}')
    try:
        _converted, errors = import_plugin(
            export_dir=patch_dir(export_dir), output_path=str(dest),
            masters=['Skyrim.esm'], is_esm=False, output_root=str(out_root))
    except Exception as exc:
        return '', _import_failed_message(f'{type(exc).__name__}: {exc}')
    if not dest.is_file():
        return '', _import_failed_message('the importer wrote no plugin file')
    if errors:
        return '', _import_failed_message(f'{errors} record error(s)')
    progress(f'  Wrote {dest}')
    return str(dest), ''


def _convert_assets(export_dir: str, out_root, progress) -> None:
    """Convert the extracted patch assets into `out_root`.

    Building the patch is ONE user action, so it has to leave installable
    files behind. Extraction alone populates `export/` only, and every texture
    it pulled stayed invisible to the game until an unrelated stage happened
    to run.
    """
    from asset_convert.asset_pipeline import convert_meshes
    progress('  Converting patch assets to output')
    try:
        stats = convert_meshes(PATCH_NAME, extract_dir=export_dir,
                               output_dir=out_root)
    except Exception as exc:
        progress(f'  Asset conversion FAILED: {exc}')
        return
    mesh = stats.get('mesh_conversion') or {}
    progress(f"  Converted {mesh.get('converted', 0)} meshes, "
             f"{stats.get('textures_copied', 0)} textures")


def _write_records(gaps: dict, export_dir: str, progress) -> str:
    """Export every gap record under its shared derived FormID.

    Imported inside the function to break the cycle with `export_morrowind`,
    which needs PATCH_NAME from this module at its own import time.
    """
    from .export_morrowind import (MorrowindContext, export_record,
                                   write_export, write_header)
    from .record_types.morrowind import tes4_signature

    ids = {key: patch_formid(key) for key in gaps}
    ctx = MorrowindContext(own_index=0)
    for key, rec in gaps.items():
        signature = tes4_signature(rec)
        ctx.register_own(rec.record_id, signature)
        ctx.gap_ids[(signature, key[1])] = ids[key]
    out = {}
    for key, rec in sorted(gaps.items()):
        lines = export_record(rec, ctx)
        if lines:
            out.setdefault(tes4_signature(rec), []).append((ids[key], lines))
    out_dir = patch_dir(export_dir)
    counts = write_export(out, out_dir)
    write_header(out_dir, [], sum(counts.values()),
                 'Objects Morroblivion does not convert')
    progress(f'  Wrote {sum(counts.values())} records to {out_dir}')
    return out_dir


def _extract_assets(records, data_dir: str, export_dir: str,
                    progress) -> int:
    """Extract the meshes the gap records name, plus EVERY vanilla texture.

    Meshes come per record; textures cannot, because third-party content
    references vanilla names from meshes that are not gap records. Both are
    taken in ONE pass per archive: `iter_bsa` holds the whole BSA in memory
    (Morrowind.bsa is ~800 MB), so walking it twice ran out of it.
    See: docs/commentary/tes4_export_morrowind.md#morroblivion-gap-patch
    """
    asset_dir = asset_root(export_dir, PATCH_NAME)
    wanted = gap_assets(records)
    progress(f'  {len(wanted)} meshes named; extracting those and all textures')
    written = 0
    for name in PATCH_ARCHIVES:
        path = os.path.join(data_dir, name)
        if os.path.isfile(path) and is_morrowind_bsa(path):
            written += _extract_one(path, wanted, asset_dir)
    progress(f'  Extracted {written} files')
    return written


def _extract_one(bsa_path: str, wanted: set, asset_dir) -> int:
    """Write every entry of one BSA `wanted` names OR that is a texture."""
    prefix = 'textures' + chr(92)
    written = 0
    for name, data in iter_bsa(bsa_path):
        key = name.replace('/', chr(92)).strip().lower()
        if key not in wanted and not key.startswith(prefix):
            continue
        dest = asset_dir / key
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written += 1
    return written


def _missing_message(data_dir: str, missing: list) -> str:
    """The refusal naming each vanilla master the chosen folder lacks."""
    lines = ['That folder is not a Morrowind Data Files directory.', '',
             f'Looked in: {data_dir or "(nothing chosen)"}', '', 'Missing:']
    lines += [f'  {name}' for name in missing]
    return '\n'.join(lines)


def _import_failed_message(reason: str) -> str:
    """The refusal when the records exported but the plugin did not build."""
    lines = [f'{PATCH_NAME} did not build: {reason}', '',
             'The records and assets are in export/, so nothing is lost -- '
             'but no plugin was written, and a Morroblivion-mode conversion '
             'will still refuse until one is.', '',
             'Re-run the build; if it fails again the log above names the '
             'record that stopped it.']
    return chr(10).join(lines)


def _no_morroblivion_message() -> str:
    """The refusal when nothing defines what the gap actually is."""
    return ('No converted Morroblivion plugin was found.\n\n'
            'The patch holds what Morroblivion does NOT supply, so '
            'Morroblivion has to be converted first:\n\n'
            '  python convert.py -f Morrowind_ob.esm')
