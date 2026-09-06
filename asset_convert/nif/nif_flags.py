"""NIF flag and enum constants shared across the mesh converter.

`NIF_FLAGS` is the per-node value; the `BSX_FLAGS_*` set is the root bitfield
that gates havok, animation and ragdoll handling, named after the object class
each combination serves; `TT_*` are the texture-transform operations.

These are object-side constants -- doors, clutter and signs -- so they live
beside the mesh converter that writes them rather than with the wearable and
body-slot tables.
"""

#: Standard Skyrim NiAVObject flags (SelectiveUpdate bits 1-3).
NIF_FLAGS = 14

#: NiAVObject "hidden" bit; means the same thing in TES4, FO3/FNV and Skyrim.
NIF_FLAG_HIDDEN = 0x0001

#: Static objects with collision: complex + havok.
BSX_FLAGS_STATIC = 0x82

#: Dynamic clutter (mass > 0): adds the rigid-body bit.
BSX_FLAGS_DYNAMIC = 0xC2

#: Animated objects -- doors, display cases, activators.
BSX_FLAGS_ANIMATED = 0x8B

#: Dynamic constrained objects, e.g. swinging signs.
BSX_FLAGS_CONSTRAINED = 0xCA

#: NiTextureTransformController.operation. See: docs/commentary/asset_convert_shader.md#texture-transform-controller-map
TT_TRANSLATE_U, TT_TRANSLATE_V, TT_ROTATE, TT_SCALE_U, TT_SCALE_V = range(5)
