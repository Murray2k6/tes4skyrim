"""Keep valid operands when an authored condition has trailing operators."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph
import pytest


def test_duplicate_trailing_boolean_operators():
    source = '''scn BoolTail
int num
begin GameMode
if (num == 11 || num == 12 || ||)
set num to 1
endif
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('BoolTail', source, 'Actor')
    assert 'If (num == 11 || num == 12)' in result
    assert '|| ||' not in result


@pytest.mark.parametrize('condition, expected', [
    ('value >= 0 && <10', 'value >= 0 && value < 10'),
    ('value >= 0 && <10 && !=5', 'value >= 0 && value < 10 && value != 5'),
    ('value < 0 || >10', 'value < 0 || value > 10'),
])
def test_omitted_range_subject(condition, expected):
    source = f'scn Range\nint value\nbegin GameMode\nif {condition}\nendif\nend'
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Range', source, 'Actor')
    assert f'If {expected}' in result
