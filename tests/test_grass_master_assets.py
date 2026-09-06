"""Inherited grass resolves through master outputs without hiding failed overrides."""
from asset_convert.grass_profile import run


def test_inherited_grass_uses_master_profile(tmp_path):
    export = tmp_path / 'export' / 'addon.esp'
    export.mkdir(parents=True)
    (export / 'GRAS.txt').write_text('Model.MODL=plants\\grass.nif\n')
    master_meshes = tmp_path / 'output' / 'base.esm' / 'meshes'
    profile = master_meshes / 'landscape' / 'grass' / 'tes4_grass.nif'
    profile.parent.mkdir(parents=True)
    profile.write_bytes(b'master-owned grass')
    addon_meshes = tmp_path / 'output' / 'addon.esp' / 'meshes'
    assert run(export, addon_meshes, master_mesh_roots=[master_meshes]) == (0, 0, 0)
    profile.unlink()
    assert run(export, addon_meshes, master_mesh_roots=[master_meshes]) == (0, 0, 1)


def test_failed_local_grass_override_is_not_masked(tmp_path):
    export = tmp_path / 'export' / 'addon.esp'
    source = export / 'meshes' / 'plants' / 'grass.nif'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'local override awaiting conversion')
    (export / 'GRAS.txt').write_text('Model.MODL=plants\\grass.nif\n')
    master_meshes = tmp_path / 'output' / 'base.esm' / 'meshes'
    profile = master_meshes / 'landscape' / 'grass' / 'tes4_grass.nif'
    profile.parent.mkdir(parents=True)
    profile.write_bytes(b'master-owned grass')
    assert run(export, tmp_path / 'output' / 'addon.esp' / 'meshes',
               master_mesh_roots=[master_meshes]) == (0, 0, 1)
