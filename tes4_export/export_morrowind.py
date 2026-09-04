"""
Morrowind export: string IDs to FormIDs, and cells to cells plus references.

Everything downstream of the export text assumes a 32-bit FormID, so the
identity Morrowind lacks has to be minted here rather than at import. An ID
resolves in three tiers: an already-converted plugin (Morroblivion first, so a
converted mod shares its objects instead of duplicating them), then an engine
marker, then a FormID derived from the authored string itself.

Morroblivion is optional. With no index the first tier is simply empty and the
plugin converts its own base records, which is the standalone path.

See: docs/commentary/tes4_export_morrowind.md#morroblivion-editorid-escape
"""

import hashlib
import os
import struct
import time
from collections import Counter

from output_layout import record_dir

from .morrowind_cell import parse_cell
from .morrowind_ids import IdIndex, load_index, marker_formid
from .morrowind_land import (TES4_TEX_SIZE, decode_heights, decode_textures,
                             encode_heights, layer_lines, ltex_index,
                             quadrant_normals, quadrant_textures)
from .morrowind_world import (TES4_CELL_SIZE, WORLDSPACE_EDID, cell_editor_id,
                              cell_grid, tes3_cell_quadrants)
from .record_types.morrowind import MORROWIND_EXPORTERS
from .tes3_reader import get_subrecord, read_file, read_masters

#: Load-order byte for records this plugin owns.
_OWN_INDEX = 0x01

#: Derived ids live above Morroblivion's blocks so the two never collide.
_DERIVED_BASE = 0x00200000
_DERIVED_SPAN = 0x00D00000

#: Rehash attempts before a derived id is declared impossible.
_MAX_REHASH = 64

#: SkyrimClimate (0x812), the climate vanilla Tamriel itself uses.
_SKYRIM_CLIMATE = '00000812'

#: LAND DATA 0x1D (4,207 vanilla LANDs): normals, layers, unknown4, auto-calc.
_LAND_FLAGS = 29

#: The same without the layers bit, when the source names no texture at all.
_LAND_FLAGS_NO_TEX = 25


class MorrowindContext:
    """Resolves Morrowind string IDs to FormIDs for one conversion.

    `index` holds every record an already-converted plugin can supply; it is
    empty when nothing has been converted yet, which is what makes the
    Morroblivion tier optional rather than required.
    """

    def __init__(self, index: IdIndex = None):
        """Start from whatever an already-converted plugin can supply."""
        self.index = index if index is not None else IdIndex()
        self.derived = {}
        self.unresolved = Counter()
        self.own_ids = set()
        self._taken = set(self.index.form_ids())
        self._exterior_cells = set()
        self._ref_counts = Counter()
        self.ltex_by_index = {}

    def register_ltex(self, index: int, form_id: str) -> None:
        """Note the FormID a LAND's VTEX index resolves to."""
        if form_id:
            self.ltex_by_index[index] = form_id

    def land_texture(self, vtex_value: int) -> str:
        """The LTEX FormID a VTEX entry names, or '' for the default.

        See: docs/commentary/tes4_export_morrowind.md#land-terrain
        """
        index = ltex_index(vtex_value)
        if index is None:
            return ''
        return self.ltex_by_index.get(index, '')

    def worldspace_id(self) -> str:
        """The FormID every converted exterior cell hangs under.

        See: docs/commentary/tes4_export_morrowind.md#the-synthetic-worldspace
        """
        return (self.index.lookup_editor_id(WORLDSPACE_EDID)
                or self.derive('wrld:' + WORLDSPACE_EDID))

    def owns_worldspace(self) -> bool:
        """Whether this plugin has to define the worldspace itself."""
        return self.index.lookup_editor_id(WORLDSPACE_EDID) is None

    def exterior_cell_id(self, grid: tuple) -> str:
        """The FormID for an exterior cell, keyed only on its grid."""
        return self.derive('cell:%d:%d' % grid)

    def world_bounds(self) -> tuple:
        """(MinX, MinY, MaxX, MaxY) in world units over every claimed cell.

        A worldspace whose bounds are an empty rectangle at the origin makes
        the engine build a degenerate object-LOD quadtree over every
        reference in it, and the load never completes.
        See: docs/commentary/tes4_export_morrowind.md#the-synthetic-worldspace
        """
        if not self._exterior_cells:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [g[0] for g in self._exterior_cells]
        ys = [g[1] for g in self._exterior_cells]
        return (float(min(xs) * TES4_CELL_SIZE),
                float(min(ys) * TES4_CELL_SIZE),
                float((max(xs) + 1) * TES4_CELL_SIZE),
                float((max(ys) + 1) * TES4_CELL_SIZE))

    def claim_exterior(self, grid: tuple) -> bool:
        """Claim a grid square; True when another cell already emitted it.

        See: docs/commentary/tes4_export_morrowind.md#coordinates-and-cell-splitting
        """
        seen = grid in self._exterior_cells
        self._exterior_cells.add(grid)
        return seen

    def next_ref_id(self, parent_cell: str) -> str:
        """The FormID for the next reference placed in this cell."""
        index = self._ref_counts[parent_cell]
        self._ref_counts[parent_cell] = index + 1
        return self.derive('refr:%s:%d' % (parent_cell, index))

    def register_own(self, record_id: str) -> None:
        """Note that this plugin exports a base record for `record_id`."""
        if record_id:
            self.own_ids.add(record_id.lower())

    def resolve(self, record_id: str) -> str:
        """The FormID this ID converts to, or '' when nothing supplies one.

        Returning '' keeps references to base objects this pass does not
        convert -- NPCs, creatures, levelled lists -- out of the output. Such a
        reference would name a record that is never written, which crashes the
        engine rather than merely showing nothing.
        """
        if not record_id:
            return ''
        existing = self.index.lookup(record_id)
        if existing:
            return existing
        marker = marker_formid(record_id)
        if marker is not None:
            return '%08X' % marker
        if record_id.lower() in self.own_ids:
            return self.derive(record_id)
        return ''

    def derive(self, record_id: str) -> str:
        """A stable FormID minted from the authored string ID.

        Hashed, never counted, so allocation order is irrelevant and adding
        records never moves existing ids. A clash is resolved by rehashing
        with a salt rather than by probing, so an id depends only on its own
        key and the keys that hash before it.
        """
        key = record_id.lower()
        found = self.derived.get(key)
        if found is not None:
            return found
        for salt in range(_MAX_REHASH):
            probe = key if salt == 0 else '%s\x00%d' % (key, salt)
            digest = hashlib.md5(probe.encode('utf-8')).digest()
            offset = int.from_bytes(digest[:4], 'little') % _DERIVED_SPAN
            candidate = '%08X' % ((_OWN_INDEX << 24) | (_DERIVED_BASE + offset))
            if candidate not in self._taken:
                self._taken.add(candidate)
                self.derived[key] = candidate
                return candidate
        raise RuntimeError('no free derived FormID for %r' % record_id)


def load_context(export_root: str, master_dirs=()) -> MorrowindContext:
    """Build a context from whatever converted plugins are available.

    `master_dirs` names export directories in priority order; Morroblivion's
    belongs first when the user has it.
    """
    index = IdIndex()
    for name in master_dirs:
        path = name if os.path.isabs(name) else os.path.join(export_root, name)
        index.merge(load_index(path))
    return MorrowindContext(index)


#: Converted exports a Morrowind plugin resolves its base objects through.
BASE_EXPORTS = ('Morrowind_ob.esm', 'Morrowind.esm', 'Tribunal.esm',
                'Bloodmoon.esm')


def run_export(file_name: str, source: str, export_dir: str) -> bool:
    """Export one Morrowind plugin and report what it produced."""
    start = time.time()
    print(f'[{file_name}] Exporting (Morrowind)...')
    masters = converted_master_dirs(export_dir, file_name)
    result = export_plugin(source, export_dir, os.path.dirname(source), masters)
    total = sum(result['counts'].values())
    print(f"  Wrote {total} records to {result['output']}")
    if result['dropped']:
        print(f"  Skipped {result['dropped']} references whose base object "
              f'is not converted (NPCs, creatures and levelled lists)')
    print(f'[{file_name}] Export complete in {time.time() - start:.2f}s')
    return True


def converted_master_dirs(export_dir: str, plugin: str) -> list:
    """Already-converted exports a Morrowind plugin borrows objects from.

    Morroblivion first when present, so a converted mod shares its records
    rather than shipping a second copy of every vanilla static. The plugin
    being exported is skipped: its own earlier export is not a master.
    """
    found = []
    for name in BASE_EXPORTS:
        if name.lower() == plugin.lower():
            continue
        path = os.path.join(export_dir, name)
        if os.path.isdir(path):
            found.append(path)
    return found


def export_plugin(source_path: str, export_dir: str, data_dir: str = None,
                  master_dirs=()) -> dict:
    """Convert one Morrowind plugin into the standard export tree.

    Records land in `record_dir(export_dir, <plugin>)`, the same resolver every
    other stage uses, so nothing downstream needs to know the source was TES3.
    Masters are read first: a Morrowind plugin names its masters' objects by
    plain string, so without them every such reference would be dropped.
    """
    plugin = os.path.basename(source_path)
    data_dir = data_dir or os.path.dirname(source_path)
    ctx = load_context(export_dir, master_dirs)

    for master in read_masters(source_path):
        master_path = os.path.join(data_dir, master)
        if os.path.exists(master_path):
            register_master_records(ctx, read_file(master_path)[1])

    records = read_file(source_path)[1]
    out = convert_plugin(records, ctx)
    out_dir = str(record_dir(export_dir, plugin))
    counts = write_export(out, out_dir)
    write_header(out_dir, _master_list(master_dirs), sum(counts.values()),
                 f'Converted from {plugin}')
    return {'plugin': plugin, 'output': out_dir, 'counts': counts,
            'dropped': sum(ctx.unresolved.values())}


def _master_list(master_dirs) -> list:
    """The converted plugins whose records this one borrows.

    Skyrim.esm is NOT listed: the writer adds it to every plugin, while a
    `Master[]` line here means "a converted export to build overrides from"
    and made the importer demand an output/Skyrim.esm that cannot exist.
    Standalone Morrowind borrows nothing and declares nothing, exactly as
    Oblivion.esm's own export header does.
    """
    masters = []
    for path in master_dirs:
        name = os.path.basename(str(path).rstrip('/\\'))
        if name and name not in masters:
            masters.append(name)
    return masters


def register_master_records(ctx: MorrowindContext, records) -> int:
    """Let `ctx` resolve base objects a master supplies, and say how many.

    A Morrowind plugin names its masters' objects by the same plain string it
    uses for its own, so a mod converted without its masters loaded drops every
    reference into them -- 32% of TR_Mainland's, which depends on four.
    """
    added = 0
    for rec in records:
        if rec.type in MORROWIND_EXPORTERS and not rec.deleted and rec.record_id:
            ctx.register_own(rec.record_id)
            added += 1
    return added


def export_record(rec, ctx: MorrowindContext) -> list:
    """The KEY=VALUE lines for one Morrowind base record, or [] if unhandled."""
    exporter = MORROWIND_EXPORTERS.get(rec.type)
    if exporter is None:
        return []
    return exporter(rec)


def convert_plugin(records, ctx: MorrowindContext) -> dict:
    """Every TES4-shaped record one Morrowind plugin becomes.

    Base records are registered first so that a reference is only written once
    its base object is known to exist.
    """
    for rec in records:
        if rec.type in MORROWIND_EXPORTERS and not rec.deleted:
            ctx.register_own(rec.record_id)
    _register_land_textures(records, ctx)

    out = {sig: [] for sig in MORROWIND_EXPORTERS}
    out['CELL'] = []
    out['REFR'] = []
    out['LAND'] = []
    for rec in records:
        if rec.deleted:
            continue
        if rec.type == 'CELL':
            _collect_cell(rec, ctx, out)
        elif rec.type == 'LAND':
            out['LAND'].extend(land_records(rec, ctx))
        elif _is_convertible(rec, ctx):
            out[rec.type].append(
                (ctx.resolve(rec.record_id), export_record(rec, ctx)))
    out['WRLD'] = worldspace_record(ctx)
    return out


def _register_land_textures(records, ctx: MorrowindContext) -> None:
    """Map each LTEX's own index to its FormID, before any LAND is written.

    A LAND names its textures by index, so the whole table has to exist
    before the first terrain record is emitted.
    """
    for rec in records:
        if rec.type != 'LTEX' or rec.deleted:
            continue
        intv = get_subrecord(rec, 'INTV')
        if intv is None or len(intv.data) < 4:
            continue
        ctx.register_ltex(struct.unpack_from('<I', intv.data, 0)[0],
                          ctx.resolve(rec.record_id))


def worldspace_record(ctx: MorrowindContext) -> list:
    """The WRLD every exterior cell hangs under, when nothing else supplies it.

    Emitted AFTER the cells so NAM0/NAM9 can span the grid they actually
    cover; the engine builds the worldspace extents and the object-LOD
    quadtree from that rectangle while it parses the file.
    See: docs/commentary/tes4_export_morrowind.md#the-synthetic-worldspace
    """
    if not ctx.owns_worldspace():
        return []
    min_x, min_y, max_x, max_y = ctx.world_bounds()
    return [(ctx.worldspace_id(),
             [f'EditorID={WORLDSPACE_EDID}', 'FULL=Morrowind',
              f'CNAM.Vanilla={_SKYRIM_CLIMATE}', 'DATA.Flags=0',
              f'NAM0.MinX={min_x}', f'NAM0.MinY={min_y}',
              f'NAM9.MaxX={max_x}', f'NAM9.MaxY={max_y}'])]


def _is_convertible(rec, ctx: MorrowindContext) -> bool:
    """Whether this plugin writes a base record of its own for `rec`."""
    return (rec.type in MORROWIND_EXPORTERS
            and marker_formid(rec.record_id) is None
            and ctx.index.lookup(rec.record_id) is None)


def _collect_cell(rec, ctx: MorrowindContext, out: dict) -> None:
    """Add one CELL's cells and references to the output buckets."""
    cells, refs = cell_records(rec, ctx)
    out['CELL'].extend(cells)
    out['REFR'].extend(refs)


def format_record(signature: str, form_id: str, lines: list) -> str:
    """One record as the same delimited block the TES4 exporter writes."""
    out = ['---RECORD_BEGIN---', f'Signature={signature}',
           f'FormID={form_id}']
    edid = [line for line in lines if line.startswith('EditorID=')]
    if edid:
        out.append(edid[0])
    out.append('RecordFlags=0')
    out.extend(line for line in lines if not line.startswith('EditorID='))
    out.append('---RECORD_END---')
    return '\n'.join(out)


def write_export(out: dict, output_dir: str) -> dict:
    """Write one file per record type; return the counts written."""
    os.makedirs(output_dir, exist_ok=True)
    counts = {}
    for signature, records in sorted(out.items()):
        if not records:
            continue
        path = os.path.join(output_dir, f'{signature}.txt')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('\n\n'.join(
                format_record(signature, fid, lines)
                for fid, lines in records) + '\n')
        counts[signature] = len(records)
    return counts


def write_header(output_dir: str, masters: list, num_records: int,
                 description: str = 'Converted from Morrowind') -> None:
    """Write the _HEADER.txt the import stage reads for the master list."""
    lines = ['HEDR.Version=1.0', f'HEDR.NumRecords={num_records}',
             'HEDR.NextObjectID=2048',
             'CNAM.Author=TESConversion',
             f'SNAM.Description={description}']
    lines.extend(f'Master[{i}]={name}' for i, name in enumerate(masters))
    lines.append('Flags=1')
    with open(os.path.join(output_dir, '_HEADER.txt'), 'w',
              encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')


def land_records(rec, ctx: MorrowindContext) -> list:
    """The four Oblivion LAND records one Morrowind LAND becomes.

    Each quadrant carries the 33x33 sub-grid of the source 65x65 field, which
    needs no resampling because vertex spacing is 128 units in both games.
    """
    intv = get_subrecord(rec, 'INTV')
    if intv is None or len(intv.data) < 8:
        return []
    cell_x, cell_y = struct.unpack_from('<ii', intv.data, 0)
    vhgt = get_subrecord(rec, 'VHGT')
    if vhgt is None:
        return []
    heights = decode_heights(vhgt.data)
    vnml = get_subrecord(rec, 'VNML')
    normals = vnml.data if vnml else b''
    vtex = get_subrecord(rec, 'VTEX')
    textures = decode_textures(vtex.data) if vtex else []

    out = []
    for quad in ((0, 0), (1, 0), (0, 1), (1, 1)):
        grid = (cell_x * 2 + quad[0], cell_y * 2 + quad[1])
        form_id = ctx.derive('land:%d:%d' % grid)
        layers = _land_layers(textures, quad, ctx)
        lines = [f'DATA.Flags={_LAND_FLAGS if layers else _LAND_FLAGS_NO_TEX}',
                 'VHGT=' + encode_heights(heights, quad).hex().upper()]
        quad_normals = quadrant_normals(normals, quad)
        if quad_normals:
            lines.append('VNML=' + quad_normals.hex().upper())
        lines.extend(layers)
        lines.append(f'ParentWRLD={ctx.worldspace_id()}')
        lines.append(f'ParentCELL={ctx.exterior_cell_id(grid)}')
        out.append((form_id, lines))
    return out


def _land_layers(textures: list, quad: tuple, ctx: MorrowindContext) -> list:
    """Every texture a TES4 quadrant uses: a dominant BASE plus ALPHA layers.

    Terrain with no base layer is what crashed the game on entering a cell.
    Morrowind carries no blend weight, but it does author which patch uses
    which texture, so the non-dominant ones become alpha layers masked by the
    patches naming them rather than being discarded.
    See: docs/commentary/tes4_export_morrowind.md#terrain-texture-blending
    """
    if not textures:
        return []
    cell = quadrant_textures(textures, quad)
    lines, count = [], 0
    for sub in ((0, 0), (1, 0), (0, 1), (1, 1)):
        patch = _sub_patch(cell, sub)
        quadrant = sub[0] + 2 * sub[1]
        for rank, (value, form_id) in enumerate(_ranked_textures(patch, ctx)):
            lines.extend(layer_lines(count, quadrant, form_id, rank,
                                     patch, value))
            count += 1
    return [f'LayerCount={count}'] + lines if count else []


def _sub_patch(cell: list, sub: tuple) -> list:
    """One 4x4 TES4 layer quadrant out of a cell's 8x8 texture patch."""
    half = TES4_TEX_SIZE // 2
    x0, y0 = sub[0] * half, sub[1] * half
    return [cell[(y0 + y) * TES4_TEX_SIZE + x0 + x]
            for y in range(half) for x in range(half)]


def _ranked_textures(patch: list, ctx: MorrowindContext) -> list:
    """One quadrant's (VTEX value, LTEX FormID) pairs, widest coverage first.

    Ties break on the VTEX value so the layer order is stable across runs.
    """
    tally = Counter(v for v in patch if ctx.land_texture(v))
    return [(value, ctx.land_texture(value))
            for value, _n in sorted(tally.items(),
                                    key=lambda kv: (-kv[1], kv[0]))]


def cell_records(rec, ctx: MorrowindContext) -> tuple:
    """Split one TES3 CELL into its TES4 CELL records and their references.

    An exterior cell becomes the four Oblivion cells covering it, each holding
    the references whose position falls inside it. Interiors stay single.
    """
    cell = parse_cell(rec)
    if cell.interior:
        return _interior_cell(cell, ctx)
    return _exterior_cells(cell, ctx)


def _interior_cell(cell, ctx: MorrowindContext) -> tuple:
    """One interior cell and every reference it holds."""
    form_id = ctx.derive('cell:' + cell.name)
    lines = [f'EditorID={cell.name}', f'FULL={cell.name}', 'DATA.Flags=1']
    if cell.water_height is not None:
        lines.append(f'XCLW.WaterHeight={cell.water_height}')
    refs = _emit_refs(cell.refs, form_id, ctx)
    return [(form_id, lines)], refs


def _exterior_cells(cell, ctx: MorrowindContext) -> tuple:
    """The four Oblivion cells one Morrowind exterior cell becomes.

    All four are emitted whether or not a reference falls in them: the cell's
    terrain is split four ways regardless, and a LAND naming a cell that was
    never written is an orphan. Emitting only the quadrants that held a
    reference stranded 1,060 of Morrowind.esm's 5,560 LAND quadrants.
    A reference sitting outside its own cell's quadrants -- which Morrowind
    tolerates -- still adds the grid square it truly falls in.
    """
    buckets = {grid: [] for grid in tes3_cell_quadrants(*cell.grid)}
    for ref in cell.refs:
        if ref.deleted:
            continue
        buckets.setdefault(cell_grid(ref.pos[0], ref.pos[1]), []).append(ref)

    base = cell.name or cell.region or 'Wilderness'
    cells, refs = [], []
    for grid, held in sorted(buckets.items()):
        edid = cell_editor_id(_safe_name(base), grid[0], grid[1])
        form_id = ctx.exterior_cell_id(grid)
        lines = [f'EditorID={edid}', 'DATA.Flags=2',
                 f'XCLC.X={grid[0]}', f'XCLC.Y={grid[1]}',
                 f'ParentWRLD={ctx.worldspace_id()}']
        if cell.name:
            lines.append(f'FULL={cell.name}')
        if not ctx.claim_exterior(grid):
            cells.append((form_id, lines))
        refs.extend(_emit_refs(held, form_id, ctx))
    return cells, refs


def _emit_refs(refs, parent_cell: str, ctx: MorrowindContext) -> list:
    """Every emittable reference in one cell, as (FormID, lines) pairs.

    Keyed on the owning cell's own FormID plus the placement's index, which is
    unique because cell ids already are -- a cell NAME is not, since Morrowind
    leaves most exterior cells unnamed.
    """
    out = []
    for ref in refs:
        if ref.deleted:
            continue
        lines = _ref_lines(ref, parent_cell, ctx)
        if lines:
            out.append((ctx.next_ref_id(parent_cell), lines))
    return out


def _safe_name(name: str) -> str:
    """A cell name reduced to the alphanumerics an EditorID allows."""
    return ''.join(ch for ch in name if ch.isalnum()) or 'Wilderness'


def _ref_lines(ref, parent_cell: str, ctx: MorrowindContext):
    """One placed reference, or None when its base object cannot resolve.

    A reference whose base record is missing crashes the engine, so an
    unresolvable one is dropped and counted rather than emitted.
    """
    base = ctx.resolve(ref.record_id)
    if not base:
        ctx.unresolved[ref.record_id] += 1
        return None
    lines = [f'NAME={base}', f'ParentCELL={parent_cell}',
             f'PosX={ref.pos[0]}', f'PosY={ref.pos[1]}', f'PosZ={ref.pos[2]}',
             f'RotX={ref.rot[0]}', f'RotY={ref.rot[1]}', f'RotZ={ref.rot[2]}']
    if ref.scale != 1.0:
        lines.append(f'XSCL.Scale={ref.scale}')
    if ref.owner:
        lines.append(f'OwnerName={ref.owner}')
    if ref.lock_level:
        lines.append(f'XLOC.Level={ref.lock_level}')
    if ref.teleport and ref.dest_pos:
        lines.extend(_teleport_lines(ref))
    return lines


def _teleport_lines(ref) -> list:
    """The destination a door reference teleports to."""
    lines = [f'XTEL.PosX={ref.dest_pos[0]}',
             f'XTEL.PosY={ref.dest_pos[1]}',
             f'XTEL.PosZ={ref.dest_pos[2]}']
    if ref.dest_rot:
        lines.extend([f'XTEL.RotX={ref.dest_rot[0]}',
                      f'XTEL.RotY={ref.dest_rot[1]}',
                      f'XTEL.RotZ={ref.dest_rot[2]}'])
    if ref.dest_cell:
        lines.append(f'XTEL.DestCell={ref.dest_cell}')
    return lines
