"""Recover omitted local declarations from authored assignments and reads."""

from .constants import KNOWN_GLOBALS, TYPE_MAP
from .resolve import resolve_property_formid
from .symbols import type_of_expr
from .tes4 import nodes as N


def recover_numeric_locals(conv, tree):
    """A written, read numeric slot needs storage even if SCTX omitted its declaration."""
    declared = {v.name.lower(): TYPE_MAP.get(v.vtype.lower(), 'Int') for v in tree.variables}
    writes = {}
    reads = set()
    for block in tree.blocks:
        for stmt in N.walk_stmts(block.body):
            for attr in ('expr', 'cond', 'value'):
                reads.update(e.name.lower() for e in N.walk_expr(getattr(stmt, attr, None))
                             if isinstance(e, N.Ident))
            if isinstance(stmt, N.Assign) and isinstance(stmt.target, N.Ident):
                writes.setdefault(stmt.target.name, []).append(stmt.value)
    for name, values in writes.items():
        low = name.lower()
        if (low in declared or low not in reads or low in KNOWN_GLOBALS
                or low in ('player', 'playerref', 'self', 'fquestdelaytime')
                or resolve_property_formid(conv.xref, name) or conv._scro_alias_for(name)):
            continue
        types = {type_of_expr(value, lambda key: declared.get(key.lower(), '')) for value in values}
        if types and types <= {'Int', 'Float', 'Bool'}:
            vtype = 'float' if 'Float' in types else 'int'
            tree.variables.append(N.VarDecl(vtype=vtype, name=name))
            declared[low] = TYPE_MAP[vtype]
