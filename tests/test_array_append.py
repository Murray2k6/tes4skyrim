"""ar_Append preserves heterogeneous values and its success result."""
import pytest

from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


@pytest.mark.parametrize(('declaration', 'value', 'method'), [
    ('int value', 'value', 'AppendInteger(value)'),
    ('float value', 'value', 'AppendNumber(value)'),
    ('string_var value', 'value', 'AppendString(value)'),
    ('ref value', 'value', 'AppendForm(value)'),
    ('array_var value', 'value', 'AppendArray(value)'),
    ('array_var value', 'value["mixed"]', 'AppendValue(value, "mixed" as String)'),
])
def test_append_values(declaration, value, method):
    source = f'''scn AppendValues
array_var target
{declaration}
int success
begin GameMode
let success := ar_Append target {value}
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('AppendValues', source, 'Actor')
    assert f'success = target.{method}' in result
    assert ';TODO' not in result and ';NE' not in result
