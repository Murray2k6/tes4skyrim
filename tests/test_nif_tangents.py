"""Mesh particle templates need the same tangent generation as scene children."""
import math

import pytest

from asset_convert.nif_converter import NifFormat as N
from asset_convert.nif_tangents import add_tangent_space


def test_tangents_reach_particle_owned_template():
    data = N.Data(version=0x14020007, user_version=12, user_version_2=83)
    system = N.NiMeshParticleSystem()
    modifier = N.NiPSysMeshUpdateModifier()
    system.num_modifiers = 1
    system.modifiers.update_size()
    system.modifiers[0] = modifier
    template = N.NiTriShape()
    template.data = geometry = N.NiTriShapeData()
    geometry.num_vertices = 3
    geometry.has_vertices = geometry.has_normals = True
    geometry.num_uv_sets = 1
    geometry.vertices.update_size()
    geometry.normals.update_size()
    geometry.uv_sets.update_size()
    for i, (x, y) in enumerate(((0, 0), (1, 0), (0, 1))):
        geometry.vertices[i].x, geometry.vertices[i].y = x, y
        geometry.normals[i].z = 1
        geometry.uv_sets[0][i].u, geometry.uv_sets[0][i].v = x, y
    geometry.set_triangles([(0, 1, 2)])
    modifier.num_meshes = 1
    modifier.meshes.update_size()
    modifier.meshes[0] = template
    data.roots = [system]
    add_tangent_space(data)
    assert geometry.extra_vectors_flags & 16
    assert len(geometry.tangents) == len(geometry.bitangents) == 3
    for tangent in (*geometry.tangents, *geometry.bitangents):
        assert tangent.z == pytest.approx(0)
        assert math.hypot(tangent.x, tangent.y) == pytest.approx(1)
