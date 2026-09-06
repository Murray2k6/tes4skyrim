"""Repair geometry Oblivion tolerates and the Skyrim-side tools do not.

Two authored defects, both fatal further down the line: non-finite (NaN) mesh
data, and a shape that declares vertices then ships none.

See: docs/commentary/asset_convert_nif.md#geometry-sanitising
"""

import math

from asset_convert.nif.pyffi_monkey_patch import apply_patches
apply_patches()
from pyffi.formats.nif import NifFormat

#: Replaces a non-finite normal, tangent or bitangent.
_UP = (0.0, 0.0, 1.0)

#: Fallback bound radius when the sphere cannot be recomputed.
_FALLBACK_RADIUS = 100.0


def _finite_vec(v) -> bool:
    """Whether all three components of a vector are finite."""
    return math.isfinite(v.x) and math.isfinite(v.y) and math.isfinite(v.z)


def _clear_empty_shape(block) -> None:
    """Empty a shape that declares vertices but ships none.

    Clears BOTH geometry layouts: the measured case stores strips, not
    triangles, and clearing only triangles left the strips to be rebuilt into
    faces indexing absent vertices.
    See: docs/commentary/asset_convert_nif.md#shapes-that-declare-no-vertices
    """
    block.num_vertices = 0
    block.vertices.update_size()
    for flag, arr in (('has_normals', 'normals'),
                      ('has_vertex_colors', 'vertex_colors')):
        if getattr(block, flag, False):
            setattr(block, flag, False)
            getattr(block, arr).update_size()
    if hasattr(block, 'uv_sets'):
        block.num_uv_sets = 0
        block.uv_sets.update_size()
    block.num_triangles = 0
    if hasattr(block, 'triangles'):
        block.num_triangle_points = 0
        block.has_triangles = False
        block.triangles.update_size()
    if hasattr(block, 'points'):
        block.num_strips = 0
        block.has_points = False
        block.strip_lengths.update_size()
        block.points.update_size()


def _repair_vertices(block) -> int:
    """Move non-finite vertices onto the mesh's finite centroid.

    The centroid collapses the offending triangle; the origin would stretch it
    across the whole model.
    """
    if not (getattr(block, 'has_vertices', False) and block.num_vertices):
        return 0
    bad = [v for v in block.vertices if not _finite_vec(v)]
    if not bad:
        return 0
    finite = [(v.x, v.y, v.z) for v in block.vertices if _finite_vec(v)]
    if finite:
        n = len(finite)
        centre = (sum(p[0] for p in finite) / n,
                  sum(p[1] for p in finite) / n,
                  sum(p[2] for p in finite) / n)
    else:
        centre = (0.0, 0.0, 0.0)
    for v in bad:
        v.x, v.y, v.z = centre
    try:
        block.update_center_radius()
    except Exception:
        pass
    return len(bad)


def _repair_directions(block) -> int:
    """Point every non-finite normal, tangent and bitangent at +Z."""
    fixed = 0
    for attr in ('normals', 'tangents', 'bitangents'):
        for v in getattr(block, attr, []):
            if not _finite_vec(v):
                v.x, v.y, v.z = _UP
                fixed += 1
    return fixed


def _repair_uvs(block) -> int:
    """Zero every non-finite UV component."""
    fixed = 0
    for uv_set in getattr(block, 'uv_sets', []):
        for uv in uv_set:
            if not math.isfinite(uv.u):
                uv.u = 0.0
                fixed += 1
            if not math.isfinite(uv.v):
                uv.v = 0.0
                fixed += 1
    return fixed


def _repair_colors(block) -> int:
    """Drive every non-finite vertex-colour channel to opaque white."""
    fixed = 0
    for c in getattr(block, 'vertex_colors', []):
        for ch in ('r', 'g', 'b', 'a'):
            if not math.isfinite(getattr(c, ch)):
                setattr(c, ch, 1.0)
                fixed += 1
    return fixed


def _repair_bounds(block) -> int:
    """Recompute a non-finite bound sphere, after the vertices are sound."""
    center = getattr(block, 'center', None)
    radius = getattr(block, 'radius', None)
    if center is None or radius is None:
        return 0
    if _finite_vec(center) and math.isfinite(radius):
        return 0
    try:
        block.update_center_radius()
    except Exception:
        center.x = center.y = center.z = 0.0
        block.radius = _FALLBACK_RADIUS
    return 1


def sanitize_geometry_data(data):
    """Repair non-finite and vertex-less geometry; count components fixed.

    Oblivion's renderer tolerated non-finite mesh data and Skyrim SE dies at
    cell load, so every NaN is driven to a sane value before the mesh ships.
    See: docs/commentary/asset_convert_nif.md#geometry-sanitising
    """
    fixed = 0
    for block in data.blocks:
        if not isinstance(block, NifFormat.NiGeometryData):
            continue
        if block.num_vertices and not getattr(block, 'has_vertices', False):
            _clear_empty_shape(block)
            fixed += 1
            continue
        fixed += _repair_vertices(block)
        fixed += _repair_directions(block)
        fixed += _repair_uvs(block)
        fixed += _repair_colors(block)
        fixed += _repair_bounds(block)
    return fixed
