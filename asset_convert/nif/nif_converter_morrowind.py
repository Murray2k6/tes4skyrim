"""Morrowind mesh fixups: the RootCollisionNode idiom, and helper nodes.

Morrowind carries no Havok data at all. Collision is a plain triangle mesh
parked under a `RootCollisionNode`, which the engine consumes and never draws;
a mesh without one gets collision built from its render geometry instead
(`references/openmw/components/nifbullet/bulletnifloader.cpp:171`). Left alone
the node ships as *visible* geometry and the object has no collision in Skyrim,
so both halves of that rule have to be reproduced here.

Detection is by BLOCK TYPE, never by name: pyffi reads the node as its own
`RootCollisionNode` class exactly as the engine registers it
(`references/openmw/components/nif/niffile.cpp:68`), and the 217 such nodes in
a strided sample of the corpus all carry an EMPTY name string.

See: docs/commentary/asset_convert_nif.md#morrowind-collision
"""

from pyffi.formats.nif import NifFormat

from asset_convert.collision.cms_builder import build_cms_collision

#: Game units to Skyrim havok units; bare, not collision.py's `/7.0`.
_HAVOK_SCALE = 0.1

#: SKY_HAV_MAT_STONE, the fallback for a material Morrowind never records.
_SKY_MAT_STONE = 3741512247

#: The biggest real collision mesh in the sampled corpus is 2,219 triangles.
_MAX_COLLISION_TRIS = 20000

#: Helper nodes Morrowind uses that must never reach Skyrim as geometry.
_HELPER_TYPES = ('AvoidNode',)

#: Skin partition limits; the values every vanilla Skyrim partition uses.
_MAX_BONES_PER_PARTITION = 4
_MAX_WEIGHTS_PER_VERTEX = 4


def is_collision_node(block) -> bool:
    """Whether this block is Morrowind's RootCollisionNode.

    See: docs/commentary/asset_convert_nif.md#morrowind-collision
    """
    return type(block).__name__ == 'RootCollisionNode'


def find_collision_node(root):
    """The RootCollisionNode the engine would use, or None.

    Direct children only and searched in REVERSE, matching
    `NiNode::findRootCollisionNode` (`references/openmw/components/nif/
    node.cpp:209`), whose recursive mode is opt-in via an "RCN" string extra.
    Every one of the 217 found in the corpus is a direct child anyway.
    """
    for child in reversed(list(getattr(root, 'children', None) or [])):
        if child is not None and is_collision_node(child):
            return child
    return None


def collision_triangles(node, scale: float = _HAVOK_SCALE) -> list:
    """Every triangle under `node`, in Skyrim havok units in the root frame.

    Returns [] when the subtree holds no usable geometry, which the engine
    treats as "collide with camera only" and we treat as no collision.
    """
    out = []
    for block in node.tree():
        if not isinstance(block, NifFormat.NiTriBasedGeom):
            continue
        data = block.data
        if data is None:
            continue
        verts = _transformed_verts(block, node, data, scale)
        for a, b, c in data.get_triangles():
            if a != b and b != c and a != c:
                out.append((verts[a], verts[b], verts[c]))
        if len(out) > _MAX_COLLISION_TRIS:
            return []
    return out


def _transformed_verts(block, root, data, scale: float) -> list:
    """This shape's vertices in the root's frame, scaled to havok units."""
    m = block.get_transform(root)
    out = []
    for v in data.vertices:
        x = v.x * m.m_11 + v.y * m.m_21 + v.z * m.m_31 + m.m_41
        y = v.x * m.m_12 + v.y * m.m_22 + v.z * m.m_32 + m.m_42
        z = v.x * m.m_13 + v.y * m.m_23 + v.z * m.m_33 + m.m_43
        out.append((x * scale, y * scale, z * scale))
    return out


def build_collision(root, tris):
    """A static bhkCollisionObject over `tris`, or None when it cannot build.

    The rigid body is the vanilla static block SpeedTree already establishes
    for a generated CMS: identity transform, mass 0, and the collision layer
    every immovable object uses.
    See: docs/commentary/asset_convert_nif.md#morrowind-collision
    """
    mopp = build_cms_collision(tris, _SKY_MAT_STONE, NifFormat)
    if mopp is None:
        return None
    mopp.shape.target = root

    body = NifFormat.bhkRigidBody()
    body.shape = mopp
    body.mass = 0.0
    body.friction = 0.5
    body.restitution = 0.4
    body.linear_damping = 0.0996
    body.angular_damping = 0.0498
    body.max_linear_velocity = 104.4
    body.max_angular_velocity = 31.57
    body.motion_system = 5
    body.quality_type = 0
    body.deactivator_type = 1
    body.havok_col_filter.layer = 1
    body.havok_col_filter_copy.layer = 1
    body.unknown_int_2 = 1
    body.unknown_3_ints[2] = -2147483648
    body.unknown_byte = 116
    body.unknown_time_factor_or_gravity_factor_1 = 1.0
    body.unknown_time_factor_or_gravity_factor_2 = 1.0

    obj = NifFormat.bhkCollisionObject()
    obj.flags = 129
    obj.target = root
    obj.body = body
    return obj


def _strip_children(root, doomed) -> int:
    """Drop `doomed` children from `root`, compacting the array."""
    keep = [c for c in root.children if c is not None and id(c) not in doomed]
    if len(keep) == root.num_children:
        return 0
    dropped = root.num_children - len(keep)
    root.num_children = len(keep)
    root.children.update_size()
    for i, child in enumerate(keep):
        root.children[i] = child
    return dropped


def convert_morrowind_collision(root, stats=None) -> bool:
    """Turn Morrowind's collision idiom into Skyrim collision on `root`.

    The node is consumed and stripped either way: it must never render. When
    it holds no geometry the engine collides with the camera only, which has
    no Skyrim equivalent, so the object simply ships without collision.
    """
    node = find_collision_node(root)
    if node is None:
        return False
    tris = collision_triangles(node)
    built = False
    if tris and getattr(root, 'collision_object', None) is None:
        obj = build_collision(root, tris)
        if obj is not None:
            root.collision_object = obj
            built = True
    _strip_children(root, {id(node)})
    if stats is not None:
        stats['mw_collision_built'] = \
            stats.get('mw_collision_built', 0) + int(built)
        stats['mw_collision_stripped'] = \
            stats.get('mw_collision_stripped', 0) + 1
    return built


def strip_helper_nodes(root, stats=None) -> int:
    """Remove the Morrowind-only helper nodes Skyrim would draw.

    AvoidNode marks geometry the pathing system routes around; it is not
    renderable content (`bulletnifloader.cpp:233`).
    """
    doomed = {id(c) for c in (getattr(root, 'children', None) or [])
              if c is not None and type(c).__name__ in _HELPER_TYPES}
    if not doomed:
        return 0
    dropped = _strip_children(root, doomed)
    if stats is not None and dropped:
        stats['mw_helpers_stripped'] = \
            stats.get('mw_helpers_stripped', 0) + dropped
    return dropped


def raise_triangle_flags(data, stats=None) -> int:
    """Set `has_triangles` on shapes that carry triangles but declare none.

    Returns the number of shapes fixed. Emptiness is judged on the ARRAY,
    never on the flag, which does not exist below 10.1.0.0.
    See: docs/commentary/asset_convert_nif.md#morrowind-triangle-flag
    """
    fixed = 0
    for block in data.blocks:
        tris = getattr(block, 'triangles', None)
        if not tris or getattr(block, 'has_triangles', True):
            continue
        block.has_triangles = True
        block.num_triangles = len(tris)
        block.num_triangle_points = len(tris) * 3
        fixed += 1
    if stats is not None and fixed:
        stats['mw_triangle_flags'] = stats.get('mw_triangle_flags', 0) + fixed
    return fixed


def build_skin_partitions(data, stats=None) -> int:
    """Give every skinned shape the NiSkinPartition Skyrim renders from.

    Returns the number of shapes partitioned. NiSkinPartition postdates
    4.0.0.2, so no Morrowind mesh carries one and the renderer dereferences
    the null. The partition is MOVED onto the NiSkinInstance, where Skyrim
    reads it; pyffi's builder leaves it on the NiSkinData instead.
    See: docs/commentary/asset_convert_nif.md#morrowind-skin-partitions
    """
    built = 0
    for block in data.blocks:
        if not isinstance(block, NifFormat.NiTriBasedGeom):
            continue
        skin = block.skin_instance
        if skin is None or skin.data is None:
            continue
        if getattr(skin, 'skin_partition', None) is not None:
            continue
        try:
            block.update_skin_partition(
                maxbonesperpartition=_MAX_BONES_PER_PARTITION,
                maxbonespervertex=_MAX_WEIGHTS_PER_VERTEX,
                stripify=False, padbones=False, verbose=0)
        except Exception:
            if stats is not None:
                stats['mw_skin_failed'] = stats.get('mw_skin_failed', 0) + 1
            continue
        partition = getattr(skin.data, 'skin_partition', None)
        if partition is None:
            continue
        skin.skin_partition = partition
        skin.data.skin_partition = None
        built += 1
    if stats is not None and built:
        stats['mw_skin_partitions'] = \
            stats.get('mw_skin_partitions', 0) + built
    return built




def run_morrowind_fixups(data, stats=None) -> None:
    """Apply every Morrowind-only repair, before the version upgrade runs."""
    raise_triangle_flags(data, stats)
    for root in data.roots:
        if not hasattr(root, 'children'):
            continue
        strip_helper_nodes(root, stats)
        convert_morrowind_collision(root, stats)


def is_morrowind(data) -> bool:
    """Whether this NIF came from Morrowind rather than a later game."""
    return 0 < getattr(data, 'version', 0) <= 0x04000002
