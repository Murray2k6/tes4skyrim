"""MenuQue calls routed to the converted Scaleform tile runtime."""

import json

from .commands import command


@command('iskeypressed', 'iskeypressed2', 'iskeypressed3')
def key_pressed(ctx, call):
    method = {'iskeypressed': 'TES4Runtime.IsVirtualKeyPressed',
              'iskeypressed2': 'Input.IsKeyPressed',
              'iskeypressed3': 'TES4Input.PhysicalKey'}[call.name]
    return f'{method}({call.arg(0, "0", wanted="Int")} as Int)'


@command('showgenericmenu')
def show_generic(ctx, call):
    plugin = getattr(ctx.xref, 'export_plugin_name', '')
    return f'TES4Menu.Open({json.dumps(plugin)}, {call.arg(0, chr(34) + chr(34))})'


def _format(ctx, call, trailing):
    end = len(call) - trailing
    # TES4 paths have literal backslashes. Papyrus string literals need them
    # escaped or a path component beginning with n/t becomes a newline/tab.
    fmt = call.source(0)
    return (ctx._format_string_call(fmt, call.extends, range(1, end))
            if fmt.startswith('"') else call.arg(0))


@command('opentextinput', 'updatetextinput', 'closetextinput', 'getinputtext',
         'insertininputtext', 'deletefrominputtext', 'movetextinputcursor',
         'gettextinputcursorpos', bare=True)
def text_input(ctx, call):
    if call.name == 'opentextinput':
        source = call.source(0)
        count = (sum(m.group(0).lower() not in ('%%', '%r', '%q', '%e')
                     for m in ctx._OBSE_FMT_RE.finditer(source))
                 if source.startswith('"') else 0)
        return (f'TES4Input.Open({_format(ctx, call, len(call) - count - 1)}, '
                f'({call.arg(count + 1, "0")} as Int), '
                f'({call.arg(count + 2, "16384")} as Int))')
    if call.name == 'getinputtext':
        return f'TES4Input.Text({call.arg(0, "False")} as Bool)'
    if call.name == 'insertininputtext':
        return f'TES4Input.Insert({_format(ctx, call, 0)})'
    if call.name in ('deletefrominputtext', 'movetextinputcursor'):
        method = 'DeleteText' if call.name == 'deletefrominputtext' else 'Move'
        args = f'({call.arg(0, "0")} as Int), ({call.arg(1, "False")} as Bool)'
        if method == 'DeleteText':
            args += f', ({call.arg(2, "False")} as Bool)'
        return f'TES4Input.{method}({args})'
    method = {'updatetextinput': 'Update', 'closetextinput': 'Close',
              'gettextinputcursorpos': 'Cursor'}[call.name]
    return f'TES4Input.{method}()'


@command('setmenufloatvalue', 'setmenustringvalue', 'getmenufloatvalue',
         'getmenustringvalue', 'getmenuhastrait', 'clickmenubutton')
def tile_value(ctx, call):
    if call.name == 'setmenufloatvalue':
        return (f'TES4Menu.SetNumber({call.arg(len(call) - 2)}, '
                f'{_format(ctx, call, 2)}, {call.arg(len(call) - 1)})')
    methods = {'setmenustringvalue': 'SetString', 'getmenufloatvalue': 'GetNumber',
               'getmenustringvalue': 'GetString', 'getmenuhastrait': 'HasTrait',
               'clickmenubutton': 'Click'}
    return (f'TES4Menu.{methods[call.name]}({call.arg(len(call) - 1)}, '
            f'{_format(ctx, call, 1)})')


@command('setmenueventhandler')
def register_event(ctx, call):
    return (f'({call.arg(1)} as TES4Function).RegisterMenuHandler('
            f'{call.arg(0)}, {call.arg(2, "1011")}, {call.arg(3, "-1")})')


@command('getactivemenumode', 'getactivemenuselection', 'getactivemenuref',
         'isbartermenuactive', 'istextinputinuse', 'xxnisgamepadconnected', 'xxnisgamepadkeypressed', bare=True)
def menu_read(ctx, call):
    if call.name == 'xxnisgamepadconnected':
        return f'TES4Runtime.IsGamepadConnected({call.arg(0, "-1")} as Int)'
    if call.name == 'xxnisgamepadkeypressed':
        return (f'TES4Runtime.IsGamepadKeyPressed(({call.arg(0, "-1")} as Int), '
                f'({call.arg(1, "0")} as Int), ({call.arg(2, "0")} as Int))')
    if call.name in ('getactivemenuselection', 'getactivemenuref'):
        name = 'GetActiveMenuSelection' if call.name == 'getactivemenuselection' else 'GetActiveMenuRef'
        return f'TES4Runtime.{name}({call.arg(0, "0")} as Int)'
    return {'getactivemenumode': 'TES4Menu.ActiveMenu()',
            'istextinputinuse': 'TES4Runtime.IsTextInputInUse()',
            'isbartermenuactive': 'UI.IsMenuOpen("BarterMenu")'}[call.name]
