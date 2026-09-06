"""Forcing a movement mode must preserve the actor's independently set speed."""
import pytest
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


@pytest.mark.parametrize(('command', 'sneak'), [('SetForceRun', 'False'), ('SetForceSneak', 'True')])
def test_force_mode_preserves_speed_and_handles_both_toggle_values(command, sneak):
    source = f'''scn ForceMode
ref target
short enabled
begin GameMode
target.{command} enabled
{command} 1
{command} 0
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('ForceMode', source, 'Actor')
    assert f'TES4Runtime.SetForcedMovement((target as Actor), (enabled) as Bool, {sneak})' in result
    assert f'TES4Runtime.SetForcedMovement(Self, (1) as Bool, {sneak})' in result
    assert f'TES4Runtime.SetForcedMovement(Self, (0) as Bool, {sneak})' in result
    assert 'SpeedMult' not in result
    assert ';TODO' not in result and ';NE' not in result
