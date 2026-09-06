"""Variable-held UDFs dispatch without requiring a statically named script."""
import pytest

from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


@pytest.mark.parametrize(('declaration', 'getter'), [
    ('string_var', 'String'), ('int', 'Integer'), ('float', 'Number'),
    ('ref', 'Form'), ('array_var', 'Array'),
])
def test_dynamic_result_type(declaration, getter):
    source = f'''scn DynamicCall
ref functionRef
ref argument
{declaration} value
begin GameMode
let value := Call functionRef argument
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('DynamicCall', source, 'Actor')
    assert '((functionRef as Form) as TES4Function).TES4Invoke(Self,' in result
    assert '.WithForm("0", argument)' in result
    assert f'.Get{getter}("result")' in result
    assert 'functionRef.TES4Call' not in result
    assert ';TODO' not in result and ';NE' not in result


def test_dynamic_argument_copies_unknown_array_value():
    source = '''scn DynamicArgument
ref functionRef
array_var arguments
int value
begin GameMode
let value := Call functionRef arguments[0]
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('DynamicArgument', source, 'Actor')
    assert '.WithValue("0", arguments, 0 as String)' in result


def test_function_exposes_uniform_dispatch_wrapper():
    source = '''scn StringFunction
ref subject
string_var text
begin Function {subject}
let text := "returned text"
SetFunctionValue text
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('StringFunction', source, 'Quest')
    assert 'extends TES4Function' in result
    assert 'TES4Collection Function TES4Invoke(ObjectReference TES4_Caller, TES4Collection TES4_Arguments)' in result
    assert '.WithString("result", TES4Call(TES4_Caller, TES4_Arguments.GetForm("0")))' in result
