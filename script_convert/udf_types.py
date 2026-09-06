"""Source-level return contracts shared by UDF definitions and callers."""

import re

from .tes4 import nodes as N
from .tes4.parser import parse
from .symbols import type_of_expr


def parameter_types(sources, variables):
    """Authored UDF input contracts, available before callers are emitted."""
    result = {}
    for name, source in sources.items():
        header = re.search(r'(?im)^\s*begin\s+_?function\s*\{([^}]*)\}', source)
        if header:
            params = header[1].replace(',', ' ').split()
            types = variables.get(name, {})
            result[name] = ['Form' if types.get(p.lower()) in ('ObjectReference', 'Actor')
                            else types.get(p.lower(), 'Int') for p in params]
    return result


def result_type(types):
    types = set(types) - {''}
    if 'TES4Collection' in types:
        return 'TES4Collection'
    if 'String' in types:
        return 'String'
    if types - {'Int', 'Float', 'Bool'}:
        return 'Form'
    return 'Float' if 'Float' in types else 'Int'


def infer_returns(sources, variables, records=None):
    expressions = {}
    elements = {}
    for name, source in sources.items():
        if not re.search(r'(?im)^\s*begin\s+_?function\b', source):
            continue
        tree = parse(source)
        writes = {}
        for block in tree.blocks:
            for st in N.walk_stmts(block.body):
                if not isinstance(st, N.Assign):
                    continue
                if isinstance(st.target, N.Index) and isinstance(st.target.target, N.Ident):
                    writes.setdefault(st.target.target.name.lower(), []).append(st.value)
                elif (isinstance(st.target, N.Ident) and isinstance(st.value, N.Call)
                      and st.value.name.lower() == 'ar_list'):
                    writes.setdefault(st.target.name.lower(), []).extend(st.value.args)
        elements[name] = writes
        values = [st.value for block in tree.blocks
                  if block.btype.lower() == 'function'
                  for st in N.walk_stmts(block.body)
                  if isinstance(st, N.SetFunctionValue) and st.value is not None]
        # OBSE Call initializes its result to zero even when the function
        # never executes SetFunctionValue (Commands_General.cpp).
        expressions[name] = values
    returns = {}
    element_types = {}
    for _ in range(len(expressions) + 1):
        updated = dict(returns)
        previous_elements = dict(element_types)
        for name, values in expressions.items():
            def lookup(key):
                if key.startswith('call:'):
                    return returns.get(key[5:].lower(), '')
                if key.startswith('element:'):
                    return element_types.get((name, key[8:].lower()), '')
                return (variables.get(name, {}).get(key.lower(), '')
                        or (records or {}).get(key.lower(), ''))
            for array, writes in elements[name].items():
                types = [type_of_expr(v, lookup) for v in writes]
                if any(types):
                    element_types[name, array] = result_type(types)
            updated[name] = result_type(type_of_expr(v, lookup) for v in values)
        if updated == returns and element_types == previous_elements:
            break
        returns = updated
    return returns
