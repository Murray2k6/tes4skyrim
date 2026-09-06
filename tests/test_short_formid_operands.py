"""TES4 accepts FormID operands with every leading zero omitted."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_trimmed_formid_and_local_precedence():
    graph = CrossRefGraph()
    graph.formid_to_edid['0000000F'] = 'Gold001'
    graph.edid_to_formid['gold001'] = '0000000F'
    graph.record_type['0000000F'] = 'MISC'
    source = 'scn Buy\nint cost\nbegin GameMode\nplayer.RemoveItem f cost\nend'
    result = ScriptConverter(graph).convert_standalone('Buy', source, 'Actor')
    assert 'RemoveItem(Gold001, cost)' in result
    source = source.replace('int cost', 'int cost\nref f')
    result = ScriptConverter(graph).convert_standalone('Buy', source, 'Actor')
    assert 'RemoveItem(f, cost)' in result
