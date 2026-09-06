"""Recover compile-time properties for TES4 scripts whose SCTX was stripped.

Some released OBSE mods ship compiled SCPT bytecode without source text.  The
export still identifies the script and its owner, while authored callers retain
every cross-script variable name and the contexts that constrain its type.  A
header-only Papyrus stub makes the script name resolvable but loses those
members.  This pass rebuilds the smallest property surface used by callers and
derives each type from assignments, comparisons, casts, and UDF signatures.
"""

from __future__ import annotations

from collections import defaultdict
import os
import re


_STUB_MARKER = 'has no exported SCTX;'
_HEADER_RE = re.compile(
    r'^\s*ScriptName\s+(\w+)\s+extends\s+(\w+)', re.IGNORECASE)
_PROP_RE = re.compile(
    r'^\s*([A-Za-z_]\w*(?:\[\])?)\s+Property\s+(\w+)\b', re.IGNORECASE)
_DECL_RE = re.compile(
    r'^\s*([A-Za-z_]\w*(?:\[\])?)\s+(?!Property\b)(\w+)\b', re.IGNORECASE)
_FUNC_RE = re.compile(
    r'^\s*(?:([A-Za-z_]\w*)\s+)?Function\s+(\w+)\s*\((.*)\)',
    re.IGNORECASE)
_EVENT_RE = re.compile(r'^\s*Event\s+\w+\s*\((.*)\)', re.IGNORECASE)

_PRIMITIVES = {'int', 'float', 'bool', 'string'}
_OBJECT_WIDE = {'form', 'objectreference'}
_OBJECT_TYPES = {
    'form', 'objectreference', 'actor', 'actorbase', 'activator', 'ammo',
    'armor', 'book', 'cell', 'class', 'effectshader', 'enchantment',
    'faction', 'flora', 'formlist', 'globalvariable', 'ingredient', 'key',
    'leveledactor', 'leveleditem', 'leveledspell', 'location', 'magiceffect',
    'message', 'miscobject', 'musictype', 'outfit', 'package', 'potion',
    'projectile', 'quest', 'race', 'scene', 'scroll', 'shout', 'soulgem',
    'sound', 'soundcategory', 'spell', 'static', 'topic', 'topicinfo', 'voiceType',
    'weapon', 'weather', 'wordofpower', 'worldspace',
}


def _code_part(line: str) -> str:
    """Return code before the first semicolon outside a quoted string."""
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ';' and not quoted:
            return line[:i]
    return line


def _split_args(text: str) -> list[str]:
    """Split a Papyrus argument list without breaking nested calls/casts."""
    out, start, depth, quoted = [], 0, 0, False
    for i, ch in enumerate(text):
        if ch == '"':
            quoted = not quoted
        elif not quoted:
            if ch in '([':
                depth += 1
            elif ch in ')]':
                depth -= 1
            elif ch == ',' and depth == 0:
                out.append(text[start:i].strip())
                start = i + 1
    out.append(text[start:].strip())
    return out


def _params(text: str) -> dict[str, str]:
    out = {}
    for raw in _split_args(text):
        bits = raw.split()
        if len(bits) >= 2:
            out[bits[1].strip().lower()] = bits[0]
    return out


def _canonical(ptype: str) -> str:
    low = (ptype or '').lower()
    return {
        'int': 'Int', 'float': 'Float', 'bool': 'Bool', 'string': 'String',
        'form': 'Form', 'objectreference': 'ObjectReference', 'actor': 'Actor',
        'actorbase': 'ActorBase', 'cell': 'Cell', 'quest': 'Quest',
        'spell': 'Spell', 'weapon': 'Weapon', 'armor': 'Armor',
        'potion': 'Potion', 'ingredient': 'Ingredient', 'race': 'Race',
        'faction': 'Faction', 'package': 'Package', 'magiceffect': 'MagicEffect',
        'effectshader': 'EffectShader', 'worldspace': 'WorldSpace',
        'leveledactor': 'LeveledActor', 'formlist': 'FormList',
        'globalvariable': 'GlobalVariable', 'enchantment': 'Enchantment',
        'book': 'Book', 'ammo': 'Ammo', 'miscobject': 'MiscObject',
    }.get(low, ptype)


def _is_object(ptype: str) -> bool:
    low = (ptype or '').lower().rstrip('[]')
    return low in _OBJECT_TYPES or low.startswith('tes4_')


def _pick_type(weighted: list[tuple[str, int]]) -> str:
    """Choose the common Papyrus type represented by authored-use evidence."""
    scores = defaultdict(int)
    for ptype, weight in weighted:
        if not ptype or ptype.lower().endswith('[]'):
            continue
        scores[_canonical(ptype)] += weight
    if not scores:
        # A TES4 numeric quest variable is the only safe useful default. Float
        # accepts Int writes and participates in every numeric operation.
        return 'Float'

    primitives = {t for t in scores if t.lower() in _PRIMITIVES}
    objects = {t for t in scores if _is_object(t)}
    if objects and not primitives:
        best = max(objects, key=lambda t: scores[t])
        near = {t for t in objects if scores[t] * 2 >= scores[best]}
        if len(near) == 1:
            return best
        lows = {t.lower() for t in near}
        if lows <= {'actor', 'objectreference'}:
            return 'ObjectReference'
        # Form/ObjectReference are fallback widths, not competing authored
        # identities.  If every specific object observation agrees, retain it:
        # `Faction` plus a generic `Form` write is a Faction, not an unknown
        # Form.  This is the common shape of source-less OBSE quest fields.
        specific = {t for t in near if t.lower() not in _OBJECT_WIDE}
        if len(specific) == 1:
            return next(iter(specific))
        return 'Form'
    if primitives and not objects:
        if 'String' in primitives and scores['String'] >= sum(
                scores[t] for t in primitives if t != 'String'):
            return 'String'
        # Int is the narrower numeric store: it promotes to Float at every
        # arithmetic/assignment use, while Float cannot flow back into an Int
        # counter without a cast. Direct Int sinks are therefore decisive.
        if 'Int' in primitives or 'Bool' in primitives:
            return 'Int'
        if 'Float' in primitives:
            return 'Float'
    # Source-less OBSE quest fields were all declared `ref`, even when used as
    # counters.  Direct arithmetic/typed sinks are stronger than a generic
    # Form observation; choose the domain with the larger authored-use score.
    # Ties stay object-typed because numeric zero is also TES4's null sentinel.
    if objects and primitives:
        primitive_score = sum(scores[t] for t in primitives)
        object_score = sum(scores[t] for t in objects)
        domain = primitives if primitive_score > object_score else objects
        return _pick_type([(t, scores[t]) for t in domain])
    if objects:
        return _pick_type([(t, scores[t]) for t in objects])
    return max(scores, key=scores.get)


def _expression_type(expr: str, env: dict[str, str], returns: dict[str, str],
                     member_match) -> str:
    expr = expr.strip()
    cast_expr = expr
    if cast_expr.startswith('(') and cast_expr.endswith(')'):
        cast_expr = cast_expr[1:-1].strip()
    # Only a cast of the WHOLE expression establishes its type.  The old
    # optional closing parenthesis also matched a cast inside the final call
    # argument (`GetFactionRank(x as Faction)`) and classified the Int result
    # itself as Faction.
    cast = re.search(r'\bas\s+([A-Za-z_]\w*)\s*$', cast_expr,
                     re.IGNORECASE)
    if cast:
        return cast.group(1)
    if re.fullmatch(r'"(?:[^"\\]|\\.)*"', expr):
        return 'String'
    if re.fullmatch(r'-?\d+', expr):
        return 'Int'
    if re.fullmatch(r'-?(?:\d+\.\d*|\d*\.\d+)', expr):
        return 'Float'
    if expr.lower() in ('true', 'false'):
        return 'Bool'
    if expr.lower() == 'none':
        return ''
    bare = expr.strip('() ').lower()
    if bare in env:
        return env[bare]
    udf = re.match(r'^([A-Za-z_]\w*)\.TES4Call\(', expr, re.IGNORECASE)
    if udf:
        callee_type = env.get(udf.group(1).lower(), '')
        return returns.get(callee_type.lower(), '')
    if re.search(r'\bGetParentCell\s*\(', expr, re.IGNORECASE):
        return 'Cell'
    if re.search(r'\bGetActorBase\s*\(', expr, re.IGNORECASE):
        return 'ActorBase'
    if re.search(r'\bGetBaseObject\s*\(', expr, re.IGNORECASE):
        return 'Form'
    if re.search(r'\bGetEquippedObject\s*\(', expr, re.IGNORECASE):
        return 'Form'
    if re.search(r'\bGetRace\s*\(', expr, re.IGNORECASE):
        return 'Race'
    if re.search(r'\bGetCurrentPackage\s*\(', expr, re.IGNORECASE):
        return 'Package'
    if re.search(r'\bGetName\s*\(', expr, re.IGNORECASE):
        return 'String'
    if re.search(r'\bGame\.GetCurrentCrosshairRef\s*\(', expr,
                 re.IGNORECASE):
        return 'ObjectReference'
    if re.search(r'\b(?:GetCombatTarget|FindRandomActorFromRef)\s*\(', expr,
                 re.IGNORECASE):
        return 'Actor'
    if re.search(r'\bTES4SKSE\.GetOwner\s*\(', expr, re.IGNORECASE):
        return 'Form'
    if re.search(r'\bTES4SKSE\.GetClass\s*\(', expr, re.IGNORECASE):
        return 'Class'
    if re.search(r'\bTES4SKSE\.GetCombatStyle\s*\(', expr,
                 re.IGNORECASE):
        return 'CombatStyle'
    if re.search(r'\bTES4SKSE\.GetEnchantment\s*\(', expr,
                 re.IGNORECASE):
        return 'Enchantment'
    if re.search(r'\b(?:Utility\.RandomInt|RandomInt|GetFactionRank|'
                 r'GetModIndex|GetSourceModIndex|'
                 r'GetWeaponType|GetArmorType|GetLevel|GetItemCount)\s*\(',
                 expr, re.IGNORECASE):
        return 'Int'
    if re.search(r'\b(?:Utility\.RandomFloat|RandomFloat|Math\.(?:pow|sqrt)|'
                 r'GetValue|GetActorValue|GetGameSettingFloat)\s*\(', expr,
                 re.IGNORECASE):
        return 'Float'
    if re.search(r'\b(?:IsRunning|IsDead|IsInCombat|IsInFaction|IsEssential|'
                 r'HasSpell|HasMagicEffect|IsDisabled|IsEnabled)\s*\(', expr,
                 re.IGNORECASE):
        return 'Bool'
    if re.fullmatch(r'Game\.GetPlayer\(\)', expr, re.IGNORECASE):
        return 'Actor'
    if '"' in expr and '+' in expr:
        return 'String'
    if re.search(r'[+*/%]|\s-\s', expr):
        return 'Float' if re.search(r'\d+\.\d+', expr) else 'Int'
    mm = member_match.fullmatch(expr.strip('() '))
    return f'@{mm.group("stype").lower()}:{mm.group("member").lower()}' if mm else ''


def populate_sourceless_stubs(output_dir: str) -> int:
    """Populate stripped-source type stubs. Returns properties recovered."""
    if not os.path.isdir(output_dir):
        return 0
    sources = {}
    stubs = {}
    for name in os.listdir(output_dir):
        if not name.lower().endswith('.psc'):
            continue
        path = os.path.join(output_dir, name)
        try:
            lines = open(path, encoding='utf-8').read().splitlines()
        except OSError:
            continue
        header = next((_HEADER_RE.match(line) for line in lines
                       if _HEADER_RE.match(line)), None)
        if not header:
            continue
        stem = header.group(1).lower()
        sources[stem] = (path, lines)
        if any(_STUB_MARKER in line for line in lines):
            stubs[stem] = (header.group(1), header.group(2), path, lines)
    if not stubs:
        return 0

    # A caller can declare the same attached record as generic Quest/Form when
    # master lookup did not recover its script type. Other callers that did
    # recover it provide an exact alias keyed by the authored property name.
    owner_alias_sets = defaultdict(set)
    for _stem, (_path, lines) in sources.items():
        for line in lines:
            pm = _PROP_RE.match(line)
            if pm and pm.group(1).lower() in stubs:
                owner_alias_sets[pm.group(2).lower()].add(pm.group(1).lower())
    owner_aliases = {name: next(iter(types))
                     for name, types in owner_alias_sets.items()
                     if len(types) == 1}

    returns = {}
    signatures = {}
    for stem, (_path, lines) in sources.items():
        for line in lines:
            fm = _FUNC_RE.match(line)
            if not fm:
                continue
            signatures[(stem, fm.group(2).lower())] = [
                t for _n, t in _params(fm.group(3)).items()]
            if fm.group(2).lower() == 'tes4call':
                returns[stem] = fm.group(1) or ''

    stub_alt = '|'.join(re.escape(s) for s in sorted(stubs, key=len,
                                                     reverse=True))
    # The owner spelling varies per caller; the named stype is filled after
    # resolving that owner through the caller's declaration environment.
    raw_member = re.compile(
        r'\b(?P<owner>[A-Za-z_]\w*)\.(?P<member>[A-Za-z_]\w*)', re.IGNORECASE)
    direct_member = re.compile(
        rf'(?P<stype>{stub_alt}):(?P<member>[A-Za-z_]\w*)', re.IGNORECASE)

    evidence = defaultdict(list)
    exact_writes = defaultdict(list)
    array_members = set()
    display = {}
    edges = set()
    uses = []
    owner_retypes = defaultdict(dict)

    for _stem, (_path, lines) in sources.items():
        env = {}
        for line in lines:
            pm = _PROP_RE.match(line)
            if pm:
                env[pm.group(2).lower()] = pm.group(1)
            fm = _FUNC_RE.match(line)
            if fm:
                env.update(_params(fm.group(3)))
            em = _EVENT_RE.match(line)
            if em:
                env.update(_params(em.group(1)))
            dm = _DECL_RE.match(line)
            if dm and dm.group(1).lower() in (_PRIMITIVES | _OBJECT_TYPES):
                env[dm.group(2).lower()] = dm.group(1)

        def members_in(code):
            found = []
            for match in raw_member.finditer(code):
                stype = env.get(match.group('owner').lower(), '').lower()
                if (stype not in stubs
                        and stype in ('quest', 'form', 'objectreference')):
                    stype = owner_aliases.get(match.group('owner').lower(), '')
                if stype not in stubs:
                    continue
                if env.get(match.group('owner').lower(), '').lower() != stype:
                    owner_retypes[_path][match.group('owner').lower()] = stype
                key = (stype, match.group('member').lower())
                display.setdefault(key, match.group('member'))
                found.append((match, key))
            return found

        for idx, line in enumerate(lines):
            code = _code_part(line).strip()
            if not code:
                continue
            found = members_in(code)
            if not found:
                continue
            uses.append((_path, idx, line, env.copy(), found))

            # Serialized xOBSE arrays have an authoritative storage domain:
            # every TES4Array helper takes the serialized String as its first
            # argument.  This remains observable even when the owning script's
            # SCTX was stripped, so do not let element-value evidence narrow
            # the owner member itself to Int/Form/Float.
            for array_call in re.finditer(
                    r'\bTES4Array\.\w+\(\s*'
                    r'(?P<owner>[A-Za-z_]\w*)\.(?P<member>[A-Za-z_]\w*)',
                    code, re.IGNORECASE):
                array_found = members_in(
                    f'{array_call.group("owner")}.{array_call.group("member")}')
                if len(array_found) == 1:
                    array_members.add(array_found[0][1])
            setter_value = re.search(
                r'\bTES4Array\.Set(?P<kind>Int|Float|String|Form|Array)\('
                r'.*,\s*(?P<owner>[A-Za-z_]\w*)\.(?P<member>[A-Za-z_]\w*)'
                r'\s*\)\s*$', code, re.IGNORECASE)
            if setter_value:
                value_found = members_in(
                    f'{setter_value.group("owner")}.'
                    f'{setter_value.group("member")}')
                if len(value_found) == 1:
                    kind = setter_value.group('kind')
                    evidence[value_found[0][1]].append(
                        ('String' if kind.lower() == 'array' else kind, 20))

            # Explicit non-string casts are strong evidence. `as String` is
            # OBSE's `$value` formatting and says nothing about storage type.
            for match, key in found:
                tail = code[match.end():]
                cm = re.match(r'\s+as\s+(\w+)', tail, re.IGNORECASE)
                if cm and cm.group(1).lower() != 'string':
                    evidence[key].append((cm.group(1), 12))

            am = re.match(r'^(.+?)\s*=\s*(.+)$', code)
            if am and not re.match(r'^(If|ElseIf|While)\b', code, re.I):
                lhs, rhs = am.group(1).strip(), am.group(2).strip()
                lhs_found, rhs_found = members_in(lhs), members_in(rhs)
                lhs_key = lhs_found[0][1] if len(lhs_found) == 1 else None
                rhs_key = (rhs_found[0][1] if len(rhs_found) == 1
                           and raw_member.fullmatch(rhs.strip('() ')) else None)
                lhs_type = env.get(lhs.lower(), '')
                rhs_type = _expression_type(rhs, env, returns, direct_member)
                if lhs_key and rhs_key:
                    edges.add(tuple(sorted((lhs_key, rhs_key))))
                elif lhs_key and rhs_type and not rhs_type.startswith('@'):
                    evidence[lhs_key].append((rhs_type, 10))
                    # A direct authored store establishes the slot's value
                    # domain more strongly than incidental reads.  Keep this
                    # separately so repeated numeric/string writes can defeat
                    # a weak generic-Form observation without making every
                    # mixed TES4 ref slot numeric.
                    # A neutral value emitted for an unsupported expression is
                    # not authored type evidence.  Treating `... = 0 ;NE:` as
                    # an exact Int store narrowed source-less Form slots and
                    # then made every real caller fail Papyrus type checking.
                    if (';NE:' not in line and ';TODO:' not in line
                            and rhs.strip().lower() not in (
                                '0', '0.0', 'none', 'false', '""')):
                        exact_writes[lhs_key].append(rhs_type)
                if rhs_key and lhs_type:
                    evidence[rhs_key].append((lhs_type, 10))
                elif rhs_found and lhs_type:
                    for _m, key in rhs_found:
                        evidence[key].append((lhs_type, 5))

            # Comparisons preserve the value domain even when the stripped
            # script never writes the member itself.  This is decisive for
            # INI-backed counters (`MOO.loadcounter == localInt`) and for base
            # form slots (`MOO.mycell == MOO.oldcell`).
            for cm in re.finditer(
                    r'([^&|]+?)\s*(==|!=|>=|<=|>|<)\s*([^&|]+)', code):
                left, right = cm.group(1).strip('() '), cm.group(3).strip('() ')
                left_found, right_found = members_in(left), members_in(right)
                left_type = _expression_type(
                    left, env, returns, direct_member)
                right_type = _expression_type(
                    right, env, returns, direct_member)
                null_right = (cm.group(2) in ('==', '!=')
                              and right.lower() in ('0', '0.0', 'none'))
                null_left = (cm.group(2) in ('==', '!=')
                             and left.lower() in ('0', '0.0', 'none'))
                for _m, key in left_found:
                    if (right_type and not right_type.startswith('@')
                            and not null_right):
                        evidence[key].append((right_type, 14))
                for _m, key in right_found:
                    if (left_type and not left_type.startswith('@')
                            and not null_left):
                        evidence[key].append((left_type, 14))

            # Arithmetic around a member is numeric evidence.  Decimal
            # operands preserve Float; otherwise Int is the narrow TES4 store.
            if re.search(r'[+*/]|\s-\s', code):
                arithmetic_type = ('Float' if re.search(r'\d+\.\d+', code)
                                   else 'Int')
                for _m, key in found:
                    evidence[key].append((arithmetic_type, 8))

            # UDF parameter declarations are exact authored type constraints.
            for cm in re.finditer(
                    r'\b([A-Za-z_]\w*)\.TES4Call\((.*)\)', code,
                    re.IGNORECASE):
                callee_type = env.get(cm.group(1).lower(), '').lower()
                want = signatures.get((callee_type, 'tes4call'), [])
                args = _split_args(cm.group(2))
                for arg, ptype in zip(args, want):
                    af = members_in(arg)
                    if len(af) == 1 and raw_member.fullmatch(
                            arg.strip().strip('()')):
                        evidence[af[0][1]].append((ptype, 11))

            for match, key in found:
                # Ordering and arithmetic can only operate on TES4 numerics.
                before, after = code[:match.start()], code[match.end():]
                if (re.search(r'(?:<=|>=|<|>)\s*$', before)
                        or re.match(r'^\s*(?:<=|>=|<|>)', after)):
                    evidence[key].append(('Float', 5))
                if (re.search(r'[+*/%]\s*$', before)
                        or re.match(r'^\s*[+*/%]', after)
                        or re.search(r'\s-\s*$', before)
                        or re.match(r'^\s*-\s+', after)):
                    evidence[key].append(
                        ('String' if '"' in code and '+' in code else 'Float', 4))
                # Equality with a declared object or string is useful; equality
                # with literal zero is intentionally ambiguous in TES4.
                cmp_after = re.match(
                    r'^\s*(?:==|!=)\s*([A-Za-z_]\w*|"[^"]*")', after)
                if cmp_after:
                    other = cmp_after.group(1)
                    other_members = members_in(after[cmp_after.start(1):])
                    if other_members:
                        edges.add(tuple(sorted((key, other_members[0][1]))))
                    else:
                        ptype = ('String' if other.startswith('"')
                                 else env.get(other.lower(), ''))
                        # The owner of another source-less field is not that
                        # field's value type (`Q.a == Q.b`).
                        if ptype and ptype.lower() not in stubs:
                            evidence[key].append((ptype, 7))

            # Equality against a complete expression is equally exact.  The
            # simple-token branch above cannot see calls such as
            # `MOO.rank == actor.GetFactionRank(faction)` or casts.  When one
            # side contains exactly one recovered member, type the member from
            # the other side's finished Papyrus expression.
            cmp = re.match(r'^(?:If|ElseIf|While)\s+(.+)$', code,
                           re.IGNORECASE)
            cmp_text = cmp.group(1) if cmp else code
            eq = re.match(r'^(.+?)\s*(==|!=)\s*(.+)$', cmp_text)
            if eq:
                left_found = members_in(eq.group(1))
                right_found = members_in(eq.group(3))
                if len(left_found) == 1 and not right_found:
                    ptype = _expression_type(eq.group(3), env, returns,
                                             direct_member)
                    if ptype and not ptype.startswith('@'):
                        evidence[left_found[0][1]].append((ptype, 10))
                elif len(right_found) == 1 and not left_found:
                    ptype = _expression_type(eq.group(1), env, returns,
                                             direct_member)
                    if ptype and not ptype.startswith('@'):
                        evidence[right_found[0][1]].append((ptype, 10))

    # Equivalent cross-script assignments propagate constraints to a fixed
    # point. They are authored aliases, not a naming heuristic.
    changed = True
    while changed:
        changed = False
        for left, right in edges:
            before_l, before_r = len(evidence[left]), len(evidence[right])
            evidence[left].extend(x for x in evidence[right]
                                  if x not in evidence[left])
            evidence[right].extend(x for x in evidence[left]
                                   if x not in evidence[right])
            changed |= (len(evidence[left]) != before_l
                        or len(evidence[right]) != before_r)

    chosen = {key: _pick_type(evidence[key]) for key in display}
    for key, types in exact_writes.items():
        normalized = [('Int' if t.lower() == 'bool' else _canonical(t))
                      for t in types if t and not t.lower().startswith('tes4_')]
        unique = {t.lower() for t in normalized}
        has_object_evidence = any(
            _canonical(t).lower() in _OBJECT_TYPES
            for t, _weight in evidence[key])
        # TES4 writes numeric zero as the null sentinel for a `ref`; it cannot
        # override an observed object flow into the same source-less slot.
        ambiguous_null = (unique == {'int'} and has_object_evidence
                          and all(t.lower() in ('int', 'bool')
                                  for t in normalized))
        if len(unique) == 1 and normalized and not ambiguous_null:
            chosen[key] = normalized[0]
    for key in array_members:
        chosen[key] = 'String'
    recovered = 0
    for stem, (script_name, extends, path, lines) in stubs.items():
        props = [(display[key], chosen[key]) for key in display if key[0] == stem]
        props.sort(key=lambda item: item[0].lower())
        if not props:
            continue
        out = [f'ScriptName {script_name} extends {extends} Conditional',
               f'{{TES4 script {script_name[5:] if script_name.startswith("TES4_") else script_name} '
               'has no exported SCTX; properties recovered from authored callers.}',
               '']
        out.extend(
            f'{ptype} Property {name} Auto'
            + (' ;TES4 array_var' if (stem, name.lower()) in array_members else '')
            for name, ptype in props)
        out.append('')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(out))
        recovered += len(props)

    # Retype generic declarations for the same attached record, so the caller
    # can actually see the recovered properties. This uses the unique authored
    # property-name alias above; ambiguous names are left untouched.
    for path, replacements in owner_retypes.items():
        source_entry = next((item for item in sources.values()
                             if item[0] == path), None)
        if not source_entry:
            continue
        lines = list(source_entry[1])
        changed_file = False
        for idx, line in enumerate(lines):
            pm = _PROP_RE.match(line)
            if not pm:
                continue
            want = replacements.get(pm.group(2).lower())
            if not want:
                continue
            canonical = stubs[want][0]
            lines[idx] = re.sub(r'^\s*\w+(?=\s+Property\b)', canonical,
                                line, count=1, flags=re.IGNORECASE)
            changed_file = True
        if changed_file:
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write('\n'.join(lines) + '\n')

    # The main converter ran before these recovered declarations existed, so
    # it could not turn TES4's numeric null sentinel into Papyrus None. Apply
    # that type-directed rewrite now for recovered object members.
    for _stem, (path, _old_lines) in sources.items():
        try:
            lines = open(path, encoding='utf-8').read().splitlines()
        except OSError:
            continue
        env = {}
        for line in lines:
            pm = _PROP_RE.match(line)
            if pm:
                env[pm.group(2).lower()] = pm.group(1).lower()
            fm = _FUNC_RE.match(line)
            if fm:
                env.update({k: v.lower() for k, v in _params(
                    fm.group(3)).items()})
            em = _EVENT_RE.match(line)
            if em:
                env.update({k: v.lower() for k, v in _params(
                    em.group(1)).items()})

        def recovered_type(owner: str, member: str) -> str:
            stype = env.get(owner.lower(), '')
            if stype not in stubs and stype in (
                    'quest', 'form', 'objectreference'):
                stype = owner_aliases.get(owner.lower(), '')
            return chosen.get((stype, member.lower()), '')

        changed_file = False
        for idx, line in enumerate(lines):
            code, sep, comment = line.partition(';')
            # Direct write: `MOO.refField = 0`.
            am = re.match(
                r'^(\s*)([A-Za-z_]\w*)\.([A-Za-z_]\w*)'
                r'(\s*=\s*)0(?:\.0)?\s*$', code, re.IGNORECASE)
            if am and _is_object(recovered_type(am.group(2), am.group(3))):
                fixed = (f'{am.group(1)}{am.group(2)}.{am.group(3)}'
                         f'{am.group(4)}None')
                lines[idx] = fixed + (f'  ;{comment}' if sep else '')
                changed_file = True
                continue

            # The main converter may already have rewritten TES4's numeric
            # zero to Papyrus None while the source-less owner was still a
            # generic ref stub.  Once recovery proves the member primitive,
            # restore the exact TES4 default instead of leaving a checker
            # mismatch (`Int = None`).
            none_m = re.match(
                r'^(\s*)([A-Za-z_]\w*)\.([A-Za-z_]\w*)'
                r'(\s*=\s*)None\s*$', code, re.IGNORECASE)
            if none_m:
                recovered_kind = recovered_type(
                    none_m.group(2), none_m.group(3))
                default = {'int': '0', 'float': '0.0', 'bool': 'False',
                           'string': '""'}.get(recovered_kind.lower())
                if default is not None:
                    fixed = (f'{none_m.group(1)}{none_m.group(2)}.'
                             f'{none_m.group(3)}{none_m.group(4)}{default}')
                    lines[idx] = fixed + (f'  ;{comment}' if sep else '')
                    changed_file = True
                    continue

            # A recovered Int field may be fed by an OBSE Float expression.
            # Papyrus requires the truncation that TES4's short/long storage
            # performed implicitly.
            value_m = re.match(
                r'^(\s*)([A-Za-z_]\w*)\.([A-Za-z_]\w*)'
                r'(\s*=\s*)(.+?)\s*$', code, re.IGNORECASE)
            if value_m and recovered_type(
                    value_m.group(2), value_m.group(3)).lower() == 'int':
                rhs = value_m.group(5).strip()
                float_source = bool(re.search(
                    r'\b(?:Utility\.RandomFloat|RandomFloat|Math\.(?:pow|sqrt)|'
                    r'GetValue|GetActorValue|GetGameSettingFloat)\s*\('
                    r'|\d+\.\d+|/', rhs, re.IGNORECASE))
                if env.get(rhs.strip('() ').lower(), '').lower() == 'float':
                    float_source = True
                if not float_source:
                    for rm in raw_member.finditer(rhs):
                        if recovered_type(rm.group('owner'),
                                          rm.group('member')).lower() == 'float':
                            float_source = True
                            break
                bool_source = bool(re.search(
                    r'\b(?:IsRunning|IsDead|IsInCombat|IsInFaction|'
                    r'IsEssential|HasSpell|HasMagicEffect|IsDisabled|'
                    r'IsEnabled)\s*\(', rhs, re.IGNORECASE))
                if float_source and not re.search(r'\bas\s+Int\b', rhs,
                                                  re.IGNORECASE):
                    fixed = (f'{value_m.group(1)}{value_m.group(2)}.'
                             f'{value_m.group(3)}{value_m.group(4)}'
                             f'({rhs}) as Int')
                    lines[idx] = fixed + (f'  ;{comment}' if sep else '')
                    changed_file = True
                    continue
                if bool_source and not re.search(r'\bas\s+Int\b', rhs,
                                                 re.IGNORECASE):
                    fixed = (f'{value_m.group(1)}{value_m.group(2)}.'
                             f'{value_m.group(3)}{value_m.group(4)}'
                             f'({rhs}) as Int')
                    lines[idx] = fixed + (f'  ;{comment}' if sep else '')
                    changed_file = True
                    continue

            def right_null(m):
                nonlocal changed_file
                if not _is_object(recovered_type(m.group(1), m.group(2))):
                    return m.group(0)
                changed_file = True
                return f'{m.group(1)}.{m.group(2)} {m.group(3)} None'

            def left_null(m):
                nonlocal changed_file
                if not _is_object(recovered_type(m.group(2), m.group(3))):
                    return m.group(0)
                changed_file = True
                return f'None {m.group(1)} {m.group(2)}.{m.group(3)}'

            fixed = re.sub(
                r'\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*(==|!=)\s*0\b',
                right_null, code, flags=re.IGNORECASE)
            fixed = re.sub(
                r'\b0\s*(==|!=)\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b',
                left_null, fixed, flags=re.IGNORECASE)
            if fixed != code:
                lines[idx] = fixed + (f';{comment}' if sep else '')
        if changed_file:
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write('\n'.join(lines) + '\n')

    if recovered:
        print(f'    source-less script stubs: {recovered} authored member(s) recovered')
    return recovered
