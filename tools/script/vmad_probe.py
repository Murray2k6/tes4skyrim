#!/usr/bin/env python3
"""Report which records in a TES5 plugin carry a given Papyrus script VMAD,
and (with --props) the script's bound property values.

Answers "is this script attached to the base NPC_ or to the placed ACHR?" — the
distinction that decides whether reference events (OnPackageEnd, OnActivate,
OnHit, ...) are ever delivered — and "did its properties actually bind?", since
an unbound Object property is None and every `== <prop>` test silently fails.
See CLAUDE.md / object_scripts.py.

Usage:
    python tools/script/vmad_probe.py output/Oblivion.esm/Oblivion.esm TES4_CGRenoteScript
    python tools/script/vmad_probe.py <esm> <script> --props
    python tools/script/vmad_probe.py <esm> <script> --types NPC_,ACHR
"""
import argparse
import mmap
import struct
import sys

from tes5_import.tes5_reader import records, subrecords


def _records(buf):
    """Yield (sig, formid, flags, data) for every record, descending GRUPs."""
    for rec in records(bytes(buf)):
        yield rec.sig, rec.form_id, rec.flags, rec.body


def _subrecords(data):
    """Yield `(tag, data)`; XXXX oversized payloads are already resolved."""
    return subrecords(data)


def _wstring(buf, pos):
    n = struct.unpack_from('<H', buf, pos)[0]
    return buf[pos + 2:pos + 2 + n].decode('latin1'), pos + 2 + n


def _parse_props(vmad, want_lower):
    """Yield (prop_name, kind, value) for the named script in this VMAD."""
    pos = 0
    _ver, _fmt = struct.unpack_from('<hH', vmad, pos)
    pos += 4
    count = struct.unpack_from('<H', vmad, pos)[0]
    pos += 2
    for _ in range(count):
        name, pos = _wstring(vmad, pos)
        pos += 1                                    # flags
        nprops = struct.unpack_from('<H', vmad, pos)[0]
        pos += 2
        for _ in range(nprops):
            pname, pos = _wstring(vmad, pos)
            ptype, _status = struct.unpack_from('<BB', vmad, pos)
            pos += 2
            if ptype == 1:                          # Object (v2 layout)
                _unused, _alias, fid = struct.unpack_from('<HhI', vmad, pos)
                pos += 8
                if name.lower() == want_lower:
                    yield pname, 'Object', f'{fid:08X}'
            elif ptype == 2:                        # wstring
                sval, pos = _wstring(vmad, pos)
                if name.lower() == want_lower:
                    yield pname, 'String', sval
            elif ptype in (3, 4):                   # int32 / float
                (val,) = struct.unpack_from('<i' if ptype == 3 else '<f',
                                            vmad, pos)
                pos += 4
                if name.lower() == want_lower:
                    yield pname, 'Int' if ptype == 3 else 'Float', val
            elif ptype == 5:                        # bool
                val = vmad[pos]
                pos += 1
                if name.lower() == want_lower:
                    yield pname, 'Bool', val
            else:
                return                              # unknown: stop parsing
        if name.lower() == want_lower:
            return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('esm')
    ap.add_argument('script', help='Papyrus script name (case-insensitive)')
    ap.add_argument('--types', default='',
                    help='comma-separated signatures to limit the scan')
    ap.add_argument('--props', action='store_true',
                    help='also print the script\'s bound property values')
    args = ap.parse_args()

    want_l = args.script.lower()
    want = want_l.encode('ascii', 'replace')
    types = {t.strip().encode() for t in args.types.split(',') if t.strip()}

    hits = []
    with open(args.esm, 'rb') as f:
        buf = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        for sig, fid, _flags, data in _records(buf):
            if types and sig not in types:
                continue
            for ssig, sdata in _subrecords(data):
                if ssig != b'VMAD':
                    continue
                if want in sdata.lower():
                    hits.append((sig.decode('latin1'), fid, bytes(sdata)))
                break

    if not hits:
        print(f'{args.script}: NOT attached to any record')
        return 1
    for sig, fid, vmad in hits:
        print(f'{sig} {fid:08X}')
        if args.props:
            try:
                for pname, kind, val in _parse_props(vmad, want_l):
                    flag = ''
                    if kind == 'Object' and val == '00000000':
                        flag = '   <-- UNBOUND (None)'
                    print(f'    {pname:32} {kind:7} {val}{flag}')
            except (struct.error, IndexError) as exc:
                print(f'    <property parse failed: {exc}>')
    print(f'\n{len(hits)} record(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
