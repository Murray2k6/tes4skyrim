"""FO3/FNV equipment: weapon animation types and biped slots.

Skyrim's only ranged animations are Bow and Crossbow, so every firearm becomes
a Crossbow: it aims flat and fires a projectile, where a bow is drawn and arced.
ETYP, BIDS, BAMT, INAM, NAM9 and NAM8 all key off the anim type, so that one
substitution carries the whole record.

FO3/FNV biped flags are a 20-bit field that shares only bits 0-2 with
Oblivion's 16-bit one, so the slot table is selected by source game.

See: docs/commentary/tes4_export_falloutnv.md#weapons-guns-become-crossbows
See: docs/commentary/tes4_export_falloutnv.md#fnv-biped-slots
"""

from ..skyrim_overrides import WEAPON_ANIM_CROSSBOW
from .common import get_int
from .world_falloutnv import is_fallout_source

#: FO3/FNV firearm anim types: pistols 3-4, rifles 5-7, launcher 9, thrown 10-13.
_GUN_TYPES = frozenset({3, 4, 5, 6, 7, 9, 10, 11, 12, 13})


def refine_anim_type(rec: dict, anim_type: int) -> int:
    """Crossbow for a FO3/FNV firearm, else the given type unchanged."""
    if get_int(rec, 'DNAM.FalloutAnimType', -1) in _GUN_TYPES:
        return WEAPON_ANIM_CROSSBOW
    return anim_type


#: FO3/FNV biped bit -> Skyrim BOD2 bit; Weapon(5) has no slot and is dropped.
FNV_BIPED_SLOT_MAP = {
    0: 0,    # Head -> 30-Head
    1: 1,    # Hair -> 31-Hair
    2: 2,    # Upper Body -> 32-Body
    3: 3,    # Left Hand -> 33-Hands
    4: 3,    # Right Hand -> 33-Hands (merged)
    6: 4,    # PipBoy -> 34-Forearms
    7: 16,   # Backpack -> 46-Unnamed
    8: 5,    # Necklace -> 35-Amulet
    9: 12,   # Headband -> 42-Circlet
    10: 1,   # Hat -> 31-Hair
    11: 12,  # Eye Glasses -> 42-Circlet
    12: 13,  # Nose Ring -> 43-Ears
    13: 13,  # Earrings -> 43-Ears
    14: 0,   # Mask -> 30-Head
    15: 5,   # Choker -> 35-Amulet
    16: 13,  # Mouth Object -> 43-Ears
    17: 17,  # Body AddOn 1 -> 47-Unnamed
    18: 18,  # Body AddOn 2 -> 48-Unnamed
    19: 19,  # Body AddOn 3 -> 49-Unnamed
}


#: FO3/FNV Upper Body is the whole body but the hands: it also claims 37-Feet.
_FNV_BODY_EXTRA = {2: [7]}


def biped_slot_tables(oblivion_map: dict, oblivion_extra: dict) -> tuple:
    """(slot map, conflict extras) for the source game.

    See: docs/commentary/tes4_export_falloutnv.md#fnv-biped-slots
    """
    if not is_fallout_source():
        return oblivion_map, oblivion_extra
    return FNV_BIPED_SLOT_MAP, {**oblivion_extra, **_FNV_BODY_EXTRA}
