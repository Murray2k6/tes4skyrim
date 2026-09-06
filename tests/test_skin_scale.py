"""Scaled skeleton frames must remain rotations plus explicit NIF scale."""
from pathlib import Path

import numpy as np
import pytest

from asset_convert.nif_converter import NifFormat as N, convert_nif
from asset_convert.skin_retarget import _m44_to_np, _skin_transform_to_np


def test_bind_pose_includes_overall_and_per_bone_scale():
    from asset_convert.skin_retarget import _bake_geoms_to_bind_pose
    root, bone, shape = N.NiNode(), N.NiNode(), N.NiTriShape()
    root.add_child(bone)
    root.add_child(shape)
    shape.data = N.NiTriShapeData()
    shape.data.num_vertices = 1
    shape.data.vertices.update_size()
    shape.data.vertices[0].x = 1.0
    skin = N.NiSkinInstance()
    shape.skin_instance = skin
    skin.skeleton_root = root
    skin.num_bones = 1
    skin.bones.update_size()
    skin.bones[0] = bone
    skin.data = N.NiSkinData()
    skin.data.num_bones = 1
    skin.data.bone_list.update_size()
    skin.data.skin_transform.scale = 2.0
    binding = skin.data.bone_list[0]
    binding.skin_transform.scale = 3.0
    binding.num_vertices = 1
    binding.vertex_weights.update_size()
    binding.vertex_weights[0].index = 0
    binding.vertex_weights[0].weight = 1.0
    assert _bake_geoms_to_bind_pose([(shape, False, None)], root) == 1
    np.testing.assert_allclose(shape.data.vertices[0].as_tuple(), (6, 0, 0))
    np.testing.assert_allclose(_skin_transform_to_np(skin.data.skin_transform), np.eye(4))
    np.testing.assert_allclose(_skin_transform_to_np(binding.skin_transform), np.eye(4))


def test_female_hand_scale_preserves_skin_binding(tmp_path, caplog):
    source = Path('export/Oblivion.esm/meshes/armor/townguardcho/f/cuirass.nif')
    if not source.exists():
        pytest.skip('Oblivion source assets are not installed')
    output = tmp_path / 'cuirass.nif'
    result = convert_nif(source, output)
    assert result['converted'], result
    data = N.Data()
    with output.open('rb') as stream:
        data.read(stream)
    checked, scaled = 0, False
    for shape in set(data.get_global_iterator()):
        skin = getattr(shape, 'skin_instance', None)
        if skin is None:
            continue
        S = _skin_transform_to_np(skin.data.skin_transform)
        for index, bone in enumerate(skin.bones):
            assert bone.rotation.is_rotation(), bone.name
            scaled |= abs(bone.scale - 1) > 0.01
            B = _skin_transform_to_np(skin.data.bone_list[index].skin_transform)
            W = _m44_to_np(bone.get_transform(skin.skeleton_root))
            np.testing.assert_allclose(S @ B @ W, np.eye(4), atol=0.001)
            checked += 1
    assert checked and scaled
    assert not any('improper rotation matrix' in record.message for record in caplog.records)


@pytest.mark.parametrize('plugin,relative', [
    ('Morrowind_ob.esm', 'armor/indoril/greaves.nif'),
    ('Morrowind_ob.esm', 'vvardenfellarmormod/high indoril/greaves.nif'),
    ("Maskar's Oblivion Overhaul.esp", 'moo/weapons/nexonsarmory/ancientbonebow.nif'),
])
def test_scaled_frames_preserve_skin_binding(plugin, relative, tmp_path, caplog):
    source = Path('export') / plugin / 'meshes' / relative
    if not source.exists():
        pytest.skip('Source assets are not installed')
    output = tmp_path / 'greaves.nif'
    result = convert_nif(source, output)
    assert result['converted'], result
    data = N.Data()
    with output.open('rb') as stream:
        data.read(stream)
    checked = 0
    for shape in data.get_global_iterator():
        skin = getattr(shape, 'skin_instance', None)
        if skin is None:
            continue
        assert shape.rotation.is_rotation()
        S = _skin_transform_to_np(skin.data.skin_transform)
        for index, bone in enumerate(skin.bones):
            assert bone.rotation.is_rotation()
            B = _skin_transform_to_np(skin.data.bone_list[index].skin_transform)
            W = _m44_to_np(bone.get_transform(skin.skeleton_root))
            np.testing.assert_allclose(S @ B @ W, np.eye(4), atol=0.001)
            checked += 1
    assert checked
    assert not any('improper rotation matrix' in record.message for record in caplog.records)
