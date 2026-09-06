"""Game-start and save-load queries must retain independent per-script latches."""
import pytest
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


@pytest.mark.parametrize(('command', 'restart'), [('GetGameRestarted', 'True'), ('GetGameLoaded', 'False')])
def test_transition_query_retains_body_and_boolean_result(command, restart):
    source = f'''scn Transition
short changed
short count
begin GameMode
set changed to {command}
if {command} == 1
set count to count + 1
endif
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Transition', source, 'Quest')
    assert f'changed = TES4Runtime.GameTransition({restart}) as Int' in result
    assert f'If TES4Runtime.GameTransition({restart})' in result
    assert 'count = count + 1' in result
    assert ';TODO' not in result and ';NE' not in result
