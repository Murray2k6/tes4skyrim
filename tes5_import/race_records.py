"""Keep plugin-defined races addressable, using the importer humanoid scaffold."""

from functools import lru_cache
from pathlib import Path
import struct

from .skyrim_overrides import RACE_MAP, TES4_RACE_FID_TO_EDID, VOICE_TYPE_MAP
from .text_reader import get_formid, get_int, get_float
from .writer import pack_record, pack_subrecord, pack_string_subrecord

_targets = {}
_voice_routes = {}


def race_target(fid):
    """(source EditorID, output race) for a remapped source identity."""
    return _targets.get(fid)


@lru_cache(maxsize=1)
def _humanoid_template():
    from asset_convert.skyrim_assets import find_skyrim_data
    from tools.esm.tes5_esm_reader import read_tes5_file
    directory = find_skyrim_data()
    if not directory:
        raise FileNotFoundError('Skyrim.esm is required to build custom races')
    _, records, _ = read_tes5_file(str(Path(directory) / 'Skyrim.esm'),
                                  parse_types={'RACE'})
    for rec in records:
        if rec.type == 'RACE' and rec.form_id == RACE_MAP['Imperial']:
            return tuple((s.type, s.data) for s in rec.subrecords)
    raise ValueError('Skyrim.esm contains no ImperialRace template')


def build_custom_races(by_type, writer, master_export=None):
    """Retain custom identities/voices instead of pointing properties at skipped records.

    Unknown humanoid races previously used the Imperial scaffold on their NPCs.
    Their own RACE now carries that scaffold and the authored race traits, with
    Imperial armor/morph compatibility so the existing converted outfits fit.
    """
    _targets.clear()
    _voice_routes.clear()
    records = [r for r in (master_export or {}).values() if r.get('Signature') == 'RACE']
    records += by_type.get('RACE', [])
    for rec in records:
        fid = get_formid(rec, 'FormID')
        edid = rec.get('EditorID', '')
        mapped = RACE_MAP.get(edid)
        # Retain the existing mapping for vanilla's unnamed vampire race.
        if not mapped and not rec.get('FULL'):
            mapped = RACE_MAP.get(TES4_RACE_FID_TO_EDID.get(fid & 0xFFFFFF, ''))
        _targets[fid] = edid, mapped or fid

    for rec in records:
        edid, target = _targets[get_formid(rec, 'FormID')]
        routes = []
        for sex in ('Male', 'Female'):
            authored = get_formid(rec, f'VNAM.{sex}Voice')
            voice_edid, voice_race = _targets.get(authored, (edid, target))
            routes.append((voice_race, VOICE_TYPE_MAP.get((voice_edid, sex), 0)))
        # Several TES4 races share one vanilla scaffold. Preserve that
        # scaffold's own route; distinct custom races have distinct identities.
        if target not in _voice_routes or edid in ('Argonian', 'Breton', 'DarkElf',
                'HighElf', 'Imperial', 'Khajiit', 'Nord', 'Orc', 'Redguard', 'WoodElf', 'Dremora'):
            _voice_routes[target] = routes

    count = 0
    for rec in by_type.get('RACE', []):
        fid = get_formid(rec, 'FormID')
        edid, target = _targets[fid]
        if target != fid or fid >> 24 != writer.own_index:
            continue
        parts = []
        for sig, payload in _humanoid_template():
            if sig in ('EDID', 'FULL', 'DESC', 'SPCT', 'SPLO', 'RNAM', 'NAM8'):
                continue
            if sig == 'DATA':
                data = bytearray(payload)
                from .constants import TES4_SKILL_TO_TES5, TES5_SKILL_ORDER
                for i in range(7):
                    skill = TES4_SKILL_TO_TES5.get(get_int(rec, f'DATA.SkillBoost[{i}].Skill', 255))
                    av = TES5_SKILL_ORDER.index(skill) + 6 if skill in TES5_SKILL_ORDER else -1
                    boost = get_int(rec, f'DATA.SkillBoost[{i}].Bonus') if av >= 0 else 0
                    struct.pack_into('<bb', data, i * 2, av, boost)
                struct.pack_into('<4f', data, 16, *(get_float(rec, 'DATA.' + key, 1.0)
                    for key in ('MaleHeight', 'FemaleHeight', 'MaleWeight', 'FemaleWeight')))
                flags = struct.unpack_from('<I', data, 32)[0]
                struct.pack_into('<I', data, 32, (flags & ~1) | (get_int(rec, 'DATA.Flags') & 1))
                payload = bytes(data)
            elif sig == 'VTCK':
                voices = struct.unpack('<II', payload)
                payload = struct.pack('<II', *(route[1] or fallback
                    for route, fallback in zip(_voice_routes[target], voices)))
            parts.append(pack_subrecord(sig, payload))
        body = pack_string_subrecord('EDID', edid)
        body += pack_string_subrecord('FULL', rec.get('FULL', ''))
        body += pack_string_subrecord('DESC', rec.get('DESC', ''))
        spells = [get_formid(rec, key) for key in sorted(rec) if key.startswith('Spell[')]
        body += pack_subrecord('SPCT', struct.pack('<I', len(spells)))
        body += b''.join(pack_subrecord('SPLO', struct.pack('<I', spell)) for spell in spells)
        body += b''.join(parts)
        for sig in ('NAM8', 'RNAM'):
            body += pack_subrecord(sig, struct.pack('<I', RACE_MAP['Imperial']))
        writer.add_record('RACE', pack_record('RACE', fid, get_int(rec, 'RecordFlags'), body))
        count += 1
    if count:
        print(f'  Custom humanoid races: {count}', flush=True)


def write_voice_routes(output_path, masters):
    output = Path(output_path)
    plugins = list(masters) + [output.name]
    rows = []
    for fid, routes in sorted(_voice_routes.items()):
        fields = []
        for sex, (race, voice) in zip(('Male', 'Female'), routes):
            for name, value in ((sex + 'VoiceRace', race), (sex + 'VoiceType', voice)):
                if value:
                    fields.append(f'@{name}={plugins[value >> 24]}|{value & 0xFFFFFF:06X}')
        rows.append(f'{plugins[fid >> 24]}\t{fid & 0xFFFFFF:06X}\t9\t-1\t-1\t' + '\t'.join(fields) + '\n')
    directory = output.parent / 'SKSE/Plugins/TES4Runtime/races'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (output.name + '.tsv')).write_text(''.join(rows), encoding='utf-8')
