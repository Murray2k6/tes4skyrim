"""The high geometry-flags byte must preserve material and tangent bits."""
import io
from pathlib import Path

import pytest

from asset_convert.nif_converter import NifFormat as N, convert_nif


def test_geometry_flags_copy_and_serialization(caplog):
    data = N.Data(version=0x14000005, user_version=11, user_version_2=11)
    geometry = N.NiTriShapeData()
    # Material bits in the high byte coexist with the authored tangent flag.
    geometry.extra_vectors_flags = 0x11
    copied = N.NiTriShapeData()
    copied.deepcopy(geometry)
    assert copied.extra_vectors_flags == 0x11
    stream = io.BytesIO()
    data._block_index_dct = {}
    copied.write(stream, data)
    stream.seek(0)
    decoded = N.NiTriShapeData()
    data._link_stack = []
    decoded.read(stream, data)
    assert decoded.extra_vectors_flags == 0x11
    assert not caplog.records


def test_mesh_with_material_bits_converts_without_enum_rejection(tmp_path, caplog):
    source = Path('export/MidasSpells.esp/meshes/magiceffects/midasstarbase.nif')
    if not source.exists():
        pytest.skip('Midas source assets are not installed')
    result = convert_nif(source, tmp_path / source.name)
    assert result['converted'], result
    assert not any('invalid enum' in record.message for record in caplog.records)
