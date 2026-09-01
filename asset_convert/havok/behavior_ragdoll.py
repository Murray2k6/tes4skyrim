"""The live-ragdoll tracking modifiers and the two death states.

Split out of hkx_behavior.build_behavior_xml.  Oblivion creatures ship no
death animations — death IS the ragdoll — so the whole death path is
generated, cloned from vanilla dogbehavior states 3 and 4.

Every constant here (bone subsets, blend durations, the release time) is a
measured vanilla value.  The bone SUBSETS especially are load-bearing:
keyframing more bones than a field names welds the corpse to its animation
pose and the ragdoll handover collapses.
See: docs/commentary/asset_convert_creature.md#ragdoll-bone-subsets
"""

from asset_convert.havok.behavior_nodes import (
    F_WILD,
    TRANSITION_TMPL,
    TRIGGER_TMPL,
)

#: Vanilla dogbehavior #0125 hkbRigidBodyRagdollControlsModifier controlData.
RB_RAGDOLL_CONTROL_DATA = (
    '<hkobject>\n'
    '\t<hkparam name="keyFrameHierarchyControlData">\n'
    '\t\t<hkobject>\n'
    '\t\t\t<hkparam name="hierarchyGain">0.170000</hkparam>\n'
    '\t\t\t<hkparam name="velocityDamping">0.000000</hkparam>\n'
    '\t\t\t<hkparam name="accelerationGain">1.000000</hkparam>\n'
    '\t\t\t<hkparam name="velocityGain">0.600000</hkparam>\n'
    '\t\t\t<hkparam name="positionGain">0.050000</hkparam>\n'
    '\t\t\t<hkparam name="positionMaxLinearVelocity">1.400000</hkparam>\n'
    '\t\t\t<hkparam name="positionMaxAngularVelocity">1.800000</hkparam>\n'
    '\t\t\t<hkparam name="snapGain">0.100000</hkparam>\n'
    '\t\t\t<hkparam name="snapMaxLinearVelocity">0.300000</hkparam>\n'
    '\t\t\t<hkparam name="snapMaxAngularVelocity">0.300000</hkparam>\n'
    '\t\t\t<hkparam name="snapMaxLinearDistance">0.030000</hkparam>\n'
    '\t\t\t<hkparam name="snapMaxAngularDistance">0.100000</hkparam>\n'
    '\t\t</hkobject>\n'
    '\t</hkparam>\n'
    '\t<hkparam name="durationToBlend">0.500000</hkparam>\n'
    '</hkobject>')

#: 8 frames after AnimateToRagdoll entry (the wolf's `Ragdoll:0.267`).
RAGDOLL_RELEASE_T = 0.266667


# ---------------------------------------------------------------------------
# Shared modifiers
# ---------------------------------------------------------------------------

def _keyframe_bones(gb, name, bone_indices):
    """An hkbKeyframeBonesModifier pinning `bone_indices` to the pose."""
    mod = gb.add('hkbKeyframeBonesModifier')
    mod.param('variableBindingSet', 'null')
    mod.param('userData', 1)
    mod.param('name', name)
    mod.param('enable', True)
    mod.param_raw('keyframeInfo', '', numelements=0)
    mod.param('keyframedBonesList', gb.bone_index_array(bone_indices).ref)
    return mod


def _drive_ragdoll(gb):
    """The PD controller driving the rigid bodies toward the pose."""
    mod = gb.add('hkbRigidBodyRagdollControlsModifier')
    mod.param('variableBindingSet', 'null')
    mod.param('userData', 1)
    mod.param('name', 'DriveRagdollRB')
    mod.param('enable', True)
    mod.param_raw('controlData', RB_RAGDOLL_CONTROL_DATA)
    mod.param('bones', gb.bone_index_array([]).ref)
    return mod


def live_tracking(gb, ragdoll):
    """Modifier refs keeping a LIVING actor's ragdoll bodies on the pose.

    Uses `keyframe_lower`, never every bone.
    See: docs/commentary/asset_convert_creature.md#ragdoll-bone-subsets
    """
    if not ragdoll:
        return []
    kf = _keyframe_bones(gb, 'KeyframeLowerBody', ragdoll['keyframe_lower'])
    return [kf.ref, _drive_ragdoll(gb).ref]


# ---------------------------------------------------------------------------
# Death states
# ---------------------------------------------------------------------------

def _powered_ragdoll(gb, name, max_force, mode, pose_bones):
    """An hkbPoweredRagdollControlsModifier at `max_force`."""
    pb0, pb1, pb2 = pose_bones
    weights = gb.add('hkbBoneWeightArray')
    weights.param('variableBindingSet', 'null')
    weights.param_array('boneWeights', [])
    m = gb.add('hkbPoweredRagdollControlsModifier')
    m.param('variableBindingSet', 'null')
    m.param('userData', 1)
    m.param('name', name)
    m.param('enable', True)
    m.param_raw('controlData', (
        '<hkobject>\n'
        f'\t<hkparam name="maxForce">{max_force:.6f}</hkparam>\n'
        '\t<hkparam name="tau">0.800000</hkparam>\n'
        '\t<hkparam name="damping">1.000000</hkparam>\n'
        '\t<hkparam name="proportionalRecoveryVelocity">2.000000'
        '</hkparam>\n'
        '\t<hkparam name="constantRecoveryVelocity">1.000000'
        '</hkparam>\n'
        '</hkobject>'))
    m.param('bones', gb.bone_index_array([]).ref)
    m.param_raw('worldFromModelModeData', (
        '<hkobject>\n'
        f'\t<hkparam name="poseMatchingBone0">{pb0}</hkparam>\n'
        f'\t<hkparam name="poseMatchingBone1">{pb1}</hkparam>\n'
        f'\t<hkparam name="poseMatchingBone2">{pb2}</hkparam>\n'
        f'\t<hkparam name="mode">{mode}</hkparam>\n'
        '</hkobject>'))
    m.param('boneWeights', weights.ref)
    return m


def _pose_clip(gb, clips):
    """The frozen pose source, single-play, releasing on its own trigger.

    See: docs/commentary/asset_convert_creature.md#the-death-pose-source
    """
    trig = gb.add('hkbClipTriggerArray')
    trig.param_raw('triggers', TRIGGER_TMPL.format(
        time=RAGDOLL_RELEASE_T, event_id=gb.eid['Ragdoll'], rel='false'),
        numelements=1)
    return gb.clip('FullyRagdollPose', clips['idle'], False,
                   triggers_ref=trig.ref, anim='ragdollpose')


def _modifier_generator(gb, name, list_name, modifier_refs, generator_ref):
    """A modifier list over `modifier_refs`, wrapped in a generator."""
    ml = gb.add('hkbModifierList')
    ml.param('variableBindingSet', 'null')
    ml.param('userData', 1)
    ml.param('name', list_name)
    ml.param('enable', True)
    ml.param_array('modifiers', modifier_refs)
    mg = gb.add('hkbModifierGenerator')
    mg.param('variableBindingSet', 'null')
    mg.param('userData', 1)
    mg.param('name', name)
    mg.param('modifier', ml.ref)
    mg.param('generator', generator_ref)
    return mg


def _fully_ragdoll(gb, ragdoll, pose_clip):
    """State 2's generator: the limp powered ragdoll over the pose.

    Vanilla #0092 'FullRagdoll' — active by default and released by
    GetUpBegin (inert for a corpse, kept for structural parity).
    """
    edm = gb.event_driven_modifier(
        'FullRagdoll',
        _powered_ragdoll(gb, 'PoweredRagdoll No Matching', 0.0,
                         'WORLD_FROM_MODEL_MODE_RAGDOLL',
                         ragdoll['pose_bones']).ref,
        -1, gb.eid['GetUpBegin'], True)
    return _modifier_generator(gb, 'Fully Ragdoll Mod Gen',
                               'Fully Ragdoll Mod List', [edm.ref],
                               pose_clip.ref)


def _contact_listener(gb, ragdoll):
    """Fires `Ragdoll` when a limb ROOT touches the ground.

    Uses `contact_bones`, never the toe tips or tail.
    See: docs/commentary/asset_convert_creature.md#ragdoll-bone-subsets
    """
    listener = gb.add('BSRagdollContactListenerModifier')
    listener.param('variableBindingSet', 'null')
    listener.param('userData', 2)
    listener.param('name', 'CollisionListener')
    listener.param('enable', True)
    listener.param_raw('contactEvent', (
        '<hkobject>\n'
        f'\t<hkparam name="id">{gb.eid["Ragdoll"]}</hkparam>\n'
        '\t<hkparam name="payload">null</hkparam>\n'
        '</hkobject>'))
    listener.param('bones', gb.bone_index_array(ragdoll['contact_bones']).ref)
    return listener


def _animate_to_ragdoll(gb, ragdoll, pose_clip):
    """State 1's generator: the freshly added bodies, still keyframed.

    Uses `keyframe_full`, which leaves the deepest limb leaves unpinned.
    See: docs/commentary/asset_convert_creature.md#ragdoll-bone-subsets
    """
    kf = _keyframe_bones(gb, 'KeyframeFullRagdoll', ragdoll['keyframe_full'])
    return _modifier_generator(
        gb, 'AnimateToRagdoll Mod Gen', 'AnimateToRagdoll ModList',
        [kf.ref, _drive_ragdoll(gb).ref, _contact_listener(gb, ragdoll).ref],
        pose_clip.ref)


def _ragdoll_blend(gb):
    """Vanilla #0082: DeathAnimation and Ragdoll blend over 0.2s."""
    return gb.blend_effect('RagdollBlend', 0.2,
                           'SELF_TRANSITION_MODE_BLEND', 0)


def death_states(gb, ragdoll, clips):
    """The two death states and the root wildcard entering them.

    Returns `(states, wildcard_ref)`; `([], 'null')` without a ragdoll.
    State 1 'AnimateToRagdoll' raises `AddRagdollToWorld` from its
    enterNotifyEvents — the ONLY thing in the pipeline that ever does —
    and state 2 'Fully Ragdoll' notifies
    RemoveCharacterControllerFromWorld.  Both are required: without state 1
    the corpse has no ragdoll and, since state 2 still removes the
    character controller, no collision at all.
    """
    if not (ragdoll and clips['idle']):
        return [], 'null'
    eid = gb.eid
    pose_clip = _pose_clip(gb, clips)
    full_rag = _fully_ragdoll(gb, ragdoll, pose_clip)
    rag_fx = _ragdoll_blend(gb)
    a2r_gen = _animate_to_ragdoll(gb, ragdoll, pose_clip)

    a2r_trans = gb.add('hkbStateMachineTransitionInfoArray')
    a2r_trans.param_raw('transitions', TRANSITION_TMPL.format(
        effect=rag_fx.ref, event_id=eid['Ragdoll'], to_state=2,
        flags='FLAG_DISABLE_CONDITION'), numelements=1)

    states = [
        gb.root_state(1, 'AnimateToRagdoll', a2r_gen.ref,
                      'AddRagdollToWorld', a2r_trans.ref),
        gb.root_state(2, 'Fully Ragdoll', full_rag.ref,
                      'RemoveCharacterControllerFromWorld'),
    ]
    root_wild = gb.add('hkbStateMachineTransitionInfoArray')
    root_wild.param_raw('transitions', '\n'.join(
        TRANSITION_TMPL.format(effect=e, event_id=ev, to_state=s,
                               flags=F_WILD)
        for ev, s, e in ((eid['DeathAnimation'], 1, rag_fx.ref),
                         (eid['Ragdoll'], 2, rag_fx.ref),
                         (eid['RagdollInstant'], 2, 'null'))), numelements=3)
    return states, root_wild.ref
