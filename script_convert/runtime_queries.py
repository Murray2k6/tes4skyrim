"""OBSE queries backed by engine state or preserved authored metadata."""

import json

from .commands import command
from .runtime_commands import _subject
from .constants import _safe_property_name


@command('getgamerestarted', 'getgameloaded', bare=True)
def game_transition(ctx, call):
    return f'TES4Runtime.GameTransition({"True" if call.name == "getgamerestarted" else "False"})'


@command('getgamedifficulty', bare=True)
def game_difficulty(ctx, call):
    """Expose Skyrim's difficulty selection on the OBSE slider scale."""
    return 'TES4SKSE.GetGameDifficulty()'


@command('getvariable', 'getrefvariable')
def script_variable(ctx, call):
    subject = (call.arg(1, wanted='Form') if len(call) > 1 else
               ctx._resolve_objref_ref(call.ref, call.extends))
    raw = call.source(0).strip('"')
    variable = (call.arg(0) if ctx.type_of(raw) == 'String' else
                json.dumps(_safe_property_name(raw)))
    method = 'ReadReferenceVariable' if call.name == 'getrefvariable' else 'ReadVariable'
    return f'TES4Runtime.{method}({subject}, {variable})'


@command('gettrainerskill', 'gettrainerlevel', bare=True)
def trainer_query(ctx, call):
    field = 'TrainerSkill' if call.name == 'gettrainerskill' else 'TrainerLevel'
    return f'TES4Runtime.SourceInt({_subject(ctx, call)}, "{field}")'


@command('getfatiguepercentage', bare=True)
def fatigue_percentage(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    return f'{subject}.GetActorValuePercentage("Stamina")'


@command('getteleportcell', bare=True)
def teleport_cell(ctx, call):
    return f'TES4Runtime.GetTeleportCell({ctx._resolve_objref_ref(call.ref, call.extends)})'


@command('getdoorteleportx', 'getdoorteleporty', 'getdoorteleportz', 'getdoorteleportrot', bare=True)
def teleport_coordinate(ctx, call):
    suffix = call.name.removeprefix('getdoorteleport')
    axis = ('x', 'y', 'z', 'rot').index(suffix)
    subject = ctx._resolve_objref_ref(call.ref, call.extends)
    return f'TES4Runtime.GetTeleportCoordinate({subject}, {axis})'


@command('getequippedweaponpoison', 'setequippedweaponpoison', 'removeequippedweaponpoison', bare=True)
def equipped_weapon_poison(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    if call.name == 'getequippedweaponpoison':
        return f'TES4Runtime.GetEquippedWeaponPoison({subject})'
    remove = call.name == 'removeequippedweaponpoison'
    value = 'None' if remove else call.arg(0, wanted='Potion')
    return f'TES4Runtime.ChangeEquippedWeaponPoison({subject}, {value}, {str(remove)})'


@command('getboundingbox', bare=True)
def bounding_box(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    return f'TES4Collection.BoundingBox({subject})'


@command('getallies', 'gettargets', bare=True)
def combat_actors(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    return f'TES4Collection.CombatActors({subject}, {str(call.name == "gettargets")})'


@command('getpclastdroppeditemref', 'getpclastdroppeditem', bare=True)
def last_dropped(ctx, call):
    method = 'GetLastDroppedReference' if call.name.endswith('ref') else 'GetLastDroppedItem'
    return f'TES4Runtime.{method}()'


@command('getracespellcount', 'getnthracespell', 'getspellcount', 'getnthspell', bare=True)
def spell_list_query(ctx, call):
    nth = 'nth' in call.name
    offset = 1 if nth else 0
    if 'race' in call.name:
        race = (call.arg(offset, wanted='Race') if len(call) > offset else
                ctx._resolve_self_ref(call.ref, call.extends, actor_func=True) + '.GetRace()')
        return (f'{race}.GetNthSpell({call.arg(0, wanted="Int")})' if nth else
                f'{race}.GetSpellCount()')
    subject = (call.arg(offset, wanted='Form') if len(call) > offset else
               ctx._resolve_objref_ref(call.ref, call.extends))
    spells = f'TES4Collection.Spells({subject})'
    return (f'({spells}.GetForm({call.arg(0, wanted="Int")} as String) as Spell)' if nth else
            f'TES4Collections.Size({spells})')


@command('isflying', 'isonground', 'isinair', bare=True)
def character_state(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    state = {'isonground': 0, 'isinair': 2, 'isflying': 4}[call.name]
    return f'(TES4Runtime.GetCharacterState({subject}) == {state})'


@command('getvelocity', 'getverticalvelocity', 'setvelocity', 'setverticalvelocity', bare=True)
def actor_velocity(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    if call.name.startswith('get'):
        axis = 'z' if call.name == 'getverticalvelocity' else call.source(0).strip('"').lower()
        if axis not in ('x', 'y', 'z'):
            return ctx.note(f'{call.written()}: invalid velocity axis')
        return f'TES4Runtime.GetVelocity({subject}, {"xyz".index(axis)})'
    if call.name == 'setverticalvelocity':
        return f'TES4Runtime.SetVelocity({subject}, 0.0, 0.0, {call.arg(0, "0.0", wanted="Float")}, True)'
    values = ', '.join(call.arg(i, '0.0', wanted='Float') for i in range(3))
    return f'TES4Runtime.SetVelocity({subject}, {values})'


@command('asciitochar', 'getformidstring', 'getnthmodname', bare=True)
def text_query(ctx, call):
    if call.name == 'getformidstring':
        return f'TES4Runtime.GetFormIDString({_subject(ctx, call)})'
    if call.name == 'getnthmodname':
        return f'Game.GetModName({call.arg(0, "0", wanted="Int")})'
    return f'TES4Runtime.AsciiToChar({call.arg(0, "0", wanted="Int")})'


_CLIMATE_FIELDS = {('getclimate' + name).lower(): index for index, name in enumerate((
    'SunriseBegin', 'SunriseEnd', 'SunsetBegin', 'SunsetEnd', 'MoonPhaseLength', 'HasMasser', 'HasSecunda'))}


@command(*_CLIMATE_FIELDS)
def climate_query(ctx, call):
    value = f'TES4Runtime.GetClimateNumber({call.arg(0, "None", wanted="Form")}, {_CLIMATE_FIELDS[call.name]})'
    return f'({value} != 0)' if 'has' in call.name else value


@command('seteventhandler', 'removeeventhandler')
def event_handler(ctx, call):
    from .tes4.nodes import BinOp
    from .emit.expr import emit, emit_source
    filters = {'ref': 'None', 'object': 'None'}
    for node in call.args[2:]:
        if isinstance(node, BinOp) and node.op == '::':
            key = emit_source(node.left).strip('"').lower()
            key = {'first': 'ref', 'second': 'object'}.get(key, key)
            if key in filters:
                filters[key] = ctx.bind_value_record(node.right) or emit(ctx, node.right, call.extends)
    enabled = 'True' if call.name == 'seteventhandler' else 'False'
    event = call.source(0).strip('"').lower()
    if event not in {'onactorequip', 'onactorunequip', 'onhit', 'onhitwith',
                     'ondeath', 'onactivate', 'onstartcombat', 'onspellcast',
                     'onscrollcast', 'onmagiceffecthit', 'onmagiceffecthit2',
                     'onmagicapply', 'onactordrop', 'loadgame', 'savegame',
                     'postloadgame'}:
        ctx.note(f'{call.raw_name}: event source {event} still needs a Skyrim producer')
    return (f'TES4Runtime.EventHandler({call.arg(0, wanted="String")}, '
            f'{call.arg(1, wanted="Form")}, {filters["ref"]}, {filters["object"]}, {enabled})')


@command('getracevoice', 'setracevoice')
def race_voice(ctx, call):
    race = call.arg(0, 'None', wanted='Race')
    if call.name == 'getracevoice':
        return f'TES4Runtime.GetRaceVoice({race}, {call.arg(1, "0", wanted="Int")})'
    return f'TES4Runtime.SetRaceVoice({race}, {call.arg(1, "None", wanted="Race")}, {call.arg(2, "2", wanted="Int")})'


@command('getdisposition', bare=True)
def disposition(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    return f'TES4Runtime.GetDisposition({subject}, {call.arg(0, "Game.GetPlayer()", wanted="Actor")})'


@command('setignorefriendlyhits', 'sifh')
def friendly_hits(ctx, call):
    subject = ctx._resolve_objref_ref(call.ref, call.extends)
    return f'{subject}.IgnoreFriendlyHits(({call.arg(0, "1")} as Bool))'


@command('setrefessential')
def reference_essential(ctx, call):
    subject = ctx._resolve_objref_ref(call.ref, call.extends)
    return f'TES4SKSE.SetRefEssential({subject}, ({call.arg(0, "0")} as Bool))'


@command('setcombatstyle', 'sendtrespassalarm', 'gettalkedtopc', 'getisplayablerace', bare=True)
def actor_engine_command(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    if call.name in ('gettalkedtopc', 'getisplayablerace'):
        method = 'GetTalkedToPC' if call.name == 'gettalkedtopc' else 'GetIsPlayableRace'
        return f'TES4Runtime.{method}({subject})'
    if call.name == 'sendtrespassalarm':
        return f'TES4Runtime.SendTrespassAlarm({subject}, {call.arg(0, "Game.GetPlayer()", wanted="Actor")})'
    return f'TES4Runtime.SetCombatStyle({subject}, {call.arg(0, "None", wanted="CombatStyle")})'


@command('getcurrentaipackage', 'getpackagetarget', 'addscriptpackage', 'removescriptpackage', bare=True)
def actor_package(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    if call.name == 'addscriptpackage':
        return f'TES4Runtime.AddScriptPackage({subject}, {call.arg(0, "None", wanted="Package")})'
    method = {'getcurrentaipackage': 'GetCurrentAIPackage',
              'getpackagetarget': 'GetPackageTarget',
              'removescriptpackage': 'RemoveScriptPackage'}[call.name]
    return f'TES4Runtime.{method}({subject})'


@command('saa', 'setactoralpha', 'setalpha')
def actor_alpha(ctx, call):
    subject = ctx._resolve_objref_ref(call.ref, call.extends)
    return f'TES4Runtime.SetAlpha({subject}, {call.arg(0, "1.0")})'


@command('lookat', 'look', 'setlookat')
def look_at(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    return f'{subject}.SetLookAt({call.arg(0, "None", wanted="ObjectReference")})'


@command('getworldmapdoor', 'getmapmenumarkername', 'getmapmenumarkerref', 'getmapmarkers', 'getmapmarkertype', bare=True)
def map_query(ctx, call):
    if call.name == 'getmapmarkers':
        return f'TES4Collection.MapMarkers(({call.arg(0, "1")} as Int), ({call.arg(1, "0")} as Int))'
    if call.name == 'getmapmarkertype':
        subject = ctx._resolve_objref_ref(call.ref, call.extends)
        return f'TES4Runtime.GetMapMarkerType({subject})'
    method = {'getworldmapdoor': 'GetWorldMapDoor', 'getmapmenumarkername': 'GetMapMenuMarkerName',
              'getmapmenumarkerref': 'GetMapMenuMarkerRef'}[call.name]
    return f'TES4Runtime.{method}()'


@command('getinvestmentgold', 'setinvestmentgold', bare=True)
def investment(ctx, call):
    subject = ctx._resolve_objref_ref(call.ref, call.extends)
    if call.name == 'getinvestmentgold':
        return f'TES4Runtime.GetInvestmentGold({subject})'
    return f'TES4Runtime.SetInvestmentGold({subject}, ({call.arg(0, "0")} as Int))'


_EQUIPPED_VALUE = tuple(prefix + 'equippedcurrent' + field
                        for prefix in ('get', 'set', 'mod') for field in ('health', 'charge'))


@command(*_EQUIPPED_VALUE)
def equipped_value(ctx, call):
    operation = {'get': 0, 'set': 1, 'mod': 2}[call.name[:3]]
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    slot = call.arg(1 if operation else 0, '0')
    value = call.arg(0, '0.0') if operation else '0.0'
    charge = 'True' if call.name.endswith('charge') else 'False'
    return f'TES4Runtime.EquippedValue({subject}, ({slot} as Int), {charge}, {operation}, {value})'


@command('resetallvariables', bare=True)
def reset_variables(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends)
    return f'TES4Runtime.ResetAllVariables({subject})'


@command('getactivequest', 'mqgetactivequest', 'setactivequest', 'clearactivequest', bare=True)
def active_quest(ctx, call):
    if call.name in ('getactivequest', 'mqgetactivequest'):
        return 'TES4Runtime.GetActiveQuest()'
    subject = call.arg(0, 'None', wanted='Quest') if call.name == 'setactivequest' else 'None'
    return f'TES4Runtime.SetActiveQuest({subject})'


@command('getpcsleephours', bare=True)
def sleep_package(ctx, call):
    return 'TES4Runtime.GetPCSleepHours()'


@command('isharvested', 'setharvested', bare=True)
def harvested(ctx, call):
    subject = ctx._resolve_objref_ref(call.ref, call.extends)
    if call.name == 'isharvested':
        return f'{subject}.IsHarvested()'
    return f'{subject}.SetHarvested(({call.arg(0, "0")} as Bool))'


@command('getnthpackage', 'getnumpackages', bare=True)
def package_list(ctx, call):
    if call.name == 'getnumpackages':
        return f'TES4Runtime.GetNumPackages({_subject(ctx, call)})'
    subject = call.arg(1) if len(call) > 1 else ctx._resolve_self_ref(call.ref, call.extends)
    return f'TES4Runtime.GetNthPackage({subject}, ({call.arg(0, "0")} as Int))'


@command('getmusictype', 'getcellmusictype', bare=True)
def cell_music(ctx, call):
    return 'TES4Runtime.SourceInt(Game.GetPlayer().GetParentCell(), "CellMusicType")'


@command('getprojectiletype', 'getprojectilesource', 'getmagicprojectilespell', 'getprojectile', bare=True)
def projectile_query(ctx, call):
    if call.name == 'getprojectile':
        subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
        return (f'TES4Runtime.GetProjectile({subject}, ({call.arg(0, "0")} as Int), '
                f'{call.arg(1, "9999.0")}, {call.arg(2, "None")})')
    method = {'getprojectiletype': 'GetProjectileType', 'getprojectilesource': 'GetProjectileSource',
              'getmagicprojectilespell': 'GetMagicProjectileSpell'}[call.name]
    subject = ctx._resolve_self_ref(call.ref, call.extends)
    return f'TES4Runtime.{method}({subject})'


_EFFECT_FORMS = {('getnthactiveeffect' + name).lower(): name for name in
                 ('MagicItem', 'Caster', 'Object', 'SummonRef', 'BoundItem', 'Data')}
_EFFECT_NUMBERS = {('getnthactiveeffect' + name).lower(): name for name in
                   ('Duration', 'TimeElapsed', 'Magnitude')}


_ACTOR_STATES = {name.lower(): name for name in
                 ('IsAttacking', 'IsPowerAttacking', 'IsTrespassing', 'GetActorLightAmount',
                  'IsSwimming', 'GetIgnoreFriendlyHits', 'IsPlayersLastRiddenHorse', 'GetIsAlerted',
                  'IsBlocking', 'GetForceRun', 'GetForceSneak', 'IsMovingForward', 'IsTorchOut')}


@command(*_ACTOR_STATES, 'getplayerspell', 'getactivespell', 'getgodmode', bare=True)
def actor_state(ctx, call):
    if call.name == 'getgodmode':
        return 'TES4Runtime.GetGodMode()'
    if call.name in ('getplayerspell', 'getactivespell'):
        return 'TES4Runtime.GetPlayerSpell()'
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    return f'TES4Runtime.{_ACTOR_STATES[call.name]}({subject})'


@command('getshouldattack')
def should_attack(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    return f'TES4Runtime.GetShouldAttack({subject}, {call.arg(0, "None", wanted="Actor")})'


@command('setforcerun', 'setforcesneak')
def force_movement(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    enabled = call.arg(0, 'False', wanted='Bool')
    return f'TES4Runtime.SetForcedMovement({subject}, ({enabled}) as Bool, {"True" if call.name == "setforcesneak" else "False"})'


@command('iscurrentfurnitureref', 'iscurrentfurnitureobj')
def current_furniture(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    base = call.name == 'iscurrentfurnitureobj'
    target = call.arg(0, 'None', wanted='Form' if base else 'ObjectReference')
    return f'TES4Runtime.IsCurrentFurniture({subject}, {target}, {"True" if base else "False"})'


@command('gethorse', 'getrider', 'getplayerslastriddenhorse', 'getplayerhaslastriddenhorse', 'issnowing', bare=True)
def mount_weather_query(ctx, call):
    if call.name == 'getplayerhaslastriddenhorse':
        return 'TES4Runtime.GetPlayerHasLastRiddenHorse()'
    if call.name == 'getplayerslastriddenhorse':
        return 'TES4Runtime.GetPlayersLastRiddenHorse()'
    if call.name == 'issnowing':
        return 'TES4Runtime.IsSnowing()'
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    return f'TES4Runtime.GetHorse({subject}, {"True" if call.name == "getrider" else "False"})'


@command('clearownership_t')
def clear_owner_t(ctx, call):
    subject = ctx._resolve_objref_ref(call.ref, call.extends)
    return f'TES4Runtime.SetOwner({subject}, None, False)'


@command('gethighactors', 'getmiddlehighactors', 'getlowactors', bare=True)
def process_actors(ctx, call):
    level = {'gethighactors': 0, 'getmiddlehighactors': 1, 'getlowactors': 3}[call.name]
    return f'TES4Collection.Actors({level})'


@command('getbaseitems', 'getequippeditems', 'getspells', 'getleveledspells', bare=True)
def form_list(ctx, call):
    inventory = call.name in ('getbaseitems', 'getequippeditems')
    method = 'Inventory' if inventory else 'Spells'
    flag = call.name in ('getequippeditems', 'getleveledspells')
    return f'TES4Collection.{method}({_subject(ctx, call)}, {"True" if flag else "False"})'


@command('getitems', bare=True)
def inventory_items(ctx, call):
    subject = ctx._resolve_objref_ref(call.ref, call.extends)
    types = 'TES4Collection.Create()' if call.args else 'None'
    for index in range(min(len(call), 10)):
        types += f'.WithInteger("{index}", {call.arg(index, wanted="Int")})'
    return f'TES4Collection.Items({subject}, {types})'


@command(*_EFFECT_FORMS, *_EFFECT_NUMBERS, 'getactiveeffectcount',
         'getnthactiveeffectcode', 'isnthactiveeffectapplied', 'dispelnthactiveeffect', bare=True)
def active_effect_query(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    if call.name == 'getactiveeffectcount':
        return f'TES4Runtime.GetActiveEffectCount({subject})'
    args = f'{subject}, ({call.arg(0, "0")} as Int)'
    if call.name in _EFFECT_FORMS:
        return f'TES4Runtime.GetActiveEffectForm({args}, "{_EFFECT_FORMS[call.name]}")'
    if call.name in _EFFECT_NUMBERS:
        return f'TES4Runtime.GetActiveEffectNumber({args}, "{_EFFECT_NUMBERS[call.name]}")'
    method = {'getnthactiveeffectcode': 'GetActiveEffectCode',
              'isnthactiveeffectapplied': 'IsActiveEffectApplied',
              'dispelnthactiveeffect': 'DispelActiveEffect'}[call.name]
    return f'TES4Runtime.{method}({args})'


@command('getactiveeffectcodes', 'getactiveeffectcasters', bare=True)
def active_effect_array(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    casters = 'True' if call.name == 'getactiveeffectcasters' else 'False'
    return f'TES4Collection.ActiveEffects({subject}, {casters})'


@command('removemeir', 'equipme', 'unequipme', 'getcontainer')
def inventory_reference(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends)
    if call.name == 'getcontainer':
        if not call.ref and call.extends == 'ObjectReference':
            ctx.sc.uses_dropme = True
            return 'TES4_Container'
        return f'TES4Runtime.GetInventoryContainer({subject})'
    if call.name == 'removemeir':
        return f'TES4Runtime.RemoveInventoryReference({subject}, {call.arg(0, "None")})'
    return f'TES4Runtime.EquipInventoryReference({subject}, {"True" if call.name == "equipme" else "False"})'


@command('getnumfactions', 'getnthfaction', 'getnthfactionrank', 'getfactions')
def faction_query(ctx, call):
    if call.name in ('getnumfactions', 'getfactions'):
        method = 'GetNumFactions' if call.name == 'getnumfactions' else 'GetFactions'
        return f'TES4Runtime.{method}({_subject(ctx, call)})'
    subject = call.arg(1) if len(call) > 1 else ctx._resolve_self_ref(call.ref, call.extends)
    method = 'GetNthFactionRank' if call.name == 'getnthfactionrank' else 'GetNthFaction'
    return f'TES4Runtime.{method}({subject}, ({call.arg(0)} as Int))'


@command('getfactionreaction', 'setfactionreaction', 'modfactionreaction')
def faction_reaction(ctx, call):
    name = {'getfactionreaction': 'GetFactionReaction',
            'setfactionreaction': 'SetFactionReaction',
            'modfactionreaction': 'ModFactionReaction'}[call.name]
    args = f'({call.arg(0)} as Faction), ({call.arg(1)} as Faction)'
    if call.name != 'getfactionreaction':
        args += f', ({call.arg(2)} as Int)'
    return f'TES4Runtime.{name}({args})'


_SOURCE = {'getservicesmask': 'Services', 'getclassspecialization': 'ClassSpecialization',
           'getbartergold': 'BarterGold', 'getminlevel': 'MinLevel', 'getmaxlevel': 'MaxLevel', 'getactorbaselevel': 'ActorBaseLevel',
           'getcreaturecombatskill': 'CreatureCombatSkill', 'getcreaturemagicskill': 'CreatureMagicSkill',
           'getcreaturestealthskill': 'CreatureStealthSkill', 'getapparatustype': 'ApparatusType',
           'isscripted': 'IsScripted',
           'getcreaturesoullevel': 'CreatureSoul', 'getactorsoullevel': 'CreatureSoul',
           'getobjecthealth': 'ObjectHealth', 'getattackdamage': 'AttackDamage', 'getobjectcharge': 'ObjectCharge'}
_FLAGS = {'offersrepair': ('Services', 1 << 17), 'offersrecharging': ('Services', 1 << 16),
          'isobliviongate': ('DoorFlags', 1),
          'hasnopersuasion': ('ActorFlags', 32768),
          'isfactionevil': ('Flags', 2), 'isfactionhidden': ('Flags', 1),
          'factionhasspecialcombat': ('Flags', 4),
          'offersweapons': ('Services', 1), 'offersarmor': ('Services', 2),
          'offersclothing': ('Services', 4), 'offersbooks': ('Services', 8),
          'offersingredients': ('Services', 16), 'offerslights': ('Services', 128),
          'offersapparatus': ('Services', 256), 'offersmiscitems': ('Services', 1024),
          'offersmagicitems': ('Services', 4096), 'offerspotions': ('Services', 8192),
          'offersspells': ('Services', 1 << 11), 'offerstraining': ('Services', 1 << 14),
          'isactorrespawning': ('ActorFlags', 8), 'ispcLeveloffset': ('ActorFlags', 128),
          'issummonable': ('ActorFlags', 16384), 'isquestitem': ('RecordFlags', 1024),
          'creatureusesweaponandshield': ('ActorFlags', 4), 'creaturehasnohead': ('ActorFlags', 32768),
          'haslowlevelprocessing': ('ActorFlags', 512), 'getcontainerrespawns': ('Flags', 2)}
_FLAGS = {key.lower(): value for key, value in _FLAGS.items()}


@command(*_SOURCE, *_FLAGS, 'getclassskills', 'getscript', 'removescript', bare=True)
def authored_query(ctx, call):
    subject = _subject(ctx, call)
    if call.name == 'removescript':
        return f'TES4Runtime.RemoveScript({subject})'
    if call.name == 'getscript':
        return f'TES4Runtime.SourceForm({subject}, "Script")'
    if call.name == 'getclassskills':
        result = 'TES4Collection.Create("Array")'
        for i in range(7):
            result += f'.WithNumber("{i}", TES4Runtime.SourceInt({subject}, "ClassSkill{i}", -1))'
        return result
    if call.name in _FLAGS:
        field, mask = _FLAGS[call.name]
        operation = '==' if call.name == 'haslowlevelprocessing' else '!='
        return f'(Math.LogicalAnd(TES4Runtime.SourceInt({subject}, "{field}"), {mask}) {operation} 0)'
    return f'TES4Runtime.SourceInt({subject}, "{_SOURCE[call.name]}")'


_NATIVES = {name.lower(): name for name in ('GetOwner', 'GetLinkedDoor', 'HasWater',
             'GetParentCellWaterHeight', 'IsInOblivion', 'GetSourceModIndex', 'IsPersistent', 'GetOpenKey',
             'GetBoundingRadius', 'GetWeight', 'GetEnchantment', 'GetEquipmentSlot', 'IsLightCarriable',
             'GetRefCount', 'GetCurrentHealth', 'GetCurrentCharge', 'IsEquipped', 'IsActivatable', 'IsOffLimits', 'DeleteReference')}
_REF_NATIVE = {'getlinkeddoor', 'getparentcellwaterheight', 'isinoblivion', 'ispersistent', 'getopenkey', 'getboundingradius', 'isactivatable', 'isofflimits', 'deletereference'}


@command(*_NATIVES, 'parentcellhaswater', 'isloaddoor', 'getmerchantcontainer', 'getparentcellowner', bare=True)
def reference_query(ctx, call):
    subject = _subject(ctx, call)
    if call.name == 'getparentcellowner':
        return f'TES4Runtime.GetOwner(({subject} as ObjectReference).GetParentCell())'
    if call.name == 'getmerchantcontainer':
        return f'(TES4Runtime.SourceForm({subject}, "MerchantContainer") as ObjectReference)'
    if call.name in ('isloaddoor', 'getlinkeddoor'):
        value = f'TES4Runtime.GetLinkedDoor(({subject}) as ObjectReference)'
        return f'({value} != None)' if call.name == 'isloaddoor' else value
    name = 'haswater' if call.name == 'parentcellhaswater' else call.name
    if name in _REF_NATIVE:
        subject = f'({subject}) as ObjectReference'
    return f'TES4Runtime.{_NATIVES[name]}({subject})'


@command('geteditorsize', 'getmodelpath', 'geticonpath', 'comparemodelpath', 'compareiconpath')
def model_query(ctx, call):
    if call.name.startswith('compare'):
        subject = call.arg(1) if len(call) > 1 else ctx._resolve_self_ref(call.ref, call.extends)
        field = 'ModelPath' if call.name == 'comparemodelpath' else 'IconPath'
        return f'TES4Runtime.SourceContains({subject}, "{field}", {call.arg(0)})'
    subject = _subject(ctx, call)
    if call.name == 'geteditorsize':
        return f'TES4Runtime.SourceFloat({subject}, "EditorSize", -1.0)'
    field = 'ModelPath' if call.name == 'getmodelpath' else 'IconPath'
    return f'TES4Runtime.SourceString({subject}, "{field}")'


@command('comparename', 'nameincludes')
def name_includes(ctx, call):
    subject = call.arg(1, wanted='Form') if len(call) > 1 else ctx._resolve_objref_ref(call.ref, call.extends)
    return f'TES4Runtime.NameIncludes({subject}, {call.arg(0, wanted="String")})'


@command('getquality', 'getcreaturebasescale', 'getcreaturemodelpaths', 'getingredient', bare=True)
def source_item_query(ctx, call):
    subject = _subject(ctx, call)
    if call.name == 'getingredient':
        return f'TES4Runtime.SourceForm({subject}, "Ingredient")'
    if call.name == 'getcreaturemodelpaths':
        return f'TES4Runtime.GetCreatureModelPaths({subject})'
    field, fallback = ('Quality', '0.0') if call.name == 'getquality' else ('CreatureBaseScale', '1.0')
    return f'TES4Runtime.SourceFloat({subject}, "{field}", {fallback})'


@command('isclonedform', 'hasname', 'getsoullevel', 'getcurrentsoullevel', 'getsoulgemcapacity', bare=True)
def basic_form_query(ctx, call):
    subject = _subject(ctx, call)
    if call.name == 'getcurrentsoullevel':
        return f'TES4Runtime.GetCurrentSoulLevel({subject})'
    if call.name in ('getsoullevel', 'getcurrentsoullevel', 'getsoulgemcapacity'):
        return f'TES4Runtime.GetSoulLevel({subject}, {"True" if call.name == "getsoulgemcapacity" else "False"})'
    method = 'IsClonedForm' if call.name == 'isclonedform' else 'HasName'
    return f'TES4Runtime.{method}({subject})'


@command('getequippedobject', 'getequipmentslottype')
def equipped_query(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    return f'TES4Runtime.GetEquippedObject({subject}, {call.arg(0)} as Int)'


@command('setcurrenthealth', 'setcurrentcharge', 'modcurrenthealth', 'modcurrentcharge')
def current_item_value(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends)
    field = 'Health' if call.name.endswith('health') else 'Charge'
    value = call.arg(0)
    if call.name.startswith('mod'):
        value = f'TES4Runtime.GetCurrent{field}({subject}) + {value}'
    return f'TES4Runtime.SetCurrent{field}({subject}, {value})'


@command('getparentworldspace', 'isfemale', 'getcombatstyle', 'isrefessential',
         'getcurrenteditorpackage', 'getcurrentweatherid', 'getcurrentclimateid', bare=True)
def engine_query(ctx, call):
    if call.name == 'getcurrentweatherid':
        return 'Weather.GetCurrentWeather()'
    if call.name == 'getcurrentclimateid':
        return 'TES4Runtime.GetCurrentClimateID()'
    subject = _subject(ctx, call)
    if call.name == 'getparentworldspace':
        return f'({subject} as ObjectReference).GetWorldSpace()'
    if call.name == 'getcurrenteditorpackage':
        return f'TES4Runtime.GetCurrentEditorPackage(({subject} as Actor))'
    base = f'(TES4SKSE.GetBaseForm({subject}) as ActorBase)'
    return {'isfemale': f'({base}.GetSex() == 1)',
            'isrefessential': f'{base}.IsEssential()',
            'getcombatstyle': f'{base}.GetCombatStyle()'}[call.name]
