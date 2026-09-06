"""Vanilla actor renaming targets the actor base and preserves literal text."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_actor_full_name_receiver_and_string():
    source = '''scn RenameActors
ref subject
begin GameMode
subject.SetActorFullName "An authored name"
SetActorFullName "Another name"
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('RenameActors', source, 'Actor')
    assert 'TES4Runtime.SetActorFullName((subject as Actor), "An authored name")' in result
    assert 'TES4Runtime.SetActorFullName(Self, "Another name")' in result
    assert ';TODO' not in result and ';NE' not in result
