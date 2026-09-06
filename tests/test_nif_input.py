"""Malformed source trailers are repaired without losing declared NIF data."""
import io
from pathlib import Path
import logging

import pytest

from asset_convert.nif_converter import NifFormat as N, convert_nif
from asset_convert.nif_input import read_source_nif


@pytest.mark.parametrize('name,vertices,indices,trailer', [
    ('60.-64.-64.32.nif', 3026, 10309, 234848),
    ('60.-32.-32.32.nif', 11744, 40186, 22698),
])
def test_terrain_trailer_repair(tmp_path, caplog, name, vertices, indices, trailer):
    source = Path('export/Oblivion.esm/meshes/landscape/lod') / name
    if not source.exists():
        pytest.skip('Oblivion source meshes are not installed')
    caplog.set_level(logging.WARNING)
    before, removed = read_source_nif(source, N)
    assert removed == trailer
    geometry = before.roots[0].data
    assert geometry.num_vertices == vertices
    assert sum(geometry.strip_lengths) == indices
    expected = list(geometry.get_triangles())
    target = tmp_path / name
    result = convert_nif(source, target)
    assert result['converted'], result
    assert result['repaired_trailing_bytes'] == trailer
    after, remaining = read_source_nif(target, N)
    assert remaining == 0
    shapes = [b for b in after.get_global_iterator() if isinstance(b, N.NiTriShapeData)]
    assert len(shapes) == 1
    assert shapes[0].num_vertices == vertices
    assert list(shapes[0].get_triangles()) == expected
    assert not caplog.records


def test_truncated_footer_is_not_repaired(tmp_path):
    data = N.Data(version=0x14000004, user_version=11, user_version_2=11)
    data.roots = [N.NiNode()]
    stream = io.BytesIO()
    data.write(stream)
    path = tmp_path / 'truncated.nif'
    path.write_bytes(stream.getvalue()[:-1])
    with pytest.raises(Exception):
        read_source_nif(path, N)
