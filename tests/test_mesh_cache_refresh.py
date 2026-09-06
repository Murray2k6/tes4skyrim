"""Mesh builds refresh both caches once, preserving untouched model facts."""
import json
import time

import pytest

from asset_convert import collision_extract as collision
from asset_convert.mesh_metadata import mesh_output_state, refresh_mesh_metadata


def _mesh(path, extent):
    if not hasattr(time, 'clock'):
        time.clock = time.perf_counter
    from pyffi.formats.nif import NifFormat as N
    data = N.Data(version=0x14020007, user_version=12, user_version_2=83)
    data.header.endian_type = 1
    root = N.NiNode()
    shape = N.NiTriShape()
    geom = N.NiTriShapeData()
    shape.data = geom
    geom.num_vertices = 3
    geom.has_vertices = True
    geom.vertices.update_size()
    geom.vertices[1].x = extent
    geom.vertices[2].y = extent
    geom.set_triangles([(0, 1, 2)])
    root.add_child(shape)
    body = N.bhkRigidBody()
    box = N.bhkBoxShape()
    box.dimensions.x = box.dimensions.y = box.dimensions.z = extent
    body.shape = box
    body.rotation.w = 1
    body.havok_col_filter.layer = 1
    obj = N.bhkCollisionObject()
    obj.target, obj.body = root, body
    root.collision_object = obj
    data.roots = [root]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as out:
        data.write(out)


def test_one_parse_updates_bounds_and_collision_and_removes_deleted_mesh(tmp_path, monkeypatch):
    meshes, cache = tmp_path / 'meshes', tmp_path / 'cache'
    for name in ('changed', 'unchanged', 'removed'):
        _mesh(meshes / f'{name}.nif', 1)
    refresh_mesh_metadata(meshes, cache, {})
    before = mesh_output_state(meshes)
    old_bounds = json.loads((cache / 'mesh_bounds_cache.json').read_text())
    old_collision = collision._deserialize((cache / 'collision_cache.bin').read_bytes())
    assert old_collision['changed.nif']['w'].size > 0
    _mesh(meshes / 'changed.nif', 4)
    (meshes / 'removed.nif').unlink()
    parsed = []
    reader = collision.read_nif_data
    def read(path):
        parsed.append(path)
        return reader(path)
    monkeypatch.setattr(collision, 'read_nif_data', read)
    refresh_mesh_metadata(meshes, cache, before)
    assert len(parsed) == 1 and parsed[0].endswith('changed.nif')
    bounds = json.loads((cache / 'mesh_bounds_cache.json').read_text())
    soups = collision._deserialize((cache / 'collision_cache.bin').read_bytes())
    assert bounds['changed.nif'][3:5] == [4, 4]
    assert bounds['unchanged.nif'] == old_bounds['unchanged.nif']
    assert 'removed.nif' not in bounds and 'removed.nif' not in soups
    assert soups['changed.nif']['w'].tolist() != old_collision['changed.nif']['w'].tolist()
    assert soups['unchanged.nif']['w'].tolist() == old_collision['unchanged.nif']['w'].tolist()
    monkeypatch.setattr(collision, 'scan_mesh_data', lambda *a, **k: pytest.fail('unchanged build rescanned'))
    refresh_mesh_metadata(meshes, cache, mesh_output_state(meshes))


def test_broken_rewrite_does_not_replace_good_caches(tmp_path):
    meshes, cache = tmp_path / 'meshes', tmp_path / 'cache'
    mesh = meshes / 'model.nif'
    _mesh(mesh, 1)
    refresh_mesh_metadata(meshes, cache, {})
    good = {p.name: p.read_bytes() for p in cache.iterdir()}
    before = mesh_output_state(meshes)
    mesh.write_bytes(b'broken output')
    with pytest.raises(RuntimeError, match='caches were not replaced'):
        refresh_mesh_metadata(meshes, cache, before)
    assert {p.name: p.read_bytes() for p in cache.iterdir()} == good


def test_deleting_last_model_clears_both_caches(tmp_path):
    meshes, cache = tmp_path / 'meshes', tmp_path / 'cache'
    mesh = meshes / 'model.nif'
    _mesh(mesh, 1)
    refresh_mesh_metadata(meshes, cache, {})
    before = mesh_output_state(meshes)
    mesh.unlink()
    refresh_mesh_metadata(meshes, cache, before)
    assert collision._deserialize((cache / 'collision_cache.bin').read_bytes()) == {}
    assert set(json.loads((cache / 'mesh_bounds_cache.json').read_text())) == {'__schema__'}


@pytest.mark.parametrize('stage', ['meshes', 'speedtrees', 'creatures'])
def test_pipeline_publishes_metadata_after_generated_meshes(tmp_path, monkeypatch, stage):
    import convert
    from asset_convert import asset_pipeline, book_inam, creature_pipeline
    monkeypatch.setattr(convert, 'SCRIPT_DIR', tmp_path)
    monkeypatch.setattr(convert, 'get_paths', lambda _: (None, None))
    export = tmp_path / 'export/Test.esm'
    export.mkdir(parents=True)
    output = tmp_path / 'output/Test.esm/meshes'
    def generate(*args, **kwargs):
        _mesh(output / 'generated.nif', 7)
        return {'mesh_conversion': {'errors': 0}, 'spt_conversion': {'ok': 1},
                'projects': [], 'errors': []}
    def book(*args, **kwargs):
        _mesh(output / 'book_inventory.nif', 2)
        return {'ok': 1, 'skip': 0, 'fail': 0}
    if stage == 'meshes':
        monkeypatch.setattr(asset_pipeline, 'convert_meshes', generate)
        monkeypatch.setattr(book_inam, 'generate_book_inams', book)
        assert convert.phase_assets('Test.esm', {}, winding_fix=False)
    elif stage == 'speedtrees':
        monkeypatch.setattr(asset_pipeline, 'convert_speedtrees', generate)
        assert convert.phase_speedtrees('Test.esm', {})
    else:
        monkeypatch.setattr(creature_pipeline, 'convert_creatures', generate)
        assert convert.phase_creatures('Test.esm', '', {})
    bounds = json.loads((export / 'mesh_bounds_cache.json').read_text())
    assert bounds['generated.nif'][3:5] == [7, 7]
    assert collision._deserialize((export / 'collision_cache.bin').read_bytes())
    if stage == 'meshes':
        assert 'book_inventory.nif' in bounds
