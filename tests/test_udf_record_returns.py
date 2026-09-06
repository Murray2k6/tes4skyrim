"""Record constants are Form results even before output properties are bound."""
from script_convert.udf_types import infer_returns
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_record_constant_return_contract():
    sources = {'pick': 'scn Pick\nbegin Function {}\nSetFunctionValue MyWeapon\nend'}
    assert infer_returns(sources, {}, {'myweapon': 'Form'}) == {'pick': 'Form'}
    assert infer_returns(sources, {'pick': {'myweapon': 'Int'}}, {'myweapon': 'Form'}) == {'pick': 'Int'}


def test_duplicate_let_keeps_the_assignment():
    source = 'scn Duplicate\nint amount\nbegin GameMode\nlet let amount := player.GetItemCount Gold001\nend'
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Duplicate', source, 'Actor')
    assert 'amount = Game.GetPlayer().GetItemCount(' in result
    assert ':=' not in result


def test_array_return_uses_authored_element_values():
    source = '''scn Pick
array_var choices
int index
begin Function {}
let choices := ar_Construct Array
let choices[0] := MyCreature
SetFunctionValue choices[index]
end'''
    variables = {'pick': {'choices': 'TES4Collection', 'index': 'Int'}}
    returns = infer_returns({'pick': source}, variables, {'mycreature': 'Form'})
    assert returns == {'pick': 'Form'}
    graph = CrossRefGraph()
    graph.function_returns = returns
    result = ScriptConverter(graph).convert_standalone('Pick', source, 'ObjectReference')
    assert 'TES4_Result = choices.GetForm(index as String)' in result


def test_numeric_array_return_uses_integer_accessor():
    source = '''scn Pick
array_var choices
begin Function {}
let choices := ar_List 2 3
SetFunctionValue choices[0]
end'''
    graph = CrossRefGraph()
    graph.function_returns = infer_returns({'pick': source}, {})
    result = ScriptConverter(graph).convert_standalone('Pick', source, 'ObjectReference')
    assert 'TES4_Result = choices.GetInteger(0 as String)' in result
