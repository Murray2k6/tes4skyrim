"""The vanilla global horse query must not be confused with the OBSE ref query."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_global_horse_query_assignment_and_condition():
    source = '''scn HorseState
short hasHorse
ref lastHorse
begin GameMode
set hasHorse to GetPlayerHasLastRiddenHorse
set lastHorse to GetPlayersLastRiddenHorse
if GetPlayerHasLastRiddenHorse == 0
endif
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('HorseState', source, 'Quest')
    assert 'hasHorse = TES4Runtime.GetPlayerHasLastRiddenHorse() as Int' in result
    assert 'lastHorse = TES4Runtime.GetPlayersLastRiddenHorse()' in result
    assert 'If !(TES4Runtime.GetPlayerHasLastRiddenHorse())' in result
    assert ';TODO' not in result and ';NE' not in result
