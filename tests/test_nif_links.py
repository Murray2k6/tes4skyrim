"""Scene replacement must preserve references outside child ownership."""
from pathlib import Path

import pytest

from asset_convert.nif_converter import NifFormat as N, convert_nif
from asset_convert.nif_links import retarget_links


def test_retarget_shared_and_weak_links_without_importing_external_nodes():
    data = N.Data(version=0x14020007, user_version=12, user_version_2=83)
    root, old, new, external = N.NiNode(), N.NiNode(), N.NiNode(), N.NiNode()
    root.add_child(old)
    root.controller = N.NiMultiTargetTransformController()
    root.controller.target = old
    root.controller.num_extra_targets = 2
    root.controller.extra_targets.update_size()
    root.controller.extra_targets[0] = old
    root.controller.extra_targets[1] = external
    retarget_links(root, {id(old): new}, data)
    assert root.children[0] is new
    assert root.controller.target is new
    assert root.controller.extra_targets[0] is new
    assert root.controller.extra_targets[1] is external
    assert external not in list(root.tree())


def test_retarget_successive_node_replacements():
    data = N.Data(version=0x14020007, user_version=12, user_version_2=83)
    root, billboard, plain, fade = N.NiNode(), N.NiBillboardNode(), N.NiNode(), N.BSFadeNode()
    root.add_child(fade)
    root.controller = N.NiTransformController()
    root.controller.target = billboard
    retarget_links(root, {id(billboard): plain, id(plain): fade}, data)
    assert root.controller.target is fade


def test_palette_targets_in_later_roots_survive_conversion(tmp_path, caplog):
    source = Path('export/Nehrim.esm/meshes/nehrim/refractioneffect.nif')
    if not source.exists():
        pytest.skip('Nehrim source assets are not installed')
    before = N.Data()
    with source.open('rb') as stream:
        before.read(stream)
    original = [entry.av_object.name if entry.av_object is not None else None
                for block in before.get_global_iterator()
                if isinstance(block, N.NiDefaultAVObjectPalette)
                for entry in block.objs]
    target = tmp_path / source.name
    result = convert_nif(source, target)
    assert result['converted'], result
    after = N.Data()
    with target.open('rb') as stream:
        after.read(stream)
    blocks = set(after.get_global_iterator())
    targets = [entry.av_object for block in after.get_global_iterator()
               if isinstance(block, N.NiDefaultAVObjectPalette) for entry in block.objs]
    assert all(target in blocks for target in targets if target is not None)
    assert [target.name if target is not None else None for target in targets] == original
    assert not any('missing from the nif tree' in record.message for record in caplog.records)


@pytest.mark.parametrize('name', ['midasfirestreak', 'midasdestructionend'])
def test_particle_animation_targets_survive_write(name, tmp_path, caplog):
    source = Path('export/MidasSpells.esp/meshes/magiceffects') / (name + '.nif')
    if not source.exists():
        pytest.skip('Midas source assets are not installed')
    output = tmp_path / source.name
    result = convert_nif(source, output)
    assert result['converted'], result
    assert not any('missing from the nif tree' in record.message
                   for record in caplog.records)
    data = N.Data()
    with output.open('rb') as stream:
        data.read(stream)
    controllers = {block for block in data.get_global_iterator()
                   if isinstance(block, N.NiMultiTargetTransformController)}
    assert controllers
    if name == 'midasfirestreak':
        assert all(controller.target is data.roots[0] for controller in controllers)
    else:
        targets = [target for controller in controllers for target in controller.extra_targets]
        assert any(isinstance(target, N.NiTriShape) and target.name == b'RefractiveSphere'
                   for target in targets)


@pytest.mark.parametrize('name', ['sefxsparkledeme03', 'seflamesofagnondem'])
def test_invisible_markers_and_billboards_keep_animation_bindings(name, tmp_path, caplog):
    source = Path('export/Oblivion.esm/meshes/effects') / (name + '.nif')
    if not source.exists():
        pytest.skip('Oblivion source assets are not installed')
    output = tmp_path / source.name
    result = convert_nif(source, output)
    assert result['converted'], result
    assert not any('missing from the nif tree' in record.message for record in caplog.records)
    data = N.Data()
    with output.open('rb') as stream:
        data.read(stream)
    blocks = set(data.get_global_iterator())
    markers = [block for block in blocks if isinstance(block, N.NiAVObject)
               and block.name.startswith(b'EditorMarker')]
    assert len(markers) == 2
    assert all(marker.flags & 1 for marker in markers)
    assert any(isinstance(marker, N.NiTriShape) and marker.data.num_triangles > 0
               for marker in markers)
    palettes = [block for block in blocks if isinstance(block, N.NiDefaultAVObjectPalette)]
    assert palettes
    assert all(entry.av_object in blocks for palette in palettes for entry in palette.objs)
    if name == 'seflamesofagnondem':
        assert any(type(entry.av_object) is N.NiNode and entry.av_object.name == b'FlameMover'
                   for palette in palettes for entry in palette.objs)
