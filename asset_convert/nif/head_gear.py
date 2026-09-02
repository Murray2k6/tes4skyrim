"""Ground models, and fitting rigid head gear onto the Skyrim skull.

A `_gnd` mesh is the dropped-item variant and takes the world-object path, not
the worn one; telling the two apart from the filename is the whole of the first
half. The second half measures a helmet or hood onto the target head rather
than scaling it, because a scale that fits the crown never fits the jaw.

See: docs/commentary/asset_convert_armor.md#head-gear-fit
"""

import numpy as np

from asset_convert.nif.pyffi_monkey_patch import apply_patches
apply_patches()
from pyffi.formats.nif import NifFormat

from asset_convert.character import head_fit
from asset_convert.character.skyrim_overrides import (
    OBLIVION_TO_SKYRIM_BONE_MAP)


def is_ground_model(nif_basename: str) -> bool:
    """Is this an armor/clothing ground (inventory) model?

    See: docs/commentary/asset_convert_armor.md#nif-armor-ground-model-conversion
    """
    return nif_basename.endswith('gnd.nif')


def strip_gnd_skin(data):
    """Strip NiSkinInstance from _gnd ground-model files.

    Leaves vertices in their bind pose, the correct rest pose for a static
    ground display model.
    See: docs/commentary/asset_convert_armor.md#nif-armor-ground-model-conversion
    """
    for root in data.roots:
        if root is None:
            continue
        for block in root.tree():
            if isinstance(block, (NifFormat.NiTriShape, NifFormat.NiTriStrips)):
                skin = getattr(block, 'skin_instance', None)
                if skin is not None and not isinstance(skin, NifFormat.BSDismemberSkinInstance):
                    block.skin_instance = None


#: Bones marking a Prn piece as HEAD gear; the Oblivion name is accepted defensively.
_PRN_HEAD_BONES = (b'NPC Head [Head]', b'Bip01 Head')


def collect_prn_head_blocks(data, prn_block_ids):
    """The Prn blocks of a NIF that hang on the HEAD bone.

    Walks the LIVE tree, never data.blocks: the strips->shape conversion
    replaces geometry objects, so data.blocks is stale by this point and an
    id() lookup over it silently matches nothing (the fit then never ran and
    every helmet fell back to the legacy PRN scale table).
    """
    blocks = []
    seen = set()
    for root in data.roots:
        if root is None:
            continue
        for block in root.tree():
            if id(block) not in prn_block_ids or id(block) in seen:
                continue
            if not isinstance(block, (NifFormat.NiTriShape,
                                      NifFormat.NiTriStrips)):
                continue
            skin = getattr(block, 'skin_instance', None)
            if skin is None or skin.num_bones < 1 or skin.bones[0] is None:
                continue
            name = bytes(skin.bones[0].name or b'')
            if name not in _PRN_HEAD_BONES:
                continue
            gd = block.data
            if gd is None or gd.num_vertices == 0:
                continue
            seen.add(id(block))
            blocks.append(block)
    return blocks


def fit_prn_head_blocks(data, prn_block_ids, src_path, race=None) -> set:
    """Fit head-attached Prn blocks onto the Skyrim head; the ids fitted.

    Runs AFTER retarget, solving all head blocks as ONE system so multi-shape
    helmets keep their seams. `race` selects a beast head pack; None fits the
    shared human head. Empty when the fit data is unavailable -- callers then
    fall back to the legacy constants.
    See: docs/commentary/asset_convert_armor.md#head-gear-fit
    """
    female = '/f/' in str(src_path).replace('\\', '/').lower()
    if not head_fit.fit_available(female):
        return set()

    blocks = collect_prn_head_blocks(data, prn_block_ids)
    if not blocks:
        return set()

    shapes = []
    for block in blocks:
        gd = block.data
        verts = np.array([[v.x, v.y, v.z] for v in gd.vertices],
                         dtype=np.float64)
        try:
            tris = np.array([tuple(t) for t in gd.get_triangles()],
                            dtype=np.int64)
        except Exception:
            tris = np.zeros((0, 3), dtype=np.int64)
        if tris.size == 0:
            tris = np.zeros((0, 3), dtype=np.int64)
        shapes.append((verts, tris))

    fitted = head_fit.fit_head_gear(shapes, female, race=race)
    if fitted is None:
        return set()
    for block, new_v in zip(blocks, fitted):
        gd = block.data
        for i, v in enumerate(gd.vertices):
            v.x = float(new_v[i, 0])
            v.y = float(new_v[i, 1])
            v.z = float(new_v[i, 2])
        try:
            gd.update_center_radius()
        except Exception:
            pass
    return {id(b) for b in blocks}


def remap_bone_names(data) -> int:
    """Rename Oblivion Bip01 skeleton bones to Skyrim NPC skeleton names.

    Skyrim's character skeleton uses fully qualified node names with bracket
    tags (e.g. 'NPC Spine1 [Spn1]') that differ from Oblivion's Bip01 rig.
    Any NiNode in the tree whose name is in OBLIVION_TO_SKYRIM_BONE_MAP is
    renamed in-place so the game's skin deformation system can find the bones.
    Returns the number of bones that were renamed.
    """
    count = 0
    for root in data.roots:
        if root is None:
            continue
        for block in root.tree():
            if isinstance(block, NifFormat.NiNode):
                raw = bytes(block.name).rstrip(b'\x00')
                name = raw.decode('latin-1', errors='replace')
                mapped = OBLIVION_TO_SKYRIM_BONE_MAP.get(name)
                if mapped:
                    block.name = mapped.encode('latin-1')
                    count += 1
    return count
