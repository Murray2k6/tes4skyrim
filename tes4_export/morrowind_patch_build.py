"""
Building the Morroblivion compatibility patch.

One pass over the vanilla ESMs collects every base record Morroblivion never
converted, exports it under an id hashed from the authored Morrowind string,
and pulls just the meshes and textures those records name out of the vanilla
BSAs. The result is a standalone plugin every Morroblivion-mode conversion
declares as a master.

Kept apart from `morrowind_patch` because that module answers questions during
a conversion -- where the patch is, what it supplies -- while this one runs
only when the user asks for a build.

See: docs/commentary/tes4_export_morrowind.md#morroblivion-gap-patch
"""

import os
import time

from asset_convert.sources.bsa_extract_morrowind import (is_morrowind_bsa,
                                                         iter_bsa)
from asset_convert.sources.source_registry import asset_root

from .morrowind_patch import (PATCH_ARCHIVES, PATCH_NAME, PATCH_SOURCES,
                              collect_gap_records, gap_assets, nif_textures,
                              patch_dir, patch_formid, source_paths,
                              supplied_index)


def build_patch(data_dir: str, export_dir: str, morroblivion_exports,
                progress=print) -> dict:
    """Build the shared patch from a Morrowind Data folder; report what it made.

    `morroblivion_exports` are the converted Morroblivion plugins whose records
    define the gap: anything they already supply is not filled.
    """
    start = time.time()
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
                'seconds': time.time() - start}

    out_dir = _write_records(gaps, export_dir, progress)
    assets = _extract_assets(gaps.values(), data_dir, export_dir, progress)
    return {'ok': True, 'records': len(gaps), 'assets': assets,
            'output': out_dir, 'seconds': time.time() - start}


def _write_records(gaps: dict, export_dir: str, progress) -> str:
    """Export every gap record under its shared derived FormID."""
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
    """Extract the meshes the gap records name, then the textures those use.

    Two passes, because a mesh's textures are only known once the mesh is on
    disk: the records name meshes, and the meshes name textures.
    """
    asset_dir = asset_root(export_dir, PATCH_NAME)
    wanted = gap_assets(records)
    if not wanted:
        return 0
    progress(f'  {len(wanted)} meshes named; extracting')
    written = _extract_set(data_dir, wanted, asset_dir)
    progress(f'  Extracted {written} of {len(wanted)}')

    textures = set()
    for root, _dirs, files in os.walk(asset_dir / 'meshes'):
        for name in files:
            if name.lower().endswith('.nif'):
                textures |= nif_textures(os.path.join(root, name))
    if textures:
        progress(f'  {len(textures)} textures used by those meshes; extracting')
        found = _extract_set(data_dir, textures, asset_dir)
        progress(f'  Extracted {found} of {len(textures)}')
        written += found
    return written


def _extract_set(data_dir: str, wanted: set, asset_dir) -> int:
    """Pull every wanted path out of the vanilla BSAs; how many landed."""
    written = 0
    for name in PATCH_ARCHIVES:
        path = os.path.join(data_dir, name)
        if os.path.isfile(path) and is_morrowind_bsa(path):
            written += _extract_one(path, wanted, asset_dir)
    return written


def _extract_one(bsa_path: str, wanted: set, asset_dir) -> int:
    """Write every entry of one BSA that `wanted` names; how many landed."""
    written = 0
    for name, data in iter_bsa(bsa_path):
        key = name.replace('/', chr(92)).strip().lower()
        if key not in wanted:
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


def _no_morroblivion_message() -> str:
    """The refusal when nothing defines what the gap actually is."""
    return ('No converted Morroblivion plugin was found.\n\n'
            'The patch holds what Morroblivion does NOT supply, so '
            'Morroblivion has to be converted first:\n\n'
            '  python convert.py -f Morrowind_ob.esm')
