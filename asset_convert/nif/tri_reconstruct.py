"""Raise or reconstruct the triangle array of a NiTriShapeData.

Several vanilla Oblivion grass meshes (GroundCoverMediumGrass01,
GroundCoverLongGrass01, GroundCoverPineappleWeed*, GroundCoverWildPlant*)
ship with ``has_triangles = False`` while the index array itself follows in
the file; a mesh written with the flag clear carries no triangles, and
Skyrim's grass planter dereferences the missing data and CTDs (no crash
log) wherever such a grass type spawns.  A populated array only needs its
flag raised.  See: docs/commentary/asset_convert_nif.md#absent-triangle-arrays

When the array is genuinely empty the geometry is reconstructible: these
meshes are grass-blade triangle lists where every blade uses the same three
UV coordinates (base-left, base-right, tip).  Verts are classified into the
three roles by UV; the role whose vertex count equals Num Triangles anchors
one blade each, and each anchor is paired with the candidate pair from the
other two roles whose midpoint lies closest below/above it (blades are
isosceles: the tip sits over the midpoint of its base).  Winding is chosen
to agree with the stored vertex normals.
"""


class UnreconstructibleGeometry(ValueError):
    """Triangle-less NiTriShapeData whose UV layout doesn't match the
    grass-blade pattern — the file carries NO topology at all (several
    dev-era Oblivion creature meshes: minotaur hair01/hornsa/minotaurold).
    Such a shape cannot render anywhere; callers drop it."""


def _role_key(uv):
    return (round(uv.u, 3), round(uv.v, 3))


def _uv_roles(tri_data):
    """The three UV-role vertex groups sorted by mean height: base, base, tip."""
    nv = tri_data.num_vertices
    if not tri_data.num_uv_sets or nv < 3:
        raise UnreconstructibleGeometry(
            'missing triangles and no UV roles to reconstruct from')
    uvs = tri_data.uv_sets[0]
    roles = {}
    for i in range(nv):
        roles.setdefault(_role_key(uvs[i]), []).append(i)
    if len(roles) != 3:
        raise UnreconstructibleGeometry(
            f'missing triangles; expected 3 UV roles, found {len(roles)}')
    verts = tri_data.vertices
    return sorted(roles.values(), key=lambda g: sum(verts[i].z for i in g) / len(g))


def _pair_blades(tri_data, pos):
    """One (anchor, other, other) index triple per blade, unwound.

    Anchors on the tips when there is one per blade, else on the base role
    with one vert per blade; the partner pair is the one whose midpoint the
    tip tops (blades are isosceles).
    """
    nt = tri_data.num_triangles
    base_a, base_b, tips = groups = _uv_roles(tri_data)

    def blade_cost(l, r, t):
        lx, ly, _ = pos(l)
        rx, ry, _ = pos(r)
        tx, ty, _ = pos(t)
        return ((lx + rx) / 2 - tx) ** 2 + ((ly + ry) / 2 - ty) ** 2

    if len(tips) == nt:
        return [min(((blade_cost(l, r, t), t, l, r) for l in base_a for r in base_b))[1:]
                for t in tips]
    anchor, other = ((base_a, base_b) if len(base_a) == nt else
                     (base_b, base_a) if len(base_b) == nt else (None, None))
    if anchor is None:
        raise ValueError(f'missing triangles; no UV role has {nt} verts '
                         f'(role sizes {[len(g) for g in groups]})')
    return [min(((blade_cost(l, r, t), l, r, t) for r in other for t in tips))[1:]
            for l in anchor]


def _wind_with_normal(tri, pos, normals):
    """The triangle wound so its face normal agrees with vertex a's normal."""
    a, b, c = tri
    if normals is None:
        return tri
    pa, pb, pc = pos(a), pos(b), pos(c)
    e1 = [pb[k] - pa[k] for k in range(3)]
    e2 = [pc[k] - pa[k] for k in range(3)]
    face = (e1[1] * e2[2] - e1[2] * e2[1],
            e1[2] * e2[0] - e1[0] * e2[2],
            e1[0] * e2[1] - e1[1] * e2[0])
    n = normals[a]
    if face[0] * n.x + face[1] * n.y + face[2] * n.z < 0:
        return (a, c, b)
    return tri


def fix_missing_triangles(tri_data):
    """Raise `has_triangles` over a populated array, or rebuild an empty one.

    Returns True if triangles were reconstructed, False if nothing to do.
    Raises ValueError when the mesh doesn't match the reconstructible
    blade-list pattern (caller should surface the file for inspection).
    Emptiness is judged on the array: the flag does not exist below 10.1.0.0
    and reads False on every Morrowind mesh.
    """
    if not hasattr(tri_data, 'has_triangles') or not tri_data.num_triangles:
        return False
    if len(tri_data.triangles):
        tri_data.has_triangles = True
        return False

    verts = tri_data.vertices

    def pos(i):
        v = verts[i]
        return (v.x, v.y, v.z)

    normals = tri_data.normals if tri_data.has_normals else None
    fixed = [_wind_with_normal(tri, pos, normals) for tri in _pair_blades(tri_data, pos)]

    tri_data.has_triangles = True
    tri_data.num_triangles = len(fixed)
    tri_data.num_triangle_points = len(fixed) * 3
    tri_data.triangles.update_size()
    for tri, (a, b, c) in zip(tri_data.triangles, fixed):
        tri.v_1, tri.v_2, tri.v_3 = a, b, c
    return True


def clear_match_groups(tri_data):
    """Drop legacy vertex match groups (unused by Skyrim; no vanilla Skyrim
    mesh carries them, and they crash the grass planter).  Returns True if
    any were removed."""
    if not getattr(tri_data, 'num_match_groups', 0):
        return False
    tri_data.num_match_groups = 0
    tri_data.match_groups.update_size()
    return True
