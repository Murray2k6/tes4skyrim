"""FO3/FNV script blocks Oblivion never emits.

`BLOCK_MAP.get(...)` returning None makes `assemble` drop the block body
entirely, so a block type absent from the table is silent data loss. FO3/FNV
author eight Oblivion does not; five have a real Papyrus event, verified
against `references/SkyrimCKWiki_210522/skyrim/<Event>_-_ObjectReference.html`.

See: docs/commentary/script_convert.md#fo3fnv-script-blocks
"""

_END = 'EndEvent'

#: FO3/FNV block type -> (Papyrus event header, terminator).
FALLOUT_BLOCK_MAP = {
    'onopen':   ('Event OnOpen(ObjectReference akActionRef)', _END),
    'onclose':  ('Event OnClose(ObjectReference akActionRef)', _END),
    'ongrab':   ('Event OnGrab()', _END),
    'onrelease': ('Event OnRelease()', _END),
    'ondestructionstagechange': (
        'Event OnDestructionStageChanged(int aiOldStage, int aiCurrentStage)',
        _END),
    'oncombatend': (
        'Event OnCombatStateChanged(Actor akTarget, int aeCombatState)', _END),
}

#: FO3/FNV blocks merged into OnCombatStateChanged, with their state guard.
FALLOUT_COMBAT_STATE_GUARDS = {'oncombatend': 'aeCombatState == 0'}

#: FO3/FNV block filters: block type -> (event parameter, Papyrus type).
FALLOUT_BLOCK_FILTER_PARAM = {
    'onopen':  ('akActionRef', 'ObjectReference'),
    'onclose': ('akActionRef', 'ObjectReference'),
}
