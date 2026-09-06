"""Master geometry survives dependent imports and worker initialization."""
import json
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

from asset_convert import collision_extract as collision
from asset_convert.mesh_metadata import mesh_cache_paths
from tes5_import.mesh_bounds import load_mesh_bounds, get_mesh_obnd


def _cache(root, entries, bounds):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'collision_cache.bin').write_bytes(collision._serialize(entries))
    (root / 'mesh_bounds_cache.json').write_text(json.dumps(bounds))


def _triangle(height):
    return {'w': [0., 0., height, 1., 0., height, 0., 1., height], 'b': []}


def _worker_geometry(keys):
    return {key: (collision.get_collision(key)['w'].tolist()
                  if collision.get_collision(key) is not None else None)
            for key in keys}


def test_transitive_master_bounds_and_collisionless_override(tmp_path):
    base, mid, mod = (tmp_path / n for n in ('Base.esm', 'Middle.esm', 'Mod.esp'))
    _cache(base, {'tes4/floor.nif': _triangle(0),
                  'tes4/marker.nif': _triangle(3)},
           {'tes4/floor.nif': [0, 0, 0, 1, 1, 0],
            'tes4/marker.nif': [0, 0, 3, 1, 1, 3]})
    _cache(mid, {}, {'tes4/marker.nif': [0, 0, 4, 1, 1, 4]})
    (mid / '_HEADER.txt').write_text('Master[0]=Base.esm\n')
    mod.mkdir()
    (mod / '_HEADER.txt').write_text('Master[0]=Middle.esm\n')
    bounds = mesh_cache_paths(mod, 'mesh_bounds_cache.json')
    soups = mesh_cache_paths(mod, 'collision_cache.bin')
    assert len(bounds) == len(soups) == 2
    load_mesh_bounds(bounds, quiet=True)
    assert get_mesh_obnd('tes4/floor.nif') == (0, 0, 0, 1, 1, 0)
    assert get_mesh_obnd('tes4/marker.nif') == (0, 0, 4, 1, 1, 4)
    assert collision.load_collision(soups, quiet=True) == 1
    assert collision.get_collision('tes4/marker.nif') is None
    assert collision.get_collision('tes4/floor.nif')['w'][2] == 0


def test_spawned_navmesh_worker_uses_plugin_collision_override(tmp_path):
    from tes5_import.navm_worker import init_worker
    base, mod = tmp_path / 'Base.esm', tmp_path / 'Mod.esp'
    _cache(base, {'tes4/floor.nif': _triangle(0)}, {})
    _cache(mod, {'tes4/floor.nif': _triangle(9)}, {})
    (mod / '_HEADER.txt').write_text('Master[0]=Base.esm\n')
    soups = mesh_cache_paths(mod, 'collision_cache.bin')
    with ProcessPoolExecutor(max_workers=1, mp_context=get_context('spawn'),
                             initializer=init_worker,
                             initargs=({}, set(), str(mod / 'collision_cache.bin'),
                                       0, None, {}, False, None, soups)) as pool:
        result = pool.submit(_worker_geometry, ['tes4/floor.nif']).result(timeout=30)
    assert result['tes4/floor.nif'][2] == 9


def test_missing_collision_clears_previous_plugin_and_digest(tmp_path, capsys):
    base = tmp_path / 'Base.esm'
    _cache(base, {'tes4/floor.nif': _triangle(0)}, {})
    collision.load_collision(base / 'collision_cache.bin', quiet=True)
    assert collision.collision_digest('tes4/floor.nif')
    collision.load_collision(tmp_path / 'missing.bin')
    assert 'could not load' in capsys.readouterr().out
    assert collision.get_collision('tes4/floor.nif') is None
    assert collision.collision_digest('tes4/floor.nif') == ''


def _model(path, sound=None, furniture=False):
    if not hasattr(time, 'clock'):
        time.clock = time.perf_counter
    from pyffi.formats.nif import NifFormat as N
    data = N.Data(version=0x14000004, user_version=11, user_version_2=11)
    data.header.endian_type = 1
    root = N.NiNode()
    data.roots = [root]
    if sound:
        manager = N.NiControllerManager()
        root.controller = manager
        manager.num_controller_sequences = 1
        manager.controller_sequences.update_size()
        seq = N.NiControllerSequence()
        manager.controller_sequences[0] = seq
        seq.name = b'Open'
        keys = N.NiTextKeyExtraData()
        seq.text_keys = keys
        keys.num_text_keys = 1
        keys.text_keys.update_size()
        keys.text_keys[0].value = ('sound: ' + sound).encode()
    if furniture:
        marker = N.BSFurnitureMarker()
        marker.num_positions = 1
        marker.positions.update_size()
        marker.positions[0].position_ref_1 = 11
        marker.positions[0].position_ref_2 = 11
        marker.positions[0].offset.z = -20
        root.add_extra_data(marker)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as out:
        data.write(out)


def test_master_door_sound_and_silent_child_override(tmp_path):
    from tes5_import.record_types import items
    from tes5_import.text_reader import set_formid_index_offset
    set_formid_index_offset(0)
    base, mod = tmp_path / 'base', tmp_path / 'mod'
    _model(base / 'door.nif', sound='AuthoredOpen')
    records = {'DOOR': [{'FormID': '01000001', 'Model.MODL': 'door.nif'}],
               'SOUN': [{'FormID': '00012345', 'EditorID': 'AuthoredOpen'}]}
    assert items.load_door_model_sounds([base, mod], records) == 1
    assert items._door_model_sounds(records['DOOR'][0]) == {'open': 0x12345}
    _model(mod / 'door.nif')
    assert items.load_door_model_sounds([base, mod], records) == 0
    assert items._door_model_sounds(records['DOOR'][0]) == {}


def test_master_furniture_origin_and_decorative_child_override(tmp_path):
    from tes5_import.record_types import items
    base, mod = tmp_path / 'base', tmp_path / 'mod'
    _model(base / 'chair.nif', furniture=True)
    records = {'FURN': [{'FormID': '00000001', 'Model.MODL': 'chair.nif'}],
               'STAT': [{'FormID': '01000002', 'Model.MODL': 'chair.nif'}]}
    assert items.load_furniture_models([base, mod], records) == 1
    assert items.get_base_origin_shift('01000002') == 20
    assert len(items._FURN_SEATS['chair.nif']) == 1
    _model(mod / 'chair.nif')
    assert items.load_furniture_models([base, mod], records) == 1
    assert items.get_base_origin_shift('01000002') == 0
    assert items._FURN_SEATS['chair.nif'] == []
