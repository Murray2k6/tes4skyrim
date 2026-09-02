"""BSXFlags values: what the engine may do with a NIF's root.

BSXFlags is a bitfield on the root NiNode that gates havok, animation and
ragdoll handling.  The four values here are the combinations vanilla Skyrim
ships for placed world objects, named after the object class each one serves.

These are object-side constants -- doors, clutter and signs -- so they live
beside the mesh converter that writes them rather than with the wearable and
body-slot tables.
"""

#: Static objects with collision: complex + havok.
BSX_FLAGS_STATIC = 0x82

#: Dynamic clutter (mass > 0): adds the rigid-body bit.
BSX_FLAGS_DYNAMIC = 0xC2

#: Animated objects -- doors, display cases, activators.
BSX_FLAGS_ANIMATED = 0x8B

#: Dynamic constrained objects, e.g. swinging signs.
BSX_FLAGS_CONSTRAINED = 0xCA
