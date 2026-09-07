"""FO3/FNV collision rules that differ from Oblivion's.

FO3/FNV ignores a NIF root's rotation as Skyrim does, its packed triangle
winding is random so the render mesh decides it, its collision layers are
Skyrim's own below 29, and a static collection hangs one fixed body per
part off scaled child nodes.
See: docs/commentary/asset_convert_falloutnv.md#collision-rules
"""

from pyffi.formats.nif import NifFormat

#: user_version_2 stamped on every FO3/FNV NIF.
FALLOUT_USER_VERSION_2 = 34

#: FO3 hkMotionType for a static element of the scene.
_MO_SYS_FIXED = 7

#: FO3: one havok unit is this many game units.
_GAME_UNITS_PER_HAVOK = 7.0

#: Whether the NIF now converting came from FO3/FNV; latched per NIF.
_SOURCE = [False]

#: FO3 layer -> Skyrim layer where the enums disagree; 0-28 are identical.
_FO3_TO_SKY_LAYER = {
    29: 32,   # DEADBIP
    31: 34,   # AVOIDBOX
    32: 35,   # COLLISIONBOX
    33: 36,   # CAMERASPHERE
    34: 37,   # DOORDETECTION
    35: 39,   # CAMERAPICK
    36: 40,   # ITEMPICK
    37: 41,   # LINEOFSIGHT
    38: 42,   # PATHPICK
    39: 43,   # CUSTOMPICK1
    40: 44,   # CUSTOMPICK2
    41: 45,   # SPELLEXPLOSION
    42: 46,   # DROPPINGPICK
    43: 0,    # NULL
}


def latch_source(data):
    """Record the source game of `data` before the Skyrim version is stamped."""
    _SOURCE[0] = int(getattr(data, 'user_version_2', 0)) == FALLOUT_USER_VERSION_2


def is_fallout_source() -> bool:
    """True while an FO3/FNV mesh is converting."""
    return _SOURCE[0]


def fo3_layer(value: int) -> int:
    """The Skyrim collision layer for an FO3 layer value.

    See: docs/commentary/asset_convert_falloutnv.md#fo3-layers
    """
    return _FO3_TO_SKY_LAYER.get(int(value), int(value))


def _packed_shape(body):
    """The bhkPackedNiTriStripsShape under a fixed rigid body, else None."""
    if not isinstance(body, NifFormat.bhkRigidBody) \
            or int(body.motion_system) != _MO_SYS_FIXED:
        return None
    shape = body.shape
    if isinstance(shape, NifFormat.bhkMoppBvTreeShape):
        shape = shape.shape
    if isinstance(shape, NifFormat.bhkPackedNiTriStripsShape) \
            and shape.data is not None:
        return shape
    return None


def _body_frame(body):
    """(rotate(v), translation) of a body: identity for a plain bhkRigidBody."""
    if not isinstance(body, NifFormat.bhkRigidBodyT):
        return (lambda v: v), (0.0, 0.0, 0.0)
    q = body.rotation
    x, y, z, w = q.x, q.y, q.z, q.w

    def rotate(v):
        """Rotate v by the unit quaternion (x, y, z, w)."""
        tx = 2.0 * (y * v[2] - z * v[1])
        ty = 2.0 * (z * v[0] - x * v[2])
        tz = 2.0 * (x * v[1] - y * v[0])
        return (v[0] + w * tx + (y * tz - z * ty),
                v[1] + w * ty + (z * tx - x * tz),
                v[2] + w * tz + (x * ty - y * tx))
    t = body.translation
    return rotate, (t.x, t.y, t.z)


def _part_vertices_in_root(node, root, body, shape):
    """Part vertices in the root frame, havok units.

    The engine applies the node scale to the shape only; the body translation
    is already scaled, the GECK wrote it that way.
    See: docs/commentary/asset_convert_falloutnv.md#static-collection-parts
    """
    scale, rot, trans = node.get_transform(root).get_scale_rotation_translation()
    rotate, tb = _body_frame(body)
    out = []
    for v in shape.data.vertices:
        r = rotate((v.x, v.y, v.z))
        b = NifFormat.Vector3()
        b.x, b.y, b.z = (r[0] * scale + tb[0], r[1] * scale + tb[1],
                         r[2] * scale + tb[2])
        w = b * rot
        out.append((w.x + trans.x / _GAME_UNITS_PER_HAVOK,
                    w.y + trans.y / _GAME_UNITS_PER_HAVOK,
                    w.z + trans.z / _GAME_UNITS_PER_HAVOK))
    return out


def _collect_parts(root):
    """[(node, collision_object, packed_shape)] for every descendant collision object.

    None when any descendant collision object is not a fixed packed part.
    """
    parts = []
    stack = [root]
    while stack:
        node = stack.pop()
        for child in getattr(node, 'children', []):
            if child is None:
                continue
            co = getattr(child, 'collision_object', None)
            if co is not None:
                shape = _packed_shape(getattr(co, 'body', None))
                if shape is None:
                    return None
                parts.append((child, co, shape))
            stack.append(child)
    return parts


def _write_packed(shape, verts, tris):
    """Replace a packed shape's geometry with the merged (verts, tris)."""
    data = shape.data
    data.num_vertices = len(verts)
    data.vertices.update_size()
    for dst, (x, y, z) in zip(data.vertices, verts):
        dst.x, dst.y, dst.z = x, y, z
    data.num_triangles = len(tris)
    data.triangles.update_size()
    for dst, (a, b, c) in zip(data.triangles, tris):
        dst.triangle.v_1, dst.triangle.v_2, dst.triangle.v_3 = a, b, c
        dst.welding_info = 0
    for owner in (shape, data):
        if getattr(owner, 'num_sub_shapes', 0) == 1:
            owner.sub_shapes[0].num_vertices = len(verts)


def merge_static_parts(root) -> bool:
    """Bake every fixed packed part under `root` into one root collision object.

    True when the root now carries the merged collision; False leaves the
    tree untouched for the Oblivion hoist.
    See: docs/commentary/asset_convert_falloutnv.md#static-collection-parts
    """
    parts = _collect_parts(root)
    if not parts:
        return False
    verts, tris = [], []
    for node, co, shape in parts:
        base = len(verts)
        verts.extend(_part_vertices_in_root(node, root, co.body, shape))
        tris.extend((base + t.triangle.v_1, base + t.triangle.v_2,
                     base + t.triangle.v_3) for t in shape.data.triangles)
        node.collision_object = None
    _node, co, shape = parts[0]
    _write_packed(shape, verts, tris)
    body = co.body
    body.__class__ = NifFormat.bhkRigidBody
    body.rotation.x = body.rotation.y = body.rotation.z = 0.0
    body.rotation.w = 1.0
    body.translation.x = body.translation.y = body.translation.z = 0.0
    body.shape = shape
    co.target = root
    root.collision_object = co
    return True
