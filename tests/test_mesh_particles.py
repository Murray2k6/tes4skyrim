"""Mesh-particle templates must survive conversion outside scene children."""
import io
import struct
from pathlib import Path

import pytest

from asset_convert.nif_converter import NifFormat as N, convert_nif


def test_mesh_particle_data_preserves_derived_payload():
    data = N.Data(version=0x14020007, user_version=12, user_version_2=83)
    mesh = N.NiMeshPSysData()
    mesh.bs_max_vertices = 125
    mesh.unknown_int_2 = 13
    mesh.unknown_byte_3 = 1
    mesh.num_unknown_ints_1 = 2
    mesh.unknown_ints_1.update_size()
    mesh.unknown_ints_1[0] = 17
    mesh.unknown_ints_1[1] = 23
    data._block_index_dct = {}
    stream = io.BytesIO()
    mesh.write(stream, data)
    payload = stream.getvalue()
    assert len(payload) == mesh.get_size(data)
    assert payload[70:] == struct.pack('<IBIIIi', 13, 1, 2, 17, 23, -1)
    decoded = N.NiMeshPSysData()
    data._link_stack = []
    decoded.read(io.BytesIO(payload), data)
    assert decoded.bs_max_vertices == 125
    assert decoded.unknown_int_2 == 13
    assert decoded.unknown_byte_3 == 1
    assert list(decoded.unknown_ints_1) == [17, 23]
    assert data._link_stack[-1] == -1


def test_mesh_particle_morph_template_roundtrip(tmp_path):
    source = Path('export/MidasSpells.esp/meshes/magiceffects/midastyraeleffect.nif')
    if not source.exists():
        pytest.skip('Midas source assets are not installed')
    target = tmp_path / 'converted.nif'
    result = convert_nif(source, target)
    assert result['converted'], result
    with target.open('rb') as stream:
        data = N.Data()
        data.read(stream)
    blocks = list(data.get_global_iterator())
    assert not any(isinstance(b, (N.NiGeomMorpherController, N.NiTriStrips))
                   for b in blocks)
    systems = [b for b in blocks if isinstance(b, N.NiMeshParticleSystem)]
    assert len(systems) == 2
    for system in systems:
        assert isinstance(system.data, N.NiMeshPSysData)
        templates = [b for m in system.modifiers
                     if isinstance(m, N.NiPSysMeshUpdateModifier) for b in m.meshes]
        assert templates
        for template in templates:
            shapes = [b for b in template.tree() if isinstance(b, N.NiTriShape)]
            assert len(shapes) > 1
            for shape in shapes:
                controller = shape.controller
                assert isinstance(controller, N.NiVisController)
                assert isinstance(controller.interpolator, N.NiBoolInterpolator)
                assert controller.stop_time == 6.0
                assert controller.flags & 6 == 0  # authored loop mode
                assert controller.interpolator.data.data.interpolation == 5
                shader = shape.bs_properties[0]
                path = shader.source_texture.lower().replace(b'\\', b'/')
                assert path.startswith((b'tes4/', b'textures/tes4/'))
