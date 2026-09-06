"""Both source spellings preserve negative coordinates and world identity."""
import pytest

from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


@pytest.mark.parametrize('name', ['PositionWorld', 'PosWorld'])
def test_world_teleport_alias_and_coordinates(name):
    graph = CrossRefGraph()
    graph.edid_to_formid['destination'] = '01001234'
    graph.formid_to_edid['01001234'] = 'Destination'
    graph.record_type['01001234'] = 'WRLD'
    source = f'scn Move\nbegin GameMode\nplayer.{name} -100.5 200 300, 1.25, Destination\nend'
    result = ScriptConverter(graph).convert_standalone('Move', source, 'Actor')
    assert 'WorldSpace Property TES4Base_Destination Auto' in result
    assert ('TES4Runtime.PositionWorld(Game.GetPlayer(), TES4Base_Destination, '
            '(-100.5) as Float, (200) as Float, (300) as Float, (1.25) as Float)') in result
    assert ';TODO:' not in result
