"""
Axis-aligned bounding boxes (AABB) for converted NIF meshes.

Used by the import pipeline to set accurate OBND values on records instead of
type-based defaults.

This module is the READER half only.  The cache is produced by
`asset_convert.collision_extract.scan_mesh_data`, which computes bounds and
collision from a SINGLE NIF parse — parsing dominates both analyses, so the
bounds scan used to re-read every mesh the collision scan had just read.  See
that function for the details.

    scan_mesh_data(mesh_dir, collision_cache, bounds_cache)  — after mesh
                                                               conversion
    load_mesh_bounds(cache_path)                             — import_main.py

Path keys are normalised: lowercase, forward slashes, relative to the mesh
output directory root.  Example: "tes4/furniture/chairnoble01.nif".

Records store raw TES4 model paths like "Furniture\\ChairNoble01.NIF"; after
_prefix_path() and normalisation these map to the same key.
"""

import json
import os
from typing import Dict, Optional, Tuple

OBNDTuple = Tuple[int, int, int, int, int, int]

# Module-level caches populated by load_mesh_bounds().
_MESH_BOUNDS: Dict[str, OBNDTuple] = {}
# Optional 7th element of a cache entry: physics flags from
# asset_convert.collision_extract.physics_flags_from_data (bit 0 =
# constrained dynamic island -> the record must be MSTT, not STAT).
_MESH_PHYSICS: Dict[str, int] = {}


def load_mesh_bounds(cache_path, quiet: bool = False) -> int:
    """Load previously computed bounds from *cache_path* into the module cache.

    Per-key lookup: if a key exists in the JSON it is used; missing keys fall
    back to type defaults (no recompute).  Returns the number of entries loaded.

    quiet=True skips the status prints — used by navmesh worker processes, which
    each call this once in their pool initializer and would otherwise spam one
    line per worker.
    """
    # Every load replaces the previous plugin's state, including failed loads.
    # Ordered paths merge master facts first and plugin overrides last.
    _MESH_BOUNDS.clear()
    _MESH_PHYSICS.clear()
    paths = [cache_path] if isinstance(cache_path, (str, os.PathLike)) else cache_path
    for path in paths:
        try:
            with open(path, encoding='utf-8') as fh:
                raw = json.load(fh)
            for key, value in raw.items():
                if key == '__schema__':
                    continue
                _MESH_BOUNDS[key] = tuple(value[:6])
                _MESH_PHYSICS[key] = int(value[6]) if len(value) > 6 else 0
        except (OSError, json.JSONDecodeError) as exc:
            if not quiet:
                print(f"  Mesh bounds: could not load {path} ({exc}), using available cache entries")
    if not quiet:
        print(f"  Mesh bounds: loaded {len(_MESH_BOUNDS)} entries from cache")
    return len(_MESH_BOUNDS)


def get_mesh_obnd(path_key: str) -> Optional[OBNDTuple]:
    """Return cached OBND tuple for *path_key*, or ``None`` if not found.

    *path_key* must be lowercase with forward slashes, relative to the mesh
    output directory root (e.g. ``"tes4/furniture/chairnoble01.nif"``).
    """
    return _MESH_BOUNDS.get(path_key)


def get_mesh_physics_flags(path_key: str) -> int:
    """Physics flags for *path_key* (0 if unknown).

    Bit 0: the converted NIF is a constrained dynamic havok island (swinging
    chains/signs).  Skyrim never simulates those on a STAT reference — the
    base record must be written as MSTT (see items.convert_STAT).

    Bit 1: a held keyframed body — the mesh needs SetMotionType(Dynamic) before
    it can move (read by script_convert.cross_ref for breakaway releases).
    """
    return _MESH_PHYSICS.get(path_key, 0)
