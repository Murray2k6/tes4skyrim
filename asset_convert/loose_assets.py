"""Extract loose dependencies named by a plugin's records and creature folders."""

from collections import deque
from pathlib import Path, PureWindowsPath
import re
import shutil

from output_layout import record_dir
from tes5_import.text_reader import parse_export_file
from .texture_prune import _texture_refs_in, _norm, _MAP_SUFFIXES


def extract_loose_assets(plugin, data_path, export_root, destination, force=False):
    source, output = Path(data_path), Path(destination)
    pending, seen, creature_folders = deque(), set(), set()
    copied = cached = 0

    def enqueue(value, category=''):
        path = PureWindowsPath(value.strip())
        if path.is_absolute() or '..' in path.parts:
            return
        parts = list(path.parts)
        if parts and parts[0].lower() == 'data':
            parts.pop(0)
        if category and (not parts or parts[0].lower() != category):
            parts.insert(0, category)
        relative = Path(*parts)
        key = relative.as_posix().lower()
        if key not in seen:
            seen.add(key)
            pending.append(relative)

    # World geometry and reference records contain no asset filenames. Avoid
    # parsing their large binary dumps to find model/icon/source-script paths.
    excluded = {'CELL', 'LAND', 'REFR', 'ACHR', 'ACRE', 'PGRD', 'ROAD'}
    for text in record_dir(export_root, plugin).glob('*.txt'):
        if len(text.stem) != 4 or text.stem in excluded:
            continue
        for rec in parse_export_file(str(text)):
            model = PureWindowsPath(rec.get('Model.MODL', ''))
            if text.stem == 'CREA' and model.name.lower() == 'skeleton.nif':
                creature_folders.add(model.parent)
            for key, value in rec.items():
                suffix = PureWindowsPath(value).suffix.lower() if len(value) < 512 else ''
                if suffix in ('.nif', '.kf'):
                    if key.startswith('NIFZ['):
                        value = str(model.parent / value)
                    enqueue(value, 'meshes')
                elif suffix == '.dds':
                    enqueue(value, 'textures')
                elif suffix == '.spt':
                    enqueue(value, 'trees')
                elif suffix in ('.wav', '.mp3', '.lip'):
                    enqueue(value, 'sound')
                elif key in ('SCTX', 'ResultScript') or key.endswith('.ResultScript'):
                    for literal in re.findall(r'"([^"\r\n]+)"', value):
                        extension = PureWindowsPath(literal).suffix.lower()
                        category = {'.nif': 'meshes', '.dds': 'textures', '.kf': 'meshes',
                                    '.wav': 'sound', '.mp3': 'sound', '.ini': ''}.get(extension)
                        if category is not None:
                            enqueue(literal, category)

    # The engine selects KF files by animation group, rather than explicit
    # record links. Include the authored creature's whole animation directory.
    for folder in sorted(creature_folders, key=str):
        root = source / 'meshes' / Path(*folder.parts)
        if root.is_dir():
            for path in root.rglob('*'):
                if path.is_file() and path.suffix.lower() in ('.nif', '.kf'):
                    enqueue(str(path.relative_to(source)))

    while pending:
        relative = pending.popleft()
        path = source / relative
        if not path.is_file():
            continue
        target = output / relative
        if (not force and target.is_file() and target.stat().st_size == path.stat().st_size
                and target.stat().st_mtime_ns == path.stat().st_mtime_ns):
            cached += 1
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.unlink(missing_ok=True)  # Break any merge-cache hard link.
            shutil.copy2(path, target)
            copied += 1
        if path.suffix.lower() in ('.nif', '.spt'):
            for texture in _texture_refs_in(path.read_bytes()):
                normalized = _norm(texture)
                if normalized:
                    enqueue(normalized, 'textures')
                    diffuse = PureWindowsPath(normalized)
                    for suffix in _MAP_SUFFIXES:
                        enqueue(str(diffuse.with_name(diffuse.stem + suffix + '.dds')), 'textures')
    print(f'  Loose assets: {copied} copied, {cached} cached', flush=True)
    return {'copied': copied, 'cached': cached}
