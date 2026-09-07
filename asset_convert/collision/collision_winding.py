"""Repair inverted collision winding: the "I fall through the floor" fix.

Split out of collision.py.  A collision triangle whose winding points the
wrong way is one-sided the wrong side, so the player falls through it.  The
repair works purely on triangle index tuples and vertex lists -- it never
touches a NIF block -- and uses the VISUAL mesh as its orientation oracle.

See: docs/commentary/asset_convert_collision.md#inverted-collision-winding-i-fall
"""

import math
from collections import deque

from collision_options import winding_fix_enabled
from asset_convert.collision.collision_falloutnv import is_fallout_source

#: An authored normal must oppose the face normal by this much to count.
AUTHORED_NORMAL_DOT = -0.3

def face_normal(tri):
    """Normalised face normal for a triangle given as three xyz tuples."""
    (v0, v1, v2) = tri
    ux, uy, uz = v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2]
    vx, vy, vz = v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2]
    nx = uy*vz - uz*vy
    ny = uz*vx - ux*vz
    nz = ux*vy - uy*vx
    mag = math.sqrt(nx*nx + ny*ny + nz*nz)
    if mag > 0:
        nx /= mag; ny /= mag; nz /= mag
    return nx, ny, nz


#: Triangles rewound so far; a list so process workers can mutate it.
INVERTED_FLOOR_FLIPS = [0]

#: Step-2 tuning in Skyrim havok units. See: docs/commentary/asset_convert_collision.md#winding-repair-steps
_VIS_RADIUS = 0.30
_VIS_PARALLEL = 0.95
_VIS_MARGIN = 3.0
_SIGN_MIN_TRIS = 4


def _tri_centroid(t):
    """The triangle's centroid as an xyz tuple."""
    return ((t[0][0] + t[1][0] + t[2][0]) / 3.0,
            (t[0][1] + t[1][1] + t[2][1]) / 3.0,
            (t[0][2] + t[1][2] + t[2][2]) / 3.0)


def _traverses_opposite(nt, a, b):
    """Whether neighbour `nt` agrees with edge (a, b); None when unshared.

    Two triangles sharing an edge are consistently wound if and only if they
    traverse it in OPPOSITE directions.
    """
    edges = ((nt[0], nt[1]), (nt[1], nt[2]), (nt[2], nt[0]))
    if (b, a) in edges:
        return True
    if (a, b) in edges:
        return False
    return None


def _orient_components(idx):
    """Step 1: make every triangle agree with its edge-neighbours.

    Returns `(flip:set, comps:list[list[int]])`.
    See: docs/commentary/asset_convert_collision.md#winding-repair-steps
    """
    edge_map = {}
    for k, t in enumerate(idx):
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            edge_map.setdefault((a, b) if a < b else (b, a), []).append(k)

    flip = set()
    seen = [False] * len(idx)
    comps = []
    for start in range(len(idx)):
        if seen[start]:
            continue
        seen[start] = True
        comps.append(_settle_component(start, idx, edge_map, flip, seen))
    return flip, comps


def _settle_component(start, idx, edge_map, flip, seen):
    """BFS one connected component from `start`, flipping what disagrees.

    Mutates `flip` and `seen`; returns the component's triangle indices.
    """
    comp = [start]
    queue = deque([start])
    while queue:
        k = queue.popleft()
        t = idx[k]
        if k in flip:
            t = (t[0], t[2], t[1])
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            edge = (a, b) if a < b else (b, a)
            for nb in edge_map.get(edge, ()):
                if nb == k or seen[nb]:
                    continue
                agrees = _traverses_opposite(idx[nb], a, b)
                if agrees is None:
                    continue
                if not agrees:
                    flip.add(nb)
                seen[nb] = True
                comp.append(nb)
                queue.append(nb)
    return comp


def _component_is_closed(comp, idx):
    """True when every edge of the component is shared by exactly 2 faces."""
    cnt = {}
    for k in comp:
        t = idx[k]
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            e = (a, b) if a < b else (b, a)
            cnt[e] = cnt.get(e, 0) + 1
    return all(c == 2 for c in cnt.values())


def _component_volume(comp, idx, verts, flip):
    """Signed volume of the component (positive when wound outward)."""
    v = 0.0
    for k in comp:
        a, b, c = idx[k]
        p, q, r = verts[a], verts[b], verts[c]
        if k in flip:
            q, r = r, q
        v += (p[0] * (q[1]*r[2] - q[2]*r[1])
              - p[1] * (q[0]*r[2] - q[2]*r[0])
              + p[2] * (q[0]*r[1] - q[1]*r[0]))
    return v / 6.0


#: Step-3 coincidence tuning. See: docs/commentary/asset_convert_collision.md#step-3-walkable-repair
_FLOOR_FLAT = 0.85
_FLOOR_PLANE_DZ = 0.05
_FLOOR_XY = 0.05


def _floor_skin_index(vdata):
    """Near-horizontal visual faces bucketed into an XY grid for lookup.

    Returns `{(gx, gy): [(cx, cy, cz, nz), ...]}` at _FLOOR_XY cell size.
    See: docs/commentary/asset_convert_collision.md#step-3-walkable-repair
    """
    grid = {}
    for vc, vn in vdata:
        if abs(vn[2]) < _FLOOR_FLAT:
            continue
        gx = int(vc[0] // _FLOOR_XY)
        gy = int(vc[1] // _FLOOR_XY)
        grid.setdefault((gx, gy), []).append((vc[0], vc[1], vc[2], vn[2]))
    return grid


def _coincident_skin_faces_up(grid, centroid):
    """Whether the render skin COINCIDENT with `centroid` points up.

    The coincident skin IS this surface, so its normal is the artist's
    statement of which way the surface faces.  False when no skin is
    coincident at all, which means a real underside or overhang.
    """
    cx, cy, cz = centroid
    gx, gy = int(cx // _FLOOR_XY), int(cy // _FLOOR_XY)
    best = None
    for ox in (-1, 0, 1):
        for oy in (-1, 0, 1):
            for vx, vy, vz, vnz in grid.get((gx + ox, gy + oy), ()):
                if abs(vz - cz) > _FLOOR_PLANE_DZ:
                    continue
                d2 = (vx - cx)**2 + (vy - cy)**2
                if d2 > _FLOOR_XY * _FLOOR_XY:
                    continue
                if best is None or d2 < best[0]:
                    best = (d2, vnz)
    return best is not None and best[1] > 0


def _repair_inverted_walkables(tris, flip, verts, idx, vdata):
    """Step 3: flip down-facing floor faces the render mesh says are up.

    Only near-horizontal faces are considered, and only where a COINCIDENT
    render skin settles the question.  Returns the number flipped.
    See: docs/commentary/asset_convert_collision.md#step-3-walkable-repair
    """
    if not vdata:
        return 0
    grid = _floor_skin_index(vdata)
    if not grid:
        return 0

    flipped = 0
    for k in range(len(idx)):
        a, b, c = idx[k]
        p, q, r = verts[a], verts[b], verts[c]
        if k in flip:
            q, r = r, q
        n = face_normal((p, q, r))
        if n[2] > -_FLOOR_FLAT:
            continue
        centroid = ((p[0] + q[0] + r[0]) / 3.0,
                    (p[1] + q[1] + r[1]) / 3.0,
                    (p[2] + q[2] + r[2]) / 3.0)
        if _coincident_skin_faces_up(grid, centroid):
            if k in flip:
                flip.discard(k)
            else:
                flip.add(k)
            flipped += 1
    return flipped


def _component_visual_vote(comp, idx, verts, flip, vdata):
    """(agree, oppose, covered) for the component against the render mesh."""
    agree = oppose = 0.0
    covered = 0
    for k in comp:
        a, b, c = idx[k]
        p, q, r = verts[a], verts[b], verts[c]
        if k in flip:
            q, r = r, q
        n = face_normal((p, q, r))
        cx = (p[0] + q[0] + r[0]) / 3.0
        cy = (p[1] + q[1] + r[1]) / 3.0
        cz = (p[2] + q[2] + r[2]) / 3.0
        hit = False
        for vc, vn in vdata:
            algn = n[0]*vn[0] + n[1]*vn[1] + n[2]*vn[2]
            if abs(algn) < _VIS_PARALLEL:
                continue
            dd = ((cx - vc[0])**2 + (cy - vc[1])**2 + (cz - vc[2])**2)
            if dd > _VIS_RADIUS * _VIS_RADIUS:
                continue
            hit = True
            w = 1.0 / (dd + 1e-9)
            if algn > 0:
                agree += w
            else:
                oppose += w
        if hit:
            covered += 1
    return agree, oppose, covered


def _authored_flips(tris, authored_normals):
    """Step 0: triangles whose winding contradicts their own stored normal.

    Ungated: it reads a fact the file states about itself, so it is safe on
    every plugin and inert wherever winding and normal already agree.
    See: docs/commentary/asset_convert_collision.md#rewritten-2026-08-20-round-3--the-winding-is-authored-stop-inferring-it
    """
    out = set()
    if not authored_normals or len(authored_normals) != len(tris):
        return out
    for i, (t, an) in enumerate(zip(tris, authored_normals)):
        if an is None:
            continue
        alen = math.sqrt(an[0]**2 + an[1]**2 + an[2]**2)
        if alen < 1e-6:
            continue
        n = face_normal(t)
        if (n[0]*an[0] + n[1]*an[1] + n[2]*an[2]) / alen < AUTHORED_NORMAL_DOT:
            out.add(i)
    return out


def _weld(tris, groups):
    """Shared vertex indices per group, as `(verts, idx)`.

    Without welding no two triangles share an edge and step 1 is a no-op;
    welding ACROSS a group seam would fuse independent pieces into one
    component and force a single orientation on both.
    See: docs/commentary/asset_convert_collision.md#welding-is-per-group
    """
    if not groups or sum(groups) != len(tris):
        groups = [len(tris)]
    vmap, verts, idx, base = {}, [], [], 0
    for gsize in groups:
        vmap.clear()
        for t in tris[base:base + gsize]:
            tri_i = []
            for v in t:
                k = (round(v[0], 4), round(v[1], 4), round(v[2], 4))
                i = vmap.get(k)
                if i is None:
                    i = len(verts)
                    vmap[k] = i
                    verts.append(v)
                tri_i.append(i)
            idx.append(tuple(tri_i))
        base += gsize
    return verts, idx


def _visual_data(visual_tris):
    """(centroid, normal) for each render face with a usable normal."""
    vdata = []
    for t in visual_tris or ():
        n = face_normal(t)
        if n[0] or n[1] or n[2]:
            vdata.append((_tri_centroid(t), n))
    return vdata


def _component_sign(comp, idx, verts, flip, vdata):
    """Step 2: True when the whole component is inside-out, else None.

    A CLOSED component must enclose positive volume; otherwise the render
    mesh decides, subject to a coverage quorum.
    See: docs/commentary/asset_convert_collision.md#winding-repair-steps
    """
    if _component_is_closed(comp, idx):
        v = _component_volume(comp, idx, verts, flip)
        if abs(v) > 1e-6:
            return v < 0
    if not vdata:
        return None
    agree, oppose, covered = _component_visual_vote(comp, idx, verts, flip,
                                                    vdata)
    if covered * 2 < len(comp):
        return None
    if oppose > agree * _VIS_MARGIN:
        return True
    if agree > oppose * _VIS_MARGIN:
        return False
    return None


def _apply_component_signs(comps, idx, verts, flip, vdata):
    """Flip every component step 2 judges inside-out."""
    for comp in comps:
        if len(comp) < _SIGN_MIN_TRIS:
            continue
        if not _component_sign(comp, idx, verts, flip, vdata):
            continue
        for k in comp:
            if k in flip:
                flip.discard(k)
            else:
                flip.add(k)


def _rewound(tris, flip):
    """`(tris, n)` with every index in `flip` reversed; the input when empty."""
    if not flip:
        return tris, 0
    out = [(t[0], t[2], t[1]) if i in flip else t
           for i, t in enumerate(tris)]
    return out, len(flip)


def repair_inverted_floors(tris, visual_tris=None, groups=None,
                           authored_normals=None):
    """Rewind collision triangles wound backwards; `(repaired_tris, n_flipped)`.

    Step 0 reads the authored normal and is ungated; steps 1-3 infer from
    adjacency, volume and the render mesh, gated per plugin except for
    FO3/FNV sources, whose winding is random.
    See: docs/commentary/asset_convert_collision.md#winding-repair-steps
    See: docs/commentary/asset_convert_falloutnv.md#two-sided-welding
    """
    if not tris:
        return tris, 0

    authored_flip = _authored_flips(tris, authored_normals)
    if not (winding_fix_enabled() or is_fallout_source()):
        return _rewound(tris, authored_flip)

    verts, idx = _weld(tris, groups)
    flip, comps = _orient_components(idx)
    vdata = _visual_data(visual_tris)
    _apply_component_signs(comps, idx, verts, flip, vdata)
    _repair_inverted_walkables(tris, flip, verts, idx, vdata)
    return _rewound(tris, flip)
