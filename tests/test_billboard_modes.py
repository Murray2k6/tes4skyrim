"""Authored billboard orientation modes survive conversion."""
from pathlib import Path

import pytest

from asset_convert.nif_converter import NifFormat as N, convert_nif, _skyrimize_billboard


def test_camera_facing_zero_mode_is_not_changed_to_axis_rotation():
    billboard = N.NiBillboardNode()
    billboard.billboard_mode = 0
    billboard.add_child(N.NiParticleSystem())
    billboard.add_child(N.NiTriShape())
    result = _skyrimize_billboard(billboard, {})
    wrappers = [node for node in result.children if isinstance(node, N.NiBillboardNode)]
    assert len(wrappers) == 1
    assert wrappers[0].billboard_mode == 0


def test_high_bit_billboard_mode_survives(tmp_path, caplog):
    source = Path('export/Nehrim.esm/meshes/oblivion/sigil/sigillighttowercap.nif')
    if not source.exists():
        pytest.skip('Nehrim source meshes are not installed')
    before = N.Data()
    with source.open('rb') as stream:
        before.read(stream)
    assert any(b.billboard_mode == 12 for b in before.get_global_iterator()
               if isinstance(b, N.NiBillboardNode))
    target = tmp_path / source.name
    result = convert_nif(source, target)
    assert result['converted'], result
    after = N.Data()
    with target.open('rb') as stream:
        after.read(stream)
    assert any(b.billboard_mode == 12 for b in after.get_global_iterator()
               if isinstance(b, N.NiBillboardNode))
    assert not any('invalid enum value' in record.message for record in caplog.records)
