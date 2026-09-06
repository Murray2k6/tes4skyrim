"""Saved executable images preserve relocated pointers and unwind tables."""
from pathlib import Path

import pefile
import pytest

from tools.disasm.skyrim_disasm import Binary, LiveBinary


def test_snapshot_vtable_and_function_bounds_match_disk(tmp_path):
    path = Path('E:/SteamLibrary/steamapps/common/Skyrim Special Edition/CreationKit.exe')
    if not path.is_file():
        pytest.skip('Unpacked Creation Kit executable is not installed')
    disk = Binary(str(path))
    capture = LiveBinary.__new__(LiveBinary)
    capture.path = str(path)
    capture.base = disk.base
    capture.data = pefile.PE(str(path), fast_load=True).get_memory_mapped_image()
    capture._prepare_image()
    path = tmp_path / 'engine.snapshot'
    capture.save_snapshot(path)
    loaded = LiveBinary.from_snapshot(path)
    assert loaded.base == capture.base
    assert loaded.data == capture.data
    tables = loaded.vtables_for('NiPSysMeshEmitter')
    assert tables == disk.vtables_for('NiPSysMeshEmitter')
    slots = dict(loaded.vtable_slots(tables[0], 46))
    assert slots == dict(disk.vtable_slots(tables[0], 46))
    assert loaded.func_bounds(slots[45]) == disk.func_bounds(slots[45])
    first_function = disk.runtime_functions()[0][0]
    assert loaded.func_bounds(first_function) == disk.func_bounds(first_function)
    assert loaded.func_bounds(first_function) is not None


def test_snapshot_rejects_wrong_signature(tmp_path):
    path = tmp_path / 'invalid.snapshot'
    path.write_bytes(bytes(16))
    with pytest.raises(ValueError, match='Not a Skyrim'):
        LiveBinary.from_snapshot(path)
