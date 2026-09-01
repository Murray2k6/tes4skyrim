"""Quadric-error-metric mesh decimation: pure numpy, no NIF knowledge.

The caller flattens a model into ONE welded vertex/triangle soup and hands it
here; `qem_decimate` collapses edges cheapest-first and returns the surviving
geometry.  Decimating a model as one welded topology is what keeps it
watertight -- shapes decimated independently leave a shared rim as a free
boundary to both, the two sides pick different survivors, and the gap is a
hole in the LOD.

`vertex_normals` and `compute_tangents` rebuild the attributes a collapse
invalidates.
See: docs/commentary/asset_convert_terrain.md#qem-decimation-tuning
"""

import heapq
import math
from typing import Optional, Tuple

import numpy as np

#: Position weld tolerance, game units.
WELD_EPS = 1e-3

#: Error floor: stop when a collapse would deviate this fraction of the diagonal.
MAX_DEV_FRAC = 0.25

#: Budget multiplier per unit of boundary-vertex fraction.
TOPO_BOUNDARY_WEIGHT = 6.0

#: Boundary-edge constraint quadric weight, multiplied by edge length squared.
_BOUNDARY_WEIGHT = 1.0

#: Hard cap on the stitch radius, in multiples of the model's median edge.
_STITCH_MAX_EDGE_MULT = 1.0

#: Proximity-stitch tolerance, as a fraction of the model diagonal.
_STITCH_FRAC = 0.008

#: Edge-length regularization, multiplied by mean face area.
_EDGE_LEN_REG = 0.5

#: Vertices a disconnected component may never fall below (a tetrahedron).
_COMP_MIN = 4

#: UV quantization when keying output vertices, in units of 1/4096.
_UV_QUANT = 4096


def is_boundary_fraction(verts: np.ndarray, tris: np.ndarray) -> float:
    """Share of welded vertices that sit on an open rim (0.0 - 1.0).

    Used to scale the decimation budget: rim vertices are pinned by the
    open-rim guard, so a model that is mostly rim has little collapsible
    interior and needs a larger budget to survive.
    """
    if len(verts) == 0 or len(tris) == 0:
        return 0.0
    keys = np.round(verts / WELD_EPS).astype(np.int64)
    uq, wid = np.unique(keys, axis=0, return_inverse=True)
    F = wid[tris]
    ok = (F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])
    F = F[ok]
    if not len(F):
        return 0.0
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    ue, c = np.unique(np.sort(e, axis=1), axis=0, return_counts=True)
    if not (c == 1).any():
        return 0.0
    return len(np.unique(ue[c == 1])) / max(len(uq), 1)


def _median_edge_length(P: np.ndarray, F: np.ndarray) -> float:
    """Median length of the unique edges of `F`, or 0.0 when there are none."""
    F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
    if not len(F):
        return 0.0
    ue = np.unique(np.sort(np.concatenate(
        [F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1), axis=0)
    return float(np.median(np.linalg.norm(P[ue[:, 0]] - P[ue[:, 1]], axis=1)))


def _stitch_radius(P: np.ndarray, F: np.ndarray) -> float:
    """Proximity-merge radius: model-relative, capped by the detail scale.

    See: docs/commentary/asset_convert_terrain.md#qem-stitch-pass
    """
    diag = float(np.linalg.norm(P.max(axis=0) - P.min(axis=0)))
    return max(WELD_EPS, min(diag * _STITCH_FRAC,
                             _median_edge_length(P, F) * _STITCH_MAX_EDGE_MULT))


def _union_find(n: int):
    """A `(find, parent)` pair over `n` elements, with path halving."""
    parent = list(range(n))

    def find(x):
        """The representative of x's set, halving the path on the way."""
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    return find, parent


def _stitch_close_nodes(P: np.ndarray, wid: np.ndarray, W: int,
                        eps: float) -> Tuple[np.ndarray, np.ndarray, int]:
    """Merge weld nodes closer than `eps`; returns (P, wid, W).

    The representative keeps its ORIGINAL position -- averaging the merged
    group would pull the surface off the silhouette.
    See: docs/commentary/asset_convert_terrain.md#qem-stitch-pass
    """
    try:
        from scipy.spatial import cKDTree
        pairs = cKDTree(P).query_pairs(eps, output_type='ndarray')
    except Exception:
        return P, wid, W
    if pairs is None or not len(pairs):
        return P, wid, W
    find, parent = _union_find(W)
    for a, b in pairs:
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[rb] = ra
    rep = np.array([find(i) for i in range(W)], dtype=np.int64)
    uniq_rep, remap = np.unique(rep, return_inverse=True)
    if len(uniq_rep) >= W:
        return P, wid, W
    return P[uniq_rep], remap[wid], len(uniq_rep)


def _face_quadrics(P: np.ndarray, F0: np.ndarray, W: int):
    """Area-weighted plane quadrics per weld node, plus twice each face area."""
    v0, v1, v2 = P[F0[:, 0]], P[F0[:, 1]], P[F0[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0)
    area2 = np.linalg.norm(fn, axis=1)
    nrm = fn / np.maximum(area2, 1e-12)[:, None]
    d = -np.einsum('ij,ij->i', nrm, v0)
    plane = np.concatenate([nrm, d[:, None]], axis=1)
    fq = plane[:, :, None] * plane[:, None, :] * area2[:, None, None]
    Q = np.zeros((W, 4, 4), np.float64)
    for k in range(3):
        np.add.at(Q, F0[:, k], fq)
    return Q, area2


def _add_boundary_quadrics(Q: np.ndarray, P: np.ndarray, boundary: np.ndarray):
    """Add constraint quadrics holding each open rim edge on its own line.

    The plane is spanned by the edge and the world axis least aligned with it.
    See: docs/commentary/asset_convert_terrain.md#qem-collapse-guards
    """
    ea, eb = boundary[:, 0], boundary[:, 1]
    edge_v = P[eb] - P[ea]
    ax = np.zeros_like(edge_v)
    ax[np.arange(len(edge_v)), np.argmin(np.abs(edge_v), axis=1)] = 1.0
    cn = np.cross(edge_v, ax)
    cl = np.linalg.norm(cn, axis=1)
    good = cl > 1e-12
    cn[good] /= cl[good][:, None]
    cd = -np.einsum('ij,ij->i', cn, P[ea])
    cplane = np.concatenate([cn, cd[:, None]], axis=1)
    w = _BOUNDARY_WEIGHT * np.einsum('ij,ij->i', edge_v, edge_v)
    cq = cplane[:, :, None] * cplane[:, None, :] * w[:, None, None]
    np.add.at(Q, ea, cq)
    np.add.at(Q, eb, cq)


def _weld(verts: np.ndarray, tris: np.ndarray, tri_mat):
    """Weld positions, stitch near-coincident nodes, drop degenerate faces.

    Returns `(P, W, F0, C0, M0)`: node positions, node count, faces in weld
    space, the original corner ids (which carry the UVs), and the per-face
    material tag.
    """
    keys = np.round(verts / WELD_EPS).astype(np.int64)
    _, first_idx, wid = np.unique(keys, axis=0, return_index=True,
                                  return_inverse=True)
    W = len(first_idx)
    P = verts[first_idx].astype(np.float64)

    eps = _stitch_radius(P, wid[tris])
    if W > 1 and eps > WELD_EPS:
        P, wid, W = _stitch_close_nodes(P, wid, W, eps)

    F0 = wid[tris]
    ok = ((F0[:, 0] != F0[:, 1]) & (F0[:, 1] != F0[:, 2])
          & (F0[:, 0] != F0[:, 2]))
    return (P, W, F0[ok], tris[ok],
            tri_mat[ok] if tri_mat is not None else None)


def _component_sizes(find, W: int, vert_faces: list) -> dict:
    """Live vertex count per connected component, keyed by its root."""
    sizes: dict = {}
    for w in range(W):
        if vert_faces[w]:
            r = find(w)
            sizes[r] = sizes.get(r, 0) + 1
    return sizes


class _Mesh:
    """Mutable half-edge state the collapse loop rewrites in place."""

    def __init__(self, P, W, F0, C0, M0, uvs, area2, Q):
        """Build the face/vertex adjacency and per-node quadric accumulators."""
        self.P, self.W, self.M0, self.Q = P, W, M0, Q
        self.PL = [tuple(map(float, p)) for p in P]
        self.faces = [[int(a), int(b), int(c)] for a, b, c in F0]
        self.face_alive = [True] * len(self.faces)
        self.vert_faces = [set() for _ in range(W)]
        for fi, f in enumerate(self.faces):
            for v in f:
                self.vert_faces[v].add(fi)
        self.version = [0] * W
        self.alive = sum(1 for s in self.vert_faces if s)
        self.corner_uv = self._chart_uvs(C0, uvs)
        self.A = np.zeros(W, np.float64)
        for k in range(3):
            np.add.at(self.A, F0[:, k], area2 / 6.0)
        self.mean_face_area = float(area2.mean()) / 2.0
        self.diag = float(np.linalg.norm(P.max(axis=0) - P.min(axis=0)))
        self._hom = np.ones(4)

    def _chart_uvs(self, C0, uvs):
        """Per-corner mutable UV slots, or None when the soup carries no UVs.

        See: docs/commentary/asset_convert_terrain.md#qem-uv-charts
        """
        if uvs is None:
            return None
        uvl = [(float(a), float(b)) for a, b in uvs]
        return [[uvl[int(C0[fi, k])] for k in range(3)]
                for fi in range(len(self.faces))]

    def cost_of(self, u, v):
        """Quadric error of collapsing u into v, plus length regularization."""
        self._hom[:3] = self.P[v]
        c = float(self._hom @ (self.Q[u] + self.Q[v]) @ self._hom)
        ux, uy, uz = self.PL[u]
        vx, vy, vz = self.PL[v]
        dx, dy, dz = ux - vx, uy - vy, uz - vz
        return c + (_EDGE_LEN_REG * self.mean_face_area
                    * (dx * dx + dy * dy + dz * dz))

    def flips(self, a, b, ox, oy, oz, nx_, ny_, nz_):
        """True if triangle (a, b, .) flips when its third vertex moves."""
        ax, ay, az = self.PL[a]
        bx, by, bz = self.PL[b]
        a1x, a1y, a1z = ax - ox, ay - oy, az - oz
        b1x, b1y, b1z = bx - ox, by - oy, bz - oz
        c1x = a1y * b1z - a1z * b1y
        c1y = a1z * b1x - a1x * b1z
        c1z = a1x * b1y - a1y * b1x
        a2x, a2y, a2z = ax - nx_, ay - ny_, az - nz_
        b2x, b2y, b2z = bx - nx_, by - ny_, bz - nz_
        c2x = a2y * b2z - a2z * b2y
        c2y = a2z * b2x - a2x * b2z
        c2z = a2x * b2y - a2y * b2x
        return (c1x * c2x + c1y * c2y + c1z * c2z) <= 0.0

    def neighbors(self, u):
        """Every weld node sharing a live face with `u`."""
        out = set()
        for fi in self.vert_faces[u]:
            out.update(self.faces[fi])
        out.discard(u)
        return out

    def uv_at(self, fi, i, u, v, cu):
        """UV for the corner of face `fi` that just moved from u to v.

        See: docs/commentary/asset_convert_terrain.md#qem-uv-charts
        """
        f = self.faces[fi]
        j, k = (i + 1) % 3, (i + 2) % 3
        ax, ay, az = self.PL[f[j]]
        bx, by, bz = self.PL[f[k]]
        ux, uy, uz = self.PL[u]
        vx, vy, vz = self.PL[v]
        ua_, ub_ = self.corner_uv[fi][j], self.corner_uv[fi][k]
        e1x, e1y, e1z = bx - ax, by - ay, bz - az
        e2x, e2y, e2z = ux - ax, uy - ay, uz - az
        d11 = e1x * e1x + e1y * e1y + e1z * e1z
        d12 = e1x * e2x + e1y * e2y + e1z * e2z
        d22 = e2x * e2x + e2y * e2y + e2z * e2z
        det = d11 * d22 - d12 * d12
        if -1e-20 <= det <= 1e-20:
            return cu
        dx, dy, dz = vx - ax, vy - ay, vz - az
        b1 = dx * e1x + dy * e1y + dz * e1z
        b2 = dx * e2x + dy * e2y + dz * e2z
        s = (b1 * d22 - b2 * d12) / det
        t_ = (d11 * b2 - d12 * b1) / det
        au, av = ua_
        return (au + s * (ub_[0] - au) + t_ * (cu[0] - au),
                av + s * (ub_[1] - av) + t_ * (cu[1] - av))


def _shares_an_edge(m: _Mesh, fi: int, nf: list, u: int, v: int,
                    dying: set) -> bool:
    """True if post-collapse face `nf` still shares an edge with a live face."""
    for a_, b_ in ((nf[0], nf[1]), (nf[1], nf[2]), (nf[2], nf[0])):
        for gi in m.vert_faces[a_]:
            if gi == fi or gi in dying or not m.face_alive[gi]:
                continue
            g = [v if w == u else w for w in m.faces[gi]]
            if a_ in g and b_ in g:
                return True
    return False


def _would_isolate(m: _Mesh, u: int, v: int, dying: set) -> bool:
    """True if collapsing u into v strands a surviving face with no neighbour.

    See: docs/commentary/asset_convert_terrain.md#qem-collapse-guards
    """
    for fi in m.vert_faces[u] | m.vert_faces[v]:
        if fi in dying or not m.face_alive[fi]:
            continue
        nf = [v if w == u else w for w in m.faces[fi]]
        if nf[0] == nf[1] or nf[1] == nf[2] or nf[0] == nf[2]:
            continue
        if not _shares_an_edge(m, fi, nf, u, v, dying):
            return True
    return False


def _would_flip(m: _Mesh, u: int, v: int) -> bool:
    """True if any face of u that survives the collapse would invert."""
    ux, uy, uz = m.PL[u]
    vx, vy, vz = m.PL[v]
    for fi in m.vert_faces[u]:
        f = m.faces[fi]
        if v in f:
            continue
        i = f.index(u)
        if m.flips(f[(i + 1) % 3], f[(i + 2) % 3], ux, uy, uz, vx, vy, vz):
            return True
    return False


def _apply_collapse(m: _Mesh, u: int, v: int) -> int:
    """Collapse u into v; returns how many THIRD vertices it stranded.

    See: docs/commentary/asset_convert_terrain.md#qem-stranded-verts
    """
    stranded = 0
    for fi in list(m.vert_faces[u]):
        f = m.faces[fi]
        if v in f:
            m.face_alive[fi] = False
            for w in f:
                had = bool(m.vert_faces[w])
                m.vert_faces[w].discard(fi)
                if had and not m.vert_faces[w] and w != u and w != v:
                    stranded += 1
            continue
        i = f.index(u)
        f[i] = v
        if m.corner_uv is not None:
            m.corner_uv[fi][i] = m.uv_at(fi, i, u, v, m.corner_uv[fi][i])
        m.vert_faces[v].add(fi)
    m.vert_faces[u].clear()
    m.Q[v] += m.Q[u]
    m.A[v] += m.A[u]
    m.version[u] += 1
    m.version[v] += 1
    return stranded


def _rejects(m: _Mesh, u: int, v: int, cost: float, max_dev2: float,
             is_boundary: np.ndarray, comp_alive: dict, cr: int) -> bool:
    """True when any collapse guard refuses this edge.

    See: docs/commentary/asset_convert_terrain.md#qem-collapse-guards
    """
    if cost > (m.A[u] + m.A[v]) * max_dev2 + 1e-12:
        return True
    if not any(v in m.faces[fi] for fi in m.vert_faces[u]):
        return True
    if is_boundary[u] and not is_boundary[v]:
        return True
    if comp_alive.get(cr, 0) <= _COMP_MIN:
        return True
    dying = {fi for fi in m.vert_faces[u] if v in m.faces[fi]}
    return _would_isolate(m, u, v, dying) or _would_flip(m, u, v)


def _seed_heap(m: _Mesh, uniq_e: np.ndarray) -> list:
    """A cost-ordered heap holding both directions of every unique edge."""
    heap = []
    for e in uniq_e:
        a, b = int(e[0]), int(e[1])
        heapq.heappush(heap, (m.cost_of(a, b), a, b, m.version[a],
                              m.version[b]))
        heapq.heappush(heap, (m.cost_of(b, a), b, a, m.version[b],
                              m.version[a]))
    return heap


def _components(m: _Mesh):
    """`(find, live-count-per-root)` over the mesh's connected components."""
    find, parent = _union_find(m.W)
    for f in m.faces:
        r0 = find(f[0])
        for k in (1, 2):
            rk = find(f[k])
            if rk != r0:
                parent[rk] = r0
    return find, _component_sizes(find, m.W, m.vert_faces)


def _collapse_loop(m: _Mesh, target: int, max_dev2: float,
                   is_boundary: np.ndarray, uniq_e: np.ndarray) -> None:
    """Collapse edges cheapest-first until the vertex budget is met.

    There is deliberately NO component-pruning fallback: overshooting the
    budget beats deleting parts of the model.
    See: docs/commentary/asset_convert_terrain.md#qem-no-component-pruning
    """
    find, comp_alive = _components(m)
    heap = _seed_heap(m, uniq_e)

    while m.alive > target and heap:
        cost, u, v, vu, vv = heapq.heappop(heap)
        if m.version[u] != vu or m.version[v] != vv:
            continue
        if not m.vert_faces[u] or not m.vert_faces[v]:
            continue
        if not math.isfinite(cost):
            continue
        cr = find(u)
        if _rejects(m, u, v, cost, max_dev2, is_boundary, comp_alive, cr):
            continue

        stranded = _apply_collapse(m, u, v) + 1
        m.alive -= stranded
        comp_alive[cr] = comp_alive.get(cr, 0) - stranded
        if not m.vert_faces[v]:
            m.alive -= 1
            comp_alive[cr] = comp_alive.get(cr, 0) - 1
            continue
        for nb in m.neighbors(v):
            heapq.heappush(heap, (m.cost_of(nb, v), nb, v, m.version[nb],
                                  m.version[v]))
            heapq.heappush(heap, (m.cost_of(v, nb), v, nb, m.version[v],
                                  m.version[nb]))


def _out_key(wnode: int, cu, mat: int):
    """Dedupe key for one output corner: node, quantized UV, material."""
    if cu is None:
        return (wnode, mat)
    return (wnode, round(cu[0] * _UV_QUANT), round(cu[1] * _UV_QUANT), mat)


def _rebuild(m: _Mesh, want_uv: bool, want_mat: bool):
    """Emit (verts, tris, uvs, tri_mat) keyed by (weld node, UV, material).

    The material is part of the key so the per-material split afterwards never
    merges or reindexes charts: two materials meeting at a welded seam share
    the POSITION while keeping separate output vertices.
    """
    out_map: dict = {}
    out_v: list = []
    out_uv: list = []
    out_t: list = []
    out_m: list = []
    for fi, f in enumerate(m.faces):
        if not m.face_alive[fi]:
            continue
        mat = int(m.M0[fi]) if m.M0 is not None else 0
        idx3 = []
        for k in range(3):
            cu = m.corner_uv[fi][k] if m.corner_uv is not None else None
            key = _out_key(f[k], cu, mat)
            j = out_map.get(key)
            if j is None:
                j = len(out_v)
                out_map[key] = j
                out_v.append(m.P[f[k]])
                if cu is not None:
                    out_uv.append(cu)
            idx3.append(j)
        if idx3[0] != idx3[1] and idx3[1] != idx3[2] and idx3[0] != idx3[2]:
            out_t.append(idx3)
            out_m.append(mat)

    if not out_t:
        return (np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int32),
                np.zeros((0, 2), np.float32) if want_uv else None,
                np.zeros((0,), np.int32) if want_mat else None)
    return (np.asarray(out_v, dtype=np.float32),
            np.asarray(out_t, dtype=np.int32),
            np.asarray(out_uv, dtype=np.float32) if want_uv else None,
            np.asarray(out_m, dtype=np.int32) if want_mat else None)


def qem_decimate(verts: np.ndarray, tris: np.ndarray,
                 uvs: Optional[np.ndarray],
                 target_verts: int,
                 max_dev_frac: float = MAX_DEV_FRAC,
                 tri_mat: Optional[np.ndarray] = None) -> Tuple:
    """Quadric-error-metric half-edge-collapse simplification.

    A collapse u->v moves u to v's exact original position, interpolates the
    moved corner's UV onto it, is charged the combined quadric error at v, and
    is refused by the boundary, component, isolation and flip guards.
    `tri_mat` tags each triangle with its source shape and is carried through
    unchanged, which is what lets a whole model be decimated as one topology.

    Returns (new_verts, new_tris, new_uvs, new_tri_mat).
    See: docs/commentary/asset_convert_terrain.md#qem-weld-seams
    """
    if len(verts) == 0 or len(tris) == 0:
        return verts, tris, uvs, tri_mat

    P, W, F0, C0, M0 = _weld(verts, tris, tri_mat)
    if not len(F0):
        return verts, tris, uvs, tri_mat

    Q, area2 = _face_quadrics(P, F0, W)
    edges = np.concatenate([F0[:, [0, 1]], F0[:, [1, 2]], F0[:, [2, 0]]])
    uniq_e, e_cnt = np.unique(np.sort(edges, axis=1), axis=0,
                              return_counts=True)
    boundary = uniq_e[e_cnt == 1]
    is_boundary = np.zeros(W, dtype=bool)
    if len(boundary):
        is_boundary[boundary.ravel()] = True
        _add_boundary_quadrics(Q, P, boundary)

    m = _Mesh(P, W, F0, C0, M0, uvs, area2, Q)
    _collapse_loop(m, max(int(target_verts), 4),
                   (m.diag * max_dev_frac) ** 2, is_boundary, uniq_e)
    return _rebuild(m, uvs is not None, tri_mat is not None)


def vertex_normals(verts: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Smooth per-vertex normals averaged from face normals."""
    n_out = np.zeros_like(verts)
    v0, v1, v2 = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0)
    d = np.linalg.norm(fn, axis=1, keepdims=True)
    d[d < 1e-10] = 1.0
    fn /= d
    for k in range(3):
        np.add.at(n_out, tris[:, k], fn)
    d2 = np.linalg.norm(n_out, axis=1, keepdims=True)
    d2[d2 < 1e-10] = 1.0
    return (n_out / d2).astype(np.float32)


def compute_tangents(verts: np.ndarray, tris: np.ndarray,
                     uvs: np.ndarray, normals: np.ndarray
                     ) -> Tuple[np.ndarray, np.ndarray]:
    """Per-vertex tangents and bitangents via UV differentials (Gram-Schmidt)."""
    tan1 = np.zeros_like(verts)
    v0, v1, v2 = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    uv0, uv1, uv2 = uvs[tris[:, 0]], uvs[tris[:, 1]], uvs[tris[:, 2]]

    dv1, dv2 = v1 - v0, v2 - v0
    duv1, duv2 = uv1 - uv0, uv2 - uv0

    denom = duv1[:, 0] * duv2[:, 1] - duv2[:, 0] * duv1[:, 1]
    with np.errstate(divide='ignore', invalid='ignore'):
        r = np.where(np.abs(denom) > 1e-10, 1.0 / denom, 0.0)

    t_face = r[:, None] * (duv2[:, 1:2] * dv1 - duv1[:, 1:2] * dv2)
    for k in range(3):
        np.add.at(tan1, tris[:, k], t_face)

    nT = np.einsum('ij,ij->i', normals, tan1)[:, None]
    t_ortho = tan1 - nT * normals
    d_t = np.linalg.norm(t_ortho, axis=1, keepdims=True)
    d_t[d_t < 1e-10] = 1.0
    tangents = (t_ortho / d_t).astype(np.float32)
    return tangents, np.cross(normals, tangents).astype(np.float32)
