"""Static affine repair preserves world-space geometry and animated frames."""
from pathlib import Path

import numpy as np
import pytest

from asset_convert.nif_converter import NifFormat as N, convert_nif
from asset_convert.nif_affine import repair_static_affine


def world_vertices(data):
    result = []

    def visit(node, parent):
        matrix = np.eye(4)
        matrix[:3, :3] = np.array(node.rotation.as_list()) * node.scale
        matrix[3, :3] = node.translation.as_tuple()
        matrix = matrix @ parent
        if isinstance(node, N.NiTriBasedGeom) and node.data is not None:
            vertices = np.array([v.as_tuple() for v in node.data.vertices])
            result.append((node.name, vertices @ matrix[:3, :3] + matrix[3, :3]))
        for child in getattr(node, 'children', ()):
            if child is not None:
                visit(child, matrix)

    for root in data.roots:
        if isinstance(root, N.NiAVObject):
            visit(root, np.eye(4))
    return result


@pytest.mark.parametrize('relative', ['seelenbewahrer/klinge2.nif', 'nehrim/natur/stamm01.nif'])
def test_authored_affine_world_geometry(relative, tmp_path, caplog):
    source = Path('export/Nehrim.esm/meshes') / relative
    if not source.exists():
        pytest.skip('Nehrim source meshes are not installed')
    data = N.Data()
    with source.open('rb') as stream:
        data.read(stream)
    before = world_vertices(data)
    assert repair_static_affine(data, N) > 0
    after = world_vertices(data)
    assert [name for name, _ in before] == [name for name, _ in after]
    for (_, original), (_, repaired) in zip(before, after):
        np.testing.assert_allclose(repaired, original, atol=1e-9)
    result = convert_nif(source, tmp_path / source.name)
    assert result['converted'], result
    assert not any('improper rotation' in record.message for record in caplog.records)


def test_animated_branch_keeps_its_frame():
    data = N.Data(version=0x14000004, user_version=11, user_version_2=11)
    root, child = N.NiNode(), N.NiNode()
    root.add_child(child)
    root.rotation.m_11 = 2.0
    data.roots = [root]
    root.controller = N.NiTransformController()
    root.controller.target = child
    before = root.rotation.get_hash()
    assert repair_static_affine(data, N) == 0
    assert root.rotation.get_hash() == before
