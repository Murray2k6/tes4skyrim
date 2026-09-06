"""Package the Skyrim runtime and source record identities it cannot infer."""

from pathlib import Path
import mmap
import re
import shutil

from .cross_ref import master_names
from .constants import papyrus_script_name
from .magic_metadata import effect_traits
from tes5_import.text_reader import parse_export_file, parse_record_block


def _reference_traits(path):
    """Read only refs with authored marker/merchant data, without loading the world."""
    if not path.stat().st_size:
        return
    with path.open('rb') as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
        previous = -1
        for match in re.finditer(rb'(?m)^(?:MapMarker\.Type|XMRC\.MerchantContainer)=', data):
            start = data.rfind(b'---RECORD_BEGIN---', 0, match.start())
            if start == previous:
                continue
            previous = start
            end = data.find(b'---RECORD_END---', match.end())
            yield parse_record_block(data[start:end].decode('utf-8').splitlines())


def deploy_runtime(export_dir, output_dir):
    export, output = Path(export_dir), Path(output_dir)
    masters = master_names(export)
    plugins = masters + [export.name]
    directory = output / 'SKSE/Plugins'
    directory.mkdir(parents=True, exist_ok=True)
    if not masters:
        dll = Path(__file__).resolve().parents[1] / 'runtime/dist/TES4Runtime.dll'
        if not dll.is_file():
            raise FileNotFoundError('Build runtime/TES4Runtime before converting scripts')
        shutil.copy2(dll, directory / dll.name)
    rows = []
    # These signatures change to another base class during import. The
    # authored identity remains relevant to GetObjectType/GetCreatureType.
    fields = {'Services': 'AIDT.Services', 'ActorFlags': 'ACBS.Flags',
              'BarterGold': 'ACBS.BarterGold', 'MinLevel': 'ACBS.CalcMin',
              'MaxLevel': 'ACBS.CalcMax', 'ActorBaseLevel': 'ACBS.Level', 'ClassSpecialization': 'DATA.Specialization',
              'CreatureCombatSkill': 'DATA.CombatSkill', 'CreatureMagicSkill': 'DATA.MagicSkill',
              'CreatureStealthSkill': 'DATA.StealthSkill', 'Flags': 'DATA.Flags',
              'MapMarkerType': 'MapMarker.Type', 'ObjectHealth': 'DATA.Health',
              'AttackDamage': 'DATA.Damage', 'BipedMask': 'BMDT.BipedFlags',
              'DoorFlags': 'FNAM.Flags', 'CreatureSoul': 'DATA.Soul',
              'CreatureModelCount': 'NIFZCount', 'CellMusicType': 'XCMT.MusicType',
              'PackageType': 'PKDT.Type'}
    for sig, type_id in (('CLAS', 5), ('FACT', 6), ('SCPT', 13), ('ENCH', 15), ('SPEL', 16), ('ACTI', 18), ('APPA', 19), ('ARMO', 20), ('BOOK', 21),
                         ('CLOT', 22), ('CONT', 23), ('DOOR', 24), ('INGR', 25),
                         ('LIGH', 26), ('MISC', 27), ('STAT', 28), ('GRAS', 29), ('TREE', 30),
                         ('FLOR', 31), ('FURN', 32), ('WEAP', 33), ('AMMO', 34),
                         ('SLGM', 38), ('KEYM', 39), ('ALCH', 40), ('SGST', 42),
                         ('NPC_', 35), ('CREA', 36), ('CELL', 48), ('WRLD', 53), ('PACK', 61),
                         ('REFR', 49), ('ACHR', 50), ('ACRE', 51), ('QUST', 59)):
        path = export / (sig + '.txt')
        if not path.is_file():
            continue
        records = _reference_traits(path) if sig in ('REFR', 'ACHR', 'ACRE') else parse_export_file(str(path))
        for rec in records:
            fid = int(rec['FormID'], 16)
            index = fid >> 24
            if index >= len(plugins):
                raise ValueError(f'{sig} {fid:08X} has no owning plugin')
            creature_type = int(rec.get('DATA.Type', '-1')) if sig == 'CREA' else -1
            weapon_type = int(rec.get('DATA.Type', '-1')) if sig == 'WEAP' else -1
            traits = {key: int(rec[field]) for key, field in fields.items() if field in rec}
            if 'EffectCount' in rec:
                traits.update(effect_traits(rec))
            traits['IsScripted'] = int(bool(rec.get('SCRI')))
            traits['RecordFlags'] = int(rec.get('RecordFlags', '0'))
            if sig in ('WEAP', 'ARMO', 'CLOT') and 'ANAM' in rec:
                traits['ObjectCharge'] = int(rec['ANAM'])
            if sig == 'NPC_':
                traits['CreatureSoul'] = 5
                if traits.get('Services', 0) & 16384:
                    traits['TrainerSkill'] = 12 + int(rec.get('AIDT.Teaches', '0'))
                    traits['TrainerLevel'] = int(rec.get('AIDT.MaxTraining', '0'))
            if sig == 'CREA':
                traits['AttackDamage'] = int(rec.get('DATA.AttackDamage', '0'))
            if sig == 'APPA':
                traits['ApparatusType'] = int(rec.get('DATA.Type', '0'))
            if sig == 'CLAS':
                traits['Services'] = int(rec.get('DATA.Services', '0'))
                for i in range(7):
                    traits[f'ClassSkill{i}'] = int(rec.get(f'DATA.MajorSkill[{i}]', '-1'))
            extra = ''.join(f'\t{key}={value}' for key, value in sorted(traits.items()))
            if sig == 'SCPT':
                script_name = papyrus_script_name(rec.get('EditorID') or f'SCPT_{fid:08X}')
                extra += f'\t$PapyrusName={script_name.encode("utf-8").hex()}'
            if sig in ('QUST', 'CELL'):
                extra += f'\t$EditorID={rec.get("EditorID", "").encode("utf-8").hex()}'
            if sig == 'FACT':
                relations = int(rec.get('RelationCount', '0'))
                extra += f'\tRelationCount={relations}'
                for i in range(relations):
                    target = int(rec[f'Relation[{i}].Faction'], 16)
                    extra += (f'\t@Relation{i}={plugins[target >> 24]}|{target & 0xFFFFFF:06X}'
                              f'\tReaction{i}={int(rec[f"Relation[{i}].Disposition"])}')
            size = rec.get('Model.MODB', rec.get('Male.WorldModel.MODB'))
            if size is not None:
                extra += f'\t%EditorSize={float(size)}'
            for key, field in (('Quality', 'DATA.Quality'), ('CreatureBaseScale', 'BNAM.BaseScale')):
                if field in rec:
                    extra += f'\t%{key}={float(rec[field])}'
            for i in range(traits.get('CreatureModelCount', 0)):
                extra += f'\t$CreatureModel{i}={rec[f"NIFZ[{i}]"].encode("utf-8").hex()}'
            for key, value in (('ModelPath', rec.get('Model.MODL', rec.get('Male.WorldModel.MODL', ''))),
                               ('IconPath', rec.get('ICON', rec.get('Male.Icon', '')))):
                extra += f'\t${key}={value.encode("utf-8").hex()}'
            if rec.get('XMRC.MerchantContainer'):
                target = int(rec['XMRC.MerchantContainer'], 16)
                extra += f'\t@MerchantContainer={plugins[target >> 24]}|{target & 0xFFFFFF:06X}'
            if rec.get('SCRI'):
                target = int(rec['SCRI'], 16)
                extra += f'\t@Script={plugins[target >> 24]}|{target & 0xFFFFFF:06X}'
            if rec.get('PFIG'):
                target = int(rec['PFIG'], 16)
                extra += f'\t@Ingredient={plugins[target >> 24]}|{target & 0xFFFFFF:06X}'
            rows.append(f'{plugins[index]}\t{fid & 0xFFFFFF:06X}\t{type_id}\t{creature_type}\t{weapon_type}{extra}\n')
    metadata = directory / 'TES4Runtime'
    metadata.mkdir(exist_ok=True)
    (metadata / (export.name + '.tsv')).write_text(''.join(sorted(rows)), encoding='utf-8')
    print(f'    Runtime source identities: {len(rows)}', flush=True)
