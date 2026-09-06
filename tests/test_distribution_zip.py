"""Distribution archives must include assets even before the BSA stage."""
import zipfile
from pathlib import Path

import convert
import pytest
from asset_convert import distribution_pack as delivery


def test_asset_only_mod_ships_loose_files(tmp_path):
    mod = tmp_path / 'Landscape Pack'
    mesh = mod / 'meshes' / 'landscape' / 'rock.nif'
    mesh.parent.mkdir(parents=True)
    mesh.write_bytes(b'converted mesh')
    assert convert.phase_pack_zip(mod.name, {}, str(tmp_path))
    with zipfile.ZipFile(tmp_path / 'Finished Mods' / 'Landscape Pack.zip') as archive:
        assert archive.namelist() == ['meshes/landscape/rock.nif']
        assert archive.read('meshes/landscape/rock.nif') == b'converted mesh'


def test_unverified_bsa_does_not_replace_converted_loose_assets(tmp_path):
    mod = tmp_path / 'Example.esp'
    scripts = mod / 'scripts'
    scripts.mkdir(parents=True)
    (mod / 'Example.esp').write_bytes(b'plugin')
    (mod / 'Example.bsa').write_bytes(b'old archive')
    (scripts / 'Example.pex').write_bytes(b'new script')
    assert convert.phase_pack_zip(mod.name, {}, str(tmp_path))
    with zipfile.ZipFile(tmp_path / 'Finished Mods' / 'Example.esp.zip') as archive:
        assert set(archive.namelist()) == {'Example.esp', 'scripts/Example.pex'}


@pytest.mark.parametrize('change', ['none', 'modify', 'add', 'delete', 'archive'])
def test_pack_receipt_tracks_whole_source_tree_and_archive(tmp_path, change):
    mod = tmp_path / 'Example.esp'
    scripts = mod / 'scripts'
    scripts.mkdir(parents=True)
    plugin = mod / 'Example.esp'
    plugin.write_bytes(b'plugin')
    bsa = mod / 'Example.bsa'
    bsa.write_bytes(b'packed script')
    script = scripts / 'Example.pex'
    script.write_bytes(b'script')
    delivery.record_pack(mod, delivery.file_state(mod, [script]), [bsa])
    runtime = mod / 'SKSE' / 'Plugins' / 'TES4Runtime.dll'
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b'runtime')
    if change == 'modify':
        script.write_bytes(b'new script')
    elif change == 'add':
        (scripts / 'New.pex').write_bytes(b'additional script')
    elif change == 'delete':
        script.unlink()
    elif change == 'archive':
        bsa.write_bytes(b'partial BSA')
    assert convert.phase_pack_zip(mod.name, {}, str(tmp_path))
    with zipfile.ZipFile(tmp_path / 'Finished Mods' / 'Example.esp.zip') as archive:
        names = set(archive.namelist())
        assert ('Example.bsa' in names) == (change == 'none')
        assert ('scripts/Example.pex' in names) == (change not in ('none', 'delete'))
        assert ('scripts/New.pex' in names) == (change == 'add')
        assert 'SKSE/Plugins/TES4Runtime.dll' in names
        assert delivery.RECEIPT not in names


def test_interrupted_zip_preserves_previous_delivery(tmp_path, monkeypatch):
    mod = tmp_path / 'Example.esp'
    mod.mkdir()
    (mod / 'Example.esp').write_bytes(b'plugin')
    destination = tmp_path / 'previous.zip'
    destination.write_bytes(b'previous completed delivery')

    def fail(*args, **kwargs):
        raise OSError('disk write failed')

    monkeypatch.setattr(zipfile.ZipFile, 'write', fail)
    with pytest.raises(OSError, match='disk write failed'):
        delivery.write_zip(mod, destination)
    assert destination.read_bytes() == b'previous completed delivery'
    assert not destination.with_suffix('.zip.part').exists()


def test_real_bsa_pack_receipt_and_zip_payload(tmp_path):
    from asset_convert.bsa_pack import pack_bsas
    from asset_convert.bsa_extract import read_bsa_files

    bsarch = Path(__file__).resolve().parents[1] / 'external/bsarch/BSArch.exe'
    if not bsarch.is_file():
        pytest.skip('BSArch is not installed')
    mod = tmp_path / 'Example.esp'
    script = mod / 'scripts' / 'Example.pex'
    script.parent.mkdir(parents=True)
    script.write_bytes(b'actual packed payload')
    (mod / 'Example.esp').write_bytes(b'plugin')
    result = pack_bsas(mod.name, output_dir=tmp_path, bsarch_path=str(bsarch))
    assert result['errors'] == []
    assert read_bsa_files(mod / 'Example.bsa', ['scripts/Example.pex']) == {
        'scripts\\example.pex': script.read_bytes()}
    assert delivery.current_archives(mod, [script]) == [mod / 'Example.bsa']
    assert convert.phase_pack_zip(mod.name, {}, str(tmp_path))
    with zipfile.ZipFile(tmp_path / 'Finished Mods' / 'Example.esp.zip') as archive:
        assert set(archive.namelist()) == {'Example.esp', 'Example.bsa'}
        assert archive.read('Example.bsa') == (mod / 'Example.bsa').read_bytes()
