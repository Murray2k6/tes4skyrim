"""Flame sockets resolve authored models across master and shared asset trees."""
import json

import pytest

from asset_convert.nif_converter import convert_nif
from asset_convert import nif_flames as flames
from pyffi.formats.nif import NifFormat


def _records(root, masters=(), model=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / '_HEADER.txt').write_text(''.join(
        f'Master[{i}]={name}\n' for i, name in enumerate(masters)))
    if model:
        (root / 'STAT.txt').write_text(
            '---RECORD_BEGIN---\nSignature=STAT\nFormID=0000001E\n'
            f'EditorID=FlameNode0\nModel.MODL={model}\n---RECORD_END---\n')


def _nif(path, child_name):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = NifFormat.Data(version=0x14000005, user_version=11,
                          user_version_2=11)
    data.header.endian_type = 1
    root = NifFormat.NiNode()
    root.name = b'Root'
    root.add_child(NifFormat.NiNode())
    root.children[0].name = child_name
    data.roots = [root]
    with path.open('wb') as stream:
        data.write(stream)


def test_transitive_master_mapping_and_child_asset_override(tmp_path):
    base, mid, mod = (tmp_path / n for n in ('Base.esm', 'Mid.esm', 'Mod.esp'))
    _records(base, model='custom/fire/candle.nif')
    _records(mid, ['Base.esm'])
    _records(mod, ['Mid.esm'])
    _nif(base / 'meshes/custom/fire/candle.nif', b'Master flame')
    _nif(mod / 'meshes/custom/fire/candle.nif', b'Overridden flame')
    host = mod / 'meshes/host.nif'
    _nif(host, b'FlameNode0')
    output = tmp_path / 'out/meshes/host.nif'
    output.parent.mkdir(parents=True)
    assert convert_nif(str(host), str(output))['converted']
    data = NifFormat.Data()
    with output.open('rb') as stream:
        data.read(stream)
    socket = next(b for b in data.blocks if getattr(b, 'name', None) == b'FlameNode0')
    assert socket.children[0].name == b'Overridden flame'


def test_asset_only_base_and_grouped_master(tmp_path):
    (tmp_path / 'sources.json').write_text(json.dumps({'version': 1, 'sources': {
        'Base.esm': {'plugin': 'Base.esm', 'group_label': 'Base Pack',
                     'group_id': 'base', 'group_plugins': ['Base.esm', 'Patch.esp']}}}))
    base = tmp_path / 'Base Pack/Base.esm'
    _records(base, model='fire/candle.nif')
    mod = tmp_path / 'Asset Pack'
    (mod / '_source').mkdir(parents=True)
    (mod / '_source/.base_plugins').write_text('Base.esm\n')
    path = tmp_path / 'Base Pack/meshes/fire/candle.nif'
    _nif(path, b'Inherited flame')
    host = mod / 'meshes/host.nif'
    assert flames._flame_socket_map(host) == {0: 'fire/candle.nif'}
    assert flames._flame_source(host, 'fire/candle.nif') == str(path)


@pytest.mark.parametrize('corrupt', [False, True])
def test_missing_or_corrupt_authored_flame_is_a_conversion_failure(tmp_path, corrupt):
    _records(tmp_path, model='custom/candle.nif')
    host = tmp_path / 'meshes/host.nif'
    _nif(host, b'FlameNode0')
    if corrupt:
        path = tmp_path / 'meshes/custom/candle.nif'
        path.parent.mkdir()
        path.write_bytes(b'broken NIF')
    with pytest.raises(Exception):
        convert_nif(str(host), str(tmp_path / 'out.nif'))
    assert not (tmp_path / 'out.nif').exists()
