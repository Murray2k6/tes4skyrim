"""Resolve authored file probes and TES4 console batches during conversion."""

import json
import re
from functools import lru_cache
from pathlib import Path, PureWindowsPath

from output_layout import assets_for
from .commands import command
from .tes4 import nodes as N


def read_batch(path):
    raw = Path(path).read_bytes()
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('cp1252')


@lru_cache(maxsize=None)
def source_roots(export_dir):
    roots = []
    if export_dir:
        root = assets_for(export_dir)
        roots.extend((root, root / 'misc'))
    config = Path(__file__).resolve().parents[1] / 'conversion_config.json'
    if config.is_file():
        data = json.loads(config.read_text(encoding='utf-8')).get('tes4DataPath')
        if data:
            roots.append(Path(data))
    return roots


def source_file(export_dir, authored):
    path = PureWindowsPath(authored)
    if path.is_absolute() or '..' in path.parts:
        return None
    parts = list(path.parts)
    if parts and parts[0].lower() == 'data':
        parts.pop(0)
    for root in source_roots(str(export_dir)):
        candidate = root.joinpath(*parts)
        if candidate.is_file():
            return candidate
    return None


def batch_sources(source, export_dir, seen=None):
    """Include batch assignments in cross-script type inference as well."""
    seen = set() if seen is None else seen
    for match in re.finditer(r'(?im)^\s*RunBatchScript\s+"([^"]+)"', source):
        path = source_file(export_dir, match.group(1))
        if path is None or path in seen:
            continue
        seen.add(path)
        text = read_batch(path)
        yield text
        yield from batch_sources(text, export_dir, seen)


@command('fileexists')
def file_exists(ctx, call):
    if call.args and isinstance(call.args[0], N.Literal) and call.args[0].is_string:
        authored = call.args[0].text[1:-1]
        return str(int(source_file(getattr(ctx.xref, 'export_dir', ''), authored) is not None))
    return f'TES4Runtime.FileExists({call.arg(0)})'


def constant_strings(sources):
    """Authored constant string assignments, including included console INIs."""
    values = {}
    pattern = re.compile(r'(?im)^[ \t]*set\s+([\w.]+)\s+to\s+sv_Construct\s+"([^"\r\n]*)"[ \t]*(?:;[^\r\n]*)?\r?$')
    for source in sources:
        for match in pattern.finditer(source):
            value = match[2]
            value = re.sub(r'%(?:%|[qre])', lambda m: {'%%': '%', '%q': '"', '%r': '\n', '%e': ''}[m[0].lower()], value, flags=re.I)
            values.setdefault(match[1].lower(), set()).add(value)
    return values


@command('runscriptline')
def run_line(ctx, call):
    from .tes4.parser import parse, Mode
    from .emit.script import emit_body
    from .emit.expr import emit, emit_source
    from .constants import _safe_property_name
    from .symbols import type_of_expr
    def external(member):
        return (isinstance(member, N.Member) and isinstance(member.owner, N.Ident)
                and member.owner.name.lower() not in ctx.sc.local_vars
                and member.owner.name.lower() not in getattr(ctx.xref, 'edid_to_formid', {}))
    def lower_writes(body):
        for index, statement in enumerate(body):
            for attr in ('body', 'orelse'):
                lower_writes(getattr(statement, attr, []))
            for _, nested, _ in getattr(statement, 'elifs', []):
                lower_writes(nested)
            if not isinstance(statement, N.Assign) or not external(statement.target):
                continue
            member = statement.target
            kind = type_of_expr(statement.value, ctx.type_of)
            if kind not in ('Int', 'Float', 'Bool', 'String'):
                continue  # Keep the diagnostic for a type that cannot be written.
            field = 'String' if kind == 'String' else 'Number'
            args = f'{json.dumps(member.owner.name)}, {json.dumps(_safe_property_name(member.name))}'
            value = emit(ctx, statement.value, call.extends)
            if statement.op:
                value = f'TES4Runtime.ReadScript{field}({args}) {statement.op} ({value})'
            if field == 'Number':
                value = f'({value}) as Float'
            body[index] = N.ExprStmt(N.Raw(f'TES4Runtime.WriteScript{field}({args}, {value})'),
                                     line=statement.line, comment=statement.comment)
    def converted(source):
        tree = parse(source, Mode.FRAGMENT)
        for statement in N.walk_stmts(tree.body):
            if not isinstance(statement, N.Assign) or not isinstance(statement.value, N.Member):
                continue
            member = statement.value
            if not external(member):
                continue
            target = emit_source(statement.target)
            kind = ctx.remote_type_of(target) or ctx.type_of(target)
            if kind in ('Int', 'Float', 'Bool'):
                fallback = emit(ctx, statement.target, call.extends)
                statement.value = N.Raw(f'(TES4Runtime.ReadScriptNumber({json.dumps(member.owner.name)}, '
                    f'{json.dumps(_safe_property_name(member.name))}, ({fallback}) as Float) as {kind})')
        lower_writes(tree.body)
        return emit_body(ctx, tree.body, call.extends)
    if not call.args:
        return 'Debug.Trace("TES4 RunScriptLine: missing command")'
    raw = call.source(0).strip('"')
    if raw.lower() == '%z' and len(call) == 2:
        variable = call.source(1).lstrip('$').lower()
        actual = call.arg(1)
        candidates = sorted(getattr(ctx.xref, 'constant_strings', {}).get(variable, ()))
        from .commands import REGISTRY
        from .constants import COMMAND_ROWS
        def is_command(source):
            head = re.match(r'(?:[A-Za-z_]\w*\.)?([A-Za-z_]\w*)(?=\s|$)', source)
            return bool(head and (head[1].lower() in {'set', 'let'}
                                 or head[1].lower() in REGISTRY
                                 or head[1].lower() in COMMAND_ROWS))
        candidates = [source for source in candidates if is_command(source)]
    elif isinstance(call.args[0], N.Literal) and all(
            match[0].lower() in ('%%', '%q', '%r', '%e') for match in ctx._OBSE_FMT_RE.finditer(raw)):
        decoded = re.sub(r'%(?:%|[qre])', lambda m: {
            '%%': '%', '%q': '"', '%r': '\n', '%e': ''}[m[0].lower()], raw, flags=re.I)
        return '\n'.join(converted(decoded))
    else:
        actual = ctx._format_string_call(call.source(0), call.extends)
        candidates = []
    result = []
    for source in candidates:
        result.append(('If ' if not result else 'ElseIf ') + actual + ' == ' + json.dumps(source, ensure_ascii=False))
        result.extend('  ' + line for line in converted(source))
    if result:
        result.append('Else')
    result.append('  Debug.Trace("TES4 RunScriptLine: unconverted command: " + ' + actual + ')')
    ctx.note('RunScriptLine: runtime command outside the translated source set')
    if candidates:
        result.append('EndIf')
    return '\n'.join(result)


@command('getformfrommod')
def form_from_mod(ctx, call):
    if len(call.args) > 1 and isinstance(call.args[1], (N.Literal, N.Ident)):
        raw = call.source(1).strip('"')
        try:
            if raw.lower() in ctx.sc.local_vars:
                raise ValueError('dynamic form ID')
            form_id = int(raw, 16) & 0xFFFFFF
        except ValueError:
            pass
        else:
            if form_id == 0x14 and call.source(0).strip('"').lower() == 'oblivion.esm':
                return 'Game.GetPlayer()'
            return f'Game.GetFormFromFile(0x{form_id:06X}, {call.arg(0)})'
    return f'TES4Polyfill.GetFormFromMod({call.arg(0)}, {call.arg(1)} as String)'


@lru_cache(maxsize=None)
def _batch_tree(path):
    from .tes4.parser import parse, Mode
    text = read_batch(path)
    return parse(text, Mode.FRAGMENT)


@command('runbatchscript')
def run_batch(ctx, call):
    # These are TES4 console commands, never operating-system commands.
    if not call.args or not isinstance(call.args[0], N.Literal) or not call.args[0].is_string:
        return None
    authored = call.args[0].text[1:-1]
    path = source_file(getattr(ctx.xref, 'export_dir', ''), authored)
    if path is None:
        return 'Debug.Trace(' + json.dumps('TES4 batch file unavailable: ' + authored) + ')'
    from .emit.script import emit_body
    stack = ctx.sc.batch_stack
    if path in stack:
        raise ValueError(f'Recursive TES4 batch include: {authored}')
    tree = _batch_tree(str(path))
    if any(isinstance(st, N.Return) for st in N.walk_stmts(tree.body)):
        raise ValueError(f'TES4 batch needs its own variable/return scope: {authored}')
    stack.append(path)
    try:
        from .commands import REGISTRY
        from .constants import COMMAND_ROWS, RETURN_TYPES
        # RunBatchScript compiles each console line separately and continues
        # after a rejected line. A naked record/variable name is not a call;
        # treating it as one made the entire containing Papyrus script fail.
        values = {st.target.name.lower() for st in N.walk_stmts(tree.body)
                  if isinstance(st, N.Assign) and isinstance(st.target, (N.Member, N.Ident))}
        values.update(getattr(ctx.xref, 'edid_to_formid', {}))
        body = []
        for st in tree.body:
            # xOBSE executes each console line with a fresh Script. A local
            # declaration cannot create a shared batch scope; it must not
            # prevent the following quest-variable assignments from running.
            if isinstance(st, (N.Comment, N.Blank, N.VarDecl)):
                continue
            expr = st.expr if isinstance(st, N.ExprStmt) else None
            if (isinstance(expr, N.Call) and not expr.args and expr.receiver is None
                    and expr.name.lower() in values
                    and expr.name.lower() not in REGISTRY
                    and expr.name.lower() not in COMMAND_ROWS
                    and expr.name.lower() not in RETURN_TYPES):
                print(f'    Console batch {authored}:{st.line}: rejected value-only line {expr.name}', flush=True)
                continue
            body.append(st)
        return '\n'.join(emit_body(ctx, body, call.extends))
    finally:
        stack.pop()
