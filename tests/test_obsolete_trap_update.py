"""TrapUpdate is an engine no-op, not an unimplemented physics update."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph
import pytest


@pytest.mark.parametrize('command', ['TrapUpdate', 'AddAchievement 1'])
def test_obsolete_command_does_not_drop_adjacent_operations(command):
    source = f'''scn TrapTick
begin GameMode
{command}
SetAngle X 15
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('TrapTick', source, 'ObjectReference')
    assert f'; {command.split()[0]}: Oblivion PC engine command has no operation' in result
    assert 'SetAngle(' in result
    assert ';TODO' not in result and ';NE' not in result
