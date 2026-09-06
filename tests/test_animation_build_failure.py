"""A mesh with failed behavior generation is not a successful conversion."""
from pathlib import Path

import pytest

from asset_convert.nif_converter import convert_nif


def test_behavior_compile_failure_is_a_mesh_error(tmp_path, monkeypatch):
    from asset_convert import hkx_animobject

    source = Path('export/Oblivion.esm/meshes/dungeons/chargen/prisonsecretwall01.nif')
    if not source.exists():
        pytest.skip('Oblivion source assets are not installed')

    def failed_compile(*args, **kwargs):
        raise RuntimeError('behavior compiler unavailable')

    monkeypatch.setattr(hkx_animobject, 'generate_animobject_project', failed_compile)
    output = tmp_path / 'meshes' / 'tes4' / 'wall.nif'
    result = convert_nif(source, output)
    assert not result['converted'], result
    assert result['error'] == 'ANIMATION'
    assert result['error_detail'] == 'RuntimeError: behavior compiler unavailable'
    assert not output.exists()
