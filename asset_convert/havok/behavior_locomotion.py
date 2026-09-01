"""The nested standing/locomotion machines: DefaultBehavior and below.

Split out of hkx_behavior.build_behavior_xml.  This is the vanilla quadruped
topology: turns nest inside StandingBehavior (unreachable while moving or
attacking) rather than sitting at the root.  The old FLAT graph made every
engine event a root wildcard, so the continuously-sent combat facing
adjustments hijacked the graph — constant body-whipping — and aborted every
attack mid-swing.

`build_default` returns `(default_sm, loco_sm, gait_eem)`: the machine the
root's DefaultState wraps, the locomotion sub-machine (None when the creature
has no forward gait) and the walk/run hysteresis modifier the root modifier
list needs (None unless the creature ships a run gait).
See: docs/commentary/asset_convert_creature.md#strafes-are-blends-not-states
"""

from asset_convert.havok.behavior_clips import (
    backward_blend_plan,
    combat_idle_clip,
    gait_thresholds,
    run_blend_plan,
    speed_blend_plan,
)
from asset_convert.havok.behavior_nodes import F_LOCAL

#: Anchor weights of the Direction blend: forward, right, backward, left.
_DIR_RIGHT, _DIR_BACK, _DIR_LEFT = 0.25, 0.5, 0.75


# ---------------------------------------------------------------------------
# Gait blends
# ---------------------------------------------------------------------------

def gait_speed_blend(gb, name, kf, spd):
    """slow-creep@5 + clip@natural + clip@2x SpeedSampled blend for one gait.

    The chaurus per-direction layout (RightSlow / Right / Right_Run); a bare
    clip when the clip has no measurable root-motion speed.  The 2x child is
    the same clip at playbackSpeed 2.0, because the engine's commanded speed
    at a strafe heading blends the MOVT columns rather than using the strafe
    column alone.
    See: docs/commentary/asset_convert_creature.md#strafes-are-blends-not-states
    """
    if not spd:
        return gb.clip(name, kf, True)
    return gb.parametric_blend(
        f'{name}Blend',
        [(f'{name}Slow', kf, max(0.02, round(5.0 / spd, 3)), 5.0),
         (name, kf, 1.0, spd),
         (f'{name}Fast', kf, 2.0, round(spd * 2.0, 3))])


def direction_family(gb, prefix, fwd_ref, loco, speeds):
    """The Direction blend around ONE gait family (walk or run).

    Forward @0 plus whatever strafe/backward clips the creature ships, each
    as its own speed blend.  None when there is nothing to blend, so the
    family stays a plain forward gait.
    """
    kids = [(fwd_ref, 0.0)]
    if 'StrafeRight' in loco:
        kids.append((gait_speed_blend(
            gb, f'{prefix}StrafeRight', loco['StrafeRight'],
            speeds.get('right')).ref, _DIR_RIGHT))
    if 'MoveBackward' in loco and ('StrafeRight' in loco
                                   or 'StrafeLeft' in loco):
        kids.append((gait_speed_blend(
            gb, f'{prefix}BackwardDir', loco['MoveBackward'],
            speeds.get('back')).ref, _DIR_BACK))
    if 'StrafeLeft' in loco:
        kids.append((gait_speed_blend(
            gb, f'{prefix}StrafeLeft', loco['StrafeLeft'],
            speeds.get('left')).ref, _DIR_LEFT))
    if len(kids) == 1:
        return None
    return gb.direction_blend(f'{prefix}DirectionalBlend', kids)


# ---------------------------------------------------------------------------
# LocomotionBehavior
# ---------------------------------------------------------------------------

def _gait_hysteresis(gb, speeds):
    """The EEM switching walk<->run on SpeedSampled, with hysteresis.

    iMovementSpeed picks the start state; comparison operators must be
    XML-escaped in the packfile text.
    """
    lo, hi = gait_thresholds(speeds)
    arr = gb.expression_array(
        [('iMovementSpeed = cond((Speed &lt; 100), 0, 1)',
          'EVENT_MODE_SEND_ONCE'),
         (f'runStart if (SpeedSampled &gt; {hi})',
          'EVENT_MODE_SEND_ON_FALSE_TO_TRUE'),
         (f'walkStart if (SpeedSampled &lt; {lo})',
          'EVENT_MODE_SEND_ON_FALSE_TO_TRUE')])
    eem = gb.add('hkbEvaluateExpressionModifier')
    eem.param('variableBindingSet', 'null')
    eem.param('userData', 2)
    eem.param('name', 'ForwardLocomotion_EEM')
    eem.param('enable', True)
    eem.param('expressions', arr.ref)
    return eem


def _forward_generator(gb, clips, speeds, loco):
    """The forward gait, as `(generator, gait_eem)`.

    One family when the creature has only a walk; two states switched by
    runStart/walkStart when it also ships a run, which is the vanilla
    forwardlocomotion layout — the walk blend and the run blend never mix
    clips.
    """
    fplan = speed_blend_plan(clips, speeds)
    walk = (gb.parametric_blend('ForwardWalkBlend', fplan) if fplan
            else gb.clip('MoveForward', loco['MoveForward'], True))
    walk = direction_family(gb, 'Walk', walk.ref, loco, speeds) or walk

    rplan = run_blend_plan(clips, speeds)
    if not rplan:
        return walk, None
    run = gb.parametric_blend('ForwardRunBlend', rplan)
    run = direction_family(gb, 'Run', run.ref, loco, speeds) or run
    sm = gb.state_machine(
        'ForwardLocomotionBehavior',
        [gb.state(0, 'ForwardWalkState', walk.ref,
                  transitions=[(gb.eid['runStart'], 1, F_LOCAL)]),
         gb.state(1, 'ForwardRunState', run.ref,
                  transitions=[(gb.eid['walkStart'], 0, F_LOCAL)])],
        binding_ref=gb.binding_set(
            [('startStateId', 'iMovementSpeed')]).ref)
    return sm, _gait_hysteresis(gb, speeds)


def _locomotion_machine(gb, clips, speeds, loco):
    """LocomotionBehavior: Forward(0) <-> Backward(1), or None.

    Strafes live inside the gait families' Direction blends, never as
    event-entered states; the engine's moveBackward event still owns the
    dedicated BackwardLocomotionState.
    """
    if 'MoveForward' not in loco:
        return None, None
    eid = gb.eid
    fwd_gen, gait_eem = _forward_generator(gb, clips, speeds, loco)
    has_back = 'MoveBackward' in loco
    states = [gb.state(
        0, 'ForwardLocomotionState', fwd_gen.ref,
        transitions=([(eid['moveBackward'], 1, F_LOCAL)] if has_back
                     else None))]
    if has_back:
        bplan = backward_blend_plan(clips, speeds)
        back = (gb.parametric_blend('BackwardSpeedBlend', bplan) if bplan
                else gb.clip('MoveBackward', loco['MoveBackward'], True))
        states.append(gb.state(1, 'BackwardLocomotionState', back.ref,
                               transitions=[(eid['moveForward'], 0,
                                             F_LOCAL)]))
    return gb.state_machine('LocomotionBehavior', states), gait_eem


# ---------------------------------------------------------------------------
# StandingBehavior and DefaultBehavior
# ---------------------------------------------------------------------------

def _standing_idle_machine(gb, clips):
    """StandingIdleBehavior: NonCombatIdle(0) <-> CombatIdle(1)."""
    eid = gb.eid
    idle = gb.clip('Idle', clips['idle'], True)
    combat = gb.clip('CombatStance', combat_idle_clip(clips), True)
    return gb.state_machine('StandingIdleBehavior', [
        gb.state(0, 'NonCombatIdleState', idle.ref,
                 transitions=[(eid['combatStanceStart'], 1, F_LOCAL)]),
        gb.state(1, 'CombatIdleState', combat.ref,
                 transitions=[(eid['combatStanceStop'], 0, F_LOCAL)]),
    ])


def _standing_machine(gb, clips, loco):
    """StandingBehavior: the idle switch plus looping turn-in-place states."""
    eid = gb.eid
    idle_sm = _standing_idle_machine(gb, clips)
    has_tr, has_tl = 'TurnRight' in loco, 'TurnLeft' in loco
    idle_trans = []
    if has_tr:
        idle_trans.append((eid['turnRight'], 1, F_LOCAL))
    if has_tl:
        idle_trans.append((eid['turnLeft'], 2, F_LOCAL))
    states = [gb.state(0, 'StandingIdleState', idle_sm.ref,
                       transitions=idle_trans or None)]
    if has_tr:
        trans = [(eid['turnStop'], 0, F_LOCAL)]
        if has_tl:
            trans.insert(0, (eid['turnLeft'], 2, F_LOCAL))
        states.append(gb.state(
            1, 'LoopingTurnRight',
            gb.clip('TurnRight', loco['TurnRight'], True).ref,
            transitions=trans))
    if has_tl:
        trans = [(eid['turnStop'], 0, F_LOCAL)]
        if has_tr:
            trans.insert(0, (eid['turnRight'], 1, F_LOCAL))
        states.append(gb.state(
            2, 'LoopingTurnLeft',
            gb.clip('TurnLeft', loco['TurnLeft'], True).ref,
            transitions=trans))
    return gb.state_machine('StandingBehavior', states)


def build_default(gb, clips, speeds):
    """DefaultBehavior: Standing(0) <-> Locomotion(1).

    Returns `(default_sm, loco_sm, gait_eem)` — the machine the root's
    DefaultState wraps, the locomotion sub-machine (None without a forward
    gait) and the walk/run hysteresis modifier (None without a run gait).
    """
    eid = gb.eid
    loco = clips['locomotion']
    loco_sm, gait_eem = _locomotion_machine(gb, clips, speeds, loco)
    standing_sm = _standing_machine(gb, clips, loco)
    states = [gb.state(
        0, 'StandingState', standing_sm.ref,
        transitions=([(eid['moveStart'], 1, F_LOCAL)] if loco_sm else None))]
    if loco_sm:
        states.append(gb.state(1, 'LocomotionState', loco_sm.ref,
                               transitions=[(eid['moveStop'], 0, F_LOCAL)]))
    return gb.state_machine('DefaultBehavior', states), loco_sm, gait_eem
