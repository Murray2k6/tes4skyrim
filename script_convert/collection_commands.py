"""Translate OBSE collections to reference-valued Skyrim runtime objects."""

from .commands import command
from .tes4 import nodes as N
from . import symbols


def kind(ptype):
    if ptype == 'Int':
        return 'Integer'
    if ptype == 'TES4Collection':
        return 'Array'
    if ptype == 'String':
        return 'String'
    if ptype and ptype not in ('Int', 'Float', 'Bool'):
        return 'Form'
    return 'Number'


def emit_key(ctx, node, extends):
    from .emit.expr import emit
    previous = ctx.sc.expected_type
    ctx.sc.expected_type = 'String'
    try:
        return emit(ctx, node, extends)
    finally:
        ctx.sc.expected_type = previous


def read(ctx, node, extends):
    from .emit.expr import emit
    wanted = ctx.sc.expected_type
    if symbols.type_of_expr(node.target, ctx.type_of) == 'String':
        ctx.sc.expected_type = 'String'
        try:
            target = emit(ctx, node.target, extends)
        finally:
            ctx.sc.expected_type = wanted
        return f'TES4Runtime.StringAt({target}, ({emit(ctx, node.index, extends)} as Int))'
    ctx.sc.expected_type = 'TES4Collection'
    try:
        target = emit(ctx, node.target, extends)
    finally:
        ctx.sc.expected_type = wanted
    key = emit_key(ctx, node.index, extends)
    suffix = kind(wanted)
    result = f'{target}.Get{suffix}({key} as String)'
    if suffix == 'Form' and wanted != 'Form':
        result += f' as {wanted}'
    return result


def write(ctx, stmt, extends):
    from .emit.expr import emit
    previous = ctx.sc.expected_type
    ctx.sc.expected_type = 'TES4Collection'
    try:
        target = emit(ctx, stmt.target.target, extends)
    finally:
        ctx.sc.expected_type = previous
    key = emit_key(ctx, stmt.target.index, extends)
    if isinstance(stmt.value, N.Index) and not stmt.op:
        ctx.sc.expected_type = 'TES4Collection'
        try:
            source = emit(ctx, stmt.value.target, extends)
        finally:
            ctx.sc.expected_type = previous
        source_key = emit_key(ctx, stmt.value.index, extends)
        return f'{target}.CopyValue({key} as String, {source}, {source_key} as String)'
    base_value = ctx.bind_value_record(stmt.value)
    value = base_value or emit(ctx, stmt.value, extends)
    ptype = ctx.type_of(base_value) if base_value else symbols.type_of_expr(stmt.value, ctx.type_of)
    suffix = kind(ptype)
    if stmt.op:
        value = f'{target}.Get{suffix}({key} as String) {stmt.op} {value}'
    return f'{target}.Set{suffix}({key} as String, {value})'


@command('ar_construct', 'ar_null', 'ar_size', 'ar_haskey', 'ar_erase', 'ar_resize', 'ar_find', 'ar_list', 'ar_append', 'ar_badnumericindex', 'ar_badstringindex')
def array_call(ctx, call):
    name = call.name
    if name == 'ar_badnumericindex':
        return '-99999'
    if name == 'ar_badstringindex':
        return '""'
    if name == 'ar_null':
        return 'None'
    if name == 'ar_construct':
        return 'TES4Collection.Create("' + call.source(0, 'Array').strip('"') + '")'
    if name == 'ar_size':
        return f'TES4Collections.Size({call.arg(0)})'
    if name == 'ar_append':
        target = call.arg(0)
        value = call.args[1]
        if isinstance(value, N.Index):
            from .emit.expr import emit
            previous = ctx.sc.expected_type
            ctx.sc.expected_type = 'TES4Collection'
            try:
                source = emit(ctx, value.target, call.extends)
            finally:
                ctx.sc.expected_type = previous
            key = emit_key(ctx, value.index, call.extends)
            return f'{target}.AppendValue({source}, {key} as String)'
        base = ctx.bind_value_record(value)
        ptype = ctx.type_of(base) if base else symbols.type_of_expr(value, ctx.type_of)
        return f'{target}.Append{kind(ptype)}({base or call.arg(1)})'
    if name == 'ar_haskey':
        return f'{call.arg(0)}.HasKey({call.arg(1)} as String)'
    if name == 'ar_erase':
        return (f'{call.arg(0)}.Erase({call.arg(1)} as String)' if len(call) > 1
                else f'{call.arg(0)}.Clear()')
    if name == 'ar_resize':
        ptype = symbols.type_of_expr(call.args[2], ctx.type_of) if len(call) > 2 else 'Float'
        return f'{call.arg(0)}.Resize{kind(ptype)}({call.arg(1)} as Int, {call.arg(2, "0.0")})'
    if name == 'ar_find':
        wanted = ctx.sc.expected_type
        value = call.arg(0)
        ptype = symbols.type_of_expr(call.args[0], ctx.type_of)
        result = f'{call.arg(1)}.Find{kind(ptype)}({value})'
        return result if wanted == 'String' else result + ' as Float'
    if name == 'ar_list':
        result = 'TES4Collection.Create("Array")'
        for i, value in enumerate(call.args):
            rendered = call.arg(i)
            ptype = symbols.type_of_expr(value, ctx.type_of)
            result += f'.With{kind(ptype)}("{i}", {rendered})'
        return result


@command('break', 'continue')
def loop_jump(ctx, call):
    if not ctx.sc.loop_stack:
        return None
    stop, skip = ctx.sc.loop_stack[-1]
    return (f'{stop} = True\n' if call.name == 'break' else '') + f'{skip} = True'
