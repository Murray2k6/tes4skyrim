"""Bare source queries must emit callable, typed Skyrim expressions."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_difficulty_query_uses_runtime_selection():
    """The bare OBSE query is a Float call, not an undeclared identifier."""
    source = 'scn Difficulty\nfloat level\nbegin GameMode\nset level to GetGameDifficulty\nend'
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Difficulty', source, 'Actor')
    assert 'level = TES4SKSE.GetGameDifficulty()' in result


def test_dropped_reference_query():
    source = 'scn Drop\nref item\nbegin GameMode\nset item to GetPCLastDroppedItemRef\nitem.Disable\nend'
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Drop', source, 'Actor')
    assert 'item = TES4Runtime.GetLastDroppedReference()' in result
    assert 'item.Disable()' in result


def test_name_substring_uses_literal_text_and_receiver():
    source = 'scn Named\nbegin GameMode\nif player.NameIncludes "ghost"\nendif\nend'
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Named', source, 'Actor')
    assert 'TES4Runtime.NameIncludes(Game.GetPlayer(), "ghost")' in result
    assert ';TODO:' not in result


def test_spell_queries_keep_receiver_and_optional_race():
    source = '''scn Spells
int count
ref magic
begin GameMode
set count to player.GetRaceSpellCount
set magic to player.GetNthRaceSpell 2
set count to player.GetSpellCount
set magic to player.GetNthSpell 1
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Spells', source, 'Actor')
    assert '(Game.GetPlayer() as Actor).GetRace().GetSpellCount()' in result
    assert '(Game.GetPlayer() as Actor).GetRace().GetNthSpell(2)' in result
    assert 'TES4Collections.Size(TES4Collection.Spells(Game.GetPlayer()))' in result
    assert 'TES4Collection.Spells(Game.GetPlayer()).GetForm(1 as String)' in result
    assert ';TODO:' not in result


def test_equipped_poison_uses_actor_instance():
    source = '''scn Poison
ref poison
begin Function {}
set poison to GetEquippedWeaponPoison
set poison to RemoveEquippedWeaponPoison
SetEquippedWeaponPoison poison
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Poison', source, 'Actor')
    assert 'TES4Runtime.GetEquippedWeaponPoison((TES4_Caller as Actor))' in result
    assert 'Potion poison' in result
    assert 'TES4Runtime.ChangeEquippedWeaponPoison((TES4_Caller as Actor), None, True)' in result
    assert 'TES4Runtime.ChangeEquippedWeaponPoison((TES4_Caller as Actor), poison, False)' in result


def test_source_actor_queries():
    source = '''scn Queries
ref target
int value
float ratio
ref cell
begin GameMode
set value to target.GetTrainerSkill
set value to target.GetTrainerLevel
set value to target.GetCurrentSoulLevel
set ratio to target.GetFatiguePercentage
set cell to target.GetTeleportCell
set ratio to target.GetDoorTeleportX
set ratio to target.GetDoorTeleportRot
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Queries', source, 'Actor')
    assert 'TES4Runtime.SourceInt(target, "TrainerSkill")' in result
    assert 'TES4Runtime.SourceInt(target, "TrainerLevel")' in result
    assert 'TES4Runtime.GetCurrentSoulLevel(target)' in result
    assert '(target as Actor).GetActorValuePercentage("Stamina")' in result
    assert 'TES4Runtime.GetTeleportCell(target)' in result
    assert 'TES4Runtime.GetTeleportCoordinate(target, 0)' in result
    assert 'TES4Runtime.GetTeleportCoordinate(target, 3)' in result
