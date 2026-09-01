"""Find NaN / Infinity / absurd floats in a converted plugin.

A poisoned float is invisible to xEdit -- it is four legal bytes and every
size/offset still nests, so the file reports as clean -- but the engine folds
these values into arithmetic while it PARSES the file, before any cell loads:
worldspace extents, cell grid bounds and the object LOD/quadtree are all built
at load time from placement data. A NaN propagates through every comparison as
false, so a bounds loop never terminates and the game sits on the main menu
forever with no crash and no log.

Checked per record type, on the subrecords whose payload is float:

  * REFR/ACHR/ACRE  DATA  position XYZ + rotation XYZ
  * CELL            XCLW  water height
  * WRLD            NAM0/NAM9 object bounds, DNAM land/water level
  * LAND            VHGT  height offset

`--max-abs` bounds the "absurd" test (default 1e9): a coordinate that large is
not a real placement, and Skyrim's world is ~2e6 units across.

Usage:
  python tools/validate/float_sanity_check.py TWMP_ValenwoodImproved.esp
  python tools/validate/float_sanity_check.py --max 40 Plugin.esp Other.esp
"""
import argparse
import math
import os
import struct
import sys
from collections import Counter

from output_layout import paths
from tes5_import.tes5_reader import records

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# (record sig, subrecord) -> (offset, count) of floats to test in the payload.
# Only fields the engine reads geometrically at load are listed; a wrong entry
# here invents findings, so each one is tied to a known binary layout.
FLOAT_FIELDS = {
    (b'REFR', b'DATA'): (0, 6),
    (b'ACHR', b'DATA'): (0, 6),
    (b'ACRE', b'DATA'): (0, 6),
    (b'PGRE', b'DATA'): (0, 6),
    (b'PHZD', b'DATA'): (0, 6),
    (b'PMIS', b'DATA'): (0, 6),
    (b'PARW', b'DATA'): (0, 6),
    (b'CELL', b'XCLW'): (0, 1),
    (b'WRLD', b'NAM0'): (0, 2),
    (b'WRLD', b'NAM9'): (0, 2),
    (b'LAND', b'VHGT'): (0, 1),
}

#: The record signatures FLOAT_FIELDS can match, so the walk reads no others.
_WANTED = tuple({sig for sig, _ in FLOAT_FIELDS})


def _classify(v: float, max_abs: float):
    """'NaN', 'Infinity', 'absurd', or None when the float is sane."""
    if math.isnan(v):
        return 'NaN'
    if math.isinf(v):
        return 'Infinity'
    return 'absurd' if abs(v) > max_abs else None


def audit(path, label, max_list, max_abs):
    """Report and count every poisoned float in one plugin."""
    with open(path, 'rb') as f:
        data = f.read()
    bad = Counter()
    examples = {}
    checked = 0

    for rec in records(data, *_WANTED):
        for st, payload in rec.subs():
            spec = FLOAT_FIELDS.get((rec.sig, st))
            if not spec:
                continue
            off, count = spec
            if len(payload) < off + 4 * count:
                continue
            for i, v in enumerate(struct.unpack_from(f'<{count}f',
                                                     payload, off)):
                checked += 1
                kind = _classify(v, max_abs)
                if kind is None:
                    continue
                key = (rec.sig.decode(), st.decode(), i, kind)
                bad[key] += 1
                examples.setdefault(key, (rec.form_id, v))

    n = sum(bad.values())
    print(f"--- {label}: {checked:,} floats checked -> "
          + (f"{n} POISONED" if n else "CLEAN"))
    for (rsig, ssig, i, kind), count in bad.most_common(max_list):
        fid, v = examples[(rsig, ssig, i, kind)]
        print(f"    {rsig}.{ssig}[{i}] {kind} x{count}"
              f"  e.g. {fid:08X} = {v!r}")
    return n


def main():
    """Audit every named plugin and return the poisoned-float total."""
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('plugin', nargs='+')
    ap.add_argument('--output-dir', default=os.path.join(SCRIPT_DIR, 'output'))
    ap.add_argument('--max', type=int, default=25)
    ap.add_argument('--max-abs', type=float, default=1e9,
                    help='magnitude above which a float is "absurd"')
    args = ap.parse_args()

    total = 0
    for name in args.plugin:
        path = str(paths(name, out_root=args.output_dir).esm)
        if not os.path.isfile(path):
            print(f"--- {name}: NOT BUILT ({path})")
            continue
        total += audit(path, name, args.max, args.max_abs)
    print(f"\nTOTAL POISONED FLOATS: {total}")
    return total


if __name__ == '__main__':
    sys.exit(0 if main() == 0 else 1)
