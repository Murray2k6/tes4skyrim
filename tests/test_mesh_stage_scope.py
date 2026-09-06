"""A targeted mesh build must not rebuild unrelated art or hide failures."""
from pathlib import Path

import pytest

import convert
from asset_convert import asset_pipeline, book_inam, grass_profile, hair_pipeline
from asset_convert.game_paths import matches_path_scope, scoped_files


@pytest.mark.parametrize('references,copied', [([], 0), (['textures/tes4/stone.dds'], 2)])
def test_targeted_pipeline_limits_auxiliary_work(tmp_path, monkeypatch, references, copied):
    """Exercise real auxiliary dispatch and texture processing on a tiny tree."""
    export = tmp_path / 'export'
    source = export / 'Test.esm'
    textures = source / 'textures'
    textures.mkdir(parents=True)
    (source / 'meshes').mkdir()
    (textures / 'stone.dds').write_bytes(b'fake diffuse')
    (textures / 'stone_g.dds').write_bytes(b'fake glow')
    (textures / 'unrelated.dds').write_bytes(b'leave this alone')
    monkeypatch.setattr(asset_pipeline.wearable_plan, 'build_plan', lambda _: {})
    monkeypatch.setattr(asset_pipeline.nif_converter, 'batch_convert',
                        lambda *a, **k: {'converted': 1, 'errors': 0,
                                         'textures_used': set(references)})
    monkeypatch.setattr(hair_pipeline, 'build_hair_plan',
                        lambda _: {1: {'model': 'characters/hair/other.nif'}})
    monkeypatch.setattr(grass_profile, 'load_grass_model_paths',
                        lambda _: {'plants/other.nif'})
    stats = asset_pipeline.convert_meshes('Test.esm', export, tmp_path / 'output',
                                          mesh_subdirs=['marker.nif'])
    assert stats['hair']['variants'] == 0
    assert stats['hair']['missing'] == 0
    assert stats['grass_profile'] == {'processed': 0, 'modified': 0, 'missing': 0}
    assert stats['textures_copied'] == copied
    target = tmp_path / 'output/Test.esm/textures/tes4'
    assert not (target / 'unrelated.dds').exists()
    assert (target / 'stone.dds').exists() == bool(references)
    assert (target / 'stone_g.dds').exists() == bool(references)


def test_texture_resume_copies_full_tree_without_entering_mesh_conversion(tmp_path, monkeypatch):
    source, output = tmp_path / 'source', tmp_path / 'output'
    (source / 'textures/subdir').mkdir(parents=True)
    (source / 'textures/subdir/stone.dds').write_bytes(b'diffuse payload')
    (output / 'meshes').mkdir(parents=True)
    mesh = output / 'meshes/already_built.nif'
    mesh.write_bytes(b'completed mesh')

    def unexpected(*args, **kwargs):
        pytest.fail('Texture resume started mesh conversion')

    monkeypatch.setattr(asset_pipeline.nif_converter, 'batch_convert', unexpected)
    stats = asset_pipeline.copy_textures(source, output)
    assert stats['textures_copied'] == 1
    assert (output / 'textures/tes4/subdir/stone.dds').read_bytes() == b'diffuse payload'
    assert mesh.read_bytes() == b'completed mesh'


def test_book_scope_preserves_collision_names(tmp_path, monkeypatch):
    """Filtering cannot change a book's name when source leaf names collide."""
    models = [r'a\book.nif', r'b\book.nif']
    expected = book_inam.inv_basename_map(models)
    seen = {}
    monkeypatch.setattr(book_inam, 'distinct_book_models', lambda _: models)
    monkeypatch.setattr(book_inam, '_split_master_owned', lambda m, *a: (m, 0))
    monkeypatch.setattr(book_inam, 'load_templates', lambda *a: {'book': b'', 'note': b''})
    monkeypatch.setattr(book_inam, '_worker_init', lambda *a: seen.update(names=a[-1]))
    monkeypatch.setattr(book_inam, '_convert_one', lambda m: (m, 'ok', ''))
    stats = book_inam.generate_book_inams('Test.esm', tmp_path, tmp_path,
                                           workers=1, mesh_subdirs=['a'])
    assert stats == {'ok': 1, 'skip': 0, 'fail': 0}
    assert seen['names'] == expected


def test_scope_component_boundaries_and_empty_selection(tmp_path):
    """Explicit paths cannot accidentally widen to similar folder names."""
    assert matches_path_scope(r'A\b.nif', ['a/b.nif'])
    assert not matches_path_scope('ab/b.nif', ['a'])
    assert not matches_path_scope('a/b.nif', [])
    root = tmp_path / 'textures'
    root.mkdir()
    selected = root / 'picked_n.DDS'
    selected.touch()
    (root / 'other_n.dds').touch()
    outside = tmp_path / 'outside_n.dds'
    outside.touch()
    assert scoped_files(root, '*_n.dds', [selected, outside]) == [selected]


@pytest.mark.parametrize('mesh_errors,book_errors', [(1, 0), (0, 1), (0, 0)])
def test_mesh_phase_reports_failures(monkeypatch, mesh_errors, book_errors):
    """A failed mesh or generated inventory model must fail the real phase."""
    monkeypatch.setattr(asset_pipeline, 'convert_meshes',
                        lambda **k: {'mesh_conversion': {'errors': mesh_errors}})
    monkeypatch.setattr(book_inam, 'generate_book_inams',
                        lambda **k: {'ok': 0, 'skip': 0, 'fail': book_errors})
    monkeypatch.setattr(convert, 'get_paths', lambda _: (None, None))
    assert convert.phase_assets('Test.esm', {}, mesh_subdirs=['marker.nif'],
                                winding_fix=False) == (not (mesh_errors or book_errors))
