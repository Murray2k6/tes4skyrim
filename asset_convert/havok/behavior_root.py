"""The root modifier list and the graph wrapper around it.

Split out of hkx_behavior.build_behavior_xml.  Everything under the root
state machine's single 'Root' state: the speed sampler that gives AI pathing
something to drive, the combat-stance reply pair the engine waits on, and the
per-feature expression modifiers each branch contributed.

Vanilla's layout is copied verbatim, userData values included — the whole
behavior state machine sits inside one hkbModifierGenerator, which is the
only child of a single-state root machine (the death states join it later).
See: docs/commentary/asset_convert_creature.md#the-speed-sampler-hookup
"""

from asset_convert.havok.behavior_nodes import VARIABLE_INFO_TMPL


# ---------------------------------------------------------------------------
# The graph's data tables
# ---------------------------------------------------------------------------

def graph_data(gb, events, variables, var_values):
    """The hkbBehaviorGraphData: string table, variable infos, initial values."""
    strings = gb.add('hkbBehaviorGraphStringData')
    strings.param_strings('eventNames', events)
    strings.param_array('attributeNames', [])
    strings.param_strings('variableNames', [n for n, _t, _iv in variables])
    strings.param_array('characterPropertyNames', [])

    values = gb.add('hkbVariableValueSet')
    values.param_structs('wordVariableValues',
                         [[('value', v)] for v in var_values])
    values.param_array('quadVariableValues', [])
    values.param_array('variantVariableValues', [])

    gdata = gb.add('hkbBehaviorGraphData')
    gdata.param_array('attributeDefaults', [])
    gdata.param_raw('variableInfos',
                    '\n'.join(VARIABLE_INFO_TMPL.format(vtype=t)
                              for _n, t, _iv in variables),
                    numelements=len(variables))
    gdata.param_structs('characterPropertyInfos', [])
    gdata.param_structs('eventInfos', [[('flags', 0)]] * len(events))
    gdata.param('variableInitialValues', values.ref)
    gdata.param('stringData', strings.ref)
    return gdata


# ---------------------------------------------------------------------------
# Root modifiers
# ---------------------------------------------------------------------------

def speed_sampler(gb):
    """The BSSpeedSamplerModifier the engine reads movement speed from.

    See: docs/commentary/asset_convert_creature.md#the-speed-sampler-hookup
    """
    binds = gb.binding_set([('state', 'iState'),
                            ('direction', 'Direction'),
                            ('goalSpeed', 'Speed'),
                            ('speedOut', 'SpeedSampled')])
    sampler = gb.add('BSSpeedSamplerModifier')
    sampler.param('variableBindingSet', binds.ref)
    sampler.param('userData', 2)
    sampler.param('name', 'BSSpeedSamplerModifier')
    sampler.param('enable', True)
    sampler.param('state', -1)
    sampler.param('direction', '0.000000')
    sampler.param('goalSpeed', '0.000000')
    sampler.param('speedOut', '0.000000')
    return sampler


def _combat_eem(gb, name, stance_val, reply_evt):
    """Sets iCombatStance and replies with `reply_evt` once it holds."""
    arr = gb.expression_array([
        (f'iCombatStance = {stance_val}', 'EVENT_MODE_SEND_ONCE'),
        (f'{reply_evt} if (iCombatStance == {stance_val})',
         'EVENT_MODE_SEND_ON_FALSE_TO_TRUE')])
    eem = gb.add('hkbEvaluateExpressionModifier')
    eem.param('variableBindingSet', 'null')
    eem.param('userData', 2)
    eem.param('name', name)
    eem.param('enable', True)
    eem.param('expressions', arr.ref)
    return eem


def combat_stance_pair(gb):
    """The StopCombat / StartCombat modifiers, in vanilla's order.

    Combat waits for the graph to reply weaponDraw before it will send any
    attack; without this pair the actor chases its target and never attacks.
    See: docs/commentary/asset_convert_creature.md#the-combat-stance-handshake
    """
    eid = gb.eid
    stop = gb.event_driven_modifier(
        'StopCombat_EDM',
        _combat_eem(gb, 'StopCombat_EEM', 0, 'weaponSheathe').ref,
        eid['combatStanceStop'], eid['combatStanceStart'], True)
    start = gb.event_driven_modifier(
        'StartCombat_EDM',
        _combat_eem(gb, 'StartCombat_EEM', 1, 'weaponDraw').ref,
        eid['combatStanceStart'], eid['combatStanceStop'], False)
    return stop, start


def root_generator(gb, behavior_sm, live_track, modifiers):
    """The RootModifierGenerator wrapping the whole behavior machine.

    `modifiers` are the optional per-feature EEMs in declaration order; the
    EquipDispatch one must run alongside the combat pair, since it turns the
    engine's weaponDraw/weaponSheathe into the per-weapon-class equip event.
    """
    sampler = speed_sampler(gb)
    stop, start = combat_stance_pair(gb)
    ml = gb.add('hkbModifierList')
    ml.param('variableBindingSet', 'null')
    ml.param('userData', 1)
    ml.param('name', 'RootModifierList')
    ml.param('enable', True)
    ml.param_array('modifiers',
                   list(live_track) + [stop.ref, start.ref, sampler.ref]
                   + [m.ref for m in modifiers if m is not None])
    mg = gb.add('hkbModifierGenerator')
    mg.param('variableBindingSet', 'null')
    mg.param('userData', 1)
    mg.param('name', 'RootModifierGenerator')
    mg.param('modifier', ml.ref)
    mg.param('generator', behavior_sm.ref)
    return mg


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

def behavior_graph(gb, behavior_name, root_states, root_wild_ref, gdata):
    """The root state machine, the graph and its container; renders the XML."""
    root_sm = gb.add('hkbStateMachine')
    root_sm.param('variableBindingSet', 'null')
    root_sm.param('userData', 0)
    root_sm.param('name', f'{behavior_name}RootBehavior')
    root_sm.param_raw('eventToSendWhenStateOrTransitionChanges', (
        '<hkobject>\n\t<hkparam name="id">-1</hkparam>\n'
        '\t<hkparam name="payload">null</hkparam>\n</hkobject>'))
    root_sm.param('startStateChooser', 'null')
    root_sm.param('startStateId', 0)
    root_sm.param('returnToPreviousStateEventId', -1)
    root_sm.param('randomTransitionEventId', -1)
    root_sm.param('transitionToNextHigherStateEventId', -1)
    root_sm.param('transitionToNextLowerStateEventId', -1)
    root_sm.param('syncVariableIndex', -1)
    root_sm.param('wrapAroundStateId', False)
    root_sm.param('maxSimultaneousTransitions', 32)
    root_sm.param('startStateMode', 'START_STATE_MODE_DEFAULT')
    root_sm.param('selfTransitionMode', 'SELF_TRANSITION_MODE_NO_TRANSITION')
    root_sm.param_array('states', [s.ref for s in root_states])
    root_sm.param('wildcardTransitions', root_wild_ref)

    graph = gb.add('hkbBehaviorGraph')
    graph.param('variableBindingSet', 'null')
    graph.param('userData', 0)
    graph.param('name', f'{behavior_name}.hkb')
    graph.param('variableMode', 'VARIABLE_MODE_DISCARD_WHEN_INACTIVE')
    graph.param('rootGenerator', root_sm.ref)
    graph.param('data', gdata.ref)

    top = gb.add('hkRootLevelContainer')
    top.param_structs('namedVariants', [
        [('name', 'hkbBehaviorGraph'), ('className', 'hkbBehaviorGraph'),
         ('variant', graph.ref)]])
    return gb.render(top)
