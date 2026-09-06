"""Legacy geometry retains authored indices when upgraded to Skyrim."""
import io
import struct
from pathlib import Path

import pytest

from asset_convert.nif_converter import NifFormat as N, convert_nif


@pytest.mark.parametrize('version,size', [(0x04000002, 2), (0x04020200, 2),
                                         (0x14000004, 1), (0x14020007, 1)])
def test_uv_count_width(version, size):
    """The duplicate XML fields must select width per stream version."""
    data = N.Data(version=version)
    count = N.NiTriShapeData()._num_uv_sets_value_
    count.set_value(1)
    stream = io.BytesIO()
    count.write(stream, data)
    assert stream.getvalue() == struct.pack('<H' if size == 2 else '<B', 1)
    assert count.get_size(data) == size
    count.read(io.BytesIO(stream.getvalue()), data)
    assert count.get_value() == 1


@pytest.mark.parametrize('name,counts', [
    ('marker_arrow.nif', [(39, 22)]),
    ('marker_map.nif', [(60, 34), (12, 10)]),
    ('marker_radius.nif', [(42, 80)]),
])
def test_legacy_mesh_keeps_geometry(tmp_path, recwarn, name, counts):
    """Read a shipped NIF 4 source and compare actual output triangle data."""
    source = Path('export/Oblivion.esm/meshes') / name
    if not source.exists():
        pytest.skip('Oblivion source assets are not installed')
    before = N.Data()
    with source.open('rb') as stream:
        before.read(stream)
    original = [b for b in before.get_global_iterator()
                if isinstance(b, N.NiTriShapeData)]
    assert [(b.num_vertices, b.num_triangles) for b in original] == counts
    controllers = [b for b in before.get_global_iterator()
                   if isinstance(b, N.NiKeyframeController)]
    target = tmp_path / 'converted.nif'
    result = convert_nif(source, target)
    assert result['converted'], result
    assert not recwarn.list
    after = N.Data()
    with target.open('rb') as stream:
        after.read(stream)
    geometry = [b for b in after.get_global_iterator()
                if isinstance(b, N.NiTriShapeData)]
    assert len(geometry) == len(original)
    shapes = [b for b in after.get_global_iterator() if isinstance(b, N.NiTriShape)]
    assert all(shape.flags & 1 for shape in shapes)  # markers stay invisible
    for converted, source_geometry in zip(geometry, original):
        assert converted.has_triangles
        assert converted.num_vertices == source_geometry.num_vertices
        assert list(converted.get_triangles()) == list(source_geometry.get_triangles())
    converted_controllers = [b for b in after.get_global_iterator()
                             if isinstance(b, N.NiTransformController)]
    assert len(converted_controllers) == len(controllers)
    for new, old in zip(converted_controllers, controllers):
        assert new.target.name == old.target.name
        assert new.start_time == old.start_time
        assert new.stop_time == old.stop_time
        assert new.interpolator.data.get_hash() == old.data.get_hash()
