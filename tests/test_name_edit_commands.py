"""OBSE name edits distinguish optional targets from calling references."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_copy_and_append_preserve_receiver_optional_target_and_string():
    source = '''scn Names
ref source
ref target
ref caller
string_var suffix
begin GameMode
caller.CopyName source target
CopyName source
caller.AppendToName suffix target
AppendToName " Charged"
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Names', source, 'ObjectReference')
    assert 'TES4Runtime.CopyName(source, target, caller)' in result
    assert 'TES4Runtime.CopyName(source, None, Self)' in result
    assert 'TES4Runtime.AppendToName(suffix, target, caller)' in result
    assert 'TES4Runtime.AppendToName(" Charged", None, Self)' in result
    assert ';TODO' not in result and ';NE' not in result
