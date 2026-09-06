"""Dynamic OBSE functions use saved Papyrus call stacks and typed value packs."""
from .collection_commands import kind, emit_key
from .emit.expr import emit
from .symbols import type_of_expr
from .tes4 import nodes as N


def dynamic_call(ctx, call, caller):
    wanted = ctx.sc.expected_type
    target = f'(({call.arg(0, wanted="Form")} as Form) as TES4Function)'
    packed = 'TES4Collection.Create("Array")'
    for index, value in enumerate(call.args[1:]):
        if isinstance(value, N.Index):
            previous = ctx.sc.expected_type
            ctx.sc.expected_type = 'TES4Collection'
            try:
                source = emit(ctx, value.target, call.extends)
            finally:
                ctx.sc.expected_type = previous
            key = emit_key(ctx, value.index, call.extends)
            packed += f'.WithValue("{index}", {source}, {key} as String)'
        else:
            base = ctx.bind_value_record(value)
            ptype = ctx.type_of(base) if base else type_of_expr(value, ctx.type_of)
            packed += f'.With{kind(ptype)}("{index}", {base or call.arg(index + 1)})'
    suffix = kind(wanted)
    result = f'{target}.TES4Invoke({caller}, {packed}).Get{suffix}("result")'
    if suffix == 'Form' and wanted != 'Form':
        result += f' as {wanted}'
    return result


def invocation_wrapper(types, result_type):
    args = ['TES4_Caller']
    for index, ptype in enumerate(types):
        suffix = kind(ptype)
        value = f'TES4_Arguments.Get{suffix}("{index}")'
        if suffix == 'Form' and ptype != 'Form' or ptype == 'Bool':
            value += f' as {ptype}'
        args.append(value)
    return [
        'TES4Collection Function TES4Invoke(ObjectReference TES4_Caller, TES4Collection TES4_Arguments)',
        f'  Return TES4Collection.Create("StringMap").With{kind(result_type)}("result", TES4Call({", ".join(args)}))',
        'EndFunction', '',
    ]
