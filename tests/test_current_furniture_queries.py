"""Furniture-reference and furniture-base tests compare different identities."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_furniture_reference_and_base_are_distinct():
    source = '''scn FurnitureQueries
ref actorRef
ref furnitureRef
ref furnitureBase
short result
begin GameMode
set result to actorRef.IsCurrentFurnitureRef furnitureRef
if IsCurrentFurnitureObj furnitureBase == 0
endif
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('FurnitureQueries', source, 'Actor')
    assert 'TES4Runtime.IsCurrentFurniture((actorRef as Actor), furnitureRef, False) as Int' in result
    assert 'If !(TES4Runtime.IsCurrentFurniture(Self, furnitureBase, True))' in result
    assert ';TODO' not in result and ';NE' not in result
