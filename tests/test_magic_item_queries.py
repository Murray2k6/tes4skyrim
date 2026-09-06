"""OBSE effect indices refer to the authored list, including translated effects."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph
from script_convert.magic_metadata import effect_traits
import pytest


@pytest.mark.parametrize('command', ['MagicEffectCodeFromChars', 'MECodeFromChars'])
def test_effect_code_chars_resolve_strings_at_runtime(command):
    source = f'''scn Codes
string_var chars
int code
begin GameMode
let chars := "FIRE"
let code := {command} chars
let code := {command} "NOT_AN_EFFECT"
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Codes', source, 'Actor')
    assert 'code = TES4Runtime.MagicEffectCodeFromChars(chars)' in result
    assert 'code = TES4Runtime.MagicEffectCodeFromChars("NOT_AN_EFFECT")' in result
    assert ';TODO' not in result and ';NE' not in result


def test_effect_chars_and_form_round_trip_are_typed():
    source = '''scn Codes
ref effect
string_var chars
int code
begin GameMode
let effect := MagicEffectFromChars "FIRE"
let chars := GetMagicEffectChars effect
let chars := GetMagicEffectCharsC code
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Codes', source, 'Actor')
    assert 'TES4Runtime.MagicEffectFromCode(TES4Runtime.MagicEffectCodeFromChars("FIRE"))' in result
    assert 'TES4Runtime.GetMagicEffectChars(TES4Runtime.SourceInt(' in result
    assert 'chars = TES4Runtime.GetMagicEffectChars(code)' in result
    assert ';TODO' not in result and ';NE' not in result


@pytest.mark.parametrize('command', ['GetMagicItemEffectCount', 'GetMIEffectCount'])
def test_effect_count_command_names(command):
    source = f'scn CountEffects\nref item\nint count\nbegin GameMode\nset count to {command} item\nend'
    result = ScriptConverter(CrossRefGraph()).convert_standalone('CountEffects', source, 'Actor')
    assert 'count = TES4Runtime.SourceInt(item, "EffectCount")' in result
    assert ';TODO' not in result and ';NE' not in result


def test_authored_effect_metadata():
    traits = effect_traits({'EffectCount': '1', 'Effect[0].EFID': 'SHLD',
                            'Effect[0].Magnitude': '20', 'Effect[0].Type': 'Touch'})
    assert traits['Effect0Magnitude'] == 20
    assert traits['Effect0Range'] == 1
    assert traits['Effect0Code'] == int.from_bytes(b'SHLD', 'little')


def test_effect_magnitude_in_formatted_text():
    source = '''scn EffectText
ref magicItem
int index
string_var text
begin GameMode
let text := sv_Construct "%g" (GetNthEffectItemMagnitude magicItem index)
let text += " " + $GetNthEffectItemMagnitude magicItem index + " "
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('EffectText', source, 'Actor')
    assert 'TES4Runtime.SourceInt(magicItem, "Effect" + (index as String) + "Magnitude")' in result
    assert ';TODO:' not in result
    assert result.count('TES4Runtime.SourceInt(magicItem, "Effect" + (index as String) + "Magnitude")') == 2


def test_dispel_accepts_magic_items_other_than_spells():
    source = 'scn DispelItem\nref item\nbegin GameMode\ndispel item\nend'
    result = ScriptConverter(CrossRefGraph()).convert_standalone('DispelItem', source, 'Actor')
    assert 'TES4Runtime.DispelMagicItem(Self, item)' in result
    assert '.DispelSpell(' not in result
