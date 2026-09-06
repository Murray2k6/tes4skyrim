"""Lower OBSE string writes without losing their numeric expression results."""

from dataclasses import replace

from script_convert.commands import Call
from script_convert.symbols import type_of_expr
from script_convert.tes4 import nodes as N
from . import expr as E

MUTATORS = {'sv_replace', 'sv_insert', 'sv_erase', 'sv_set'}


def contains(node):
    return node is not None and any(n.called in MUTATORS for n in N.walk_expr(node))


def temporary(conv, kind, node, role):
    # UDF parameter inference emits the same tree twice. Reuse its temporaries.
    key = (id(node), role)
    name = conv.sc.expression_temps.setdefault(key, f'TES4_StringEdit{len(conv.sc.expression_temps)}')
    conv.sc.synthetic_vars[name] = kind
    conv.sc.var_types[name.lower()] = kind
    conv.sc.local_vars.add(name.lower())
    return N.Ident(name=name)


def lower(conv, node, extends):
    """Return prerequisite Papyrus lines and the expression that reads the result.

    Only expressions containing a string write are changed. Boolean right sides
    keep their short-circuit guards; operands before a write are evaluated first.
    """
    if not contains(node):
        return [], node
    if isinstance(node, N.BinOp):
        before, left = lower(conv, node.left, extends)
        right_lines, right = lower(conv, node.right, extends)
        if not right_lines:
            return before, replace(node, left=left, right=right)
        logical = node.op in ('&&', '||', 'and', 'or')
        kind = 'Bool' if logical else type_of_expr(left, conv.type_of) or 'Float'
        saved = temporary(conv, 'Float' if kind == 'GlobalVariable' else kind, node, 'left')
        before.append(f'{saved.name} = {E.emit(conv, left, extends)}')
        if logical:
            guard = '!' if node.op in ('||', 'or') else ''
            before += [f'If {guard}{saved.name}']
            before += ['  ' + line for line in right_lines]
            before += [f'  {saved.name} = {E.emit(conv, right, extends)}', 'EndIf']
            return before, saved
        return before + right_lines, replace(node, left=saved, right=right)
    if isinstance(node, N.Unary):
        before, operand = lower(conv, node.operand, extends)
        return before, replace(node, operand=operand)
    if isinstance(node, N.Call):
        before, args = [], []
        for index, arg in enumerate(node.args):
            lines, value = lower(conv, arg, extends)
            before += lines
            # Format literals and string-write lvalues must keep their source
            # spelling. Earlier evaluated arguments to an enclosing call do not.
            if node.called not in MUTATORS and not isinstance(value, N.Literal) and any(
                    contains(later) for later in node.args[index + 1:]):
                saved = temporary(conv, type_of_expr(value, conv.type_of) or 'Float', node, index)
                before.append(f'{saved.name} = {E.emit(conv, value, extends)}')
                value = saved
            args.append(value)
        current = replace(node, args=tuple(args))
        if current.called not in MUTATORS:
            return before, current
        lines, result = edit(conv, current, extends, node)
        return before + lines, result
    if isinstance(node, N.Index):
        before, target = lower(conv, node.target, extends)
        lines, index = lower(conv, node.index, extends)
        return before + lines, replace(node, target=target, index=index)
    return [], node


def edit(conv, node, extends, original):
    call = Call(conv, E.emit_source(node.receiver) if node.receiver else None,
                node.name, extends, node.args)
    previous = conv._arg_nodes
    conv._arg_nodes = call.args
    try:
        index, formatted = 0, '""'
        if node.called != 'sv_erase':
            source = call.source(0)
            consumed = sum(m.group(0).lower() not in ('%%', '%r', '%q', '%e')
                           for m in conv._OBSE_FMT_RE.finditer(source)) if source.startswith('"') else 0
            index = 1 + consumed
            formatted = (conv._format_string_call(source, extends, range(1, index))
                         if source.startswith('"') else call.arg(0))
        if index >= len(call):
            raise ValueError(f'{node.name} requires a string variable')
        args = [call.arg(index), formatted, f'"{node.called[3:]}"',
                f'({call.arg(index + 1, "0")}) as Int',
                f'({call.arg(index + 2, "-1")}) as Int',
                f'({call.arg(index + 3, "False")}) as Bool',
                f'({call.arg(index + 4, "-1")}) as Int']
        pair = temporary(conv, 'String[]', original, 'pair')
        result = temporary(conv, 'Int', original, 'result')
        lines = [f'{pair.name} = TES4Runtime.StringEdit({", ".join(args)})']
        lines += conv.emit_assignment(N.Assign(target=call.args[index],
            value=N.Raw(text=f'{pair.name}[0]')), extends).splitlines()
        lines += [f'{result.name} = {pair.name}[1] as Int', f'{pair.name} = None']
        return lines, result
    finally:
        conv._arg_nodes = previous


def statement(conv, stmt, extends):
    field = 'value' if isinstance(stmt, (N.Assign, N.SetFunctionValue)) else 'expr'
    value = getattr(stmt, field, None)
    before, value = lower(conv, value, extends)
    if not before:
        return [], stmt
    if isinstance(stmt, N.ExprStmt) and stmt.expr.called in MUTATORS:
        return before, N.Blank()
    return before, replace(stmt, **{field: value})
