"""FO3/FNV dismemberment gore caps, kept hidden as the FO3 engine loads them.

FO3/FNV hide BSDismemberSkinInstance partitions typed 101-113 (section caps)
and 201-213 (torso caps) at load and reveal one when a limb comes off.
Skyrim has no limb dismemberment and the converter rebuilds partitions from
the wearing record's slot, so the caps would render permanently; the hidden
bit keeps them off and the geometry prep carries it through.

See: docs/commentary/asset_convert_falloutnv.md#dismemberment-gore-caps
"""

from pyffi.formats.nif import NifFormat

from asset_convert.nif.nif_flags import NIF_FLAG_HIDDEN

#: BSDismemberBodyPartType values FO3/FNV hide until that limb is severed.
_CAP_RANGE = range(100, 1000)


def _cap_triangle_share(skin) -> float:
    """Fraction of a dismember skin's triangles that lie in cap partitions."""
    parts = [int(p.body_part) for p in skin.partitions]
    blocks = (list(skin.skin_partition.skin_partition_blocks)
              if skin.skin_partition is not None else [])
    if len(blocks) != len(parts):
        return sum(bp in _CAP_RANGE for bp in parts) / len(parts) if parts else 0.0
    total = sum(int(b.num_triangles) for b in blocks)
    caps = sum(int(b.num_triangles) for bp, b in zip(parts, blocks)
               if bp in _CAP_RANGE)
    return caps / total if total else 0.0


def hide_dismember_caps(data) -> int:
    """Set the hidden bit on every gore-cap shape; the number hidden.

    A shape is a cap when at least half its triangles sit in cap partitions.
    See: docs/commentary/asset_convert_falloutnv.md#dismemberment-gore-caps
    """
    hidden = 0
    for root in data.roots:
        if root is None:
            continue
        for block in root.tree():
            skin = getattr(block, 'skin_instance', None)
            if not isinstance(skin, NifFormat.BSDismemberSkinInstance):
                continue
            if _cap_triangle_share(skin) >= 0.5:
                block.flags = int(block.flags) | NIF_FLAG_HIDDEN
                hidden += 1
    return hidden
