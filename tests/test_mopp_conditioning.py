"""Native MOPP compilation must retain the source frame without crash retries."""
import json
from pathlib import Path

import pytest

from asset_convert.cms_builder import run_mopp_bridge
from asset_convert.mopp import walk_mopp


@pytest.mark.parametrize('extent,offset', [(0.034, 0.0), (2.0, 30000.0), (256.0, -30000.0)])
def test_native_build_preserves_mopp_coordinates(extent, offset, monkeypatch):
    from asset_convert import cms_builder as builder

    if not Path(builder._MOPP_BRIDGE).exists():
        pytest.skip('native MOPP compiler is not installed')
    vertices = [(offset + x * extent, y * extent, z * extent)
                for x, y, z in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                                (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))]
    triangles = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
                 (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
                 (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    keys = [0x40000 + 3 * i for i in range(len(triangles))]
    native_run = builder.subprocess.run
    calls = []

    def capture(argv, **kwargs):
        result = native_run(argv, **kwargs)
        assert result.returncode == 0, result.stderr
        request = json.loads(Path(argv[argv.index('--input') + 1]).read_text())
        response = json.loads(Path(argv[argv.index('--output') + 1]).read_text())
        calls.append((request, response))
        return result

    monkeypatch.setattr(builder.subprocess, 'run', capture)
    result = run_mopp_bridge(vertices, triangles, keys, timeout=10)
    assert len(calls) == 1
    request, response = calls[0]
    assert request['triangles'] == [i for triangle in triangles for i in triangle]
    assert request['shape_keys'] == keys
    assert len(result['welding_info']) == len(triangles)
    code = bytes.fromhex(result['mopp_data_hex'])
    walked = walk_mopp(code, len(code))
    assert not walked['errors']
    assert walked['tris'] == set(keys)
    # Compare the native compiler's coordinate frame to the returned source
    # frame: every vertex must address the same location in MOPP space.
    for i, vertex in enumerate(vertices):
        for axis in range(3):
            native = ((request['vertices'][3 * i + axis] - response['mopp_origin'][axis])
                      * response['mopp_scale'])
            restored = (vertex[axis] - result['mopp_origin'][axis]) * result['mopp_scale']
            assert restored == pytest.approx(native, abs=0.01)
