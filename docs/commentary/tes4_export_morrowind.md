# Morrowind (TES3) export

**Code:** `tes4_export/tes3_reader.py`, `tes4_export/export_morrowind.py`,
`tes4_export/morrowind_ids.py`, `tes4_export/morrowind_world.py`,
`tes4_export/morrowind_cell.py`, `tes4_export/morrowind_land.py`,
`tes4_export/record_types/morrowind.py`

Morrowind shares no container structure with TES4, so it gets a parallel reader
rather than the header-size probe FO3/FNV needed. The exporter's contract is
unchanged: emit the same KEY=VALUE vocabulary `tes5_import` already consumes, so
no new record converters are required.

Format authority is the OpenMW source at `references/openmw/components/esm3/`.

## <a id="the-tes3-container"></a>The TES3 container

| | TES4 | TES3 |
|---|---|---|
| Record header | 20 bytes (24 for FO3/FNV) | **16** — type, dataSize, unused, flags |
| Subrecord header | 6 bytes, u16 size | **8 bytes, u32 size** |
| Grouping | nested GRUP tree | **none** — a flat record stream |
| Identity | 32-bit FormID | **case-insensitive string** in NAME |
| Deletion | header flag | **a DELE subrecord** |

`esmreader.cpp:332-393` is the spec. Walking `Morrowind.esm` with a 16-byte
stride reaches exact EOF at 48,295 records: INFO 23693, STAT 2788, NPC_ 2675,
CELL 2538, DIAL 2358, GMST 1449, LAND 1390, PGRD 1194.

Strings are cp1252 and NUL-*padded*, not NUL-terminated — decoding as UTF-8
destroys every accented character in the German and French releases.

## <a id="coordinates-and-cell-splitting"></a>Coordinates and cell splitting

**World positions are carried across unchanged.** Morroblivion did not scale
them, which is measurable: the `hlaalu_loaddoor` references span
X -25737..57000 / Y -65313..-9723 in *both* Morrowind.esm and Morroblivion, and
Tel Mora's references sit at X~107k / Y~118k in both.

Only the grid changes, and only because the cell size halved — 8192 units in
Morrowind against 4096 in Oblivion (`openmw/components/misc/constants.hpp:24`).
So one Morrowind cell covers a 2x2 block of Oblivion cells:

    grid = floor(pos / 4096)

Verified against Morroblivion: **156,181 of 156,316** placed references satisfy
it. The 135 exceptions are all cell (0,0), the persistent-reference holding
cell, which is expected rather than a violation.

The quadrant suffix Morroblivion appends is `(x mod 2) + 2*(y mod 2)`, giving
`00`/`01`/`02`/`03` south-west first — measured with exactly 100 cells in each
bucket and no exceptions. Tel Mora at Morrowind grid (13,14) becomes Oblivion
(26,28) `TelSMora00`, matching the shipped plugin.


## <a id="the-synthetic-worldspace"></a>The synthetic worldspace

Morrowind has **no WRLD record at all** -- there is one implicit exterior and a
cell is located purely by its grid X/Y. TES5 requires every exterior cell to
name a parent worldspace, so one has to be minted.

Both conversion paths land in `WrldMorrowind`, and which of them owns the
record is the only difference between them:

| Morroblivion converted | worldspace FormID | WRLD written |
|---|---|---|
| yes | `01380000`, borrowed from its export | none |
| no | derived from the EditorID | one |

Defining a second WRLD under the same EditorID when Morroblivion already ships
one would split the map in two rather than join it, which is the entire point
of the Morroblivion path -- so `worldspace_record` returns nothing there.

The borrow needs `IdIndex.lookup_editor_id`, not `lookup`: Morroblivion
authored `WrldMorrowind` itself, so it is a plain name and must NOT be run
through the Morrowind EditorID escape (which would ask for `0WrldMorrowind`).
`WRLD` is in `BASE_TYPES` purely so the index carries it.

### The WRLD must name a climate that exists

`convert_WRLD` falls back to Oblivion's `DefaultClimate` (`0x0000015F`) for a
worldspace with no authored CNAM, because 57 of 84 TES4 worldspaces author
none. A standalone Morrowind conversion contains no Oblivion records at all,
so that fallback dangles -- caught by `tools/validate/dangling_ref_check.py`
as the only dangling reference in the whole 45 MB output.

The synthetic WRLD therefore authors `CNAM.Climate=00000812`, SkyrimClimate,
which is the climate vanilla Tamriel itself uses and is always present.

### NAM0/NAM9 must span the grid — an empty rectangle crashes before the menu

The synthetic WRLD shipped with `NAM0`/`NAM9` all zeros, because the exporter
never wrote the four keys `convert_WRLD` reads (`NAM0.MinX`, `NAM0.MinY`,
`NAM9.MaxX`, `NAM9.MaxY`) and `get_float` defaults them to 0.0. The result is
a worldspace whose declared object bounds are a zero-area rectangle at the
origin, while its cells span x -36..47, y 10..35.

**The game crashed before reaching the main menu.** Nothing structural was
wrong: `plugin_load_audit`, `dangling_ref_check`, `float_sanity_check` (1.84M
floats) and `refr_rotation_check` (305,858 refs) were all CLEAN, and no crash
log was written — the failure is inside plugin parsing, before CrashLogger can
catch it. This is the "a CLEAN audit is not an alibi" case: a VALUE the engine
chokes on, not a STRUCTURE it rejects.

The engine builds the worldspace extents and the object-LOD quadtree from that
rectangle at load time, so a degenerate rectangle containing 305,858
references subdivides against bounds nothing falls inside.

The fix computes the bounds from the exterior cells actually claimed —
`MorrowindContext.world_bounds()` — which is why `worldspace_record` is emitted
AFTER the cell loop rather than before it. Measured for Morrowind.esm:
`NAM0 = (-147456, -155648)`, `NAM9 = (196608, 229376)`, against Morroblivion's
own `(-290816, -180224)`..`(229376, 249856)` for the same worldspace.

A side effect confirms the field is load-bearing: with real bounds the
world-map cloud bank generator runs and the WRLD gains a `MODL`, which it
skips entirely when `NAM0.MinX` is absent.

### The parent keys are FormIDs, and the importer reads only these

The import stage binds children to parents through `get_formid`, so the
export has to write these exact keys:

| Record | Keys |
|---|---|
| exterior CELL | `ParentWRLD` |
| LAND | `ParentWRLD` **and** `ParentCELL` |
| exterior REFR | `ParentCELL` |

Anything else is silently ignored -- there is no error and no warning. An
early version emitted `ParentWorldspace=WrldMorrowind` (a name, not an id) on
cells and `CellX=`/`CellY=` on LAND; `import_main.py` reads neither, so every
exterior cell would have imported as an INTERIOR and every LAND would have
been orphaned.

### All four quadrants are always emitted

A Morrowind cell splits into four Oblivion-sized cells, and the terrain splits
with it whether or not anything is placed in a given quarter. Emitting only
the quadrants that held a reference stranded **1,060 of Morrowind.esm's 5,560
LAND quadrants** (19%) -- terrain naming a cell that was never written.

Emitting all four raises the exterior cell count from 4,500 to 6,750 and
leaves 0 orphaned LAND records. A reference sitting outside its own cell's
four quadrants -- which Morrowind tolerates -- still adds the grid square it
actually falls in, so no reference is lost either.

## <a id="morroblivion-editorid-escape"></a>The Morroblivion EditorID escape

ESPConverter allocated FormIDs sequentially as it walked its input, so **they
are not reproducible** and must never be chased. Its EditorIDs, however, are a
deterministic escape: `0` + the Morrowind ID with each non-alphanumeric
character replaced by a letter.

| Char | `_` | space | `,` | `'` | `:` | `-` | `.` |
|---|---|---|---|---|---|---|---|
| Code | `U` | `S` | `V` | `A` | `X` | `D` | `P` |

`ex_redoran_hut_01` becomes `0exUredoranUhutU01`;
`Sadrith Mora, Volmyni Dral's House` becomes
`0SadrithSMoraVSVolmyniSDralAsSHouse`.

Measured **96.2% exact agreement** (8,662/9,002) with the shipped plugin across
13 base types and all three masters. The 340 differences are objects
Morroblivion authored itself (`NOSIT`, `Static`, `PNIF` variants), not encoding
failures.

The escape is used in ONE direction only. Decoding back is ambiguous, because
`A`/`S`/`U`/`V`/`X` are themselves legal ID characters — build the index by
encoding Morrowind IDs forward, never by parsing Morroblivion's.

Indexing Morroblivion's 421 MB dump costs 0.1s because only `EditorID=` and
`FormID=` lines are read. It resolves **89.3%** of vanilla Morrowind base
records (9,366 of 10,486); most of the remainder are engine markers, which are
named rather than converted and handed to the existing
`skyrim_overrides.TES4_MARKER_FORMID_TO_SKYRIM` table.

## <a id="cell-references"></a>CELL references

Morrowind has no REFR record: a cell's references follow its header fields as
repeating runs that each begin with `FRMR`. `NAME` and `DATA` appear in **both**
halves, so the split must be positional — scanning for subrecord names reads a
reference's ID as the cell's own. `cellref.cpp:70-160` is the vocabulary.

`NAM0` inside the reference stream is a "temp refs" section marker, not a field.

## <a id="land-terrain"></a>LAND terrain

A Morrowind LAND is 65x65 vertices over 8192 units; an Oblivion LAND is 33x33
over 4096 — **identical 128-unit vertex spacing**. One Morrowind cell therefore
splits into four Oblivion cells by taking 33x33 sub-grids sharing an edge row
and column, with no resampling and no interpolation.

Both games delta-encode heights identically (a running offset per row, then per
column, times eight), so a quadrant re-encodes straight back into TES4 form.
Morrowind's deltas are already whole bytes, so the round trip is **exact —
measured at zero height error** over 22 LAND records times 4 quadrants.

Two decoding steps are easy to miss:

- `VTEX` ships swizzled as a 4x4 grid of 4x4 blocks and must be de-transposed
  (`transposeTextureData`, `loadland.cpp:31-39`).
- Every `VTEX` entry is an **LTEX index plus one**; zero means "no texture, use
  the default" (`Storage::getTextureName`: *"NB: All vtex ids are +1 compared to
  the ltex ids"*).

Of 1,390 LAND records, 1,292 carry the full VNML/VHGT/VTEX payload.

### Terrain textures: the crash on entering a cell

The first build reached the main menu and then crashed loading into
`WrldMorrowind`. Every structural validator was CLEAN — `plugin_load_audit`,
`dangling_ref_check`, `float_sanity_check` (1.84M floats),
`refr_rotation_check` (305,858 refs), `land_record_check` (LAND first in group,
0 violations) — and the cell's 37 meshes were all present and readable. Two
VALUE defects, both in terrain:

**1. No texture layers at all.** `morrowind_land.py` had `decode_textures`,
`ltex_index` and `quadrant_textures` fully implemented, but
`export_morrowind.py` never called them: all 5,168 LAND records shipped with
VHGT and VNML and nothing else. Morroblivion averages ~838 layer entries per
LAND. Terrain with no base layer gives the landscape shader nothing to draw.

Each TES4 quadrant gets one BASE layer from the dominant index over its 4x4
sub-patch. Measured: 5,006 of 5,168 LANDs carry layers (4,965 with all four
quadrants); the other 162 name only the default texture in the source and
correctly carry none.

### <a id="terrain-texture-blending"></a>One base layer per quadrant is not enough

The first fix stopped at that BASE layer, on the reasoning that Morrowind has
no blend weights and so "there is no alpha layer to recover". **That reasoning
was wrong, and it threw away most of the terrain.** Morrowind has no *weight*
per patch, but it fully authors *which patch uses which texture* — and the
spatial signal is exactly what ATXT/VTXT encodes. Keeping only the dominant
index per quadrant discards the rest.

Measured over `Morrowind.esm`'s 1,292 LANDs with VTEX (20,672 layer quadrants):

| distinct textures in a 4x4 layer quadrant | quadrants |
|---|---|
| 1 | 3,456 (16.7%) |
| 2 | 8,341 (40.3%) |
| 3 | 5,935 (28.7%) |
| 4 | 2,424 (11.7%) |
| 5+ | 516 (2.5%) |

**83.3% of layer quadrants lost texture data**, and the dominant texture covered
only **67.1%** of a quadrant's area on average. Of TES4 cells, 88.1% use two or
more textures. The visible symptom is a cell painted in one flat texture.

Every non-dominant texture in a quadrant now becomes an ALPHA layer. The
quadrant's VTXT opacity grid is 17x17 vertices over the same 4x4 patches
(`wbVTXTPosition`: `pos = row*17 + col`, range 0..288), so one patch spans four
vertex cells and each vertex is shared by the one to four patches meeting at it.
A vertex's opacity is the share of those patches using the texture — 1.0 inside
a patch, a partial value on a boundary. That ramp is what vanilla writes:
sampling 300 Skyrim.esm LANDs, **62.6% of opacity values are strictly between 0
and 1**, only 30.5% are fully opaque, and quadrants carry 1–6 alpha layers
(mode 5). Morrowind's worst quadrant holds 8 distinct textures, so the
importer's six-alpha cap (`build_land_layers`, which keeps the highest-coverage
layers) binds on 4 quadrants of 20,672.

**2. `DATA.Flags` was 3, which is not a value vanilla ever writes.**
Per xEdit (`wbDefinitionsTES5.pas`): `0x001` normals/height map, `0x002`
vertex colours, `0x004` layers, `0x008` unknown4, `0x010` auto-calc normals.
The old value claimed vertex colours that were never written and omitted
layers. Census of vanilla Skyrim's 15,564 LAND records: 31 (5,887), 25
(5,094), 29 (4,207), 28 (149) — **`3` appears zero times, and every value has
`0x008` set**. We now write **29** (`0x1D`), the vanilla value that carries
everything we emit and omits only the colours bit.

### LTEX ICON is relative to Textures\\, not Textures\\Landscape\\

`convert_LTEX` unconditionally prepended `landscape\` because an Oblivion LTEX
ICON is a bare filename relative to `Textures\Landscape\`. Morrowind stores a
bare filename too, but ships the file **flat** at `textures\tx_sand_01.dds`,
so the prefix invented a folder that does not exist: all 107 terrain TXST
records pointed at a missing file.

The export now emits the full `textures\` path and `_landscape_icon` only
prepends the folder for a path that is not already rooted. Oblivion's output
is byte-identical. Measured: TXST diffuse files missing on disk went from
**107 of 107 to 2 of 107**, and those two (`Tx_MA_sandstone02`,
`tx_lavacrust00`) are in no Morrowind BSA at all and are referenced by zero
terrain layers — dead LTEX records Bethesda shipped without assets.

## <a id="nif-4002"></a>Morrowind NIFs are version 4.0.0.2

pyffi does **not** read them out of the box — measured **0 of 60** vanilla
meshes on a first attempt. The version is `0x04000002` and block types are
inline length-prefixed strings per block rather than a header type table.

The first confirmed defect is that `NiGeometryData`'s `has_*` booleans are one
byte at 4.0.0.2 where pyffi reads four, which desynchronises the stream. Fixes
belong in `_install_morrowind_layouts`, beside the existing
`_install_early_oblivion_layouts` that solves the same class of problem for the
10.x meshes in Oblivion's BSAs.

## <a id="what-converts"></a>What the first pass converts

Measured on `Morrowind.esm` (48,295 source records, ~7s):

| | with Morroblivion | standalone |
|---|---|---|
| Records written | 317,656 | 324,628 |
| Cells | 5,634 | 5,634 |
| References | 305,858 | 305,858 |
| Base records | 1,296 | 7,968 |

The base-record difference is the whole point: with Morroblivion present, 6,672
objects are referenced rather than duplicated.

10,258 references (3.2%) are deliberately dropped — their base object is an
NPC, creature or levelled list, none of which this pass converts. A reference
whose base record is missing crashes the engine, so `resolve` returns `''` for
an unconverted base and the reference is skipped and counted rather than
written. Verified: 305,858 references with **zero** dangling base or parent-cell
ids in the standalone output, which is the weaker of the two paths.

Every ICON is rewritten `.tga` to `.dds`: Morrowind records name icons `.tga`
but its archives ship `.dds` and the engine substitutes at load. Without the
rename all 2,908 icon references point at files that do not exist. Mesh paths
need no such fix — 7,693 of 7,699 resolve, the six that do not being dangling
in vanilla Morrowind itself.

`TR_Mainland.esm` (four masters, 108,448 records) converts to 1,259,102 records
in 26s with 98.2% of references kept, but ONLY because its masters are read
first: a Morrowind plugin names its masters' objects by the same plain string it
uses for its own, so without them 32% of its references would be dropped.

## <a id="tes3-bsa"></a>The TES3 BSA

A different format from every later BSA: magic `0x00000100` (not `BSA\0`), a
flat path list with no folder records, and no compression at all. Parsed from
`Morrowind.bsa`: 11,090 files — 5,798 `.nif`, 5,187 `.dds`, 97 `.kf`.

Vanilla textures are **already DDS**, so TGA/BMP decoding is a loose-mod concern
and not on the critical path.
