"""The fenced-gold polyfill reads a Float global, including in arithmetic."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_fenced_gold_difference_into_integer_slot():
    source = '''scn Gold
short saved
begin GameMode
set saved to GetAmountSoldStolen - saved
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Gold', source, 'Actor')
    assert 'saved = (TES4GoldFenced.GetValue() - saved) as Int' in result
