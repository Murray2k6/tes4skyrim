"""
Morrowind base-object exporters.

Each emits the KEY=VALUE vocabulary the TES4 exporters already produce, so
tes5_import needs no new converters. Morrowind names its mesh MODL and its
display name FNAM where TES4 uses MODL and FULL.

See: docs/commentary/tes4_export_morrowind.md#the-tes3-container
"""

import struct

from ..record_types.common import escape_value
from ..tes3_reader import Tes3Record, get_string, get_subrecord

#: Source extensions that always ship as DDS, whatever a record calls them.
_IMAGE_EXTS = ('tga', 'bmp')


def as_dds(path: str) -> str:
    """A texture path with a .tga or .bmp extension changed to .dds.

    Morrowind names textures .tga but its archives ship .dds, substituting at
    load; without this every icon path names a file that does not exist.
    """
    stem, dot, ext = path.rpartition('.')
    if dot and ext.lower() in _IMAGE_EXTS:
        return stem + '.dds'
    return path


def _emit_str(lines: list, key: str, rec: Tes3Record, sig: str) -> None:
    """Emit a string subrecord under the TES4 key name."""
    sub = get_subrecord(rec, sig)
    if sub:
        text = get_string(sub)
        if text:
            lines.append(f'{key}={escape_value(text)}')


def _emit_model(lines: list, rec: Tes3Record) -> None:
    """Emit the mesh path, normalised the way the asset stages expect."""
    sub = get_subrecord(rec, 'MODL')
    if sub:
        path = get_string(sub).replace('/', chr(92))
        if path:
            lines.append(f'Model.MODL={escape_value(path)}')


def _emit_common(lines: list, rec: Tes3Record) -> None:
    """EditorID, display name, mesh and script -- shared by most types."""
    lines.append(f'EditorID={escape_value(rec.record_id)}')
    _emit_str(lines, 'FULL', rec, 'FNAM')
    _emit_model(lines, rec)
    _emit_str(lines, 'ScriptName', rec, 'SCRI')


def _emit_icon(lines: list, rec: Tes3Record, sig: str = 'ITEX',
               prefix: str = '') -> None:
    """Emit the inventory icon path, renamed to the file that ships.

    Morrowind records name icons `.tga`, but its own BSAs contain `.dds` --
    the engine substitutes the extension at load time and we must too, or
    every icon path points at a file that does not exist.
    """
    sub = get_subrecord(rec, sig)
    if sub is None:
        return
    path = get_string(sub).replace('/', chr(92))
    if path:
        lines.append(f'ICON={escape_value(prefix + as_dds(path))}')




def export_STAT(rec: Tes3Record) -> list:
    """A static: a mesh and nothing else."""
    lines = [f'EditorID={escape_value(rec.record_id)}']
    _emit_model(lines, rec)
    return lines


def export_ACTI(rec: Tes3Record) -> list:
    """An activator."""
    lines = []
    _emit_common(lines, rec)
    return lines


def export_DOOR(rec: Tes3Record) -> list:
    """A door, with its open and close sound IDs."""
    lines = []
    _emit_common(lines, rec)
    _emit_str(lines, 'OpenSound', rec, 'SNAM')
    _emit_str(lines, 'CloseSound', rec, 'ANAM')
    return lines


def export_CONT(rec: Tes3Record) -> list:
    """A container: capacity, flags and its inventory list."""
    lines = []
    _emit_common(lines, rec)
    cndt = get_subrecord(rec, 'CNDT')
    if cndt and len(cndt.data) >= 4:
        lines.append(f"Weight={struct.unpack_from('<f', cndt.data, 0)[0]}")
    flag = get_subrecord(rec, 'FLAG')
    if flag and len(flag.data) >= 4:
        lines.append(f"ContainerFlags={struct.unpack_from('<I', flag.data, 0)[0]}")
    _emit_inventory(lines, rec)
    return lines


def _emit_inventory(lines: list, rec: Tes3Record) -> None:
    """Emit NPCO entries: a 4-byte count then a fixed 32-byte item ID."""
    index = 0
    for sub in rec.subrecords:
        if sub.type != 'NPCO' or len(sub.data) < 36:
            continue
        count = struct.unpack_from('<i', sub.data, 0)[0]
        item = sub.data[4:36].split(b'\x00', 1)[0].decode('cp1252', 'replace')
        lines.append(f'Item[{index}].Object={escape_value(item)}')
        lines.append(f'Item[{index}].Count={count}')
        index += 1


def export_LIGH(rec: Tes3Record) -> list:
    """A light: LHDT carries weight, value, time, radius, colour and flags."""
    lines = []
    _emit_common(lines, rec)
    _emit_icon(lines, rec)
    lhdt = get_subrecord(rec, 'LHDT')
    if lhdt and len(lhdt.data) >= 24:
        weight, value, time, radius, color, flags = struct.unpack_from(
            '<fiiiIi', lhdt.data, 0)
        lines.append(f'Weight={weight}')
        lines.append(f'Value={value}')
        lines.append(f'Time={time}')
        lines.append(f'Radius={radius}')
        lines.append(f'LightColor={color}')
        lines.append(f'LightFlags={flags}')
    return lines


def export_MISC(rec: Tes3Record) -> list:
    """Miscellaneous clutter: weight, value and a key flag."""
    lines = []
    _emit_common(lines, rec)
    _emit_icon(lines, rec)
    mcdt = get_subrecord(rec, 'MCDT')
    if mcdt and len(mcdt.data) >= 12:
        weight, value, flags = struct.unpack_from('<fii', mcdt.data, 0)
        lines.append(f'Weight={weight}')
        lines.append(f'Value={value}')
        lines.append(f'MiscFlags={flags}')
    return lines


def export_WEAP(rec: Tes3Record) -> list:
    """A weapon: WPDT is 32 bytes of stats."""
    lines = []
    _emit_common(lines, rec)
    _emit_icon(lines, rec)
    _emit_str(lines, 'ENAM', rec, 'ENAM')
    wpdt = get_subrecord(rec, 'WPDT')
    if wpdt and len(wpdt.data) >= 32:
        weight, value, wtype, health, speed, reach, enchant = \
            struct.unpack_from('<fihHffH', wpdt.data, 0)
        lines.append(f'Weight={weight}')
        lines.append(f'Value={value}')
        lines.append(f'WeaponType={wtype}')
        lines.append(f'Health={health}')
        lines.append(f'Speed={speed}')
        lines.append(f'Reach={reach}')
        lines.append(f'EnchantPoints={enchant}')
        _emit_weapon_damage(lines, wpdt.data)
    return lines


def _emit_weapon_damage(lines: list, data: bytes) -> None:
    """Emit the three min/max damage pairs at the tail of WPDT."""
    flags = struct.unpack_from('<i', data, 28)[0]
    lines.append(f'WeaponFlags={flags}')
    for i, name in enumerate(('Chop', 'Slash', 'Thrust')):
        lines.append(f'{name}Min={data[22 + i * 2]}')
        lines.append(f'{name}Max={data[23 + i * 2]}')


def export_ARMO(rec: Tes3Record) -> list:
    """Armour: AODT is 24 bytes of stats."""
    lines = []
    _emit_common(lines, rec)
    _emit_icon(lines, rec)
    _emit_str(lines, 'ENAM', rec, 'ENAM')
    aodt = get_subrecord(rec, 'AODT')
    if aodt and len(aodt.data) >= 24:
        atype, weight, value, health, enchant, armor = struct.unpack_from(
            '<ifiiii', aodt.data, 0)
        lines.append(f'ArmorType={atype}')
        lines.append(f'Weight={weight}')
        lines.append(f'Value={value}')
        lines.append(f'Health={health}')
        lines.append(f'EnchantPoints={enchant}')
        lines.append(f'ArmorRating={armor}')
    return lines


def export_LTEX(rec: Tes3Record) -> list:
    """A landscape texture and the index LAND's VTEX refers to it by.

    The ICON carries the full `textures\\` path: Morrowind stores a bare file
    name and ships it flat, where Oblivion's is relative to a Landscape
    subfolder the import stage prepends.
    See: docs/commentary/tes4_export_morrowind.md#land-terrain
    """
    lines = [f'EditorID={escape_value(rec.record_id)}']
    _emit_icon(lines, rec, 'DATA', prefix='textures' + chr(92))
    intv = get_subrecord(rec, 'INTV')
    if intv and len(intv.data) >= 4:
        lines.append(f"TextureIndex={struct.unpack_from('<I', intv.data, 0)[0]}")
    return lines


def export_BOOK(rec: Tes3Record) -> list:
    """A book or scroll; BKDT's IsScroll decides which."""
    lines = []
    _emit_common(lines, rec)
    _emit_icon(lines, rec)
    _emit_str(lines, 'ENAM', rec, 'ENAM')
    _emit_str(lines, 'BookText', rec, 'TEXT')
    bkdt = get_subrecord(rec, 'BKDT')
    if bkdt and len(bkdt.data) >= 20:
        weight, value, scroll, skill, enchant = struct.unpack_from(
            '<fiiii', bkdt.data, 0)
        lines.append(f'Weight={weight}')
        lines.append(f'Value={value}')
        lines.append(f'IsScroll={scroll}')
        lines.append(f'TeachesSkill={skill}')
        lines.append(f'EnchantPoints={enchant}')
    return lines


def export_ALCH(rec: Tes3Record) -> list:
    """A potion."""
    lines = []
    lines.append(f'EditorID={escape_value(rec.record_id)}')
    _emit_str(lines, 'FULL', rec, 'FNAM')
    _emit_model(lines, rec)
    _emit_str(lines, 'ScriptName', rec, 'SCRI')
    _emit_icon(lines, rec, 'TEXT')
    _emit_weight_value(lines, get_subrecord(rec, 'ALDT'))
    return lines


def export_INGR(rec: Tes3Record) -> list:
    """An alchemy ingredient."""
    lines = []
    _emit_common(lines, rec)
    _emit_icon(lines, rec)
    _emit_weight_value(lines, get_subrecord(rec, 'IRDT'))
    return lines


def _emit_weight_value(lines: list, sub) -> None:
    """Emit the leading float weight and int value shared by several types."""
    if sub and len(sub.data) >= 8:
        weight, value = struct.unpack_from('<fi', sub.data, 0)
        lines.append(f'Weight={weight}')
        lines.append(f'Value={value}')


def export_CLOT(rec: Tes3Record) -> list:
    """Clothing; CTDT packs value and enchant points as u16."""
    lines = []
    _emit_common(lines, rec)
    _emit_icon(lines, rec)
    _emit_str(lines, 'ENAM', rec, 'ENAM')
    ctdt = get_subrecord(rec, 'CTDT')
    if ctdt and len(ctdt.data) >= 12:
        ctype, weight, value, enchant = struct.unpack_from('<ifHH', ctdt.data, 0)
        lines.append(f'ClothingType={ctype}')
        lines.append(f'Weight={weight}')
        lines.append(f'Value={value}')
        lines.append(f'EnchantPoints={enchant}')
    return lines


def export_APPA(rec: Tes3Record) -> list:
    """An alchemy apparatus."""
    lines = []
    _emit_common(lines, rec)
    _emit_icon(lines, rec)
    aadt = get_subrecord(rec, 'AADT')
    if aadt and len(aadt.data) >= 16:
        atype, quality, weight, value = struct.unpack_from('<iffi', aadt.data, 0)
        lines.append(f'ApparatusType={atype}')
        lines.append(f'Quality={quality}')
        lines.append(f'Weight={weight}')
        lines.append(f'Value={value}')
    return lines


def export_REPA(rec: Tes3Record) -> list:
    """A repair hammer: weight, value, uses, then quality."""
    return _tool_lines(rec, 'RIDT', ('Uses', 'Quality'))


def export_PROB(rec: Tes3Record) -> list:
    """A probe: weight, value, quality, then uses."""
    return _tool_lines(rec, 'PBDT', ('Quality', 'Uses'))


def export_LOCK(rec: Tes3Record) -> list:
    """A lockpick: weight, value, quality, then uses."""
    return _tool_lines(rec, 'LKDT', ('Quality', 'Uses'))


def _tool_lines(rec: Tes3Record, sig: str, tail: tuple) -> list:
    """A repair/probe/lockpick tool; `tail` names the last two fields in order.

    REPA stores uses before quality where PROB and LOCK store quality first,
    so the order is passed in rather than assumed.
    """
    lines = []
    _emit_common(lines, rec)
    _emit_icon(lines, rec)
    data = get_subrecord(rec, sig)
    if data and len(data.data) >= 16:
        weight, value = struct.unpack_from('<fi', data.data, 0)
        lines.append(f'Weight={weight}')
        lines.append(f'Value={value}')
        fmt = '<i' if tail[0] == 'Uses' else '<f'
        lines.append(f'{tail[0]}={struct.unpack_from(fmt, data.data, 8)[0]}')
        fmt = '<i' if tail[1] == 'Uses' else '<f'
        lines.append(f'{tail[1]}={struct.unpack_from(fmt, data.data, 12)[0]}')
    return lines


#: TES3 signature -> exporter. Types absent here are not converted this pass.
MORROWIND_EXPORTERS = {
    'STAT': export_STAT,
    'ACTI': export_ACTI,
    'DOOR': export_DOOR,
    'CONT': export_CONT,
    'LIGH': export_LIGH,
    'MISC': export_MISC,
    'WEAP': export_WEAP,
    'ARMO': export_ARMO,
    'LTEX': export_LTEX,
    'BOOK': export_BOOK,
    'ALCH': export_ALCH,
    'INGR': export_INGR,
    'CLOT': export_CLOT,
    'APPA': export_APPA,
    'REPA': export_REPA,
    'PROB': export_PROB,
    'LOCK': export_LOCK,
}
