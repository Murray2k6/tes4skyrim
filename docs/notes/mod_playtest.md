# Mod playtest reports

Reported by the user on 2026-09-03. These are open in-game observations, in the
user's order. Causes have not been established, and no fix is claimed here.

| Area | Reported behavior and expected behavior |
|---|---|
| Midas shop | The shop exists, but the player cannot buy anything. The report does not distinguish a missing barter option from an empty or unusable barter menu. |
| Apparatus | The user is unsure whether apparatus can be used. Preserve this as an open usability question, not a confirmed failure. |
| Midas spells | Spells do not work when expected, including casting behavior. The report calls these “Modas spells”; grouped with Midas provisionally. Specific spells and failure points were not supplied. |
| MOO fast travel and LOD | Traveling to overworld fast-travel markers behaves strangely. Destinations seem like instanced versions of wilderness cells, with severely broken LOD. The appearance of instancing is reported; duplicated cells or worldspaces have not been demonstrated. |
| Weather | Weather did not translate well and appears all black. The report follows the MOO observations but does not name the affected weather records or establish their owning plugin. |
| Encounters and spawn points | The user has not yet seen the mod's encounters or extra spawn points and suspects incomplete conversion. Absence during play is reported; the spawning mechanism and coverage have not been measured. |
| NPC and quest dialogue/disposition | Dialogue and disposition behave incorrectly for NPCs and quests. Specific actors, topics, and quest stages were not supplied. |
| Akatosh Mount spell sequence | Expected: receive a spell to choose a mount, then receive a spell to summon and control that selected mount. Observed: the first spell appears; the second does not. Receiving the selection spell alone does not satisfy the expected behavior. |
| Books | All books tested fail to turn pages and show a blank image instead of the expected interior text/font. Preserve page turning and text rendering as separate failures. The report does not limit the book problem to Akatosh Mount. |

## Conversion paths located for follow-up

These are source entry points, not diagnoses:

- Shop services: `tes5_import/record_types/actors.py`.
- Apparatus and book records: `tes5_import/record_types/equipment.py`.
- Spell effects and scripted behavior: `tes5_import/record_types/magic.py`
  and `script_convert/`.
- World/cell/reference conversion: `tes5_import/record_types/world.py`.
- Weather: `tes5_import/record_types/weather.py`.
- Leveled actor conversion: `tes5_import/leveled_actors.py`; scripted spawning
  also requires tracing the source scripts.
- Dialogue: `tes5_import/dialog_converter.py`,
  `tes5_import/dialog_conditions.py`, and `script_convert/`.
- Book reading assets: `asset_convert/book_inam.py`.
