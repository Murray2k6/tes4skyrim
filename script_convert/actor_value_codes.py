"""Generate the runtime form of the converter's numeric actor-value map."""

from pathlib import Path

from .constants import ACTOR_VALUE_MAP, TES4_ATTRIBUTES


def write_setter(directory, names):
    """Share dynamic SetAVC/ModAVC dispatch between a master and its plugins."""
    lines = ['ScriptName TES4ActorValues Hidden', '',
             'String Function Name(Int code) Global']
    for index, name in sorted(names.items()):
        target = name if name in TES4_ATTRIBUTES else ACTOR_VALUE_MAP.get(name)
        if target:
            lines += [f'  If code == {index}', f'    Return "{target}"', '  EndIf']
    lines += ['  Return ""', 'EndFunction', '',
              'Float Function GetBase(Form subject, Int code) Global',
              '  If subject == None', '    Return 0.0', '  EndIf',
              '  String actorValue = Name(code)',
              '  If TES4Polyfill.IsTES4Attribute(actorValue)',
              '    Return TES4Polyfill.TES4AttributeStub()', '  EndIf',
              '  Return TES4Runtime.GetBaseActorValueForForm(subject, actorValue)',
              'EndFunction', '',
              'Int Function Set(Actor subject, Int code, Float amount, Bool modify = False) Global',
              '  If subject == None', '    Return 0', '  EndIf',
              '  If code == 69',
              '    If modify',
              '      TES4Runtime.ChangeVampirism(subject, amount, 1)',
              '    Else', '      TES4Runtime.ChangeVampirism(subject, amount, 0)',
              '    EndIf', '    Return 0', '  EndIf',
              '  String actorValue = Name(code)',
              '  If actorValue == ""',
              '    Debug.Trace("TES4ActorValues: unmapped actor-value code " + code)',
              '    Return 0', '  EndIf',
              '  If modify',
              '    TES4Polyfill.ModTES4ActorValue(subject, actorValue, amount)',
              '  Else',
              '    TES4Polyfill.SetTES4ActorValue(subject, actorValue, amount)',
              '  EndIf', '  Return 0', 'EndFunction', '']
    Path(directory, 'TES4ActorValues.psc').write_text('\n'.join(lines), encoding='utf-8')
