"""Actor command aliases have the receiver requirements of their target method."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_actor_aliases_inside_user_function():
    source = '''scn ActorAliases
ref item
begin Function {item}
EquipItemNS item
AddSpellNS item
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('ActorAliases', source, 'TES4Function')
    assert '(TES4_Caller as Actor).EquipItem(' in result
    assert '(TES4_Caller as Actor).AddSpell(' in result
