"""Compile authored TES4 custom-menu XML to Skyrim Scaleform movies.

MenuQue is an Oblivion runtime, not a conversion dependency. Its XML and
tile operations are translated into the open TES4Menu movie runtime.
"""

import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from .bsa_extract import read_bsa_files


ROOT = Path(__file__).resolve().parents[1]
TILES = {'menu', 'rect', 'image', 'text', 'nif'}
OPERATORS = {'copy', 'add', 'sub', 'mul', 'mult', 'div', 'min', 'max',
             'mod', 'rand', 'floor', 'ceil', 'round', 'abs', 'gt', 'gte', 'lt', 'lte',
             'eq', 'neq', 'and', 'or', 'not', 'onlyif', 'onlyifnot', 'onlynotif', 'ref'}
# xOBSE GameTiles.h's engine Tile::Value ID table.
ENTITIES = {'true': 2, 'false': 1, 'generic': 999, 'GenericMenu': 1011,
            'no_click_past': 102, 'click_past': 101, 'center': 2, 'left': 1, 'right': 4,
            'xbox': 1, 'xboxhint': 1, 'xbuttona': 1, 'xbuttonb': 1,
            'xbuttonx': 1, 'xbuttony': 1, 'xbuttonlt': 1, 'xbuttonrt': 1}


class MenuSource:
    """Loose files override archives; cache reads while expanding includes."""
    def __init__(self, roots):
        self.roots = [Path(p) for p in roots]
        self.cache = {}

    def read(self, rel):
        rel = rel.replace('\\', '/').lstrip('/')
        if '..' in Path(rel).parts:
            raise ValueError(f'Unsafe menu asset path: {rel}')
        key = rel.lower()
        if key in self.cache:
            return self.cache[key]
        for root in self.roots:
            for path in (root / rel, root / 'misc' / rel):
                if path.is_file():
                    self.cache[key] = path.read_bytes()
                    return self.cache[key]
        for root in self.roots:
            preferred = 'Oblivion - Misc.bsa' if key.startswith('menus/') else 'Oblivion - Textures - Compressed.bsa'
            archives = sorted(root.glob('*.bsa'), key=lambda p: (p.name != preferred, p.name))
            for archive in archives:
                found = read_bsa_files(str(archive), [rel.replace('/', '\\')])
                blob = found.get(key.replace('/', '\\'))
                if blob is not None:
                    self.cache[key] = blob
                    return blob
        raise FileNotFoundError(rel)


class _XML(HTMLParser):
    """TES4 accepts fragments and mismatched trait closers, unlike XML parsers."""
    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.root = {'tag': 'root', 'attrs': {}, 'children': [], 'text': ''}
        self.stack = [self.root]
        text = re.sub(r'<(/?)_', r'<\1tes4_', text)
        self.feed(re.sub(r'&([A-Za-z_]\w*);', r'&#38;\1;', text))

    def handle_starttag(self, tag, attrs):
        if tag.startswith('tes4_'):
            tag = '_' + tag[5:]
        node = {'tag': tag, 'attrs': dict(attrs), 'children': [], 'text': ''}
        self.stack[-1]['children'].append(node)
        self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.stack.pop()

    def handle_endtag(self, tag):
        if len(self.stack) > 1:
            self.stack.pop()

    def handle_data(self, data):
        self.stack[-1]['text'] += data

    def handle_entityref(self, name):
        self.handle_data('&' + name + ';')

    def handle_charref(self, name):
        self.handle_data(chr(int(name[1:], 16) if name.startswith('x') else int(name)))


def _value(text):
    text = text.strip()
    if text.startswith('&') and text.endswith(';'):
        name = text[1:-1]
        if name not in ENTITIES:
            raise ValueError(f'Unknown TES4 UI entity: {text}')
        return ENTITIES[name]
    try:
        return float(text) if '.' in text else int(text)
    except ValueError:
        return text


def _expression(node):
    ops = []
    for child in node['children']:
        op = child['tag']
        if op not in OPERATORS:
            raise ValueError(f'Unsupported TES4 tile operator: {op}')
        attrs = child['attrs']
        ops.append([op, attrs.get('src', ''), attrs.get('trait', ''),
                    _expression(child) if child['children'] else _value(child['text'])])
    return ops if ops else _value(node['text'])


def read_layout(path, sources, includes=()):
    """Expand prefabs, preserving tile names and trait expression order."""
    if path.lower() in includes:
        raise ValueError(f'Recursive menu include: {path}')
    root = _XML(sources.read(path).decode('cp1252')).root
    def expand(node):
        result = []
        for child in node['children']:
            tag = child['tag']
            if tag == 'include':
                inc = child['attrs']['src'].replace('\\', '/')
                if not inc.lower().startswith('menus/'):
                    inc = 'menus/prefabs/' + inc
                result.extend(read_layout(inc, sources, includes + (path.lower(),)))
            elif tag in TILES:
                result.append({'kind': tag, 'name': child['attrs'].get('name', ''),
                               'items': expand(child)})
            elif tag == 'template':
                result.append({'template': child['attrs'].get('name', ''),
                               'items': expand(child)})
            else:
                result.append({'trait': tag, 'value': _expression(child)})
        return result
    return expand(root)


def _as2(value):
    """MTASC's AS2 object keys are identifiers, unlike JSON's quoted keys."""
    if isinstance(value, dict):
        return '{' + ','.join(k + ':' + _as2(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ','.join(_as2(v) for v in value) + ']'
    return json.dumps(value, ensure_ascii=True)


def convert_menus(export_dir, output_dir, data_dir):
    """Compile this plugin's generic XML menus and their referenced artwork."""
    export = Path(export_dir)
    from output_layout import assets_for
    assets = assets_for(export)
    menus = assets / 'misc/menus/generic'
    from script_convert.cross_ref import master_names
    root_plugin = not master_names(export)
    if not menus.is_dir() and not root_plugin:
        return 0
    output = Path(output_dir)
    sources = MenuSource([assets, data_dir])
    compiler = ROOT / 'external/mtasc/mtasc.exe'
    if not compiler.is_file():
        raise FileNotFoundError('Menu conversion requires external/mtasc/mtasc.exe')
    work = ROOT / 'temp/menu_compile' / export.name
    work.mkdir(parents=True, exist_ok=True)
    runtime = ROOT / 'asset_convert/menu_runtime/TES4Menu.as'
    count = 0
    if root_plugin:
        dest = output / 'interface/tes4menus/TES4TextInput.swf'
        dest.parent.mkdir(parents=True, exist_ok=True)
        (work / 'TES4InputMovie.as').write_text(
            'class TES4InputMovie { static function main(mc:MovieClip) { TES4TextInput.start(mc); }}',
            encoding='ascii')
        completed = subprocess.run([str(compiler), '-cp', str(runtime.parent),
            '-cp', str(work),
            '-version', '8', '-header', '1280:960:30', '-main', '-swf', str(dest),
            str(work / 'TES4InputMovie.as')],
            capture_output=True, text=True, timeout=60)
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
        count += 1
    textures = set()
    for menu in sorted(menus.rglob('*.xml')):
        rel = menu.relative_to(assets / 'misc').as_posix()
        try:
            layout = read_layout(rel, sources)
        except FileNotFoundError as exc:
            # Optional layouts for UI replacers may refer to a replacer the
            # source installation does not contain. FileExists selects the
            # installed variant in the converted script too.
            print(f'    Menu XML unavailable: {rel}: missing {exc}', flush=True)
            continue
        def collect(items):
            for item in items:
                value = item.get('value')
                if isinstance(value, str) and value.lower().endswith('.dds'):
                    textures.add(value.replace('\\', '/'))
                collect(item.get('items', []))
        collect(layout)
        swf_rel = Path('interface/tes4menus') / export.name / menu.relative_to(menus).with_suffix('.swf')
        dest = output / swf_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        source = ('class TES4Layout { static function main(mc:MovieClip) { '
                  'TES4Menu.start(mc, ' + _as2(layout) + '); }}')
        (work / 'TES4Layout.as').write_text(source, encoding='ascii')
        completed = subprocess.run([str(compiler), '-cp', str(runtime.parent),
            '-cp', str(work), '-version', '8', '-header', '1280:960:30',
            '-main', '-swf', str(dest), str(work / 'TES4Layout.as')],
            capture_output=True, text=True, timeout=60)
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
        count += 1
        print(f'    Menu XML: {rel} -> {swf_rel}', flush=True)
    for texture in sorted(textures):
        try:
            data = sources.read('textures/' + texture)
        except FileNotFoundError:
            # Vanilla itself names absent images in hidden platform branches
            # (button_no_background.xml). A tile with no source texture
            # remains textureless; the rest of its menu still executes.
            print(f'    Menu image absent in source: {texture} (tile has no texture)', flush=True)
            continue
        path = output / 'textures/tes4' / texture
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return count
