"""Numeric source slots remain variables when their names resemble commands."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


SOURCE = '''scn Flag
begin GameMode
set SkipAnim to 1
if SkipAnim == 0
endif
end'''


def test_written_read_flag_gets_storage():
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Flag', SOURCE, 'Actor')
    assert 'Int Property SkipAnim Auto Conditional' in result
    assert 'SkipAnim = 1' in result
    assert 'If SkipAnim == 0' in result


def test_real_global_keeps_its_binding():
    graph = CrossRefGraph()
    graph.edid_to_formid['skipanim'] = '00001234'
    graph.formid_to_edid['00001234'] = 'SkipAnim'
    graph.record_type['00001234'] = 'GLOB'
    result = ScriptConverter(graph).convert_standalone('Flag', SOURCE, 'Actor')
    assert 'Int Property SkipAnim' not in result
    assert 'SkipAnim.SetValue(1)' in result
    assert 'If SkipAnim.GetValue()' in result
