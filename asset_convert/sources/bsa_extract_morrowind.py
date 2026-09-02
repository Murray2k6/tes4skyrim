"""
Morrowind BSA reading.

The TES3 archive predates every later BSA and shares nothing with them: the
magic is 0x00000100 rather than "BSA\\0", there are no folder records (each
entry carries one flat path), and nothing is ever compressed.

    header (12):  version(4) hashTableOffset(4) fileCount(4)
    sizes/offsets (fileCount x 8):  size(4) offset(4)
    name offsets  (fileCount x 4):  offset into the name block
    name block:   null-terminated paths
    hash table    (fileCount x 8)
    file data

Offsets in the size/offset table are relative to the end of the hash table.

See: docs/commentary/tes4_export_morrowind.md#tes3-bsa
"""

import struct
from pathlib import Path

#: Version field standing where later archives put the "BSA\0" magic.
TES3_BSA_MAGIC = 0x00000100

_HEADER_SIZE = 12


def is_morrowind_bsa(bsa_path) -> bool:
    """True when this archive is Morrowind's format rather than a later one."""
    try:
        with open(bsa_path, 'rb') as fh:
            head = fh.read(4)
    except OSError:
        return False
    return (len(head) == 4
            and struct.unpack('<I', head)[0] == TES3_BSA_MAGIC)


def iter_bsa(bsa_path):
    """Yield (filepath_str, data_bytes) for every file in a Morrowind BSA.

    Matches the tuple shape the Oblivion reader yields, so extraction consumes
    either without knowing which game the archive came from.
    """
    data = Path(bsa_path).read_bytes()
    version, hash_offset, count = struct.unpack_from('<III', data, 0)
    if version != TES3_BSA_MAGIC:
        raise ValueError(f'Not a Morrowind BSA: {bsa_path}')

    names = _read_names(data, count)
    data_start = _HEADER_SIZE + hash_offset + count * 8
    for index, name in enumerate(names):
        size, offset = struct.unpack_from('<II', data, _HEADER_SIZE + index * 8)
        start = data_start + offset
        yield name, data[start:start + size]


def _read_names(data: bytes, count: int) -> list:
    """Every stored path, in the order the size/offset table uses."""
    name_offsets_at = _HEADER_SIZE + count * 8
    block_at = name_offsets_at + count * 4
    names = []
    for index in range(count):
        offset = struct.unpack_from('<I', data, name_offsets_at + index * 4)[0]
        start = block_at + offset
        end = data.index(b'\x00', start)
        names.append(data[start:end].decode('cp1252', errors='replace'))
    return names
