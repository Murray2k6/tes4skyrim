"""Verify the WRLD->CNAM->CLMT->WLST->WTHR->IMSP->IMGS + REGN->RDWT chain
in a converted TES5 plugin."""
import struct
import sys

from tes5_import.tes5_reader import records as read_records

path = sys.argv[1]
data = open(path, 'rb').read()

records = {}   # fid -> (sig, subrecords list)
by_sig = {}

for rec in read_records(data):
    s = rec.sig.decode('ascii')
    records[rec.form_id] = (s, rec.subs())
    by_sig.setdefault(s, []).append(rec.form_id)

print({k: len(v) for k, v in sorted(by_sig.items())
       if k in ('WTHR', 'IMGS', 'CLMT', 'REGN', 'WRLD', 'SPGD')})

def exists(fid, want):
    if fid == 0:
        return True
    if fid >> 24 == 0:   # Skyrim.esm master ref: can't check, assume vanilla
        return True
    return records.get(fid, ('?',))[0] == want

bad = 0
# WRLD CNAM -> CLMT
for fid in by_sig.get('WRLD', []):
    subs = dict((s, d) for s, d in records[fid][1])
    cnam = subs.get(b'CNAM')
    if cnam is None:
        print(f'WRLD {fid:08X}: NO CNAM'); bad += 1
    elif not exists(struct.unpack('<I', cnam)[0], 'CLMT'):
        print(f'WRLD {fid:08X}: dangling CNAM {struct.unpack("<I", cnam)[0]:08X}'); bad += 1
# CLMT WLST -> WTHR
for fid in by_sig.get('CLMT', []):
    for s, d in records[fid][1]:
        if s == b'WLST':
            for off in range(0, len(d) - 11, 12):
                w = struct.unpack_from('<I', d, off)[0]
                if not exists(w, 'WTHR'):
                    print(f'CLMT {fid:08X}: dangling WLST weather {w:08X}'); bad += 1
# REGN RDWT -> WTHR
for fid in by_sig.get('REGN', []):
    for s, d in records[fid][1]:
        if s == b'RDWT':
            for off in range(0, len(d) - 11, 12):
                w = struct.unpack_from('<I', d, off)[0]
                if not exists(w, 'WTHR'):
                    print(f'REGN {fid:08X}: dangling RDWT weather {w:08X}'); bad += 1
# WTHR IMSP -> IMGS (own records, so fully checkable) + MNAM -> SPGD
n_precip = 0
for fid in by_sig.get('WTHR', []):
    subs = records[fid][1]
    d = dict((s, v) for s, v in subs)
    imsp = d.get(b'IMSP')
    if imsp is None or len(imsp) != 16:
        print(f'WTHR {fid:08X}: missing IMSP'); bad += 1
        continue
    slots = struct.unpack('<4I', imsp)
    if len(set(slots)) != 4:
        print(f'WTHR {fid:08X}: IMSP slots not distinct {slots}'); bad += 1
    for s in slots:
        if s == 0x161 or not exists(s, 'IMGS'):
            print(f'WTHR {fid:08X}: bad IMSP target {s:08X}'); bad += 1
        elif (s >> 24) != 0:
            hn = dict((a, b) for a, b in records[s][1]).get(b'HNAM')
            if hn is None or len(hn) != 36:
                print(f'IMGS {s:08X}: missing/short HNAM'); bad += 1
    mnam = d.get(b'MNAM')
    if mnam and struct.unpack('<I', mnam)[0]:
        n_precip += 1

print(f'weathers with precipitation SPGD: {n_precip}')
print('CHAIN OK' if bad == 0 else f'{bad} PROBLEMS')
