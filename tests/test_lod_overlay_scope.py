"""An overlay is attached to a worldspace only if it puts records THERE.

`create_lod` picks a worldspace's overlays from the master chain: every selected
plugin that depends on the worldspace's owner. That gate answers what a plugin is
ALLOWED to touch, not what it DOES touch, and the two diverge badly. On the
12-plugin selection all 9 of Oblivion.esm's dependents were stacked onto all 18 of
its worldspaces — 162 overlay attachments, each one a full re-parse of the file in
both the object and terrain generators, measured at 114 s of which 4 s was useful.

`touched_worldspace_fids` closes that gap by reporting the worldspaces a plugin
actually has WRLD/CELL/LAND/REFR records under.

The subtle half is what it must NOT do. A raw FormID means nothing across
plugins: the index byte is an offset into each file's OWN master list, so
Morrowind_ob.esm's 02xxxxxx and Tamriel.esp's 02xxxxxx are both "self" and name
completely unrelated records. The two really do collide on 4 CELL FormIDs, and
resolving one plugin's cells against another's table turns that coincidence into
183 phantom overrides — Morrowind interior clutter dragged into Cyrodiil's
distant terrain. Scope is therefore judged per file, from its own records only.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asset_convert.lod.sibling_lod import touched_worldspace_fids
from asset_convert.lod.esm_scan import formid_remap_table, plugin_masters


def _rec(sig: bytes, fid: int, body: bytes = b'') -> bytes:
    return sig + struct.pack('<IIIII', len(body), 0, fid, 0, 0) + body


def _grup(label: int, gtype: int, payload: bytes) -> bytes:
    return (b'GRUP' + struct.pack('<I', 24 + len(payload))
            + struct.pack('<I', label) + struct.pack('<III', gtype, 0, 0)
            + payload)


def _sub(sig: bytes, payload: bytes) -> bytes:
    return sig + struct.pack('<H', len(payload)) + payload


def _plugin(tmp_path: Path, name: str, payload: bytes,
            masters=('Skyrim.esm', 'Oblivion.esm')) -> Path:
    """A minimal file: TES4 header (with a MAST list) followed by `payload`.

    The master list is not decoration — FormIDs are resolved through it, so a
    file declaring none would own every id it mentions and `0100003C` would
    stop meaning Oblivion.esm's Tamriel.
    """
    hdr = b''.join(_sub(b'MAST', m.encode() + b'\0') + _sub(b'DATA', bytes(8))
                   for m in masters)
    p = tmp_path / name
    p.write_bytes(_rec(b'TES4', 0, hdr) + payload)
    return p


def _norm(fid: int, masters=('Skyrim.esm', 'Oblivion.esm')) -> int:
    """The load-order-wide id these tests' MASTER-owned raw ids normalise to."""
    from asset_convert.lod.esm_scan import global_file_index
    top = fid >> 24
    owner = masters[top] if top < len(masters) else None
    assert owner is not None, 'use _self() for ids the plugin owns'
    return global_file_index(owner.lower()) << 24 | (fid & 0x00FFFFFF)


def _self(esm: Path, fid: int) -> int:
    """Same, for an id whose index byte is past the master list (self-owned)."""
    from asset_convert.lod.esm_scan import global_file_index
    return global_file_index(esm.name.lower()) << 24 | (fid & 0x00FFFFFF)


def test_records_under_a_worldspace_grup_are_detected(tmp_path):
    """A REFR inside a type-1 GRUP counts, even with no WRLD record present.

    This is the override case: a plugin edits a master's worldspace through the
    master's GRUPs and ships no WRLD of its own.
    """
    esm = _plugin(tmp_path, 'ov.esp',
                  _grup(0x0100003C, 1,
                        _grup(0x02000001, 6, _rec(b'REFR', 0x02000002))))
    assert touched_worldspace_fids(esm) == {_norm(0x0100003C)}


def test_own_wrld_record_counts_even_when_empty(tmp_path):
    """Defining a worldspace counts, so a not-yet-populated one is not dropped."""
    esm = _plugin(tmp_path, 'own.esm', _rec(b'WRLD', 0x02380000))
    # 02 is past the 2-entry master list, so it is this file itself.
    assert touched_worldspace_fids(esm) == {_self(esm, 0x02380000)}


def test_unrelated_worldspaces_are_not_claimed(tmp_path):
    """A plugin carrying only its own worlds must not claim the master's.

    Morrowind_ob.esm depends on Oblivion.esm and so passes the master-chain gate
    for all 18 of its worldspaces, while placing nothing in any of them.
    """
    esm = _plugin(tmp_path, 'mw.esm',
                  _rec(b'WRLD', 0x02380000)
                  + _grup(0x02380000, 1,
                          _grup(0x02380001, 6, _rec(b'REFR', 0x02380002))))
    touched = touched_worldspace_fids(esm)
    assert touched == {_self(esm, 0x02380000)}
    assert _norm(0x0100003C) not in touched


def test_interior_cells_claim_no_worldspace(tmp_path):
    """Interior CELLs sit outside any type-1 GRUP and belong to no worldspace.

    The 4 colliding FormIDs behind the 183 phantom refs were interiors.
    """
    esm = _plugin(tmp_path, 'int.esm',
                  _grup(0, 2, _grup(0x02006037, 6, _rec(b'REFR', 0x0201CE5D))))
    assert touched_worldspace_fids(esm) == set()


def test_scope_is_per_file_not_shared(tmp_path):
    """Two plugins sharing a raw CELL FormID must not inherit each other's scope.

    Both files use index byte 02, which is "self" in each — the same number
    naming two unrelated records. Judging them jointly would put the interior
    plugin into the exterior plugin's worldspace.

    Normalisation is what makes this hold structurally rather than by luck:
    each file's 02 resolves to a DIFFERENT global byte, so the two ids are no
    longer equal even as plain integers.
    """
    shared_cell = 0x02006037
    exterior = _plugin(
        tmp_path, 'ext.esp',
        _grup(0x0100003C, 1,
              _grup(shared_cell, 6, _rec(b'REFR', 0x02000010))))
    interior = _plugin(
        tmp_path, 'int.esp',
        _grup(0, 2, _grup(shared_cell, 6, _rec(b'REFR', 0x02000020))))

    assert touched_worldspace_fids(exterior) == {_norm(0x0100003C)}
    # The collision must NOT pull the interior plugin into TES4Tamriel.
    assert touched_worldspace_fids(interior) == set()


# ---------------------------------------------------------------------------
# The normalisation itself
# ---------------------------------------------------------------------------

def _remap(esm: Path, fid: int) -> int:
    t = formid_remap_table(esm)
    return t[fid >> 24] | (fid & 0x00FFFFFF)


def test_same_index_byte_in_two_files_resolves_to_different_ids(tmp_path):
    """The core defect: 02 means a different file in each plugin.

    Morrowind_ob.esm and Tamriel.esp both declare [Skyrim, Oblivion] and are
    therefore both 02 = self. Their 4 shared CELL FormIDs are numeric
    coincidence, and merging on the raw value read them as overrides — 183
    Morrowind interior objects placed into Cyrodiil's distant terrain.
    """
    a = _plugin(tmp_path, 'Morrowind_ob.esm', b'')
    b = _plugin(tmp_path, 'Tamriel.esp', b'')
    shared = 0x02006037
    assert _remap(a, shared) != _remap(b, shared)
    # ...while the low 24 bits, the part that is genuinely the record, survive.
    assert _remap(a, shared) & 0x00FFFFFF == shared & 0x00FFFFFF


def test_the_same_master_record_resolves_identically_from_any_plugin(tmp_path):
    """A REAL override must still merge: both files' 01 is Oblivion.esm."""
    a = _plugin(tmp_path, 'ElsweyrAnequina.esp', b'')
    b = _plugin(tmp_path, 'TWMP_ValenwoodImproved.esp', b'',
                masters=('Skyrim.esm', 'Oblivion.esm', 'Tamriel.esp'))
    assert _remap(a, 0x01075902) == _remap(b, 0x01075902)


def test_a_master_at_different_slots_still_resolves_to_one_id(tmp_path):
    """The slot-shift case that makes raw comparison unsalvageable.

    ElsweyrAnequina.esp is its own 02, but in TWMP_Valenwood_Elsweyr.esp slot
    02 is Tamriel.esp and ANQ sits at 03. The same ANQ record is therefore
    written 02xxxxxx in one file and 03xxxxxx in the other; only resolving the
    index byte through each file's own master list unifies them.
    """
    anq = _plugin(tmp_path, 'ElsweyrAnequina.esp', b'')
    ve = _plugin(tmp_path, 'TWMP_Valenwood_Elsweyr.esp', b'',
                 masters=('Skyrim.esm', 'Oblivion.esm', 'Tamriel.esp',
                          'ElsweyrAnequina.esp'))
    assert plugin_masters(ve)[3] == 'elsweyranequina.esp'
    # ANQ's own 02xxxxxx == the child's 03xxxxxx, and neither equals the
    # child's 02xxxxxx (which is Tamriel.esp).
    assert _remap(anq, 0x02014FE0) == _remap(ve, 0x03014FE0)
    assert _remap(anq, 0x02014FE0) != _remap(ve, 0x02014FE0)



def test_a_supplier_that_places_nothing_still_supplies_assets(tmp_path):
    """Overlay scoping must not scope ASSETS.

    The Morroblivion compatibility patch defines 3,215 base records and no
    references, so it is correctly dropped from the overlays -- but its
    textures still have to resolve, or LODGen reports them missing.

    Here Patch.esp touches nothing and Places.esp touches W1.
    See: docs/commentary/asset_convert_terrain.md#lod-suppliers-vs-contributors
    """
    from tools.release.create_lod import _plan_jobs

    owner = 'Owner.esm'
    plugins = [owner, 'Patch.esp', 'Places.esp']
    (tmp_path / owner).mkdir()
    (tmp_path / owner / owner).write_bytes(b'x')

    def _out(root, name, export_root=None):
        """Every plugin's output root, flat under tmp_path."""
        return tmp_path / name

    for n in plugins:
        (tmp_path / n).mkdir(exist_ok=True)
        (tmp_path / n / n).write_bytes(b'x')

    jobs = _plan_jobs(
        ['W1'], {'W1': owner}, plugins,
        {owner: {7}, 'Patch.esp': set(), 'Places.esp': {7}},
        tmp_path, tmp_path, _out,
        lambda n, root, order: [owner],
        lambda esm, edid: 7)

    assert len(jobs) == 1
    _edid, _owner, _esm, _ov, contributors, suppliers = jobs[0]
    assert 'Patch.esp' not in contributors, 'it places nothing: not overlaid'
    assert 'Patch.esp' in suppliers, 'but its assets must still resolve'
    assert 'Places.esp' in contributors and 'Places.esp' in suppliers



def test_lodgen_input_drops_only_the_banned_model(tmp_path):
    """The retry strips a faulting model by EditorID and keeps everything else.

    A NullReferenceException kills the whole LODGen run, so the bake is retried
    without the model that threw. The EditorID sits at field 9 of a reference
    row; header lines carry no tab and must survive untouched.
    See: docs/commentary/asset_convert_terrain.md#lodgen-nullreference-retry
    """
    from asset_convert.lod.lod_gen import _drop_lodgen_refs

    def _row(edid):
        """One reference row whose base EditorID is `edid`."""
        return '\t'.join(['02011A01', '00000C00'] + ['0.0'] * 7
                         + [edid, '00008000', '', 'm.nif', '', '', ''])

    src = tmp_path / 'in.txt'
    src.write_text('\n'.join([
        'GameMode=TES5', 'Worldspace=W1',
        _row('GoodOne'), _row('Waterfall_01'), _row('GoodTwo'),
        _row('Waterfall_01'),
    ]) + '\n', encoding='utf-8')

    assert _drop_lodgen_refs(src, {'Waterfall_01'}) is True
    out = src.read_text(encoding='utf-8').splitlines()
    assert out[:2] == ['GameMode=TES5', 'Worldspace=W1'], 'headers survive'
    assert len(out) == 4, 'both Waterfall rows dropped, both Good rows kept'
    assert not any('Waterfall_01' in ln for ln in out)
    assert sum(1 for ln in out if 'GoodOne' in ln) == 1

    assert _drop_lodgen_refs(src, {'Absent'}) is False, 'no match: no rewrite'


def test_animated_ninode_roots_are_not_accepted_by_lodgen():
    """Subclassing NiNode is not enough — LODGen throws on these roots.

    `NiBSAnimationNode` IS a NiNode subclass, so the isinstance-derived set
    accepted it and LODGen died with NullReferenceException on the four
    Tamriel Data models that carry one.
    See: docs/commentary/asset_convert_terrain.md#lodgen-rejects-animated-roots
    """
    from asset_convert.lod.lod_gen import (_LODGEN_BAD_ROOTS,
                                           _ninode_root_names)

    accepted = _ninode_root_names()
    assert 'NiBSAnimationNode' not in accepted
    assert 'NiSwitchNode' not in accepted
    assert not (accepted & _LODGEN_BAD_ROOTS), 'the two sets are disjoint'
    assert {'NiNode', 'BSFadeNode'} <= accepted, 'ordinary roots still bake'
