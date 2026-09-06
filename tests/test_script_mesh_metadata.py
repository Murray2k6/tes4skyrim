"""Dependent scripts must see master trap facts without leaking prior plugins."""
import json

from asset_convert.collision_extract import BOUNDS_SCHEMA_VERSION
from script_convert.cross_ref import CrossRefGraph
from script_convert.mesh_metadata import load_script_mesh_metadata
from tes5_import.mesh_bounds import load_mesh_bounds, get_mesh_obnd, get_mesh_physics_flags


def write_cache(directory, flags):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'mesh_bounds_cache.json'
    path.write_text(json.dumps({'__schema__': [BOUNDS_SCHEMA_VERSION],
                               'tes4/trap.nif': [0, 0, 0, 1, 2, 3, flags]}))
    return path


def test_master_trap_flags_and_plugin_override(tmp_path, capsys):
    master = tmp_path / 'Base.esm'
    cache = write_cache(master, 2)
    mod = tmp_path / 'Addon.esp'
    mod.mkdir()
    (mod / '_HEADER.txt').write_text('Master[0]=Base.esm\n')
    assert load_script_mesh_metadata(mod) == [str(cache)]
    graph = CrossRefGraph()
    graph.edid_to_formid['release'] = '01000001'
    graph.record_base['01000001'] = '00000002'
    graph.record_model['00000002'] = r'Trap.nif'
    assert graph.needs_havok_release('Release')
    assert 'WARNING' not in capsys.readouterr().out
    write_cache(mod, 0)
    load_script_mesh_metadata(mod)
    assert not graph.needs_havok_release('Release')


def test_missing_and_empty_loads_clear_previous_plugin(tmp_path):
    valid = write_cache(tmp_path / 'First.esm', 2)
    for empty in (tmp_path / 'missing.json', []):
        load_mesh_bounds(valid, quiet=True)
        assert get_mesh_physics_flags('tes4/trap.nif') == 2
        load_mesh_bounds(empty, quiet=True)
        assert get_mesh_obnd('tes4/trap.nif') is None
        assert get_mesh_physics_flags('tes4/trap.nif') == 0


def test_missing_metadata_for_owned_meshes_still_warns(tmp_path, capsys):
    mesh = tmp_path / 'Addon.esp' / 'meshes' / 'trap.nif'
    mesh.parent.mkdir(parents=True)
    mesh.write_bytes(b'')
    load_script_mesh_metadata(mesh.parent.parent)
    assert 'mesh physics metadata is missing or outdated' in capsys.readouterr().out
