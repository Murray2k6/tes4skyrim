"""Generate tangent space for geometry that has a texture coordinate basis."""


def add_tangent_space(data):
    from pyffi.formats.nif import NifFormat as N

    visited = set()
    for block in data.get_global_iterator():
        if id(block) in visited or not isinstance(block, N.NiTriBasedGeom):
            continue
        visited.add(id(block))
        geometry = block.data
        if not isinstance(geometry, N.NiTriBasedGeomData):
            raise ValueError(f'{block.name!r} has no triangle geometry data')
        # Hidden markers and untextured effect geometry legitimately have no
        # UVs. A tangent basis is undefined there; no stream should be added.
        if not geometry.uv_sets or not geometry.has_normals or not geometry.num_vertices:
            continue
        if any(isinstance(extra, N.NiBinaryExtraData) and
               extra.name == b'Tangent space (binormal & tangent vectors)'
               for extra in block.get_extra_datas()):
            continue
        block.update_tangent_space()
