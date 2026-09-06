"""OBSE key queries retain their three distinct input sources."""
import pytest

from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


@pytest.mark.parametrize(('command', 'function'), [
    ('IsKeyPressed', 'TES4Runtime.IsVirtualKeyPressed'),
    ('IsKeyPressed2', 'Input.IsKeyPressed'),
    ('IsKeyPressed3', 'TES4Input.PhysicalKey'),
])
def test_key_query_in_assignment_and_condition(command, function):
    source = f'''scn Keys
short pressed
short key
begin GameMode
set key to 42
set pressed to {command} key
if {command} 264 || {command} key
endif
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Keys', source, 'Actor')
    assert f'{function}(myKey as Int)' in result
    assert f'{function}(264 as Int)' in result
    assert f'pressed = {function}(myKey as Int) as Int' in result
    assert ';TODO:' not in result
    assert ';NE:' not in result
