"""Generate _far.nif LOD meshes by decimating full-resolution Skyrim NIFs.

Called from lod_gen.generate_lod() as a pre-pass to ensure all LOD-flagged
objects have a _far.nif before LODGenx64 is invoked.

Algorithm
---------
1. Read the converted Skyrim NIF (v20.2.0.7, BSStream 83).
2. Transform every solid (non-skinned) shape into a common root space and
   concatenate it into ONE vertex/triangle soup, tagging each triangle with
   the shape it came from.
3. Simplify that soup with quadric-error-metric (QEM) half-edge collapses:
   positions are welded for topology, edges are collapsed cheapest-first into
   a surviving original vertex, the moved corner's UV is interpolated onto the
   survivor, boundary edges carry constraint quadrics so open rims shrink last,
   and collapses that would flip a face normal are rejected.
4. Split the surviving triangles back out by material tag and write each group
   into its original shape, so every shape keeps its own texture and shader.
5. Recompute smooth per-vertex normals; recompute tangent/bitangent vectors
   from UV differentials (standard tangent-space method).
6. Strip collision, controllers, skin, vertex colors, and extra data from all
   nodes, and clear the VertexColors shader flag (SF2 bit 0x20).
7. Write to <model_base>_far.nif.

Decimating the whole model as one welded topology is what keeps it watertight.
Shapes used to be decimated INDEPENDENTLY, which left a rim shared by two
shapes as a free boundary to both: each side chose different survivors, the
rims drifted apart, and the gap was the hole.  Welding makes the shared rim one
graph node, so a collapse moves both sides at once.

BSLightingShaderProperty is COPIED from the source (correct flags, no
recreation) — this fixes the missing ZBufferTest flag that caused objects to
not render in-game.
"""

import io
import math
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from worker_budget import worker_count

from asset_convert.game_paths import win_join
from asset_convert.nif.pyffi_monkey_patch import apply_patches
apply_patches()
from pyffi.formats.nif import NifFormat
from asset_convert.lod.mesh_decimate import (compute_tangents,
                                             is_boundary_fraction,
                                             qem_decimate, vertex_normals,
                                             MAX_DEV_FRAC,
                                             TOPO_BOUNDARY_WEIGHT,
                                             WELD_EPS)

_SKYRIM_VER = 0x14020007
_NIF_FLAGS  = 14

#: Share of source verts to keep, targeting vanilla object-LOD density +25%.
_DECIMATE_RATIO = 0.05

#: Floor on a model's combined budget: small props must still read as themselves.
_MIN_TOTAL_TARGET = 24

#: The base tier is bounded by the ratio alone; only _far8/_far16 cap verts.
_NO_CAP = 1 << 30

#: SF2 bit to clear when removing vertex colors.
_SF2_VERTEX_COLORS = 0x20

#: Trees get a crossed-quad billboard instead: decimating leaf cards shreds them.
_TREE_MODEL_PREFIX = 'tes4\\speedtrees\\'
BILLBOARD_TEX_DIR = 'tes4\\trees\\billboards'


# ---------------------------------------------------------------------------
# Decimation helpers
# ---------------------------------------------------------------------------


_TIER_MIN_GAIN = 0.90

TIER8  = dict(ratio=0.5,  cap=250, dev=0.08, suffix='_far8')
TIER16 = dict(ratio=0.25, cap=120, dev=0.12, suffix='_far16')


# ---------------------------------------------------------------------------
# NIF in-place modification (per-shape)
# ---------------------------------------------------------------------------

def _strip_node(node) -> None:
    """Remove collision, controller, and extra data from a NIF node."""
    if hasattr(node, 'collision_object'):
        node.collision_object = None
    if hasattr(node, 'controller'):
        node.controller = None
    if hasattr(node, 'num_extra_data_list'):
        node.num_extra_data_list = 0
        if hasattr(node, 'extra_data_list'):
            node.extra_data_list.update_size()


def _write_shape_geometry(shape, d_v: np.ndarray, d_t: np.ndarray,
                          d_uv: Optional[np.ndarray]) -> bool:
    """Write decimated geometry into `shape`, compacting unused vertices.

    Recomputes normals and tangents, strips vertex colors and clears the
    VertexColors SF2 bit.  Shared by the per-shape path and the whole-model
    welded path, which differ only in how the geometry was produced.
    """
    d = getattr(shape, 'data', None)
    if d is None or not isinstance(d, NifFormat.NiTriShapeData):
        return False
    if len(d_t) == 0:
        return False

    used  = np.unique(d_t)
    v_map = np.full(len(d_v), -1, dtype=np.int32)
    v_map[used] = np.arange(len(used), dtype=np.int32)
    f_v  = d_v[used]
    f_t  = v_map[d_t]
    f_uv = d_uv[used] if d_uv is not None else None
    f_n  = vertex_normals(f_v, f_t)

    nv = len(f_v)
    nt = len(f_t)

    # --- Write geometry ---
    d.num_vertices = nv
    d.has_vertices = True
    d.vertices.update_size()
    for i, (x, y, z) in enumerate(f_v):
        d.vertices[i].x = float(x)
        d.vertices[i].y = float(y)
        d.vertices[i].z = float(z)

    d.has_normals = True
    d.normals.update_size()
    for i, (nx, ny, nz) in enumerate(f_n):
        d.normals[i].x = float(nx)
        d.normals[i].y = float(ny)
        d.normals[i].z = float(nz)

    # UVs (_ListWrap has no update_size; resize via list primitives)
    if f_uv is not None:
        try:
            inner_uv = d.uv_sets[0]
            elem_type = inner_uv._elementType
            list.clear(inner_uv)
            list.extend(inner_uv, [elem_type() for _ in range(nv)])
            for i, (u, v) in enumerate(f_uv):
                d.uv_sets[0][i].u = float(u)
                d.uv_sets[0][i].v = float(v)
        except Exception:
            f_uv = None  # fall back: no UVs

    # Vertex colors — remove
    d.has_vertex_colors = False
    if hasattr(d, 'vertex_colors'):
        d.vertex_colors.update_size()

    # Tangents + bitangents
    has_tang = bool(getattr(d, 'extra_vectors_flags', 0) & 0x10)
    if has_tang:
        if f_uv is not None:
            try:
                f_tang, f_bita = compute_tangents(f_v, f_t, f_uv, f_n)
                d.tangents.update_size()
                for i, (tx, ty, tz) in enumerate(f_tang):
                    d.tangents[i].x = float(tx)
                    d.tangents[i].y = float(ty)
                    d.tangents[i].z = float(tz)
                d.bitangents.update_size()
                for i, (bx, by, bz) in enumerate(f_bita):
                    d.bitangents[i].x = float(bx)
                    d.bitangents[i].y = float(by)
                    d.bitangents[i].z = float(bz)
            except Exception:
                d.extra_vectors_flags = getattr(d, 'extra_vectors_flags', 0) & ~0x10
                if hasattr(d, 'tangents'):   d.tangents.update_size()
                if hasattr(d, 'bitangents'): d.bitangents.update_size()
        else:
            # No UVs — resize to new vert count with zero vectors
            if hasattr(d, 'tangents'):   d.tangents.update_size()
            if hasattr(d, 'bitangents'): d.bitangents.update_size()

    d.num_triangles       = nt
    d.num_triangle_points = nt * 3
    d.has_triangles       = True
    d.triangles.update_size()
    for i, (a, b, c) in enumerate(f_t):
        d.triangles[i].v_1 = int(a)
        d.triangles[i].v_2 = int(b)
        d.triangles[i].v_3 = int(c)

    d.consistency_flags = 0x4000  # CT_STATIC
    d.unknown_int_2     = 0

    # Remove VertexColors bit from SF2 since vertex colors are stripped
    for prop in getattr(shape, 'bs_properties', []):
        if prop is None:
            continue
        sf2 = getattr(prop, 'shader_flags_2', None)
        if sf2 is None:
            continue
        # SkyrimShaderPropertyFlags2 has no integer setter; use the named bit
        try:
            sf2.slsf_2_vertex_colors = 0
        except Exception:
            pass

    return True


def _collect_shapes(node, out: list) -> None:
    """Recursively collect all NiTriShapes in the NIF tree."""
    if node is None:
        return
    for child in getattr(node, 'children', []):
        if child is None:
            continue
        if isinstance(child, NifFormat.NiTriShape):
            out.append(child)
        elif isinstance(child, NifFormat.NiNode):
            _collect_shapes(child, out)


def _shape_world_transform(root, shape):
    """4x4 world transform of `shape` within `root`, or None if not found."""
    def walk(node, m):
        t = np.eye(4, dtype=np.float64)
        r = getattr(node, 'rotation', None)
        if r is not None:
            t[:3, :3] = [[r.m_11, r.m_12, r.m_13],
                         [r.m_21, r.m_22, r.m_23],
                         [r.m_31, r.m_32, r.m_33]]
        s = float(getattr(node, 'scale', 1.0) or 1.0)
        t[:3, :3] *= s
        tr = getattr(node, 'translation', None)
        if tr is not None:
            t[:3, 3] = [tr.x, tr.y, tr.z]
        m2 = m @ t
        if node is shape:
            return m2
        for c in getattr(node, 'children', []) or []:
            if c is None:
                continue
            got = walk(c, m2)
            if got is not None:
                return got
        return None
    return walk(root, np.eye(4, dtype=np.float64))


def _decimate_nif_inplace(nif_data, ratio: float,
                          cap: int = _NO_CAP,
                          max_dev_frac: float = MAX_DEV_FRAC) -> bool:
    """Decimate all geometry in the NIF in-place as ONE welded topology.

    Every shape is transformed to root space and concatenated into a single
    soup tagged per triangle with its source shape, decimated together so a
    shared rim is one topology node, then split back out by tag so each shape
    keeps its own texture and shader.  The budget counts WELDED nodes and
    scales with the model's open-rim fraction.

    Returns True if at least one shape survived.
    See: docs/commentary/asset_convert_terrain.md#qem-topology-budget
    """
    # ---- collect valid shapes ---------------------------------------------
    all_shapes: list = []
    for root in nif_data.roots:
        _collect_shapes(root, all_shapes)

    valid: List[tuple] = []          # (shape, data, verts, tris, uvs, world)
    for shape in all_shapes:
        d = getattr(shape, 'data', None)
        if (d is None
                or not isinstance(d, NifFormat.NiTriShapeData)
                or d.num_vertices < 3
                or d.num_triangles < 1
                or getattr(shape, 'skin_instance', None) is not None):
            continue
        v = np.array([(p.x, p.y, p.z) for p in d.vertices], dtype=np.float64)
        t = np.array([(x.v_1, x.v_2, x.v_3) for x in d.triangles],
                     dtype=np.int32)
        if not len(t):
            continue
        uv = None
        try:
            if len(d.uv_sets) > 0 and len(d.uv_sets[0]) == d.num_vertices:
                uv = np.array([(u.u, u.v) for u in d.uv_sets[0]],
                              dtype=np.float32)
        except Exception:
            pass
        world = None
        for root in nif_data.roots:
            world = _shape_world_transform(root, shape)
            if world is not None:
                break
        valid.append((shape, d, v, t, uv, world))

    if not valid:
        return False

    # ---- build one welded soup in root space ------------------------------
    # A shape with no UVs would otherwise force the whole model to lose UVs,
    # so give it zeros and let its own chart stay degenerate; every real LOD
    # mesh here is textured.
    any_uv = any(x[4] is not None for x in valid)
    V: list = []
    T: list = []
    U: list = []
    M: list = []
    base = 0
    for mi, (shape, d, v, t, uv, world) in enumerate(valid):
        if world is not None:
            vw = (world[:3, :3] @ v.T).T + world[:3, 3]
        else:
            vw = v
        V.append(vw)
        T.append(t + base)
        M.append(np.full(len(t), mi, dtype=np.int32))
        if any_uv:
            U.append(uv if uv is not None
                     else np.zeros((len(v), 2), dtype=np.float32))
        base += len(v)

    verts = np.concatenate(V).astype(np.float32)
    tris  = np.concatenate(T).astype(np.int32)
    mats  = np.concatenate(M).astype(np.int32)
    uvs   = np.concatenate(U).astype(np.float32) if any_uv else None

    weld_nodes = len(np.unique(np.round(verts / WELD_EPS).astype(np.int64),
                               axis=0))
    b_frac = float(is_boundary_fraction(verts, tris))
    topo_scale = 1.0 + TOPO_BOUNDARY_WEIGHT * b_frac
    total_target = min(max(_MIN_TOTAL_TARGET,
                           int(weld_nodes * ratio * topo_scale)), cap)

    d_v, d_t, d_uv, d_m = qem_decimate(verts, tris, uvs, total_target,
                                        max_dev_frac, tri_mat=mats)
    if d_m is None or not len(d_t):
        return False

    # ---- split back out per material --------------------------------------
    survivors = 0
    kept_shapes = set()
    for mi, (shape, d, v, t, uv, world) in enumerate(valid):
        sel = d_t[d_m == mi]
        if len(sel) < 1:
            continue
        # Back to this shape's LOCAL space: the soup was welded in root space.
        s_v = d_v
        if world is not None:
            inv = np.linalg.inv(world)
            s_v = (inv[:3, :3] @ d_v.T.astype(np.float64)).T + inv[:3, 3]
            s_v = s_v.astype(np.float32)
        if _write_shape_geometry(shape, s_v, sel, d_uv):
            kept_shapes.add(id(shape))
            survivors += 1

    if not survivors:
        return False

    # ---- prune the tree to surviving shapes -------------------------------
    for root in nif_data.roots:
        if root is None:
            continue
        _strip_node(root)
        root.flags = _NIF_FLAGS
        _prune_to_kept(root, kept_shapes)
    return True


def _prune_to_kept(node, kept_shapes: set) -> int:
    """Keep only NiTriShapes in `kept_shapes`; drop empty NiNodes."""
    keep: list = []
    survivors = 0
    for child in getattr(node, 'children', []) or []:
        if child is None:
            continue
        if isinstance(child, NifFormat.NiTriShape):
            if id(child) in kept_shapes:
                keep.append(child)
                survivors += 1
        elif isinstance(child, NifFormat.NiNode):
            _strip_node(child)
            sub = _prune_to_kept(child, kept_shapes)
            if sub > 0:
                keep.append(child)
                survivors += sub
    node.num_children = len(keep)
    node.children.update_size()
    for i, c in enumerate(keep):
        node.children[i] = c
    return survivors


# ---------------------------------------------------------------------------
# Tree billboard LOD (vanilla-style flat crossed quads)
# ---------------------------------------------------------------------------

def _write_billboard_flat_normal(path: Path, size: int = 128) -> None:
    """Write a flat-normal uncompressed DDS so billboard LOD is lit evenly."""
    import struct as _struct
    path.parent.mkdir(parents=True, exist_ok=True)
    hdr = b'DDS ' + _struct.pack('<I', 124)
    hdr += _struct.pack('<I', 0x1 | 0x2 | 0x4 | 0x1000 | 0x8)
    hdr += _struct.pack('<II', size, size)
    hdr += _struct.pack('<I', size * 4)
    hdr += _struct.pack('<II', 0, 0)
    hdr += b'\x00' * 44
    hdr += _struct.pack('<II', 32, 0x41)              # RGB | ALPHAPIXELS
    hdr += _struct.pack('<I', 0)
    hdr += _struct.pack('<I', 32)
    hdr += _struct.pack('<IIII', 0x00ff0000, 0x0000ff00, 0x000000ff, 0xff000000)
    hdr += _struct.pack('<I', 0x1000)
    hdr += _struct.pack('<IIII', 0, 0, 0, 0)
    # BGRA (255,128,128,255) = flat +Z normal
    px = bytes((255, 128, 128, 255)) * (size * size)
    path.write_bytes(hdr + px)


def _billboard_geometry(width: float, z_bottom: float, z_top: float):
    """Crossed-quad card verts/normals/uvs/tris (two quads at 90°)."""
    hw = width / 2.0
    verts = np.array([
        (-hw, 0.0, z_bottom), (hw, 0.0, z_bottom),
        (hw, 0.0, z_top),     (-hw, 0.0, z_top),
        (0.0, -hw, z_bottom), (0.0, hw, z_bottom),
        (0.0, hw, z_top),     (0.0, -hw, z_top),
    ], dtype=np.float32)
    normals = np.array([(0, 1, 0)] * 4 + [(1, 0, 0)] * 4, dtype=np.float32)
    # DDS v=0 is the top of the rendered tree
    uvs = np.array([(0, 1), (1, 1), (1, 0), (0, 0)] * 2, dtype=np.float32)
    tris = np.array([(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)],
                    dtype=np.int32)
    return verts, normals, uvs, tris


def generate_tree_billboard_far(dst_path: Path, obnd, model_rel: str,
                                tex_root: Path) -> bool:
    """Write a crossed-quad billboard _far.nif for a TREE model.

    Uses Oblivion's own shipped billboard render
    (textures\\tes4\\trees\\billboards\\<model stem>.dds — a full-tree render
    including the trunk).  Card size comes from OBND, which the importer
    derived from the billboard dimensions, so proportions match.  Returns
    False if the billboard texture doesn't exist (caller falls back to
    geometry decimation).
    """
    stem = os.path.splitext(os.path.basename(
        model_rel.replace('\\', '/')))[0].lower()
    # Some plugins prefix their tree MESHES with load-order digits that the
    # shipped billboard TEXTURES do not carry — TWMP Valenwood/Elsweyr ships
    # `00llltreevwelmforestmosssu.nif` against `llltreevwelmforestmosssu.dds`.
    # A miss here silently falls through to geometry decimation, which is how
    # 5,471-vertex trees ended up baked into every tile that places them:
    # those four Valenwood species alone accounted for 12 GB of one Tamriel
    # bake.  So retry without a leading digit run before giving up.
    candidates = [stem]
    _bare = stem.lstrip('0123456789')
    if _bare and _bare != stem:
        candidates.append(_bare)
    for _cand in candidates:
        if win_join(tex_root, f'{BILLBOARD_TEX_DIR}\\{_cand}.dds').exists():
            stem = _cand
            break
    else:
        return False
    diffuse_rel = f'{BILLBOARD_TEX_DIR}\\{stem}.dds'
    normal_rel = f'{BILLBOARD_TEX_DIR}\\{stem}_n.dds'
    normal_path = win_join(tex_root, normal_rel)
    if not normal_path.exists():
        try:
            _write_billboard_flat_normal(normal_path)
        except Exception:
            return False

    width = height = z_min = 0.0
    if obnd:
        x1, y1, z1, x2, y2, z2 = obnd
        width  = float(max(x2 - x1, y2 - y1))
        height = float(z2 - z1)
        z_min  = float(z1)
    if width <= 0:
        width = 256.0
    if height <= 0:
        height, z_min = 384.0, 0.0
    # Sink the card slightly so it doesn't float on slopes (LODGen's own
    # flat-billboard code uses the same 5-unit sink).
    verts, normals, uvs, tris = _billboard_geometry(
        width, z_min - 5.0, z_min + height)

    tsd = NifFormat.NiTriShapeData()
    tsd.num_vertices = len(verts)
    tsd.has_vertices = True
    tsd.vertices.update_size()
    tsd.has_normals = True
    tsd.normals.update_size()
    tsd.num_uv_sets = 1
    tsd.uv_sets.update_size()
    for i in range(len(verts)):
        v = tsd.vertices[i]
        v.x, v.y, v.z = map(float, verts[i])
        n = tsd.normals[i]
        n.x, n.y, n.z = map(float, normals[i])
        uv = tsd.uv_sets[0][i]
        uv.u, uv.v = map(float, uvs[i])
    tsd.num_triangles = len(tris)
    tsd.num_triangle_points = len(tris) * 3
    tsd.has_triangles = True
    tsd.triangles.update_size()
    for i, (a, b, c) in enumerate(tris):
        t = tsd.triangles[i]
        t.v_1, t.v_2, t.v_3 = int(a), int(b), int(c)
    ctr = (verts.min(axis=0) + verts.max(axis=0)) / 2.0
    tsd.center.x, tsd.center.y, tsd.center.z = map(float, ctr)
    tsd.radius = float(np.linalg.norm(verts - ctr, axis=1).max())
    tsd.consistency_flags = 0x4000  # CT_STATIC

    texset = NifFormat.BSShaderTextureSet()
    texset.num_textures = 9
    texset.textures.update_size()
    texset.textures[0] = f'textures\\{diffuse_rel}'.encode()
    texset.textures[1] = f'textures\\{normal_rel}'.encode()

    shader = NifFormat.BSLightingShaderProperty()
    shader.texture_set = texset
    shader.uv_scale.u = 1.0
    shader.uv_scale.v = 1.0
    shader.glossiness = 1.0
    shader.specular_strength = 0.0
    shader.alpha = 1.0
    shader.emissive_multiple = 1.0
    shader.texture_clamp_mode = 3
    shader.shader_flags_1.slsf_1_z_buffer_test = 1
    shader.shader_flags_1.slsf_1_specular = 0
    shader.shader_flags_2.slsf_2_z_buffer_write = 1
    shader.shader_flags_2.slsf_2_double_sided = 1

    alpha = NifFormat.NiAlphaProperty()
    alpha.flags = 4844        # alpha testing, GREATER (LODGen's own value)
    alpha.threshold = 128

    shape = NifFormat.NiTriShape()
    shape.name = b'TreeBillboard'
    shape.flags = _NIF_FLAGS
    shape.data = tsd
    shape.bs_properties.update_size()
    shape.bs_properties[0] = shader
    shape.bs_properties[1] = alpha
    try:
        shape.update_tangent_space(as_extra=False)
    except Exception:
        pass

    root = NifFormat.BSFadeNode()
    root.name = (stem + '_far').encode('latin1')
    root.flags = _NIF_FLAGS
    root.num_children = 1
    root.children.update_size()
    root.children[0] = shape

    data = NifFormat.Data()
    data.version = _SKYRIM_VER
    data.user_version = 12
    data.user_version_2 = 83
    data.header.endian_type = 1
    data.roots = [root]
    buf = io.BytesIO()
    try:
        data.write(buf)
    except Exception:
        return False

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    dst_path.write_bytes(buf.getvalue())
    marker = dst_path.with_suffix('.nif.generated')
    marker.write_text('generated by lod_far_gen (tree billboard)\n',
                      encoding='utf-8')
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Bounded per-process error visibility: _far.nif generation runs across many
# worker processes and thousands of models, so an unbounded print per failure
# would flood the log -- but printing NOTHING (the previous behaviour) left
# "generated 0 (77 failed)" with no way to diagnose it. Same cap pattern as
# bsa_extract.py's own error reporting.
_far_nif_errors_reported = 0


def _report_far_nif_error(what: str, exc: Exception) -> None:
    global _far_nif_errors_reported
    if _far_nif_errors_reported >= 5:
        return
    _far_nif_errors_reported += 1
    print(f'    _far.nif error ({what}): {type(exc).__name__}: {exc}')


def generate_far_nif(src_path: Path, dst_path: Path,
                     decimate_ratio: float = _DECIMATE_RATIO,
                     cap: int = _NO_CAP,
                     max_dev_frac: float = MAX_DEV_FRAC) -> bool:
    """Generate dst_path (_far.nif) by decimating each shape in src_path.

    Only processes NIFs already in Skyrim format (v20.2.0.7).
    Each shape retains its original BSLightingShaderProperty (correct flags
    and textures).  Returns True on success, False on skip/failure.

    A marker file <dst_path>.generated is written alongside the NIF so the
    pipeline knows this file was auto-generated (and may be overwritten on
    subsequent runs) rather than being a hand-crafted LOD mesh.
    """
    if not src_path.exists():
        return False

    nif_data = _read_skyrim_nif(src_path)
    if nif_data is None:
        return False
    return _decimate_and_write(nif_data, src_path.stem, dst_path,
                               decimate_ratio, cap, max_dev_frac)


def _read_skyrim_nif(src_path: Path):
    """Parse a Skyrim-version NIF, or None if unreadable/wrong version.

    PyFFI's reader is ~65% of all _far.nif generation time (it builds a Python
    object per struct field), so callers that need several outputs from one
    source should read ONCE and reuse the parsed tree.
    """
    nif_data = NifFormat.Data()
    try:
        with open(src_path, 'rb') as fh:
            nif_data.inspect(fh)
            if nif_data.version != _SKYRIM_VER:
                return None
            nif_data.read(fh)
    except Exception as exc:
        _report_far_nif_error(f'read {src_path}', exc)
        return None
    return nif_data


def strip_parallax(nif_data) -> int:
    """Clear the heightmap shader from a mesh about to be written as LOD.

    🔴 A distant-LOD mesh must never carry parallax, and this is the only place
    that can guarantee it. `_decimate_and_write` reduces the FULL model in
    place and copies its shader properties verbatim — so a parallax source
    hands its shader type 3, its `SLSF1_Parallax` flag and its slot-3 height
    map straight to the LOD tier, while the decimation rebuilds the geometry
    and drops the vertex colors that shader requires. The result renders
    unlit-black.

    Found by `parallax_check.py verify`: 60 malformed shapes, every one in a
    `_far`/`_far8`/`_far16` mesh, all reported "no vertex colors". Skipping
    parallax when CONVERTING a source `_far.nif` fixes only half of it; a tier
    DERIVED from a parallax full model needs this.

    It is also pointless work even when it renders: a per-pixel height offset
    at LOD distance resolves to nothing, and LODGen bakes these into `.bto`.
    """
    cleared = 0
    for block in nif_data.blocks:
        if not isinstance(block, NifFormat.BSLightingShaderProperty):
            continue
        touched = False
        if int(block.skyrim_shader_type) == 3:      # SHADER_TYPE_HEIGHTMAP
            block.skyrim_shader_type = 0            # back to Default
            touched = True
        if int(block.shader_flags_1.slsf_1_parallax):
            block.shader_flags_1.slsf_1_parallax = 0
            touched = True
        ts = block.texture_set
        if ts is not None and len(ts.textures) > 3 and bytes(ts.textures[3]):
            ts.textures[3] = b''
            touched = True
        cleared += bool(touched)
    return cleared


def _decimate_and_write(nif_data, src_stem: str, dst_path: Path,
                        decimate_ratio: float, cap: int,
                        max_dev_frac: float) -> bool:
    """Decimate an already-parsed NIF in place and write it to dst_path."""
    if not _decimate_nif_inplace(nif_data, decimate_ratio, cap, max_dev_frac):
        return False
    return _write_decimated(nif_data, src_stem, dst_path)



def _write_decimated(nif_data, src_stem: str, dst_path: Path) -> bool:
    """Write an already-decimated NIF to dst_path (+ its .generated marker)."""
    # Whatever this was derived from, it ships as LOD — never with parallax.
    # Here rather than in _decimate_and_write so BOTH callers are covered: the
    # coarser `_far8`/`_far16` tiers are written straight through this.
    strip_parallax(nif_data)

    # Rename root to <stem>_far
    for root in nif_data.roots:
        if root is not None:
            root.name = ((src_stem + '_far').encode('latin1')
                         if not src_stem.endswith('_far')
                         else src_stem.encode('latin1'))

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    try:
        nif_data.write(buf)
    except Exception as exc:
        _report_far_nif_error(f'write {dst_path}', exc)
        return False

    with open(dst_path, 'wb') as fh:
        fh.write(buf.getvalue())

    # Write marker so regen passes know this is auto-generated
    marker = dst_path.with_suffix('.nif.generated')
    marker.write_text('generated by lod_far_gen\n', encoding='utf-8')
    return True


def _is_generated(far_path: Path) -> bool:
    """Return True if far_path was written by generate_far_nif (has marker)."""
    return far_path.with_suffix('.nif.generated').exists()


def is_tree_model(stat: dict) -> bool:
    """True if this stat should get billboard tree LOD."""
    if stat.get('sig') == 'TREE':
        return True
    rel = stat.get('model', '').lower().replace('/', '\\').lstrip('\\')
    if rel.startswith('meshes\\'):
        rel = rel[len('meshes\\'):]
    return rel.startswith(_TREE_MODEL_PREFIX)


def generate_missing_far_nifs(stats: dict, output_meshes_dir: Path,
                               referenced_models: 'set | None' = None,
                               workers: int = None,
                               force_regen_generated: bool = False,
                               tex_root: 'Path | None' = None) -> int:
    """Generate _far.nif files for all LOD-flagged stats that lack one.

    TREE-type stats get a crossed-quad billboard card (Oblivion's shipped
    billboard render); everything else is QEM-decimated from the full mesh.

    Args:
        stats:                  {form_id: {flags, model, ...}} from lod_gen._parse_esm()
        output_meshes_dir:      e.g. output/Oblivion.esm/meshes/
        referenced_models:      If provided, only generate for models in this set.
        workers:                Process count; defaults to cpu_count - 1.
        force_regen_generated:  If True, regenerate files that were previously
                                auto-generated (have a .nif.generated marker).
                                Hand-crafted _far.nif files (no marker) are
                                never overwritten.
        tex_root:               textures/ root (for billboard lookup); defaults
                                to <output_meshes_dir>/../textures.

    Returns the number of _far.nif files successfully created.
    """
    from asset_convert.lod.lod_gen import (FLAG_DISTANT_LOD, FLAG_WORLD_MAP, far_nif_path,
                          LOD8_MIN_SIZE, obnd_max_dim)
    import multiprocessing as mp

    if workers is None:
        workers = worker_count()
    if tex_root is None:
        tex_root = output_meshes_dir.parent / 'textures'

    tasks: List[tuple] = []
    seen: set = set()

    for stat in stats.values():
        flags = stat.get('flags', 0)
        if not (flags & (FLAG_DISTANT_LOD | FLAG_WORLD_MAP)):
            continue
        model = stat.get('model', '')
        if not model or model in seen:
            continue
        seen.add(model)

        if referenced_models is not None and model not in referenced_models:
            continue

        # Resolve to filesystem paths
        rel = model.lower().replace('/', '\\').lstrip('\\')
        if rel.startswith('meshes\\'):
            rel = rel[len('meshes\\'):]
        src = win_join(output_meshes_dir, rel)

        far_rel = far_nif_path(rel.replace('\\', '/')).replace('/', '\\')
        dst = win_join(output_meshes_dir, far_rel)

        far_exists = dst.exists()
        if far_exists:
            if not force_regen_generated:
                continue  # skip — we have a _far.nif and aren't forcing regen
            if not _is_generated(dst):
                continue  # skip — hand-crafted, never overwrite

        tree = is_tree_model(stat)
        if not src.exists() and not tree:
            continue  # source doesn't exist yet

        # Which far-ring tiers does this object need?  (Trees reuse their
        # billboard at every level, so they never need tier meshes.)
        need8  = (not tree) and obnd_max_dim(stat) >= LOD8_MIN_SIZE
        need16 = (not tree) and bool(flags & FLAG_WORLD_MAP)

        tasks.append((src, dst, tree, stat.get('obnd'), rel, tex_root,
                      need8, need16))

    if not tasks:
        print(f'  LOD: all {len(seen)} unique models already have _far.nif')
        return 0

    print(f'  LOD: generating {len(tasks)} _far.nif files with {workers} workers...')
    success = failed = 0

    if workers <= 1:
        for task in tasks:
            if _far_nif_worker(task):
                success += 1
            else:
                failed += 1
    else:
        # Use multiprocessing.Pool for true CPU parallelism (PyFFI is GIL-bound)
        with mp.Pool(processes=workers) as pool:
            for ok in pool.imap_unordered(_far_nif_worker, tasks, chunksize=8):
                if ok:
                    success += 1
                else:
                    failed += 1

    print(f'  LOD: generated {success} _far.nif files ({failed} failed/skipped)')
    return success


def _tier_path(far_path: Path, suffix: str) -> Path:
    """foo_far.nif → foo<suffix>.nif (e.g. foo_far8.nif)."""
    stem = far_path.stem
    if stem.endswith('_far'):
        stem = stem[:-len('_far')]
    return far_path.with_name(stem + suffix + '.nif')


def _render_missing_billboard(src: Path, model_rel: str, tex_root: Path) -> bool:
    """Render `textures\\tes4\\trees\\billboards\\<stem>.dds` for a tree.

    Oblivion ships these; plugins often do not, and a tree without one used to
    be decimated as full geometry.  Rendering it here keeps the billboard path
    whole, so no tree ever reaches the simplifier.  Written next to the shipped
    ones so the normal lookup finds it on the very next call.
    """
    from asset_convert.lod.tree_billboard import (render_billboard, write_dds_rgba,
                                 BILLBOARD_DIR)
    if not Path(src).exists():
        return False
    stem = os.path.splitext(os.path.basename(
        str(model_rel).replace('\\', '/')))[0]
    dst = win_join(tex_root, BILLBOARD_DIR + '\\' + stem + '.dds')
    if dst.exists():
        return True
    try:
        # Sibling texture trees resolve a plugin's leaves against its master's.
        roots = [Path(tex_root)]
        parent = Path(tex_root).parent.parent
        if parent.is_dir():
            roots += [d / 'textures' for d in sorted(parent.iterdir())
                      if (d / 'textures').is_dir()
                      and (d / 'textures') != Path(tex_root)]
        img = render_billboard(Path(src), roots, 512)
        if img is None:
            return False
        write_dds_rgba(img, dst)
        return True
    except Exception as exc:
        _report_far_nif_error('billboard %s' % stem, exc)
        return False


def _far_nif_worker(args: tuple) -> bool:
    """Top-level worker for multiprocessing.Pool — must be picklable."""
    src, dst, tree, obnd, model_rel, tex_root, need8, need16 = args
    if tree:
        if generate_tree_billboard_far(dst, obnd, model_rel, tex_root):
            return True
        # No shipped billboard for this tree — RENDER one rather than falling
        # through to decimation.  Decimating a canopy is catastrophic at LOD
        # scale: the card is 8 verts, the decimated tree is 25-330 KB, and it
        # is baked once per placement.  Censused across the load order, 113
        # such trees accounted for 3.35 GB of baked geometry that becomes
        # 0.05 GB as cards — 63x lighter — and one of them
        # (`dementiatree10l`, 8,006 placements in a single level-16 tile)
        # drove that tile to 663 MB on its own.
        if _render_missing_billboard(src, model_rel, tex_root):
            if generate_tree_billboard_far(dst, obnd, model_rel, tex_root):
                return True
        # Still nothing to draw with — fall back to decimation.
    if not dst.exists() or _is_generated(dst):
        if not src.exists():
            return False
        if not generate_far_nif(src, dst):
            return False

    # Far-ring tiers are decimated FROM the _far.nif (also works for the
    # hand-crafted vanilla _far meshes, which are already low-poly).
    #
    # Decimation mutates the parsed tree in place, so each tier needs its own
    # parse — but they can all come from ONE disk read of the _far.nif we just
    # wrote, instead of re-reading (and re-stat'ing) the file per tier.  PyFFI
    # parsing is ~65% of this stage's runtime and 48% of all reads were these
    # tier re-reads.
    tiers = []
    if need8:
        p8 = _tier_path(dst, TIER8['suffix'])
        if not p8.exists() or _is_generated(p8):
            tiers.append((p8, TIER8))
    if need16:
        p16 = _tier_path(dst, TIER16['suffix'])
        if not p16.exists() or _is_generated(p16):
            tiers.append((p16, TIER16))
    if not tiers:
        return True

    try:
        far_bytes = dst.read_bytes()
    except OSError:
        return True

    # Vertex count of the parent _far.nif, to decide whether a tier is worth
    # shipping at all (see below).
    try:
        parent = NifFormat.Data()
        fh = io.BytesIO(far_bytes)
        parent.inspect(fh)
        parent.read(fh)
        parent_verts = _reachable_vert_count(parent)
    except Exception:
        parent_verts = 0

    for tier_path, tier in tiers:
        nif_data = NifFormat.Data()
        try:
            fh = io.BytesIO(far_bytes)
            nif_data.inspect(fh)
            if nif_data.version != _SKYRIM_VER:
                continue
            nif_data.read(fh)
        except Exception:
            continue
        if not _decimate_nif_inplace(nif_data, tier['ratio'], tier['cap'],
                                     tier['dev']):
            continue
        # A tier only earns its place if it is meaningfully lighter than the
        # mesh it would replace.  Many models are already at their floor after
        # the base pass — every component is down to its minimum and the
        # isolation guard refuses to go further — so asking for half of that
        # returns the same geometry.  Writing it anyway costs generation time
        # and ships a duplicate mesh for LODGen to bake; leaving it absent
        # makes `_lod_meshes_for` fall back to the _far.nif, which is the same
        # geometry by a shorter route.
        tier_verts = _reachable_vert_count(nif_data)
        if parent_verts and tier_verts >= parent_verts * _TIER_MIN_GAIN:
            if tier_path.exists() and _is_generated(tier_path):
                try:
                    tier_path.unlink()
                    tier_path.with_suffix('.nif.generated').unlink(
                        missing_ok=True)
                except OSError:
                    pass
            continue
        _write_decimated(nif_data, dst.stem, tier_path)
    return True


def _reachable_vert_count(nif_data) -> int:
    """Vertices actually reachable from the roots (what the writer keeps)."""
    shapes: list = []
    for root in nif_data.roots:
        if root is not None:
            _collect_shapes(root, shapes)
    total = 0
    for shape in shapes:
        d = getattr(shape, 'data', None)
        if d is not None:
            total += d.num_vertices
    return total
