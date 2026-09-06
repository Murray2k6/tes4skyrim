"""Numeric actor-value writes must not fall through to nonexistent methods."""

from script_convert.actor_value_codes import write_setter
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph
from script_convert.runtime_commands import _AV_CODE_NAMES


def test_setter_literal_and_runtime_codes():
    source = '''scn NumericValues
ref target
short index
float amount
begin GameMode
set amount to GetAVForBaseActorC index target
set amount to GetAVForBaseActor Health target
target.SetAVC 8 amount
target.ModAVC 10 -25
target.SetActorValueC index amount
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('NumericValues', source, 'Actor')
    assert 'SetActorValue("Health", amount)' in result
    assert 'ModActorValue("Stamina", -25)' in result
    assert 'TES4ActorValues.Set((target as Actor), index, amount, False)' in result
    assert 'TES4ActorValues.GetBase(target, index)' in result
    assert 'TES4ActorValues.GetBase(target, 8)' in result
    assert ';TODO:' not in result
    assert ';NE:' not in result


def test_generated_setter_keeps_existing_attribute_and_vampire_rules(tmp_path):
    write_setter(tmp_path, _AV_CODE_NAMES)
    source = (tmp_path / 'TES4ActorValues.psc').read_text(encoding='utf-8')
    assert 'If code == 8\n    Return "Health"' in source
    assert 'If code == 10\n    Return "Stamina"' in source
    assert 'If code == 0\n    Return "strength"' in source
    assert 'TES4Runtime.ChangeVampirism(subject, amount, 1)' in source
    assert 'TES4Polyfill.SetTES4ActorValue(subject, actorValue, amount)' in source
