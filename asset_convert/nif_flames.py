"""
Flame attachment for Oblivion's "fake" light NIFs.

Oblivion marks where a flame burns with an empty FlameNode* NiNode and attaches
a flame NIF there at runtime. Skyrim has no such runtime attachment, so the
matching Oblivion flame NIF is converted once (cached per worker) and its
subtree grafted under each marker.

See: docs/commentary/asset_convert_nif.md#flame-attachment-flamenode-sockets
"""

import io as _io
import re
from pathlib import Path

from pyffi.formats.nif import NifFormat
from output_layout import assets_for
from .base_plugins import ordered_record_dirs
from .mesh_metadata import resolve_mesh_paths

#: Reads FlameNode<N> STAT records: the plugin owns the socket->flame mapping, so never guess it.
_FLAME_STAT_RE = re.compile(
    r'EditorID=(FlameNode(\d+))\s.*?Model\.MODL=([^\r\n]+)', re.S)
#: Socket names match the engine's table EXACTLY: "FlameNode0"/"12" but never a zero-padded "07".
_FLAME_SOCKET_RE = re.compile(r'^FlameNode(0|[1-9][0-9]*)(?![0-9])')
#: export_root_lower -> {socket index: authored model path}, including masters.
_FLAME_SOCKET_MAP = {}


def _asset_root(src_path):
    norm = str(src_path).replace('\\', '/')
    position = norm.lower().rfind('/meshes/')
    return Path(norm[:position]) if position >= 0 else None


def _flame_socket_map(src_path):
    """{socket index: authored model path} from effective FlameNode STATs."""
    export_root = _asset_root(src_path)
    if export_root is None:
        return {}
    ck = str(export_root).lower()
    cached = _FLAME_SOCKET_MAP.get(ck)
    if cached is not None:
        return cached
    table = {}
    for record_dir in ordered_record_dirs(export_root):
        stat_txt = record_dir / 'STAT.txt'
        if not stat_txt.is_file():
            continue
        blob = stat_txt.read_text(encoding='latin1')
        for rec in blob.split('---RECORD_BEGIN---'):
            if 'FlameNode' not in rec:
                continue
            m = _FLAME_STAT_RE.search(rec)
            if not m:
                continue
            model = m.group(3).strip().replace(chr(92), '/')
            table[int(m.group(2))] = '/'.join(
                part for part in model.lower().split('/') if part)
    _FLAME_SOCKET_MAP[ck] = table
    return table


def _flame_socket_index(node_name):
    """The N in a FlameNode<N> marker name, or None.

    Oblivion suffixes duplicates ("FlameNode0@#3", "FlameNode0	"), so match a
    leading run of digits rather than parsing the whole name.
    """
    if isinstance(node_name, bytes):
        node_name = node_name.decode('latin1', 'replace')
    m = _FLAME_SOCKET_RE.match(node_name)
    return int(m.group(1)) if m else None


def _flame_nif_for_socket(src_path, index):
    """The flame NIF for a FlameNode<index> socket; None burns nothing."""
    if index is None:
        return None
    return _flame_socket_map(src_path).get(index)


#: Resolved source path -> converted NIF bytes.
_FLAME_CACHE = {}
#: Same key as _FLAME_CACHE -> the flip-book atlas jobs that conversion produced.
_FLAME_ATLAS_JOBS = {}
_FLAME_SOURCES = {}


def _flame_source(src_path, flame_name):
    root = _asset_root(src_path)
    if root is None:
        raise ValueError(f'Flame host has no source meshes directory: {src_path}')
    key = (str(root).lower(), flame_name)
    if key in _FLAME_SOURCES:
        return _FLAME_SOURCES[key]
    roots = list(dict.fromkeys(assets_for(d) / 'meshes'
                              for d in ordered_record_dirs(root)))
    roots.append(root / 'meshes')
    found = resolve_mesh_paths(roots, [flame_name])
    if flame_name not in found:
        raise FileNotFoundError(
            f'Flame model {flame_name!r} for {src_path} is absent from the mod and its bases')
    _FLAME_SOURCES[key] = found[flame_name]
    return found[flame_name]


def _load_converted_flame(src_path, flame_name, convert_nif):
    """Convert the winning authored flame model once per worker.

    `convert_nif` is passed in rather than imported: the flame subtree is built
    by the very converter that calls this, so importing it here would be circular.
    Callers deep-copy by re-reading the returned bytes.
    """
    flame_src = _flame_source(src_path, flame_name)
    cache_key = flame_src.lower()
    if cache_key in _FLAME_CACHE:
        return _FLAME_CACHE[cache_key]
    fdata = NifFormat.Data()
    with open(flame_src, 'rb') as f:
        fdata.read(f)
    fstats = convert_nif(fdata, fix_textures=True, src_path=flame_src)
    buf = _io.BytesIO()
    fdata.write(buf)
    result = buf.getvalue()
    _FLAME_ATLAS_JOBS[cache_key] = fstats.get('_flipbook_atlases', {})
    _FLAME_CACHE[cache_key] = result
    return result


def _reread_flame_children(flame_bytes):
    """Deep-copy a converted flame by re-reading its bytes; its root's children."""
    fdata = NifFormat.Data()
    buf = _io.BytesIO(flame_bytes)
    fdata.inspect(buf)
    buf.seek(0)
    fdata.read(buf)
    return [c for c in fdata.roots[0].children if c is not None]


def _is_empty_flame_socket(child):
    """True for an empty FlameNode* NiNode -- a marker awaiting a graft."""
    if not isinstance(child, NifFormat.NiNode) or child.num_children:
        return False
    name = getattr(child, 'name', b'') or b''
    if isinstance(name, bytes):
        name = name.decode('latin1')
    return name.startswith('FlameNode')


def _socket_name(child):
    """A marker node's name as text."""
    name = getattr(child, 'name', b'') or b''
    return name.decode('latin1') if isinstance(name, bytes) else name


def _mark_root_animated(root_node):
    """Set BSXFlags bit 0 (Animated): grafted particles need per-frame updates."""
    if not hasattr(root_node, 'extra_data_list'):
        return
    for ed in root_node.extra_data_list:
        if isinstance(ed, NifFormat.BSXFlags):
            ed.integer_data |= 0x01
            return
    bsx = NifFormat.BSXFlags()
    bsx.name = b'BSX'
    bsx.integer_data = 0x01
    root_node.num_extra_data_list += 1
    root_node.extra_data_list.update_size()
    for i in range(root_node.num_extra_data_list - 1, 0, -1):
        root_node.extra_data_list[i] = root_node.extra_data_list[i - 1]
    root_node.extra_data_list[0] = bsx


def _propagate_atlas_jobs(src_path, used_flames, stats):
    """Carry the flames' flip-book atlas jobs onto the host's stats.

    Idempotent and exists-checked, so convert_nif builds them into this host's
    output tree as well.
    """
    for name in used_flames:
        jobs = _FLAME_ATLAS_JOBS.get(_flame_source(src_path, name).lower(), {})
        if jobs:
            stats.setdefault('_flipbook_atlases', {}).update(jobs)


def _graft_socket(child, src_path, convert_nif, used_flames):
    """Graft the flame for one marker. True when something was attached.

    The marker's authored rotation, translation and scale are left untouched.
    """
    flame_name = _flame_nif_for_socket(src_path, _flame_socket_index(_socket_name(child)))
    if flame_name is None:
        return False
    flame_bytes = _load_converted_flame(src_path, flame_name, convert_nif)
    if flame_bytes is None:
        return False
    used_flames.add(flame_name)
    kids = _reread_flame_children(flame_bytes)
    child.num_children = len(kids)
    child.children.update_size()
    for j, k in enumerate(kids):
        child.children[j] = k
    return True


def convert_flame_nodes(root_node, src_path, convert_nif, stats=None):
    """Graft the converted flame NIF under every empty FlameNode* marker.

    Modifies root_node's tree in-place and returns the graft count. The
    marker's TRANSLATION, SCALE and ROTATION are all kept: the rotation is the
    authored host-frame -> flame-frame hook-up, not a stray value, and zeroing
    it lays the flame on its side. The socket is resolved per marker, since one
    mesh can mix socket families.

    See: docs/commentary/asset_convert_nif.md#the-marker-rotation-must-not-be-zeroed
    """
    used_flames = set()
    count = 0
    pending = [root_node]
    while pending:
        node = pending.pop()
        if not isinstance(node, NifFormat.NiNode):
            continue
        for child in node.children:
            if child is None:
                continue
            if _is_empty_flame_socket(child):
                if _graft_socket(child, src_path, convert_nif, used_flames):
                    count += 1
            else:
                pending.append(child)

    if count:
        _mark_root_animated(root_node)
        if stats is not None:
            _propagate_atlas_jobs(src_path, used_flames, stats)
    return count
