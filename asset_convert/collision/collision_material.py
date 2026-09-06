"""Oblivion havok material enums -> Skyrim CRC material values.

Split out of collision.py.  Oblivion stores a material as a small enum index;
Skyrim stores a CRC of the material's name.  Values <= 31 are Oblivion
indices and anything larger is already a Skyrim CRC, which makes the
conversion idempotent -- safe to call on a partially converted tree.
"""

OB_TO_SK_MATERIAL = {
    0:  3741512247,  # Stone            → SKY_HAV_MAT_STONE
    1:  3839073443,  # Cloth            → SKY_HAV_MAT_CLOTH
    2:  3106094762,  # Dirt             → SKY_HAV_MAT_DIRT
    3:  3739830338,  # Glass            → SKY_HAV_MAT_GLASS
    4:  1848600814,  # Grass            → SKY_HAV_MAT_GRASS
    5:  1288358971,  # Metal            → SKY_HAV_MAT_SOLID_METAL
    6:  2974920155,  # Organic          → SKY_HAV_MAT_ORGANIC
    7:  591247106,   # Skin             → SKY_HAV_MAT_SKIN
    8:  1024582599,  # Water            → SKY_HAV_MAT_WATER
    9:  500811281,   # Wood             → SKY_HAV_MAT_WOOD
    10: 1570821952,  # Heavy Stone      → SKY_HAV_MAT_HEAVY_STONE
    11: 2229413539,  # Heavy Metal      → SKY_HAV_MAT_HEAVY_METAL
    12: 3070783559,  # Heavy Wood       → SKY_HAV_MAT_HEAVY_WOOD
    13: 3074114406,  # Chain            → SKY_HAV_MAT_MATERIAL_CHAIN
    14: 398949039,   # Snow             → SKY_HAV_MAT_SNOW
    15: 899511101,   # Stone Stairs     → SKY_HAV_MAT_STAIRS_STONE
    16: 1461712277,  # Cloth Stairs     → SKY_HAV_MAT_STAIRS_WOOD (carpeted)
    17: 899511101,   # Dirt Stairs      → SKY_HAV_MAT_STAIRS_STONE
    18: 880200008,   # Glass Stairs     → SKY_HAV_MAT_STAIRS_GLASS
    19: 899511101,   # Grass Stairs     → SKY_HAV_MAT_STAIRS_STONE
    20: 899511101,   # Metal Stairs     → SKY_HAV_MAT_STAIRS_STONE (no metal stairs)
    21: 1461712277,  # Organic Stairs   → SKY_HAV_MAT_STAIRS_WOOD
    22: 1461712277,  # Skin Stairs      → SKY_HAV_MAT_STAIRS_WOOD
    23: 899511101,   # Water Stairs     → SKY_HAV_MAT_STAIRS_STONE
    24: 1461712277,  # Wood Stairs      → SKY_HAV_MAT_STAIRS_WOOD
    25: 899511101,   # Heavy Stone Strs → SKY_HAV_MAT_STAIRS_STONE
    26: 899511101,   # Heavy Metal Strs → SKY_HAV_MAT_STAIRS_STONE
    27: 1461712277,  # Heavy Wood Strs  → SKY_HAV_MAT_STAIRS_WOOD
    28: 899511101,   # Chain Stairs     → SKY_HAV_MAT_STAIRS_STONE
    29: 1560365355,  # Snow Stairs      → SKY_HAV_MAT_STAIRS_SNOW
    30: 1288358971,  # Elevator         → SKY_HAV_MAT_SOLID_METAL
    31: 2974920155,  # Rubber           → SKY_HAV_MAT_ORGANIC
}


def set_havok_material(hm, value):
    """Write `value` raw into every material item of a HavokMaterial.

    See: docs/commentary/asset_convert_collision.md#havok-material-crc
    """
    for it in getattr(hm, '_items', []):
        if it.__class__.__name__.endswith('HavokMaterial'):
            it._value = int(value)


def get_havok_material(hm):
    """Return the raw material int stored in a HavokMaterial struct."""
    for it in getattr(hm, '_items', []):
        if it.__class__.__name__.endswith('HavokMaterial'):
            return int(it.get_value())
    return 0


def convert_materials(shape, _seen=None):
    """Recursively map Oblivion material enums to Skyrim CRC values.

    Idempotent: a value over 31 is already a CRC and is left alone.
    See: docs/commentary/asset_convert_collision.md#havok-material-crc
    """
    if shape is None:
        return
    if _seen is None:
        _seen = set()
    if id(shape) in _seen:
        return
    _seen.add(id(shape))

    hm = getattr(shape, 'material', None)
    if hm is not None and hasattr(hm, '_items'):
        cur = get_havok_material(hm)
        if 0 <= cur <= 31:
            set_havok_material(hm, OB_TO_SK_MATERIAL.get(cur, 3741512247))

    for attr in ('shape',):
        convert_materials(getattr(shape, attr, None), _seen)
    for list_attr in ('sub_shapes',):
        subs = getattr(shape, list_attr, None)
        if subs is not None:
            for s in subs:
                convert_materials(s, _seen)
    data = getattr(shape, 'data', None)
    if data is not None:
        subs = getattr(data, 'sub_shapes', None)
        if subs is not None:
            for s in subs:
                convert_materials(s, _seen)
