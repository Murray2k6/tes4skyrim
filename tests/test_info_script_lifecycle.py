"""A stored dialogue editor draft is not an executable result script."""
import struct

from tes4_export.record_types.dialog_misc import export_INFO
from tes4_export.tes4_reader import Record, Subrecord
from tes5_import.text_reader import parse_record_block
from script_convert.pipeline import info_needs_fragment


def exported_info(source, bytecode):
    fields = [Subrecord('SCTX', source.encode()),
              Subrecord('SCHR', struct.pack('<5I', 0, 0, len(bytecode), 0, 0))]
    if bytecode:
        fields.append(Subrecord('SCDA', bytecode))
    return ['Signature=INFO', 'FormID=00001234', *export_INFO(
        Record('INFO', 0, 0, 0x1234, subrecords=fields))]


def test_uncompiled_text_survives_export_without_becoming_a_fragment():
    source = 'MissingActor.StartCombat Player'
    exported = exported_info(source, b'')
    assert f'ResultScript={source}' in exported
    assert 'ResultScript.Bytecode=' in exported
    record = parse_record_block(exported)
    assert record['ResultScript.SourceText'] == source
    assert not record.get('ResultScript')
    assert not info_needs_fragment(record)


def test_compiled_result_still_runs_and_keeps_its_exact_bytes():
    # DisablePlayerControls from the original Nehrim INFO's SCDA.
    exported = exported_info('DisablePlayerControls', bytes.fromhex('61100000'))
    record = parse_record_block(exported)
    assert record['ResultScript.Bytecode'] == '61100000'
    assert record['ResultScript'] == 'DisablePlayerControls'
    assert info_needs_fragment(record)
