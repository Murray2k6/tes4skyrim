"""The shared TES5 binary reader: headers, subrecords, GRUP context."""
import struct
import zlib

import pytest

from tes5_import import tes5_reader as R


def sub(tag: bytes, data: bytes) -> bytes:
    """One subrecord: 4-byte tag, u16 size, body."""
    return tag + struct.pack('<H', len(data)) + data


def rec(sig: bytes, body: bytes, flags: int = 0, fid: int = 1) -> bytes:
    """One record with a 24-byte TES5 header."""
    return (sig + struct.pack('<3I', len(body), flags, fid)
            + struct.pack('<HHI', 0, 44, 0)[:8] + body)


def grup(label: bytes, gtype: int, payload: bytes) -> bytes:
    """One GRUP wrapping `payload`; size counts the header."""
    return (b'GRUP' + struct.pack('<I', len(payload) + R.GRP_HDR)
            + label + struct.pack('<3I', gtype, 0, 0)[:12] + payload)


def plugin(payload: bytes, masters_: tuple = ()) -> bytes:
    """A TES4 header carrying `masters_`, followed by `payload`."""
    body = sub(b'HEDR', struct.pack('<fiI', 1.7, 0, 2048))
    for m in masters_:
        body += sub(b'MAST', m + b'\x00') + sub(b'DATA', b'\x00' * 8)
    return rec(b'TES4', body) + payload


class TestSubrecords:
    """Body splitting and lookup."""

    def test_pairs_come_back_in_file_order(self):
        """subrecords preserves the order the file stores."""
        body = sub(b'EDID', b'a\x00') + sub(b'FULL', b'b\x00')
        assert R.subrecords(body) == [(b'EDID', b'a\x00'), (b'FULL', b'b\x00')]

    def test_a_repeated_tag_keeps_every_copy(self):
        """Array subrecords (MNAM LOD, CTDA chains) must not collapse."""
        body = sub(b'MNAM', b'x') + sub(b'MNAM', b'y') + sub(b'MNAM', b'z')
        assert [d for _, d in R.subrecords(body)] == [b'x', b'y', b'z']

    def test_sub_map_keeps_the_last_of_a_repeated_tag(self):
        """sub_map is lossy by design; the last value wins."""
        body = sub(b'MNAM', b'x') + sub(b'MNAM', b'y')
        assert R.sub_map(body)[b'MNAM'] == b'y'

    def test_a_truncated_trailing_subrecord_is_dropped(self):
        """Real plugins carry these; the readable ones still come back."""
        body = sub(b'EDID', b'ok\x00') + b'FULL' + struct.pack('<H', 99)
        assert R.subrecords(body) == [(b'EDID', b'ok\x00')]

    def test_first_sub_returns_none_when_absent(self):
        """A missing tag is None, not an exception."""
        assert R.first_sub(sub(b'EDID', b'a'), b'MODL') is None

    def test_zstr_stops_at_the_null(self):
        """Trailing bytes after the terminator are discarded."""
        assert R.zstr(b'meshes\\x.nif\x00junk') == 'meshes\\x.nif'


class TestRecord:
    """Header fields, the compressed body, and accessors."""

    def test_header_fields_are_read(self):
        """Signature, FormID and the next offset come off the header."""
        built = rec(b'STAT', sub(b'EDID', b'e\x00'), fid=7)
        got, nxt = R.read_record(built, 0)
        assert (got.sig, got.form_id) == (b'STAT', 7)
        assert nxt == len(built)

    def test_a_compressed_body_is_inflated(self):
        """A flagged body is transparently decompressed."""
        inner = sub(b'EDID', b'zipped\x00')
        packed = struct.pack('<I', len(inner)) + zlib.compress(inner)
        got, _ = R.read_record(rec(b'STAT', packed, R.FLAG_COMPRESSED), 0)
        assert got.string(b'EDID') == 'zipped'

    def test_a_corrupt_deflate_stream_yields_an_empty_body(self):
        """One bad record must not abort a whole-plugin scan."""
        packed = struct.pack('<I', 40) + b'not really deflate'
        got, _ = R.read_record(rec(b'STAT', packed, R.FLAG_COMPRESSED), 0)
        assert got.body == b''

    def test_a_record_running_past_the_end_is_refused(self):
        """A truncated record reads as None rather than short data."""
        raw = rec(b'STAT', sub(b'EDID', b'e\x00'))[:-4]
        assert R.read_record(raw, 0) == (None, 0)

    def test_the_deleted_flag_is_exposed(self):
        """An override's delete flag drives removal downstream."""
        got, _ = R.read_record(rec(b'REFR', b'', R.FLAG_DELETED), 0)
        assert got.deleted

    def test_string_falls_back_when_the_tag_is_absent(self):
        """A missing string subrecord yields the supplied default."""
        got, _ = R.read_record(rec(b'STAT', b''), 0)
        assert got.string(b'EDID', 'fallback') == 'fallback'


class TestMasters:
    """The MAST list drives cross-plugin FormID identity."""

    def test_masters_come_back_lowercased_in_order(self):
        """Declaration order is the index-byte mapping, so it must hold."""
        raw = plugin(b'', (b'Skyrim.esm', b'Update.ESM'))
        assert R.masters(raw) == ['skyrim.esm', 'update.esm']

    def test_a_plugin_with_no_masters_gives_an_empty_list(self):
        """A standalone plugin owns index byte 0."""
        assert R.masters(plugin(b'')) == []

    def test_a_non_tes4_file_gives_an_empty_list(self):
        """Garbage in never raises."""
        assert R.masters(b'JUNKJUNKJUNK') == []

    def test_header_end_lands_on_the_first_group(self):
        """header_end skips exactly the TES4 record."""
        raw = plugin(grup(b'STAT', R.GRP_TOP, rec(b'STAT', b'')))
        assert raw[R.header_end(raw):][:4] == b'GRUP'


class TestGroupContext:
    """The enclosing GRUP chain a record is found under."""

    @pytest.fixture
    def worldspace_plugin(self):
        """A WRLD with one exterior cell holding one REFR."""
        refr = rec(b'REFR', sub(b'NAME', struct.pack('<I', 0x123)), fid=0x30)
        cell_kids = grup(struct.pack('<I', 0x20), 9, refr)
        cell = rec(b'CELL', sub(b'XCLC', struct.pack('<2i', 4, -5)), fid=0x20)
        block = grup(struct.pack('<2h', -5, 4), R.GRP_EXT_BLOCK,
                     cell + cell_kids)
        world_kids = grup(struct.pack('<I', 0x10), R.GRP_WORLD_CHILDREN, block)
        wrld = rec(b'WRLD', sub(b'EDID', b'Tamriel\x00'), fid=0x10)
        return plugin(grup(b'WRLD', R.GRP_TOP, wrld + world_kids))

    def test_every_record_is_yielded_once(self, worldspace_plugin):
        """Nesting must not duplicate or drop a record."""
        sigs = [r.sig for r in R.records(worldspace_plugin)]
        assert sigs == [b'WRLD', b'CELL', b'REFR']

    def test_the_refr_knows_its_worldspace(self, worldspace_plugin):
        """The type-1 GRUP label is the owning worldspace."""
        for r, stack in R.walk(worldspace_plugin):
            if r.sig == b'REFR':
                assert stack.worldspace == 0x10
                return
        pytest.fail('no REFR yielded')

    def test_the_refr_knows_its_cell(self, worldspace_plugin):
        """The innermost cell-children GRUP label is the owning cell."""
        for r, stack in R.walk(worldspace_plugin):
            if r.sig == b'REFR':
                assert stack.cell == 0x20
                return
        pytest.fail('no REFR yielded')

    def test_the_top_group_signature_is_available(self, worldspace_plugin):
        """A type-0 label is a signature, not a FormID."""
        for _, stack in R.walk(worldspace_plugin):
            assert stack.top == b'WRLD'

    def test_an_exterior_block_label_reads_as_y_then_x(self,
                                                       worldspace_plugin):
        """Exterior block labels pack Y before X."""
        for _, stack in R.walk(worldspace_plugin):
            block = stack.of_type(R.GRP_EXT_BLOCK)
            if block is not None:
                assert block.label_grid == (-5, 4)
                return
        pytest.fail('no block GRUP seen')

    def test_a_record_outside_any_worldspace_reports_none(self):
        """An interior or top-level record has no worldspace or cell."""
        raw = plugin(grup(b'STAT', R.GRP_TOP, rec(b'STAT', b'')))
        for _, stack in R.walk(raw):
            assert stack.worldspace is None and stack.cell is None

    def test_naming_signatures_filters_in_file_order(self,
                                                     worldspace_plugin):
        """Only the requested signatures come back, in file order."""
        got = list(R.records(worldspace_plugin, b'REFR', b'CELL'))
        assert [r.sig for r in got] == [b'CELL', b'REFR']

    def test_a_wanted_signature_still_reaches_nested_records(
            self, worldspace_plugin):
        """A REFR lives under WRLD, so asking for one must enter that block."""
        got = list(R.records(worldspace_plugin, b'REFR'))
        assert [r.form_id for r in got] == [0x30]

    def test_asking_for_wrld_skips_its_children(self, worldspace_plugin):
        """A WRLD search must not walk the cells behind each worldspace."""
        seen = []
        for _, stack in R.walk(worldspace_plugin, b'WRLD'):
            seen.append(tuple(g.type for g in stack.groups))
        assert seen == [(R.GRP_TOP,)]

    def test_pruning_a_group_skips_its_whole_subtree(self,
                                                     worldspace_plugin):
        """`prune` covers what a signature alone cannot decide."""
        got = list(R.records(
            worldspace_plugin,
            prune=lambda g, _: g.type == R.GRP_WORLD_CHILDREN))
        assert [r.sig for r in got] == [b'WRLD']

    def test_pruning_nothing_matches_an_unpruned_walk(self,
                                                      worldspace_plugin):
        """A prune that never fires changes no output."""
        a = [r.sig for r in R.records(worldspace_plugin)]
        b = [r.sig for r in R.records(worldspace_plugin,
                                      prune=lambda g, _: False)]
        assert a == b

    def test_no_bodies_leaves_the_body_empty(self, worldspace_plugin):
        """Header-only scans skip the slice but keep sig and FormID."""
        got = list(R.records(worldspace_plugin, bodies=()))
        assert [r.sig for r in got] == [b'WRLD', b'CELL', b'REFR']
        assert all(r.body == b'' for r in got)
        assert [r.form_id for r in got] == [0x10, 0x20, 0x30]

    def test_bodies_narrows_which_records_are_read(self, worldspace_plugin):
        """Every record still yields; only the named ones carry a body."""
        got = {r.sig: r.body for r in R.records(worldspace_plugin,
                                                bodies=(b'CELL',))}
        assert set(got) == {b'WRLD', b'CELL', b'REFR'}
        assert got[b'CELL'] and not got[b'WRLD'] and not got[b'REFR']


class TestMalformed:
    """A damaged plugin must stop cleanly, never loop or raise."""

    def test_a_group_claiming_zero_size_terminates(self):
        """A zero-size GRUP would otherwise spin forever."""
        raw = plugin(b'GRUP' + struct.pack('<I', 0) + b'STAT'
                     + struct.pack('<3I', 0, 0, 0)[:12])
        assert list(R.records(raw)) == []

    def test_a_group_overrunning_the_file_terminates(self):
        """A GRUP larger than the file must not read past the end."""
        raw = plugin(b'GRUP' + struct.pack('<I', 1 << 20) + b'STAT'
                     + struct.pack('<3I', 0, 0, 0)[:12])
        assert list(R.records(raw)) == []

    def test_trailing_garbage_stops_the_walk(self):
        """Records before the garbage are still returned."""
        raw = plugin(grup(b'STAT', R.GRP_TOP, rec(b'STAT', b''))) + b'\x00\x01'
        assert [r.sig for r in R.records(raw)] == [b'STAT']

    def test_a_file_shorter_than_a_header_is_empty(self):
        """A stub file yields nothing and reports its own length."""
        assert list(R.records(b'TES4')) == []
        assert R.header_end(b'TES4') == 4
