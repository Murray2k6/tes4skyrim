"""Reference variable reads must retain Form type in comparisons."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_reference_variable_read_in_comparison():
    source = '''scn ReadVariable
ref target
ref item
begin GameMode
if target.GetRefVariable myWeap == item
set item to 0
endif
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('ReadVariable', source, 'Actor')
    assert ('TES4SKSE.NumericFormID(TES4Runtime.ReadReferenceVariable(target, "myWeap"))'
            ' == item') in result
    assert ';TODO:' not in result


def test_remote_emitted_form_contract_overrides_prebinding_type():
    graph = CrossRefGraph()
    graph.ref_as_base_form.add(('holder', 'value'))
    conv = ScriptConverter(graph)
    conv.sc.property_refs['Owner'] = 'TES4_Holder'
    conv.sc.var_types['target'] = 'ObjectReference'
    conv._value_type = 'ObjectReference'
    assert conv._typed_assign('target', 'Owner.value', None, 'Actor') == (
        'target = Owner.value as ObjectReference')


def test_cross_script_ref_fed_by_integer_variable_is_numeric(tmp_path):
    sources = {'Holder': 'scn Holder\nref code\nbegin GameMode\nset code to 0\nend',
               'Writer': 'scn Writer\nint number\nbegin GameMode\nset Holder.code to number\nend'}
    path = tmp_path / 'SCPT.txt'
    path.write_text('\n'.join(
        '---RECORD_BEGIN---\nSignature=SCPT\nEditorID=' + name + '\nSCTX=' +
        source.replace('\n', '\\n') + '\n---RECORD_END---'
        for name, source in sources.items()), encoding='utf-8')
    graph = CrossRefGraph()
    graph.build_ref_as_int_map(str(path))
    assert ('holder', 'code') in graph.ref_as_int


def test_udf_return_contract_reaches_public_field(tmp_path):
    sources = {'Pick': 'scn Pick\nref value\nbegin Function {value}\nSetFunctionValue value\nend',
               'Holder': 'scn Holder\nref value\nbegin GameMode\nset value to Call Pick player\nend'}
    path = tmp_path / 'SCPT.txt'
    path.write_text('\n'.join(
        '---RECORD_BEGIN---\nSignature=SCPT\nEditorID=' + name + '\nSCTX=' +
        source.replace('\n', '\\n') + '\n---RECORD_END---'
        for name, source in sources.items()), encoding='utf-8')
    graph = CrossRefGraph()
    graph.build_ref_as_int_map(str(path))
    assert ('holder', 'value') in graph.ref_as_base_form
