"""Load the same ordered mesh facts in the parent and spawned script workers."""
from asset_convert.collision_extract import bounds_cache_is_current
from output_layout import assets_for
from script_convert.cross_ref import export_dirs_with_masters
from tes5_import.mesh_bounds import load_mesh_bounds


def load_script_mesh_metadata(export_dir):
    paths = []
    seen = set()
    for directory in export_dirs_with_masters(export_dir):
        assets = assets_for(directory)
        if assets in seen:
            continue
        seen.add(assets)
        cache = assets / 'mesh_bounds_cache.json'
        if bounds_cache_is_current(str(cache)):
            paths.append(str(cache))
        elif (assets / 'meshes').is_dir() and next((assets / 'meshes').rglob('*.nif'), None):
            print(f'  WARNING: mesh physics metadata is missing or outdated: {cache}. '
                  'Rebuild mesh metadata before converting scripts that release traps.')
    load_mesh_bounds(paths, quiet=True)
    return paths
