"""Ordered source assets and metadata for a plugin and its TES4 masters."""
from output_layout import assets_for
from pathlib import Path
import os


def mesh_asset_roots(export_dir):
    from script_convert.cross_ref import export_dirs_with_masters
    return list(dict.fromkeys(assets_for(d) for d in
                              export_dirs_with_masters(export_dir)))


def mesh_cache_paths(export_dir, filename):
    """Include missing caches for owned meshes so readers report real failures."""
    return [str(root / filename) for root in mesh_asset_roots(export_dir)
            if (root / filename).is_file()
            or next((root / 'meshes').rglob('*.nif'), None) is not None]


def resolve_mesh_paths(meshes_dirs, model_keys):
    """Resolve each exact authored model path, with the last asset owner winning."""
    roots = ([Path(meshes_dirs)] if isinstance(meshes_dirs, (str, Path))
             else [Path(d) for d in meshes_dirs])
    found = {}
    for key in sorted(model_keys):
        for root in reversed(roots):
            path = root / key
            if path.is_file():
                found[key] = str(path)
                break
    return found


def mesh_output_state(mesh_dir):
    """Ephemeral write inventory; timestamps never enter a persistent cache key."""
    state = {}
    pending = [(str(mesh_dir), '')] if Path(mesh_dir).is_dir() else []
    while pending:
        directory, prefix = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                key = prefix + entry.name.lower()
                if entry.is_dir(follow_symlinks=False):
                    pending.append((entry.path, key + '/'))
                elif entry.name.lower().endswith('.nif') and entry.is_file():
                    # Windows directory enumeration already includes this stat;
                    # os.walk + os.stat issued a second syscall for every NIF.
                    stat = entry.stat()
                    state[key] = (stat.st_size, stat.st_mtime_ns)
    return state


def refresh_mesh_metadata(mesh_dir, asset_dir, before):
    """Refresh both caches for written/deleted outputs, including generated art."""
    from .collision_extract import scan_mesh_data, bounds_cache_is_current
    after = mesh_output_state(mesh_dir)
    changed = {key for key in before.keys() | after.keys()
               if before.get(key) != after.get(key)}
    collision = Path(asset_dir) / 'collision_cache.bin'
    bounds = Path(asset_dir) / 'mesh_bounds_cache.json'
    if not after and not before:
        return
    if changed or not collision.is_file() or not bounds_cache_is_current(bounds):
        scan_mesh_data(str(mesh_dir), str(collision), str(bounds),
                       relative_paths=changed)
