"""Statement BODIES: a tree walk that emits Papyrus lines with their nesting.

`convert_standalone` used to convert a block by handing `_convert_line` one
SOURCE LINE at a time.  That is why the string layer exists: a line on its own
has no structure, so every structural question -- is this `if` closed? how deep
am I? does this `else` belong to that `if`? -- had to be re-derived by counting
keywords across the emitted text afterwards (`_balance_if_endif`,
`_remove_dead_code_after_return`, the block-depth counter in `_convert_line`).

The parser already owns all of it: an `If` node holds its own body, its elseif
chain and its else, so walking the tree emits closed, correctly-indented blocks
by construction and there is nothing left to repair.

`emit/stmt.py` converts one statement; this module walks the bodies and owns
LAYOUT -- indentation, the `Else`/`EndIf`/`EndWhile` closers, and re-attaching
each statement's trailing source comment.
"""

from __future__ import annotations

import re

from script_convert.emit import stmt as S
from script_convert.emit import string_edits
from script_convert.tes4 import nodes as N

#: Papyrus indents with two spaces per level, matching the emitted events.
INDENT = '  '


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def emit_body(conv, body, extends: str, depth: int = 0) -> list[str]:
    """Papyrus lines for a list of statement nodes, indented from `depth`.

    Recurses through `If`/`While` rather than tracking a running depth counter,
    so a body cannot come out unbalanced and a `Return` cannot strand the lines
    that follow it inside the wrong block.
    """
    body = _drop_duplicate_say(conv, body)
    animated = _animated_targets(body)
    out = []
    open_walk = conv.sc.refwalk_var
    conv.sc.refwalk_var = ''
    for st in body:
        lines = emit_stmt(conv, st, extends, depth)
        if (conv.sc.loop_stack and conv.sc.loop_stack[-1][1]
                and not isinstance(st, (N.Comment, N.Blank, N.VarDecl))):
            skip = conv.sc.loop_stack[-1][1]
            lines = [INDENT * depth + f'If !{skip}'] + [INDENT + l for l in lines] + [INDENT * depth + 'EndIf']
        out += _deferred_destroy(lines, animated)
        # Papyrus rejects statements after an unconditional Return in the
        # same block; TES4 accepted such unreachable leftovers.
        if isinstance(st, N.Return):
            break
    # An OBSE ref-walk's `While` is opened by a `Label` mid-body and its `Goto`
    # cannot close it in place (the Goto sits inside the loop's own `if` nest,
    # and `EndWhile` there would cross those blocks).  The walk therefore ends
    # where the body containing its Label ends, which only the walker knows.
    if conv.sc.refwalk_var and conv.sc.refwalk_labels:
        out.append(INDENT * depth + 'EndWhile')
        conv.sc.refwalk_labels = set()
    conv.sc.refwalk_var = open_walk
    return out


def emit_stmt(conv, st: N.Stmt, extends: str, depth: int) -> list[str]:
    """Papyrus lines for ONE statement, including any body it owns."""
    pad = INDENT * depth
    if isinstance(st, N.If):
        return _if(conv, st, extends, depth)
    if isinstance(st, (N.While, N.ForEach)):
        return _loop(conv, st, extends, depth)
    conv.sc.block_depth = depth
    text = _text(conv, st, extends)
    if not text:
        # A blank source line stays blank; a declaration emits nothing at all
        # (it was hoisted to a property), so it must not leave an empty line.
        return [''] if isinstance(st, N.Blank) else []
    return _indent(text, pad)


def _loop(conv, st, extends, depth):
    from script_convert.emit import expr as E
    from script_convert.constants import _safe_property_name
    from script_convert.symbols import type_of_expr
    pad = INDENT * depth
    tag = f'TES4_Loop{st.line}'
    if conv.sc.batch_stack:
        import hashlib
        tag += hashlib.sha256(str(conv.sc.batch_stack[-1].name).encode()).hexdigest()[:8]
    controlled = _has_loop_jump(st.body)
    stop, skip = (tag + 'Stop', tag + 'Skip') if controlled else ('', '')
    types = {stop: 'Bool', skip: 'Bool'} if controlled else {}
    prefix = [pad + f'{stop} = False'] if controlled else []
    step = []
    setup = []
    suffix = []
    inventory_scope = ''
    if isinstance(st, N.ForEach):
        cursor, source = tag + 'Index', tag + 'Source'
        target = conv._convert_ref(E.emit_source(st.target), extends)
        filtered = isinstance(st.value, N.Call) and st.value.name.lower() == 'getinvrefsforitem'
        source_type = type_of_expr(st.value, conv.type_of)
        is_array = not filtered and (source_type == 'TES4Collection' or conv._is_obse_array(st.value))
        types.update({cursor: 'Int', source: 'TES4Collection' if is_array else 'Int'})
        if filtered:
            receiver = E.emit_source(st.value.receiver) if st.value.receiver else ''
            owner = conv._resolve_objref_ref(receiver, extends)
            item = E.emit(conv, st.value.args[0], extends) if st.value.args else 'None'
            src = f'TES4Runtime.BeginInventory({owner}, {item})'
        else:
            src = E.emit(conv, st.value, extends)
        if not filtered and not is_array and source_type == 'Form':
            src = f'({src} as ObjectReference)'
        if not filtered and not is_array:
            src = f'TES4Runtime.BeginInventory({src})'
        prefix += [pad + f'{source} = {src}', pad + f'{cursor} = 0']
        if is_array:
            prefix += [pad + f'{target} = TES4Collection.Create("StringMap")']
            key = tag + 'Key'
            types[key] = 'String'
            condition = f'{cursor} < TES4Collections.Size({source})'
            setup = [f'{key} = {source}.KeyAt({cursor})',
                     f'If {source}.Kind == 2',
                     f'  {target}.SetString("key", {key})',
                     'Else',
                     f'  {target}.SetNumber("key", {key} as Float)',
                     'EndIf',
                     f'{target}.CopyValue("value", {source}, {key})']
            suffix = [pad + f'{target} = None']
        else:
            if isinstance(st.target, N.Ident):
                name = st.target.name
                ptype = 'TES4Collection' if filtered else 'Form'
                conv.sc.var_types[name.lower()] = ptype
                conv.sc.var_types[_safe_property_name(name).lower()] = ptype
            condition = f'{cursor} < TES4Runtime.InventorySize({source})'
            setup = [f'{target} = TES4Runtime.InventoryReference({source}, {cursor})']
            if filtered:
                prefix += [pad + f'{target} = TES4Collection.Create("StringMap")']
                setup = [f'{target}.SetInteger("key", {cursor})',
                         f'{target}.SetForm("value", TES4Runtime.InventoryReference({source}, {cursor}))']
            inventory_scope = source
            suffix = [pad + f'TES4Runtime.EndInventory({source})', pad + f'{target} = None']
        step = [pad + INDENT + f'{cursor} += 1']
    else:
        condition_lines, cond = string_edits.lower(conv, st.cond, extends)
        condition = S.emit_condition(conv, cond, extends)
        prefix += [pad + line for line in condition_lines]
        if condition_lines:
            if controlled:
                step += [pad + INDENT + f'If !{stop}']
                step += [pad + INDENT * 2 + line for line in condition_lines]
                step += [pad + INDENT + 'EndIf']
            else:
                step += [pad + INDENT + line for line in condition_lines]
    for name, ptype in types.items():
        conv.sc.synthetic_vars[name] = ptype
        conv.sc.var_types[name.lower()] = ptype
        conv.sc.local_vars.add(name.lower())
    conv.sc.loop_stack.append((stop, skip))
    if inventory_scope:
        conv.sc.inventory_scopes.append(inventory_scope)
    try:
        body = emit_body(conv, st.body, extends, depth + 1)
    finally:
        conv.sc.loop_stack.pop()
        if inventory_scope:
            conv.sc.inventory_scopes.pop()
    condition = f'!{stop} && ({condition})' if controlled else condition
    reset = [pad + INDENT + f'{skip} = False'] if controlled else []
    return (prefix + [pad + f'While {condition}'] + reset
            + [pad + INDENT + line for line in setup] + body + step
            + [pad + 'EndWhile'] + suffix)


def _has_loop_jump(body):
    for st in body:
        if isinstance(st, N.ExprStmt) and st.expr.called in ('break', 'continue'):
            return True
        if isinstance(st, N.If):
            parts = [st.body, st.orelse] + [branch for _, branch, _ in st.elifs]
            if any(_has_loop_jump(part) for part in parts):
                return True
    return False


def _indent(text: str, pad: str) -> list[str]:
    """A statement's lines at `pad`, keeping any nesting between them.

    Only the FIRST line sits at the statement's depth; the rest keep their
    offset from it.  Re-padding a multi-line handler flat closed one block too
    many and swallowed the events after it (98 Nehrim scripts).
    """
    parts = text.splitlines()
    if not parts:
        return []
    base = len(parts[0]) - len(parts[0].lstrip())
    out = [pad + parts[0].strip()]
    for part in parts[1:]:
        if not part.strip():
            out.append(part)
            continue
        extra = max(len(part) - len(part.lstrip()) - base, 0)
        out.append(pad + ' ' * extra + part.strip())
    return out


def _if(conv, st: N.If, extends: str, depth: int) -> list[str]:
    """`If` with its elseif chain and else, each body owning its own nesting."""
    pad = INDENT * depth
    before, cond = string_edits.lower(conv, st.cond, extends)
    from dataclasses import replace
    out = [pad + line for line in before]
    out.append(pad + _text(conv, replace(st, cond=cond), extends))
    out += emit_body(conv, st.body, extends, depth + 1)
    nested = 0
    for cond, body, _line in st.elifs:
        before, cond = string_edits.lower(conv, cond, extends)
        header = _text(conv, N.If(cond=cond, body=[], line=_line), extends)
        if before:
            out.append(pad + 'Else')
            depth += 1
            nested += 1
            pad = INDENT * depth
            out += [pad + line for line in before]
            out.append(pad + header)
        else:
            out.append(pad + 'Else' + header)
        out += emit_body(conv, body, extends, depth + 1)
    if st.orelse:
        out.append(pad + 'Else')
        out += emit_body(conv, st.orelse, extends, depth + 1)
    out.append(pad + 'EndIf')
    for _ in range(nested):
        depth -= 1
        out.append(INDENT * depth + 'EndIf')
    return out


def _text(conv, st: N.Stmt, extends: str) -> str:
    """One statement's converted text, with its trailing comment re-attached.

    The comment rides on the NODE, so it can never be emitted in the middle of
    the expression it followed -- the failure `_repair_commented_condition`
    existed to undo.
    """
    conv._line_comments.clear()
    before, st = string_edits.statement(conv, st, extends)
    text = conv._guard_stage_timer(S.emit(conv, st, extends))
    if before:
        text = '\n'.join(before + ([text] if text else []))
    if isinstance(st, N.Comment):
        text = _source_comment(text)
    notes = '  '.join(conv._line_comments)
    conv._line_comments.clear()
    if notes:
        # A command that converts to nothing but notes IS the comment; one
        # that produced a value keeps the notes beside it.
        text = notes if text.strip() in ('', '0') else f'{text}  {notes}'
    source_note = _source_comment(st.comment)
    if source_note and not text.lstrip().startswith(';'):
        text = f'{text}  {source_note}' if text else source_note
    return _safe_comments(text)


def _source_comment(comment: str) -> str:
    """Keep an author's TODO distinct from conversion-failure TODO markers."""
    return re.sub(r'(?i)\bTODO\b(?:\s*:)?', 'Source note:', comment)


def _safe_comments(text: str) -> str:
    """`;/` broken up: Papyrus reads it as a BLOCK comment and eats the file."""
    return text.replace(';/', '; /') if ';/' in text else text


def _comment(line: str) -> str:
    """The line, commented out in place, keeping its indentation."""
    stripped = line.lstrip()
    if not stripped or stripped.startswith(';'):
        return line
    return line[:len(line) - len(stripped)] + ';' + stripped


# ---------------------------------------------------------------------------
# Adjacent-statement rules
# ---------------------------------------------------------------------------

def _drop_duplicate_say(conv, body):
    """Collapse Oblivion's measure-then-deliver Say pair to ONE line.

    `Set L to X.Say T` then `X.SayTo Player T` -- both TES4 calls speak, so a
    literal conversion played 92 lines TWICE.  SayLine measures AND delivers,
    so the bare delivery for the same (receiver, topic) is dropped.

    A statement may sit between the halves, so scan a 3-statement window; a
    nested body ends it, since two Says in different branches are two beats.
    """
    says = {i: sig for i, st in enumerate(body)
            if (sig := _say_signature(st)) is not None}
    if len(says) < 2:
        return body
    window = 3
    drop = set()
    for i, sig in says.items():
        for j in range(i + 1, min(i + 1 + window, len(body))):
            if j in drop or _opens_a_body(body[j]):
                break
            if says.get(j) == sig:
                drop.add(j if _is_say_assignment(body[i]) else i)
                break
    return [st for i, st in enumerate(body) if i not in drop] if drop else body


def _say_signature(st):
    """`(receiver, topic)` if this statement speaks a line, else None."""
    expr = getattr(st, 'expr', None) or getattr(st, 'value', None)
    call = _find_say(expr)
    if call is None:
        return None
    recv = getattr(call.receiver, 'name', '') if call.receiver else ''
    n = 1 if (call.name.lower() == 'sayto' and len(call.args) >= 2) else 0
    topic = getattr(call.args[n], 'name', '') if len(call.args) > n else ''
    return (recv.lower(), topic.lower()) if topic else None


def _find_say(expr):
    """The `Say`/`SayTo` call inside `expr`, or None.

    An assignment wraps it (`set len to ref.Say topic`), so the walk has to
    reach through the arithmetic the author may have added to it.
    """
    if expr is None:
        return None
    for node in N.walk_expr(expr):
        if isinstance(node, N.Call) and node.name.lower() in ('say', 'sayto'):
            return node
    return None


def _is_say_assignment(st) -> bool:
    """Is this the MEASURING half -- the one that keeps the duration?"""
    return isinstance(st, N.Assign)


def _opens_a_body(st) -> bool:
    """Does this statement open a nested body, ending a scan window?"""
    return isinstance(st, (N.If, N.While, N.ForEach))


#: The polyfill call a `setDestroyed 1` becomes, and its deferred twin.
_SETDESTROYED = 'TES4Polyfill.SetDestroyed('
_DESTROY_AFTER = 'TES4Polyfill.DestroyAfterAnimation('


def _animated_targets(body) -> set:
    """Objects this body starts an ANIMATION on, by source name.

    TES4 pairs `playgroup forward 0` with `setDestroyed 1` constantly
    (CTrigTripwire01SCRIPT, CTrapLogs01SCRIPT, MPlanksBreakAway01Script)
    because in Oblivion setDestroyed on a record with no destruction data only
    blocked re-activation.  The destroy still has to run -- it is what stops
    the trap re-triggering -- but not until the polyfill has waited out the
    clip, or the object vanishes mid-animation.
    """
    names = set()
    for st in N.walk_stmts(body):
        for expr in N.walk_expr(getattr(st, 'expr', None)):
            if expr.called != 'playgroup':
                continue
            recv = getattr(expr, 'receiver', None)
            names.add(getattr(recv, 'name', '').lower() or 'self')
    return names


def _deferred_destroy(lines: list, animated: set) -> list:
    """Rewrite a destroy on a just-animated object into the deferred form.

    Only `SetDestroyed ... true` defers: `setDestroyed 0` UN-destroys, and
    rewriting it dropped the flag so both directions destroyed the object.
    """
    if not animated:
        return lines
    out = []
    for line in lines:
        head, sep, rest = line.partition(_SETDESTROYED)
        if not sep:
            out.append(line)
            continue
        target = rest.split(',')[0].strip()
        if target.lower() not in animated:
            out.append(line)
            continue
        args = [a.strip() for a in rest.rsplit(')', 1)[0].split(',')]
        if len(args) > 2 and args[2].lower() != 'true':
            out.append(line)
            continue
        out.append(f'{head}{_DESTROY_AFTER}{args[0]}, {args[1]})')
    return out
