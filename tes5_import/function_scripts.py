"""Preserve SCPT identity and give OBSE Functions property-bound instances.

SCPT has no TES5 equivalent. A Function-only SCPT becomes a Quest at the
source record's shifted FormID, so references to the function remain valid.
Function locals live on the calling stack, not on this shared host.
"""

import re
import struct

from script_convert.constants import papyrus_script_name
from script_convert.pipeline import build_vmad_object_script
from .object_scripts import _resolve_props
from .text_reader import get_formid, get_formid_index_offset
from .writer import pack_subrecord, pack_string_subrecord, pack_record


_FUNCTION = re.compile(r'^\s*begin\s+_?function\b', re.I | re.M)


def build_function_hosts(by_type, writer, xref, fid_to_edid):
    """Emit hosts/identity keywords; masters supply their own SCPT identities."""
    count = 0
    for rec in by_type.get('SCPT', ()):
        source = rec.get('SCTX', '')
        edid = rec.get('EditorID', '') or 'Script_' + rec['FormID']
        if not _FUNCTION.search(source):
            body = pack_string_subrecord('EDID', edid)
            writer.add_record('KYWD', pack_record('KYWD', get_formid(rec, 'FormID'), 0, body))
            continue
        props = _resolve_props(source, edid, 'Quest', xref, fid_to_edid,
                               get_formid_index_offset())
        body = pack_string_subrecord('EDID', edid)
        body += pack_subrecord('VMAD', build_vmad_object_script(
            papyrus_script_name(edid), props))
        body += pack_subrecord('DNAM', struct.pack('<HBBII', 0x11, 0, 0, 0, 0))
        body += pack_subrecord('NEXT', b'')
        writer.add_record('QUST', pack_record('QUST', get_formid(rec, 'FormID'), 0, body))
        count += 1
    return count
