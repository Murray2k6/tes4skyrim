"""Rigid Prn attachment: a static piece skinned onto one bone.

Oblivion attaches a helmet, shield or weapon with a `Prn` NiStringExtraData
naming an attach node; Skyrim has no such mechanism and expects real skinning.
So the piece gets a BSDismemberSkinInstance with a single bone at weight 1.0,
and its node transforms are baked into the vertices first so the bind pose is
the identity the skin solve assumes.

See: docs/commentary/asset_convert_armor.md#rigid-prn-skinning
"""

from asset_convert.nif.pyffi_monkey_patch import apply_patches
apply_patches()
from pyffi.formats.nif import NifFormat

from asset_convert.character.skyrim_overrides import (
    ARMOR_DEFAULT_BODY_PART, ARMOR_GEOMETRY_BODY_PARTS,
    OBLIVION_TO_SKYRIM_BONE_MAP)
from asset_convert.nif.nif_flags import NIF_FLAGS


def get_body_parts_for_geometry(geom_name: str, num_partitions: int) -> list[int]:
    """Return a list of BSDismemberSkinInstance body_part IDs, one per partition block.

    Body parts are inferred from substrings in the geometry name (lower-cased).
    When num_partitions > 1 and a multi-partition list is configured for the
    matched keyword, that list is used; otherwise the single body part is repeated.
    """
    lower = geom_name.lower()
    for keyword, single_bp, multi_bps in ARMOR_GEOMETRY_BODY_PARTS:
        if keyword in lower:
            if multi_bps is not None and num_partitions > 1:
                result = list(multi_bps)
                while len(result) < num_partitions:
                    result.append(result[-1])
                return result[:num_partitions]
            return [single_bp] * num_partitions
    return [ARMOR_DEFAULT_BODY_PART] * num_partitions


def get_prn_bone(root_node):
    """Return the 'Prn' NiStringExtraData value on a root node, or None."""
    ed_list = getattr(root_node, 'extra_data_list', None)
    if ed_list is None:
        return None
    for ed_idx in range(root_node.num_extra_data_list):
        ed = ed_list[ed_idx]
        if isinstance(ed, NifFormat.NiStringExtraData):
            ed_name = bytes(ed.name).rstrip(b'\x00').decode('latin-1',
                                                            errors='replace')
            if ed_name == 'Prn':
                return bytes(ed.string_data).rstrip(b'\x00').decode(
                    'latin-1', errors='replace')
    return None


def bake_root_transform_into_verts(root_node):
    """Bake ONLY the root node's own transform into the geometry verts.

    The per-geometry offset is left intact, unlike the sibling that flattens
    both -- skin_retarget still needs it to place a PRN piece.
    See: docs/commentary/asset_convert_armor.md#rigid-prn-skinning
    """
    root_m = root_node.get_transform()
    if root_m.is_identity():
        return
    rot = root_m.get_matrix_33()
    for block in list(root_node.tree()):
        if not isinstance(block, (NifFormat.NiTriShape, NifFormat.NiTriStrips)):
            continue
        gd = block.data
        if gd is None:
            continue
        for v in gd.vertices:
            nv = v * root_m
            v.x, v.y, v.z = nv.x, nv.y, nv.z
        if getattr(gd, 'has_normals', 0):
            for n in gd.normals:
                nn = n * rot
                n.x, n.y, n.z = nn.x, nn.y, nn.z
        try:
            gd.update_center_radius()
        except Exception:
            pass
    root_node.rotation.set_identity()
    root_node.translation.x = root_node.translation.y = 0.0
    root_node.translation.z = 0.0
    root_node.scale = 1.0


def bake_node_transforms_into_verts(root_node):
    """Bake each geometry's node-to-root transform PLUS the root's own
    transform into the vertex/normal data, then zero those transforms.

    Needed before rigid-skinning Prn-attached creature parts: skinned
    rendering ignores node transforms, but Oblivion applied them when
    parenting the part to the bone (doghead's root carries a real rotation).
    After baking, vertices are in bone-local space so an identity bind
    matrix is correct.
    """
    root_m = root_node.get_transform()
    for block in list(root_node.tree()):
        if not isinstance(block, (NifFormat.NiTriShape, NifFormat.NiTriStrips)):
            continue
        gd = block.data
        if gd is None:
            continue
        full = block.get_transform(root_node) * root_m
        rot = full.get_matrix_33()
        for v in gd.vertices:
            nv = v * full
            v.x, v.y, v.z = nv.x, nv.y, nv.z
        if getattr(gd, 'has_normals', 0):
            for n in gd.normals:
                nn = n * rot
                n.x, n.y, n.z = nn.x, nn.y, nn.z
        block.rotation.set_identity()
        block.translation.x = block.translation.y = block.translation.z = 0.0
        block.scale = 1.0
        try:
            gd.update_center_radius()
        except Exception:
            pass
    root_node.rotation.set_identity()
    root_node.translation.x = root_node.translation.y = 0.0
    root_node.translation.z = 0.0
    root_node.scale = 1.0


#: Body part -> its Oblivion attach bone. See: docs/commentary/asset_convert_armor.md#prn-bone-fallback
BODY_PART_FALLBACK_PRN_BONE = {
    131: 'Bip01 Head',
    33:  'Bip01 R Hand',
    37:  'Bip01 R Foot',
}


#: Prn bone name fragment -> biped slot.  First match in order wins.
_PRN_BONE_SLOTS = (
    (('head', 'neck'), 131),
    (('hand', 'finger'), 33),
    (('foot', 'toe'), 37),
    (('calf', 'thigh'), 38),
)


def _prn_body_part(prn_bone):
    """The biped slot a rigidly-attached piece on this bone belongs to.

    Vanilla Skyrim puts helmets on the HAIR slot, which is why a head bone
    maps to 131 rather than a head slot.
    """
    low = prn_bone.lower()
    for fragments, slot in _PRN_BONE_SLOTS:
        if any(f in low for f in fragments):
            return slot
    return ARMOR_DEFAULT_BODY_PART


def _insert_bone_node(root_node, prn_bone):
    """Add the named bone placeholder as the root's FIRST child.

    Vanilla Skyrim helmets carry the bone NiNode before their geometry.
    """
    bone_node = NifFormat.NiNode()
    bone_node.name = prn_bone.encode('latin-1')
    bone_node.flags = NIF_FLAGS
    old_count = root_node.num_children
    root_node.num_children = old_count + 1
    root_node.children.update_size()
    for ci in range(old_count, 0, -1):
        root_node.children[ci] = root_node.children[ci - 1]
    root_node.children[0] = bone_node
    return bone_node


def _rigid_skin_data(geom_data):
    """NiSkinData binding every vertex to one bone at weight 1.0.

    The bind is IDENTITY because the caller leaves the verts in bone-LOCAL
    space, so `vert . I . boneWorld` places the part and tracks the bone under
    animation and ragdoll.  The per-bone bounding sphere is the vertex bounds:
    the engine visibility-culls skinned geometry by it, and a zero radius is
    never visible in game even though NifSkope renders the mesh fine.
    See: docs/commentary/asset_convert_armor.md#rigid-prn-skinning
    """
    skin = NifFormat.NiSkinData()
    skin.skin_transform.rotation.m_11 = 1.0
    skin.skin_transform.rotation.m_22 = 1.0
    skin.skin_transform.rotation.m_33 = 1.0
    skin.skin_transform.scale = 1.0
    skin.num_bones = 1
    skin.bone_list.update_size()

    entry = skin.bone_list[0]
    entry.skin_transform.rotation.m_11 = 1.0
    entry.skin_transform.rotation.m_22 = 1.0
    entry.skin_transform.rotation.m_33 = 1.0
    entry.skin_transform.scale = 1.0
    num_verts = geom_data.num_vertices
    entry.num_vertices = num_verts
    entry.vertex_weights.update_size()
    for vi in range(num_verts):
        entry.vertex_weights[vi].index = vi
        entry.vertex_weights[vi].weight = 1.0

    verts = geom_data.vertices
    cx = (min(v.x for v in verts) + max(v.x for v in verts)) / 2.0
    cy = (min(v.y for v in verts) + max(v.y for v in verts)) / 2.0
    cz = (min(v.z for v in verts) + max(v.z for v in verts)) / 2.0
    entry.bounding_sphere_offset.x = cx
    entry.bounding_sphere_offset.y = cy
    entry.bounding_sphere_offset.z = cz
    entry.bounding_sphere_radius = max(
        ((v.x - cx) ** 2 + (v.y - cy) ** 2 + (v.z - cz) ** 2) ** 0.5
        for v in verts)
    return skin


def _rigid_skin_instance(root_node, bone_node, skin_data, body_part, plain):
    """The skin instance for a rigid part: plain for creatures, else dismember."""
    bsd = (NifFormat.NiSkinInstance() if plain
           else NifFormat.BSDismemberSkinInstance())
    bsd.skeleton_root = root_node
    bsd.data = skin_data
    bsd.skin_partition = None
    bsd.num_bones = 1
    bsd.bones.update_size()
    bsd.bones[0] = bone_node
    if not plain:
        bsd.num_partitions = 1
        bsd.partitions.update_size()
        bsd.partitions[0].body_part = body_part
        bsd.partitions[0].part_flag.pf_editor_visible = 1
        bsd.partitions[0].part_flag.pf_start_net_boneset = 1
    return bsd


def add_prn_skin(data, root_node, keep_bone_names=False, plain=False,
                  fallback_bone=None):
    """Skin rigidly-attached armor to its Prn bone; count the shapes done.

    Oblivion attaches helmets and the like to a bone through a `Prn`
    NiStringExtraData rather than skinning them, and Skyrim requires
    BSDismemberSkinInstance on all worn geometry.

    keep_bone_names keeps the ORIGINAL Oblivion bone name, for creature parts
    whose converted skeleton keeps Oblivion bones; plain builds a
    NiSkinInstance, which is what vanilla creature meshes use.
    See: docs/commentary/asset_convert_armor.md#rigid-prn-skinning
    """
    if not isinstance(root_node, NifFormat.NiNode):
        return 0
    prn_val = get_prn_bone(root_node) or fallback_bone
    if prn_val is None:
        return 0
    prn_bone = (prn_val if keep_bone_names
                else OBLIVION_TO_SKYRIM_BONE_MAP.get(prn_val, prn_val))

    bone_node = _insert_bone_node(root_node, prn_bone)
    body_part = _prn_body_part(prn_bone)

    skinned = 0
    for block in list(root_node.tree()):
        if not isinstance(block, (NifFormat.NiTriShape, NifFormat.NiTriStrips)):
            continue
        if getattr(block, 'skin_instance', None) is not None:
            continue
        geom_data = block.data
        if geom_data is None or geom_data.num_vertices == 0:
            continue
        block.skin_instance = _rigid_skin_instance(
            root_node, bone_node, _rigid_skin_data(geom_data), body_part,
            plain)
        skinned += 1
    return skinned


def _dismember_from(skin, geom_name):
    """A BSDismemberSkinInstance carrying `skin`'s bones and skeleton refs.

    Partition body parts come from the geometry name, and each partition takes
    vanilla's worn-armor part_flag (editor_visible | start_net_boneset = 257).
    """
    bsd = NifFormat.BSDismemberSkinInstance()
    bsd.skeleton_root = skin.skeleton_root
    bsd.data = skin.data
    bsd.skin_partition = skin.skin_partition
    bsd.num_bones = skin.num_bones
    bsd.bones.update_size()
    for idx in range(skin.num_bones):
        bsd.bones[idx] = skin.bones[idx]

    n_blocks = 0
    if skin.skin_partition is not None:
        n_blocks = skin.skin_partition.num_skin_partition_blocks
    body_parts = get_body_parts_for_geometry(geom_name, n_blocks)

    bsd.num_partitions = n_blocks
    bsd.partitions.update_size()
    for idx in range(n_blocks):
        bsd.partitions[idx].body_part = body_parts[idx]
        bsd.partitions[idx].part_flag.pf_editor_visible = 1
        bsd.partitions[idx].part_flag.pf_start_net_boneset = 1
    return bsd


def upgrade_skin_instances(data):
    """Convert NiSkinInstance -> BSDismemberSkinInstance for worn gear.

    Skyrim's character pipeline needs the body-part table to know which biped
    slot each partition covers; a plain NiSkinInstance never renders.
    See: docs/commentary/asset_convert_armor.md#nif-worn-armor-conversion
    """
    for root in data.roots:
        if root is None:
            continue
        for block in root.tree():
            if not isinstance(block, (NifFormat.NiTriShape,
                                      NifFormat.NiTriStrips)):
                continue
            skin = getattr(block, 'skin_instance', None)
            if skin is None or isinstance(
                    skin, NifFormat.BSDismemberSkinInstance):
                continue
            geom_name = bytes(block.name).rstrip(b'\x00').decode(
                'latin-1', errors='replace')
            block.skin_instance = _dismember_from(skin, geom_name)
