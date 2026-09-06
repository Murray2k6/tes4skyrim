"""Mixed flag/reference storage preserves writes and identity comparisons."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph
import pytest


def test_numeric_reference_storage_and_comparison():
    """The lock must store the same identity checked in either operand order."""
    source = '''scn Lock
short owner
ref victim
begin GameMode
set owner to 1
set owner to victim
if owner == victim
set owner to 0
endif
if victim != owner
endif
if victim == 0
endif
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Lock', source, 'Actor')
    assert 'owner = TES4SKSE.NumericFormID(victim)' in result
    assert 'owner == TES4SKSE.NumericFormID(victim)' in result
    assert 'TES4SKSE.NumericFormID(victim) != owner' in result
    assert 'victim == None' in result
    assert 'owner = 1' in result
    assert 'TES4 stored ref in short' not in result


def test_remote_numeric_slot_accepts_reference():
    """Use the owning script's public field contract for remote writes."""
    graph = CrossRefGraph()
    graph.ref_as_int.add(('holder', 'value'))
    conv = ScriptConverter(graph)
    conv.sc.property_refs['Owner'] = 'TES4_Holder'
    conv.sc.var_types['victim'] = 'ObjectReference'
    assert conv._typed_assign('Owner.value', 'victim', None, 'Actor') == (
        'Owner.value = TES4SKSE.NumericFormID(victim)')


@pytest.mark.parametrize(('declaration', 'expression', 'accessor'), [
    ('int', '*child', 'Integer'),
    ('int', '*child + 1', 'Integer'),
    ('float', '*child', 'Number'),
    ('string_var', '*child', 'String'),
    ('array_var', '*child', 'Array'),
])
def test_dereference_uses_value_type(declaration, expression, accessor):
    source = f'''scn PairRead
array_var child
{declaration} value
begin GameMode
let value := {expression}
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('PairRead', source, 'Actor')
    assert f'value = TES4Collections.Dereference{accessor}(child)' in result
    assert 'NumericFormID' not in result
