"""Typed calls to the converter's open-source Skyrim runtime."""

from .commands import command
from .constants import ACTOR_VALUE_MAP, TES4_ATTRIBUTES


_TYPE_TESTS = {'isactivator': 18, 'isapparatus': 19, 'isarmor': 20,
               'isbook': 21, 'isclothing': 22, 'iscontainer': 23, 'isdoor': 24,
               'isingredient': 25, 'islight': 26, 'ismisc': 27, 'isweapon': 33,
               'isammo': 34, 'isnpc': 35, 'iscreature': 36, 'issoulgem': 38,
               'iskey': 39, 'ispotion': 40, 'isflora': 31}


def _subject(ctx, call):
    return call.arg(0) if len(call) else ctx._resolve_objref_ref(call.ref, call.extends)


def _cell_destination(ctx, call, index):
    name = call.source(index).strip('"')
    fid = ctx.xref.edid_to_formid.get(name.lower(), '') if ctx.xref else ''
    # Exterior CELL forms cannot bind as Papyrus properties. Preserve the
    # authored identity for native lookup instead of creating an unbound Cell.
    if fid and ctx.xref.record_type.get(fid) == 'CELL':
        destination, editor = 'None', f'"{name}"'
    else:
        destination, editor = call.arg(index, 'None', wanted='Cell'), '""'
    return destination, editor


@command('positioncell')
def position_cell(ctx, call):
    ref = ctx._resolve_objref_ref(call.ref, call.extends)
    destination, editor = _cell_destination(ctx, call, 4)
    values = ', '.join(f'({call.arg(i, "0", wanted="Float")}) as Float' for i in range(4))
    return f'TES4Runtime.PositionCell({ref}, {destination}, {editor}, {values})'


@command('positionworld', 'posworld')
def position_world(ctx, call):
    ref = ctx._resolve_objref_ref(call.ref, call.extends)
    world = call.arg(4, 'None', wanted='WorldSpace')
    values = ', '.join(f'({call.arg(i, "0", wanted="Float")}) as Float' for i in range(4))
    return f'TES4Runtime.PositionWorld({ref}, {world}, {values})'


@command('getstartingpos', 'getstartingangle')
def starting_coordinate(ctx, call):
    axis = call.source(0).strip('"').lower()
    if axis not in ('x', 'y', 'z'):
        return ctx.note(f'{call.written()}: invalid coordinate axis')
    ref = ctx._resolve_objref_ref(call.ref, call.extends)
    angle = 'True' if call.name == 'getstartingangle' else 'False'
    return f'TES4Runtime.GetStartingCoordinate({ref}, {"xyz".index(axis)}, {angle})'


@command('rotate')
def rotate(ctx, call):
    """Preserve axis, integer angular speed and the update's elapsed time."""
    axis = call.source(0).strip('"').upper()
    if axis not in ('X', 'Y', 'Z'):
        return ctx.note(f'{call.written()}: invalid coordinate axis')
    ref = ctx._resolve_objref_ref(call.ref, call.extends)
    speed = call.arg(1, '0', wanted='Int')
    polling = ctx.sc.current_block_type.lower() in ('gamemode', 'scripteffectupdate')
    elapsed = 'TES4_SecondsPassed' if polling and ctx.sc.gsp_realtime else '-1.0'
    return f'TES4Polyfill.Rotate({ref}, "{axis}", {speed}, {elapsed})'


@command('getworldspaceparentworldspace', 'getworldparentworld')
def parent_world(ctx, call):
    return f'TES4Runtime.GetParentWorld({call.arg(0, "None", wanted="WorldSpace")})'


@command('setcellpublicflag', 'setcellownership', 'setcellfullname')
def cell_state(ctx, call):
    destination, editor = _cell_destination(ctx, call, 0)
    if call.name == 'setcellfullname':
        return f'TES4Runtime.SetCellName({destination}, {editor}, {call.arg(1, '""', wanted="String")})'
    if call.name == 'setcellpublicflag':
        value = call.arg(1, 'False', wanted='Bool')
        return f'TES4Runtime.SetCellPublic({destination}, {editor}, ({value}) as Bool)'
    owner = call.arg(1, 'Game.GetPlayer()', wanted='Form')
    return f'TES4Runtime.SetCellOwner({destination}, {editor}, {owner})'


@command('getterrainheight')
def terrain_height(ctx, call):
    return f'TES4Runtime.GetTerrainHeight({call.arg(0, "0.0", wanted="Float")}, {call.arg(1, "0.0", wanted="Float")})'


@command('getname')
def form_name(ctx, call):
    return f'TES4Runtime.GetName({_subject(ctx, call)})'


@command('setname', 'setnameex')
def rename_form(ctx, call):
    source = call.source(0)
    consumed = (sum(m.group(0).lower() not in ('%%', '%r', '%q', '%e')
                    for m in ctx._OBSE_FMT_RE.finditer(source))
                if call.name == 'setnameex' and source.startswith('"') else 0)
    index = 1 + consumed
    value = (ctx._format_string_call(source, call.extends, range(1, index))
             if call.name == 'setnameex' and source.startswith('"') else call.arg(0))
    subject = call.arg(index) if len(call) > index else ctx._resolve_self_ref(call.ref, call.extends)
    return f'TES4Runtime.SetName({subject}, {value})'


@command('setactorfullname')
def actor_full_name(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    return f'TES4Runtime.SetActorFullName({subject}, {call.arg(0, chr(34) + chr(34), wanted="String")})'


@command('copyname', 'appendtoname')
def edit_base_name(ctx, call):
    caller = ctx._resolve_self_ref(call.ref, call.extends)
    target = call.arg(1, 'None', wanted='Form')
    if call.name == 'copyname':
        return f'TES4Runtime.CopyName({call.arg(0, "None", wanted="Form")}, {target}, {caller})'
    suffix = call.arg(0, '""', wanted='String')
    return f'TES4Runtime.AppendToName({suffix}, {target}, {caller})'


@command('getdescription')
def description(ctx, call):
    if len(call) > 1:
        return None  # TES4 skill-rank text needs a separate source mapping.
    return f'TES4Runtime.GetDescription({_subject(ctx, call)})'


@command(*_TYPE_TESTS, 'isactor', bare=True)
def type_test(ctx, call):
    subject = f'TES4Runtime.GetObjectType({_subject(ctx, call)})'
    if call.name == 'isactor':
        return f'({subject} == 35 || {subject} == 36)'
    return f'({subject} == {_TYPE_TESTS[call.name]})'


@command('getclass', 'getarmortype', 'getweapontype', 'isfood')
def item_traits(ctx, call):
    subject = _subject(ctx, call)
    if call.name == 'getclass':
        return f'(TES4SKSE.GetBaseForm({subject}) as ActorBase).GetClass()'
    method = {'getarmortype': 'GetArmorType', 'getweapontype': 'GetWeaponType',
              'isfood': 'IsFood'}[call.name]
    return f'TES4Runtime.{method}({subject})'


_SKILL_CODES = {name.lower(): index for index, name in enumerate((
    'Armorer', 'Athletics', 'Blade', 'Block', 'Blunt', 'HandToHand', 'HeavyArmor',
    'Alchemy', 'Alteration', 'Conjuration', 'Destruction', 'Illusion', 'Mysticism',
    'Restoration', 'Acrobatics', 'LightArmor', 'Marksman', 'Mercantile', 'Security',
    'Sneak', 'Speechcraft'), 12)}


@command('isclassskill', 'ismajor', 'isclassskillc', 'ismajorc', 'ismajorref')
def class_skill(ctx, call):
    skill = _SKILL_CODES.get(call.source(0).strip('"').lower())
    code = str(skill) if skill is not None else call.arg(0, '-1', wanted='Int')
    subject = (call.arg(1, wanted='Form') if len(call) > 1 else
               ctx._resolve_self_ref(call.ref, call.extends))
    return f'TES4Runtime.IsClassSkill({subject}, ({code}) as Int)'


_AV_CODE_NAMES = {index: name for name, index in _SKILL_CODES.items()}
_AV_CODE_NAMES.update(enumerate(('strength', 'intelligence', 'willpower', 'agility',
                                'speed', 'endurance', 'personality', 'luck',
                                'health', 'magicka', 'fatigue', 'encumbrance')))
_AV_CODE_NAMES.update(enumerate(('aggression', 'confidence', 'energy', 'responsibility'), 33))
_AV_CODE_NAMES.update(enumerate((
    'bounty', 'fame', 'infamy', 'magickamultiplier', 'nighteyebonus', 'attackbonus',
    'defendbonus', 'castingpenalty', 'blindness', 'chameleon', 'invisibility', 'paralysis',
    'silence', 'confusion', 'detectitemrange', 'spellabsorbchance', 'spellreflectchance',
    'swimspeedmultiplier', 'waterbreathing', 'waterwalking', 'stuntedmagicka', 'detectliferange',
    'reflectdamage', 'telekinesis', 'resistfire', 'resistfrost', 'resistdisease', 'resistmagic',
    'resistnormalweapons', 'resistparalysis', 'resistpoison', 'resistshock', 'vampirism',
    'darkness', 'resistwaterdamage'), 37))


@command('getactorvaluec', 'getavc', 'getbaseactorvaluec', 'getbaseavc',
         'getbaseav2', 'getbaseav2c', 'getmaxav', 'getmaxavc')
def extended_actor_value(ctx, call):
    name = call.source(0).strip('"').lower()
    if call.name.endswith('c'):
        try:
            name = _AV_CODE_NAMES[int(name, 0)]
        except (ValueError, KeyError):
            return ctx.note(f'{call.written()}: source actor-value code needs runtime resolution')
    if name == 'vampirism':
        return vampire_value(ctx, call)
    if name in TES4_ATTRIBUTES:
        return ctx.note(f'{call.written()}: requires converted attribute state')
    if name not in ACTOR_VALUE_MAP:
        return ctx.note(f'{call.written()}: requires a converted actor-value equivalent')
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    av = ACTOR_VALUE_MAP.get(name, name)
    if call.name.startswith('getmax'):
        return f'TES4Runtime.GetMaxActorValue({subject}, "{av}")'
    method = 'GetBaseActorValue' if call.name.startswith('getbase') else 'GetActorValue'
    if name == 'encumbrance' and method == 'GetActorValue':
        av = 'InventoryWeight'
    return f'{subject}.{method}("{av}")'


@command('getavforbaseactor', 'getavforbaseactorc')
def base_actor_value(ctx, call):
    if call.name.endswith('c'):
        code = call.arg(0, '-1', wanted='Int')
    else:
        name = call.source(0).strip('"').lower()
        code = str(next((i for i, value in _AV_CODE_NAMES.items() if value == name), -1))
    subject = (call.arg(1, wanted='Form') if len(call) > 1 else
               ctx._resolve_objref_ref(call.ref, call.extends))
    return f'TES4ActorValues.GetBase({subject}, {code})'


def vampire_value(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    if call.name.startswith('get'):
        base = 'True' if call.name.startswith('getbase') else 'False'
        return f'TES4Runtime.GetVampirism({subject}, {base})'
    operation = 2 if call.name.startswith('force') else 1 if call.name.startswith('mod') else 0
    return f'TES4Runtime.ChangeVampirism({subject}, {call.arg(1, "0", wanted="Float")}, {operation})'


@command('getvampire', bare=True)
def vampire(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    return f'((TES4Runtime.GetVampirism({subject}) as Int) > 0)'


@command('setactorvaluec', 'setavc', 'modactorvaluec', 'modavc')
def numeric_actor_value(ctx, call):
    try:
        code = int(call.source(0), 0)
    except ValueError:
        subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
        modify = 'True' if call.name.startswith('mod') else 'False'
        return (f'TES4ActorValues.Set({subject}, {call.arg(0, "-1", wanted="Int")}, '
                f'{call.arg(1, "0.0", wanted="Float")}, {modify})')
    if code == 69:
        return vampire_value(ctx, call)
    name = _AV_CODE_NAMES.get(code)
    if name not in TES4_ATTRIBUTES and name not in ACTOR_VALUE_MAP:
        return ctx.note(f'{call.written()}: unmapped actor-value code {code}')
    from .emit.dispatch import emit_command
    from .tes4.nodes import Ident
    method = 'modactorvalue' if call.name.startswith('mod') else 'setactorvalue'
    return emit_command(ctx, call.ref, method, call.extends,
                        (Ident(name), *call.args[1:]))


@command('setweight', 'modweight', 'setlightradius', 'setradius')
def item_component(ctx, call):
    subject = (call.arg(1, wanted='Form') if len(call) > 1 else
               ctx._resolve_self_ref(call.ref, call.extends))
    if call.name in ('setweight', 'modweight'):
        modify = 'True' if call.name == 'modweight' else 'False'
        return f'TES4Runtime.ChangeWeight({subject}, ({call.arg(0)}) as Float, {modify})'
    return f'TES4Runtime.SetLightRadius({subject}, ({call.arg(0)}) as Int)'


@command('getgoldvalue', 'getfullgoldvalue', bare=True)
def gold_value(ctx, call):
    full = 'True' if call.name == 'getfullgoldvalue' else 'False'
    return f'TES4Runtime.GetGoldValue({_subject(ctx, call)}, {full})'


@command('getweaponspeed', 'getweaponreach', bare=True)
def weapon_number(ctx, call):
    reach = 'True' if call.name == 'getweaponreach' else 'False'
    return f'TES4Runtime.GetWeaponNumber({_subject(ctx, call)}, {reach})'


@command('setenchantment', 'removeenchantment', bare=True)
def enchantment(ctx, call):
    if call.name == 'removeenchantment':
        return f'TES4Runtime.ChangeEnchantment({_subject(ctx, call)}, None, True)'
    subject = (call.arg(1, wanted='Form') if len(call) > 1 else
               ctx._resolve_self_ref(call.ref, call.extends))
    return f'TES4Runtime.ChangeEnchantment({subject}, {call.arg(0, "None", wanted="Form")}, False)'


@command('setgoldvalue', 'modgoldvalue', 'setgoldvalue_t')
def change_gold_value(ctx, call):
    subject = (call.arg(1, wanted='Form') if len(call) > 1 else
               ctx._resolve_self_ref(call.ref, call.extends))
    modify = 'True' if call.name == 'modgoldvalue' else 'False'
    persist = 'False' if call.name.endswith('_t') else 'True'
    return f'TES4Runtime.ChangeGoldValue({subject}, ({call.arg(0)}) as Float, {modify}, {persist})'


@command('setitemvalue')
def item_value(ctx, call):
    subject = ctx._resolve_objref_ref(call.ref, call.extends)
    return f'TES4Runtime.SetItemValue({subject}, {call.arg(0, "0", wanted="Int")})'


@command('getobseversion', 'getobserevision', 'isplugininstalled', 'getmodindex')
def runtime_capability(ctx, call):
    if call.name == 'getobseversion':
        return '(TES4Runtime.Available() as Int) * 21'
    if call.name == 'getobserevision':
        return '(TES4Runtime.Available() as Int) * 4'
    if call.name == 'getmodindex':
        return f'Game.GetModByName({call.arg(0)})'
    plugin = call.source(0).strip('"').lower()
    if plugin == 'obse_kyoma_menuque':
        return 'TES4Runtime.Available()'
    return f'Game.IsPluginInstalled({call.arg(0)})'


@command('setsummonable', 'setactorrespawns', 'setnorumors', 'setcontainerrespawns')
def form_flag(ctx, call):
    subject = (call.arg(1, wanted='Form') if len(call) > 1 else
               ctx._resolve_self_ref(call.ref, call.extends))
    enabled = f'({call.arg(0, "0")}) as Bool'
    if call.name == 'setcontainerrespawns':
        return f'TES4Runtime.SetContainerRespawns({subject}, {enabled})'
    mask = {'setactorrespawns': 8, 'setnorumors': 8192, 'setsummonable': 16384}[call.name]
    return f'TES4Runtime.SetActorFlag({subject}, {mask}, {enabled})'


@command('getobjecttype', 'getcreaturetype', 'isformvalid')
def form_type(ctx, call):
    subject = _subject(ctx, call)
    if call.name == 'isformvalid':
        return f'({subject} != None)'
    method = 'GetObjectType' if call.name == 'getobjecttype' else 'GetCreatureType'
    return f'TES4Runtime.{method}({subject})'


@command('isreference', bare=True)
def is_reference(ctx, call):
    return f'(({_subject(ctx, call)} as ObjectReference) != None)'


@command('getavmod', 'getavmodf', 'getavmodc', 'modavmod', 'setavmod', 'setavmodf')
def av_modifier(ctx, call):
    av = call.source(0).strip('"').lower()
    modifier = call.source(1).strip('"').lower()
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    if not call.name.startswith('get'):
        absolute = 'True' if call.name.startswith('set') else 'False'
        return (f'TES4Runtime.ModifyAVModifier({subject}, "{ACTOR_VALUE_MAP.get(av, av)}", '
                f'"{modifier}", ({call.arg(2)}) as Float, {absolute})')
    return f'TES4Runtime.GetAVModifier({subject}, "{ACTOR_VALUE_MAP.get(av, av)}", "{modifier}")'


@command('getweathercolor', 'setweathercolor', 'getweathersundamage')
def weather(ctx, call):
    names = {'getweathercolor': 'GetWeatherColor', 'setweathercolor': 'SetWeatherColor',
             'getweathersundamage': 'GetWeatherSunDamage'}
    form_pos = {'getweathercolor': 2, 'setweathercolor': 4, 'getweathersundamage': 0}[call.name]
    args = []
    for i in range(len(call)):
        value = call.arg(i)
        args.append(f'({value} as Weather)' if i == form_pos else f'({value} as Int)')
    return f'TES4Runtime.{names[call.name]}({", ".join(args)})'


_LEVELED_NAMES = (
    'AddToLeveledList', 'ClearLeveledList', 'RemoveFromLeveledList',
    'RemoveLevItemByLevel', 'RemoveNthLevItem', 'GetNumLevItems',
    'GetNthLevItem', 'GetNthLevItemLevel', 'GetNthLevItemCount',
    'GetChanceNone', 'SetChanceNone', 'GetCalcAllLevels', 'GetCalcEachInCount',
    'GetLevItemIndexByForm', 'GetLevItemIndexByLevel', 'GetLevItemByLevel',
)
_LEVELED_METHODS = {name.lower(): name for name in _LEVELED_NAMES}


@command(*_LEVELED_METHODS, 'calclevitem', 'calcleveleditem', 'calclevitemnr', 'calcleveleditemnr')
def leveled_list(ctx, call):
    if call.name.startswith('calclev'):
        args = [call.arg(0), call.arg(1, '0'),
                f'({call.arg(2, "True")} as Bool)', call.arg(3, '-1'),
                'False' if call.name.endswith('nr') else 'True']
        method = 'CalcLeveledItem'
    else:
        method = _LEVELED_METHODS[call.name]
        args = [call.arg(i) for i in range(len(call))]
    return f'TES4Runtime.{method}({", ".join(args)})'
