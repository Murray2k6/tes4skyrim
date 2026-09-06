"""Saved item-value writes retain integer precision and the calling reference."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_item_value_reference_and_exact_integer():
    source = '''scn ValueWrite
ref subject
begin GameMode
subject.SetItemValue 16777217
SetItemValue 50
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('ValueWrite', source, 'ObjectReference')
    assert 'TES4Runtime.SetItemValue(subject, 16777217)' in result
    assert 'TES4Runtime.SetItemValue(Self, 50)' in result
    assert ';TODO' not in result and ';NE' not in result
