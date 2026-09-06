"""Import every module in a package and report the ones that fail.

A stale import after a refactor is invisible to the gate, to the tests that do
not touch that stage, and to a partial pipeline run: `asset_convert/speedtree/
spt_converter.py` kept importing `asset_convert.nif.bsx_flags` after that module
was renamed, and the whole --speedtrees-only stage would have died on the first
call with nothing else complaining.

Usage:
    python tools/validate/import_sweep.py                  # every first-party package
    python tools/validate/import_sweep.py asset_convert    # just one
    python tools/validate/import_sweep.py --quiet          # exit code only
"""

import argparse
import importlib
import pkgutil
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: First-party packages, swept when no package is named on the command line.
DEFAULT_PACKAGES = ('asset_convert', 'tes4_export', 'tes5_import',
                    'script_convert')

#: Modules a sweep must skip: importing one has a side effect or needs a GPU.
SKIP_SUFFIXES = ('.__main__',)


def _walk(package_name):
    """Every importable module name under a package, the package itself first."""
    try:
        package = importlib.import_module(package_name)
    except Exception:
        return [package_name]
    names = [package_name]
    for mod in pkgutil.walk_packages(package.__path__, package_name + '.'):
        if not mod.name.endswith(SKIP_SUFFIXES):
            names.append(mod.name)
    return names


def sweep(package_names, verbose=True):
    """Import everything under each package; the list of (name, error) failures."""
    failures = []
    total = 0
    for package_name in package_names:
        for name in _walk(package_name):
            total += 1
            try:
                importlib.import_module(name)
            except Exception as exc:
                failures.append((name, exc, traceback.format_exc()))
    if verbose:
        print(f'{total} modules imported, {len(failures)} failed')
        for name, exc, tb in failures:
            print(f'\n  {name}\n    {type(exc).__name__}: {exc}')
            for line in tb.strip().splitlines()[-4:-1]:
                print(f'    {line.strip()}')
    return failures


def main() -> int:
    """Sweep the named packages; non-zero when any module fails to import."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('packages', nargs='*', default=None,
                    help='packages to sweep (default: every first-party one)')
    ap.add_argument('--quiet', action='store_true',
                    help='print nothing; report through the exit code')
    args = ap.parse_args()

    sys.path.insert(0, str(REPO))
    packages = args.packages or list(DEFAULT_PACKAGES)
    failures = sweep(packages, verbose=not args.quiet)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
