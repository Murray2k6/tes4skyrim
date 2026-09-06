"""Hidden Windows workers must retain CPython's venv handle protocol."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows spawn protocol')
def test_hidden_pool_delivers_results_and_keeps_venv(tmp_path):
    script = tmp_path / 'workers.py'
    script.write_text('''import multiprocessing as mp
import sys
from subprocess_flags import configure_multiprocessing

def worker(value):
    return value * value, sys.prefix

if __name__ == '__main__':
    configure_multiprocessing()
    configure_multiprocessing()
    with mp.Pool(2) as pool:
        results = pool.map_async(worker, [3, 7]).get(timeout=15)
    assert results == [(9, sys.prefix), (49, sys.prefix)], results
    print('worker results and interpreter prefix match', flush=True)
''', encoding='utf-8')
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, str(script)], env=environment,
                            text=True, capture_output=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'worker results and interpreter prefix match' in result.stdout
