"""Large script/book payloads must not consume the following fields as text."""
import struct

import pytest

from tes4_export.tes4_reader import parse_subrecords, Record, Subrecord
from tes4_export.record_types.dialog_misc import export_INFO
from tools.esm.tes5_esm_reader import _parse_subrecords


@pytest.mark.parametrize('parse', [parse_subrecords, _parse_subrecords])
def test_extended_script_preserves_source_variables_and_references(parse):
    source = b'Scn LargeScript\r\n' + b'; authored comment\r\n' * 4000 + b'\0'
    data = (b'XXXX\x04\x00' + struct.pack('<I', len(source))
            + b'SCTX\x00\x00' + source
            + b'SCVR\x06\x00state\x00'
            + b'SCRO\x04\x00\x78\x56\x34\x12')
    subs = parse(data)
    assert [(s.type, s.data) for s in subs] == [
        ('SCTX', source), ('SCVR', b'state\0'), ('SCRO', b'\x78\x56\x34\x12')]


@pytest.mark.parametrize('parse', [parse_subrecords, _parse_subrecords])
def test_truncated_extended_payload_does_not_become_fake_subrecords(parse):
    data = b'XXXX\x04\x00' + struct.pack('<I', 100000) + b'DESC\0\0partial'
    assert parse(data) == []


def test_dialogue_export_preserves_compiled_reference_table():
    record = Record('INFO', 0, 0, 0x1234, subrecords=[
        Subrecord('SCTX', b'RenamedActor.StartCombat Player\0'),
        Subrecord('SCRO', struct.pack('<I', 0x0100ABCD)),
        Subrecord('SCRO', struct.pack('<I', 0x14)),
    ])
    lines = export_INFO(record)
    assert 'SCRO[0]=0100ABCD' in lines
    assert 'SCRO[1]=00000014' in lines
