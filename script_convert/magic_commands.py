"""TES4 magic-item operations backed by their converted engine records."""

from .commands import command
from .runtime_commands import _AV_CODE_NAMES


_ITEM_EFFECT_FIELDS = {('getntheffectitem' + field).lower(): field
                       for field in ('Magnitude', 'Area', 'Duration', 'Range', 'ActorValue', 'Code')}


@command('dispel')
def dispel_item(ctx, call):
    subject = ctx._resolve_self_ref(call.ref, call.extends, actor_func=True)
    return f'TES4Runtime.DispelMagicItem({subject}, {call.arg(0, "None", wanted="Form")})'


@command(*_ITEM_EFFECT_FIELDS, 'getmagiceffectcount', 'getmagicitemeffectcount', 'getmieffectcount')
def item_effect_value(ctx, call):
    subject = call.arg(0, 'None', wanted='Form')
    if call.name in ('getmagiceffectcount', 'getmagicitemeffectcount', 'getmieffectcount'):
        return f'TES4Runtime.SourceInt({subject}, "EffectCount")'
    index = call.arg(1, '0', wanted='Int')
    field = _ITEM_EFFECT_FIELDS[call.name]
    return f'TES4Runtime.SourceInt({subject}, "Effect" + ({index} as String) + "{field}")'


def _effect_code(call, index=0, numeric=False):
    if numeric:
        return call.arg(index, '0', wanted='Int')
    return f'TES4Runtime.SourceInt({call.arg(index, "None", wanted="MagicEffect")}, "EffectCode")'


@command('getmagiceffectcode', 'getmecode')
def effect_code(ctx, call):
    return _effect_code(call)


@command('magiceffectcodefromchars', 'mecodefromchars', 'magiceffectfromchars')
def effect_from_chars(ctx, call):
    chars = call.arg(0, '""', wanted='String')
    code = f'TES4Runtime.MagicEffectCodeFromChars({chars})'
    return f'TES4Runtime.MagicEffectFromCode({code})' if call.name == 'magiceffectfromchars' else code


@command('getmagiceffectchars', 'getmagiceffectcharsc')
def effect_chars(ctx, call):
    return f'TES4Runtime.GetMagicEffectChars({_effect_code(call, numeric=call.name.endswith("c"))})'


@command('getspelltype', 'setspelltype')
def spell_type(ctx, call):
    setting = call.name == 'setspelltype'
    subject = call.arg(1 if setting else 0, 'None', wanted='Spell')
    value = call.arg(0, '-1', wanted='Int') if setting else '-1'
    return f'TES4Runtime.SpellType({subject}, {value}, {"True" if setting else "False"})'


@command('magiceffectfromcode', 'getmagiceffectusedobject', 'getmagiceffectusedobjectc')
def effect_object(ctx, call):
    if call.name == 'magiceffectfromcode':
        return f'TES4Runtime.MagicEffectFromCode({call.arg(0, "0", wanted="Int")})'
    effect = (f'TES4Runtime.MagicEffectFromCode({call.arg(0, "0", wanted="Int")})'
              if call.name.endswith('c') else call.arg(0, 'None', wanted='MagicEffect'))
    return f'TES4Runtime.GetMagicEffectUsedObject({effect})'


@command('setmagiceffectusedobject', 'setmagiceffectusedobjectc', 'setmagiceffectlight', 'setmagiceffectlightc')
def change_effect_object(ctx, call):
    effect = (f'TES4Runtime.MagicEffectFromCode({call.arg(1, "0", wanted="Int")})'
              if call.name.endswith('c') else call.arg(1, 'None', wanted='MagicEffect'))
    light = 'True' if 'light' in call.name else 'False'
    return f'TES4Runtime.ChangeMagicEffectObject({effect}, {call.arg(0, "None", wanted="Form")}, {light})'


_MATCHING = ('magicitemhaseffect', 'magichaseffect', 'magicitemhaseffectcode', 'magichaseffectc',
             'magicitemhaseffectcount', 'magichaseffectcount', 'magicitemhaseffectcountcode', 'magichaseffectcountc')


@command(*_MATCHING)
def matching_effects(ctx, call):
    numeric = call.name.endswith(('code', 'c'))
    code = _effect_code(call, numeric=numeric)
    named_av = None if numeric else next(
        (index for index, name in _AV_CODE_NAMES.items() if name == call.source(2).strip('"').lower()), None)
    av = str(named_av) if named_av is not None else call.arg(2, '-1', wanted='Int')
    result = f'TES4Runtime.CountMatchingEffects({call.arg(1, "None", wanted="Form")}, {code}, {av})'
    return result if 'count' in call.name else f'({result} > 0)'
