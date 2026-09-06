"""Motion command conversion preserves the authored actor, axes and values."""

from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_actor_velocity_reads_and_vertical_write():
    source = '''scn Motion
ref target
float speed
short changed
begin GameMode
set speed to target.GetVelocity Y
set speed to target.GetVelocity Z +30
set changed to target.SetVerticalVelocity -123.5
target.SetVelocity 10 -20 speed
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Motion', source, 'Actor')
    assert ';NE:' not in result
    assert ';TODO:' not in result
    assert 'GetVelocity((target as Actor), 1)' in result
    assert 'GetVelocity((target as Actor), 2) + 30' in result
    assert '0.0, 0.0, -123.5, True)' in result
    assert '10, -20, speed)' in result


def test_implicit_effect_actor_velocity():
    source = '''scn MotionEffect
float speed
begin ScriptEffectUpdate
set speed to GetVerticalVelocity
SetVerticalVelocity speed
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('MotionEffect', source, 'ActiveMagicEffect')
    assert 'GetVelocity(GetTargetActor(), 2)' in result
    assert 'SetVelocity(GetTargetActor(), 0.0, 0.0, speed, True)' in result
    assert ';NE:' not in result


def test_rotation_uses_elapsed_time_and_preserves_axis_and_signed_speed():
    source = '''scn Rotation
ref target
float speed
begin GameMode
target.Rotate Z, -15
Rotate X speed
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Rotation', source, 'ObjectReference')
    assert 'Float TES4_SecondsPassed' in result
    assert 'TES4_SecondsPassed = TES4_Now - TES4_LastTick' in result
    assert 'TES4Polyfill.Rotate(target, "Z", -15, TES4_SecondsPassed)' in result
    assert 'TES4Polyfill.Rotate(Self, "X", speed as Int, TES4_SecondsPassed)' in result
    assert ';NE:' not in result
    assert ';TODO:' not in result


def test_rotation_event_uses_frame_time_even_with_a_poll_in_same_script():
    source = '''scn Rotation
begin OnActivate
Rotate Y 90
end
begin GameMode
Rotate Z 30
end'''
    result = ScriptConverter(CrossRefGraph()).convert_standalone('Rotation', source, 'ObjectReference')
    assert 'TES4Polyfill.Rotate(Self, "Y", 90, -1.0)' in result
    assert 'TES4Polyfill.Rotate(Self, "Z", 30, TES4_SecondsPassed)' in result
