"""Active-effect arrays must use array iteration, never inventory cursors."""
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_active_effect_array_iteration():
    source = '''scn Effects
array_var entry
long code
begin GameMode
ForEach entry <- GetActiveEffectCodes
let code := entry->value
loop
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Effects', source, 'Actor')
    assert 'TES4Collection.ActiveEffects(Self, False)' in result
    assert 'TES4Collections.Size(' in result
    assert 'TES4Collection Property entry' in result
    assert 'entry.GetInteger("value" as String)' in result
    assert 'BeginInventory' not in result


def test_integer_collection_values_do_not_round_through_float():
    source = '''scn ExactCodes
array_var values
long code
begin GameMode
let values := ar_List 1094861636
let code := values[0]
let values[0] := code
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('ExactCodes', source, 'Actor')
    assert '.WithInteger("0", 1094861636)' in result
    assert 'values.GetInteger(0 as String)' in result
    assert 'values.SetInteger(0 as String, code)' in result


def test_inventory_items_preserves_type_filter():
    source = '''scn Items
array_var items
begin GameMode
let items := player.GetItems 20 22
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Items', source, 'Actor')
    assert 'TES4Collection.Items(Game.GetPlayer(), TES4Collection.Create().WithInteger("0", 20).WithInteger("1", 22))' in result
    assert ';NE:' not in result


def test_inventory_reference_array_loop_keeps_filter_and_entry():
    source = '''scn InventoryRefs
array_var entry
ref item
ref owner
ref found
begin GameMode
ForEach entry <- owner.GetInvRefsForItem item
let found := entry->value
loop
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('InventoryRefs', source, 'Actor')
    assert 'TES4Runtime.BeginInventory(owner, item)' in result
    assert 'entry.SetForm("value", TES4Runtime.InventoryReference(' in result
    assert 'found = entry.GetForm("value" as String)' in result
    assert 'TES4Runtime.EndInventory(' in result


def test_iterator_dereference_uses_value_entry():
    source = '''scn Dereference
array_var entry
int blockID
begin GameMode
let blockID := *entry
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Dereference', source, 'Actor')
    assert 'blockID = TES4Collections.DereferenceInteger(entry)' in result


def test_nested_string_keys_stay_strings_in_numeric_reads():
    source = '''scn Bounds
array_var bounds
float height
begin GameMode
let bounds := GetBoundingBox
let height := bounds["extent"]["z"]
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Bounds', source, 'Actor')
    assert '.GetArray("extent" as String).GetNumber("z" as String)' in result
    assert 'Property z ' not in result
    assert 'bounds = TES4Collection.BoundingBox(Self)' in result


def test_combat_actor_arrays_are_collections():
    source = '''scn Combat
array_var allies
array_var targets
begin GameMode
let allies := GetAllies
let targets := GetTargets
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Combat', source, 'Actor')
    assert 'allies = TES4Collection.CombatActors(Self, False)' in result
    assert 'targets = TES4Collection.CombatActors(Self, True)' in result
