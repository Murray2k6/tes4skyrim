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

## <a id="per-type-id-namespaces"></a>Morrowind namespaces IDs by type; FormIDs do not

A TES3 string ID is unique only *within* a record type, so one name may denote
two unrelated records. Vanilla has exactly one such name — `Sound_Boat_Creak`
is both a `SOUN` and a `SCPT` — but the flat 32-bit FormID space has no
namespaces at all, and keying derivation on the bare name gave both records
`00712579`. Two records sharing a FormID is a malformed plugin: the later one
silently replaces the earlier, so the sound went missing and the script was
loaded as a sound.

Derivation is therefore keyed on `<TES4 signature>:<id>`, matching the
`wrld:` / `cell:` / `land:` / `refr:` prefixes every other derived id already
carries. `register_own` keeps a *list* of signatures per name, and `resolve`
takes the signature its call site already knows — `SCRI` names a script,
`SNAM` a sound. An untyped cell reference passes none and gets the first
registered type, which is correct because a reference can only place a
placeable object; `SCPT` and `SOUN` are never placed.

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

That first pass dropped 10,258 references (3.2%) whose base object was an NPC,
creature or levelled list. With actors and leveled lists exported the
standalone conversion of `Morrowind.esm` now writes (measured, 8.4s):

| | count |
|---|---|
| Records | 343,016 |
| Base records | 11,848 (NPC_ 2,675, CREA 260, LVLI 227, LVLC 116, KEYM 285, AMMO 68, SOUN 430, GLOB 73, FACT 22, CLAS 77 among them) |
| Placements | 319,249 = REFR 315,343 + ACHR 3,043 + ACRE 863 |
| ...of which synthesised door markers | 3,133, one per load door |
| References dropped | **0** |
| Dangling FormIDs across NAME, ParentCELL, XTEL.Door, XOWN.Owner, XLOC.Key, Item[], Entry[], Faction[], Relation[], CNAM.Class, SNAM/ANAM sounds | **0** |

A reference whose base record is missing crashes the engine, so `resolve`
still returns `''` for an unconverted base and such a reference is skipped and
counted rather than written; nothing in Morrowind.esm reaches that path any
more. `write_export` also deletes a record file left by an earlier run for a
type the current run no longer emits (REPA/PROB/LOCK became MISC), which
otherwise imported beside their replacements under the same FormIDs.

Every ICON is rewritten `.tga` to `.dds`: Morrowind records name icons `.tga`
but its archives ship `.dds` and the engine substitutes at load. Without the
rename all 2,908 icon references point at files that do not exist. Mesh paths
need no such fix — 7,693 of 7,699 resolve, the six that do not being dangling
in vanilla Morrowind itself.

## <a id="masters"></a>Masters

**Code:** `export_morrowind.converted_master_dirs`, `load_context`,
`morrowind_ids.load_index`.

A Morrowind plugin names its masters' objects by the same plain string it uses
for its own, so a dependent plugin can only reference what its masters
supply. The rule is: **a master's object resolves only through that master's
converted export**; an object whose master is not converted is dropped and
counted, never minted. The first version registered every master record as
the plugin's own and minted a derived FormID for each, which wrote 11,854
`NAME=` lines on TR_Mainland pointing at records nothing defines -- a REFR
whose base is missing crashes the engine.

**An unconverted master REFUSES the export**, the same contract the import
stage enforces with `MissingMasterOutputError`. The master list fixes the
plugin's own load-order byte, so exporting without one does not merely drop
references -- it renumbers every record into a master's id space. Measured
before the gate existed: TR_Mainland, whose chain is four long, took byte
`0x02` because only two of its masters were converted, putting its own records
where Bloodmoon's belong. The refusal names each missing master and the command
that converts it.

The master list is the plugin's own `MAST` chain, in its order (`record_dir`,
so an imported mod's folder resolves). The own load-order byte is the length of
that list, the TES4 convention the importer's `load_master_export` re-keys
against; a masterless plugin such as Morrowind.esm writes `0x00` exactly as
Oblivion.esm does. Each
master's index is re-keyed into the borrower's list the same way: the master's
own byte (the length of ITS header's `Master[]` list) becomes its slot, and
each of its masters is translated by name; a byte naming a file the borrower
does not load is unreachable and skipped.

The index answers under the raw Morrowind ID as well as the Morroblivion
escape, because our own exports write the raw ID as `EditorID`; before that the
converted-master tier resolved 0 of Morrowind.esm's 11,742 exported records.
Cells are indexed too -- interiors under `cell:<name>`, exteriors under
`cell:<x>:<y>` from `XCLC`, terrain under `land:<parent cell>` -- so a door or
placement into a master's cell names the master's record, and a worldspace the
master already defines is not emitted twice. When the borrower's cells reach
past the master's `NAM0`/`NAM9`, the WRLD is emitted again under the master's
FormID with the union bounds, which the importer applies as an override.

**Source set** (`morrowindSource` in `conversion_config.json`, Settings ▸
Morrowind source in the GUI): `vanilla` borrows from the declared masters;
`morroblivion` puts every converted `Morrowind_ob*` export first and drops the
three vanilla ESMs from the list, so a mod shares Morroblivion's objects
instead of shipping a second copy of every static. Morroblivion's cells and
worldspace use its own EditorIDs, so in that mode doors into vanilla interiors
link only where the escaped name matches, and exteriors do not link at all.

`TR_Mainland.esm` (four masters, 108,448 records) converts in 26s with 98.2%
of references kept when all four masters are converted first.

## <a id="morroblivion-gap-patch"></a>The Morroblivion gap patch

**Code:** `tes4_export/morrowind_patch.py`.

Morroblivion resolves **89.3%** of vanilla Morrowind's base records, so in
Morroblivion mode a dependent plugin routinely places objects its master cannot
supply. Measured against an index covering 89% of Morrowind.esm, Bloodmoon
alone places **50 distinct such objects across 342 references**. Dropping them
loses authored content; minting them in the plugin's own space makes every
plugin needing the same object ship a rival copy, so two mods placing
`ex_scrapwood01` would put two of it in the world.

So each plugin exports one PATCH beside itself, `<plugin> - Morroblivion
Patch.esp`, holding exactly the objects it references, a declared master
defines, and the index cannot supply. A gap is judged on all four conditions:
referenced by this plugin, not defined by it, absent from the index, present in
a master's binary. An id absent from the master binaries too is genuinely
missing and stays dropped and counted.

**The fill id is derived from the authored Morrowind string** in the shared
`mwpatch` site, never from the plugin's own id space, so every plugin that
needs `ex_scrapwood01` names the SAME record. Two patches defining it are
override-compatible rather than duplicates, which is what makes several
Morroblivion mods loadable together. The key is the authored string, so the id
is stable across machines and builds -- the same contract `derive_formid`
states for every other generated record.

The patch is generated only in Morroblivion mode. With all masters converted
the index is complete, no gap exists, and no patch is written.

## <a id="tes4-vocabulary"></a>Every exporter speaks the TES4 KEY vocabulary

The importers read TES4's key names and nothing else: `convert_WEAP` reads
`DATA.Type`/`DATA.Weight`/`DATA.Damage`, `convert_CONT` reads `DATA.Flags` and
`Item[i].FormID`, `convert_LIGH` reads `DATA.Color.R` and so on. The first
pass invented its own names (`Weight=`, `WeaponType=`, `ContainerFlags=`,
`LightColor=`, `Item[i].Object=<string>`), so every stat on every Morrowind
item was silently discarded on import -- weapons had type 0, lights had no
color and radius 128, containers were empty. `tools/validate/import_sweep.py`
and a grep of `get_int(rec, '...')` in `tes5_import/record_types/` are the
contract; each Morrowind exporter now emits exactly those keys, with the
Morrowind enum translated to the TES4 one where they differ:

| Morrowind | TES4 key | Translation |
|---|---|---|
| WPDT type 0-13 | `DATA.Type` | short/long blade 1H -> 0, long blade 2H and spear -> 1, blunt 1H and axe 1H -> 2, blunt 2H and axe 2H -> 3, bow/crossbow -> 5, thrown -> 0; arrow/bolt become **AMMO** |
| WPDT chop/slash/thrust max | `DATA.Damage` | the largest of the three |
| WPDT enchant | `ANAM` | Morrowind stores points x10 |
| LHDT color u32 | `DATA.Color.R/G/B` | little-endian RGBA bytes |
| LHDT flags | `DATA.Flags` | identical bits; 0x10 (Fire) is masked by the importer |
| CNDT weight, FLAG | `DATA.Weight`, `DATA.Flags` | Respawn 0x02 -> TES4 0x01 |
| MCDT flags & 1 (key) | record becomes **KEYM** | 285 of 536 MISC records |
| BKDT skill | `DATA.Teaches` | the 27-skill enum mapped onto TES4's 21 (medium armor -> heavy, axe/spear -> blunt, short blade -> blade, unarmored -> light armor, enchant -> mysticism) |
| BKDT isScroll | `DATA.Flags` 0x01 | |
| ALDT autocalc | `ENIT.Flags` | TES4's bit is "NO auto-calc", so it is inverted |
| REPA / PROB / LOCK | **MISC** | Skyrim has no repair or probe items; the importer had no dispatch for these signatures, so their references dangled |

Records the importer could not dispatch (REPA, PROB, LOCK) were being written
by the exporter, registered as convertible, and REFERENCED -- every placed
lockpick named a base record the import never wrote.

## <a id="equipment-slots"></a>Equipment slots and weight class

Morrowind has no biped mask; an armor's slot is its `AODT` type and a
clothing's its `CTDT` type. Each maps onto TES4's `BMDT.BipedFlags`:

| Type | TES4 bits |
|---|---|
| Helmet | Head + Hair (0x3) |
| Cuirass, Shirt | Upper Body (0x4) |
| Greaves, Pants, Skirt | Lower Body (0x8) |
| Robe | Upper + Lower Body (0xC) |
| Boots, Shoes | Foot (0x20) |
| Gauntlet, Bracer, Glove | Hand (0x10) |
| Shield | Shield (0x2000) |
| Ring | Right Ring (0x40) |
| Amulet | Amulet (0x100) |
| Pauldron, Belt | none -- no slot exists in either later game |

Weight class is not stored either; Morrowind derives it from weight against a
per-type GMST (`iHelmWeight` 5, `iPauldronWeight` 10, `iCuirassWeight` 30,
`iGauntletWeight` 5, `iGreavesWeight` 15, `iBootsWeight` 20, `iShieldWeight`
15): light up to `fLightMaxMod` 0.6 of it, medium up to `fMedMaxMod` 0.9, else
heavy. TES4 has only the heavy bit (`BMDT.GeneralFlags` 0x80), so medium and
heavy both set it -- bonemold and orcish land in Heavy Armor, as Skyrim's own
orcish does.

### <a id="worn-models"></a>Worn models are assembled from body parts

**Code:** `tes4_export/morrowind_armor.py`,
`asset_convert/character/morrowind_armor.py`.

Morrowind dresses an actor from per-body-part `BODY` meshes: each `ARMO`/`CLOT`
carries `INDX` (part slot) + `BNAM`/`CNAM` (male/female BODY id) pairs, and the
BODY's `MODL` is the mesh. Measured on Morrowind.esm's 280 ARMO: helmets,
cuirasses, shields, gauntlets and bracers are one part each; greaves are 3-5
(groin, upper legs, knees), boots 2-4 (feet, ankles), pauldrons 1-3. Every
cuirass part is already skinned to `Bip01` bones; every other part is a RIGID
mesh authored in the frame of the attach node the engine hangs it on
(`Left Knee` under `Bip01 L Calf`, `Groin` under `Bip01 Pelvis`, ...).

The exporter resolves the parts through the BODY records of the plugin and its
masters, names a synthetic worn model per record
(`armor\morrowind\m\<escaped id>.nif`, `f\` when any female part exists) as
`Male/Female.BipedModel.MODL`, and lists the parts as
`MorrowindPart[i].Slot/.Male/.Female`. Because the biped key is present the
importer builds an ARMA exactly as for Oblivion armor. Parts are listed only
for records with a biped slot; pauldrons and belts have none in either later
game.

The mesh stage assembles the model before the ordinary conversion runs
(`assemble_armor`, called from `asset_pipeline.convert_meshes`): the rest-pose
skeleton `base_anim.nif` supplies each attach node's parent bone and offset, a
rigid part is baked into that bone's local frame and given a one-bone identity
skin -- the same shape `add_prn_skin` gives an Oblivion helmet, so the worn
path treats it as a Prn piece -- and a skinned part is re-bound to the shared
skeleton. Shields are not skinned: the root carries `Prn=Shield` and the
Oblivion shield path takes it. The result is written as a Morrowind-version
NIF beside the source meshes, so everything downstream is unchanged.
See: [asset_convert_armor.md#morrowind-armor-assembly](asset_convert_armor.md#morrowind-armor-assembly).

Armor rating is `AODT.armor x 100`: TES4 stores hundredths and the importer
passes the value straight to Skyrim's `DNAM`, which also stores hundredths.

## <a id="actors-and-placements"></a>Actors and their placements

`NPC_` and `CREA` export into the TES4 actor vocabulary (`ACBS.*`, `AIDT.*`,
`DATA.<skill>`, `Faction[i]`, `Item[i]`), so `convert_NPC_`/`convert_CREA` and
everything downstream of them -- outfits, vendor factions, Skyrim race
override, the leveled-actor shells -- run unchanged. The race is named by the
OBLIVION race FormID (`RNAM.Race=000191C1` for Dark Elf), because
`_resolve_npc_race` maps that id through `TES4_RACE_FID_TO_EDID` and
`RACE_MAP` to the Skyrim race; no RACE record is needed or written.

| Morrowind | TES4 |
|---|---|
| FLAG Female 0x01 / Essential 0x02 / Respawn 0x04 / Autocalc 0x10 | `ACBS.Flags` 0x01 / 0x02 / 0x08 / 0x10 |
| CREA FLAG Biped 0x01 / Respawn 0x02 / Weapon 0x04 / Essential 0x80 | `ACBS.Flags` 0x01 / 0x08 / 0x04 / 0x02 (swims, flies, walks keep their bits) |
| NPDT 52-byte: level, 8 attributes, 27 skills, health, mana, fatigue, gold | `ACBS.Level`, `DATA.<attribute>`, `DATA.<skill>` (the 27 folded onto 21, taking the larger where two collide), `DATA.Health`, `ACBS.SpellPoints`, `ACBS.Fatigue`, `ACBS.BarterGold` |
| NPDT 12-byte (autocalc): level, disposition, reputation, rank, gold | `ACBS.Level`, `ACBS.BarterGold`; stats come from the Autocalc bit |
| AIDT hello, fight, flee, alarm, services | `AIDT.EnergyLevel` 50, `AIDT.Aggression`=fight, `AIDT.Confidence`=100-flee, `AIDT.Responsibility`=alarm, `AIDT.Services` with Morrowind-only bits (picks 0x20, probes 0x40, repair items 0x200, spellmaking 0x8000) cleared |
| ANAM faction + NPDT rank | `Faction[0].FormID` / `.Rank` |
| CREA NPDT type 0-3 | `DATA.Type` (the enums agree) |
| CREA soul value | `DATA.Soul` by Morrowind's own gem capacities: 30 petty, 60 lesser, 100 common, 200 greater, else grand |
| CREA attack min/max x3 | `DATA.AttackDamage` = the largest max |

AI packages export as PACK records the actor lists in order (see
[AI packages](#ai-packages)); the importer's default package list still gives
every actor the vanilla sandbox fallback underneath them.

A placed NPC is an **ACHR** and a placed creature an **ACRE**, decided by the
base record's signature, which the ID index now records alongside the FormID.
A REFR whose base is an actor is not a valid Skyrim record, and a placed
leveled creature stays a REFR because the importer's Phase 0h turns those into
shell ACHRs itself.

## <a id="ai-packages"></a>AI packages

**Code:** `tes4_export/record_types/morrowind_packages.py`.

Morrowind stores an actor's packages inline on the actor (`AI_W` wander,
`AI_T` travel, `AI_F` follow, `AI_E` escort, `AI_A` activate, each optionally
followed by `CNDT`), where TES4 stores PACK records the actor lists by FormID.
Measured on Morrowind.esm: 2,817 `AI_W`, 170 `AI_T`, 70 `AI_F`, 3 `CNDT`.
Each `AI_*` becomes one PACK with a FormID derived from `pack:<actor>:<index>`
and is listed in file order, because both later engines run the first package
whose conditions pass.

| Morrowind | TES4 PACK | Location / target |
|---|---|---|
| `AI_W` distance, duration | Wander (5) | near editor location, radius = distance |
| `AI_T` x, y, z | Travel (6) | near an XMarker placed at the position |
| `AI_F` id, duration [, x, y, z] | Follow (1) | the target's placed reference [+ marker] |
| `AI_E` id, duration [, x, y, z] | Escort (2) | the same |
| `AI_A` id | Find (0) | object id, which the importer turns into Activate |

Coordinates are cell-local, and the package sits on the BASE actor, so a
destination marker goes into the exterior grid the position falls in, else into
the cell of the actor's first placement. A package whose marker cell or target
placement cannot be found is dropped and counted (`package:<kind>` in the
unresolved tally). The schedule is "any time" with Morrowind's duration in
hours, which the importer converts to minutes; the per-package idle chances have
no TES4 field and are left to Skyrim's own sandbox idles.

### A dropped package must also drop the actor's reference

The actor's `AIPackage[i]` lines are written while the actor is converted, but
a package can only be resolved after the cells and placements exist, so
`package_records` runs at the end of the export. A package that fails there was
already named by its actor, leaving a `PKID` pointing at a PACK no record
defines.

Skyrim does not reject that at load. `TESNPC::InitItem` resolves each form
pointer and, on failure, formats a warning -- `<SIG> Form '<EditorID>'
(<FormID>)` against `"UNKNOWN form"` -- for every actor, every load. Measured
from a live hang: one such NPC (`Navil Ienith`, a travel package with no
resolvable destination cell) left the game spinning in
`__stdio_common_vsprintf_s` under the data handler's per-form-type init loop,
and it never reached the main menu.

So `package_records` records each failure in `ctx.dropped_packages` and
`prune_dropped_packages` rewrites the affected actors, renumbering the
survivors so the indices stay contiguous. The invariant to hold: **every
`AIPackage[i]` names a PACK the export actually writes** -- checked as
references == records over `NPC_.txt` + `CREA.txt` against `PACK.txt`.

## <a id="creatures"></a>Creatures: one NIF split into a creature folder

**Code:** `tes4_export/record_types/morrowind_actors.py` (`export_CREA`),
`asset_convert/havok/creature_split_morrowind.py`.

The creature pipeline converts "any folder holding a skeleton.nif plus .kf
animations" (`creature_pipeline.convert_creatures`), which is Oblivion's
layout. A Morrowind creature is ONE self-contained NIF: `r\Guar.NIF` holds the
`Bip01` skeleton, 17 skinned shapes, 50 `NiKeyframeController`s spanning a
single 27 s timeline and one `NiTextKeyExtraData` whose 58 keys cut that
timeline into animation groups (`Idle: Start` / `Loop Start` / `Loop Stop` /
`Stop`, `Attack1: Hit`, `SoundGen: Left`). 52 of the 105 creature meshes
instead pair an `x<name>.nif` model with an `x<name>.kf` (a
`NiSequenceStreamHelper` whose extra-data chain names each controller's node),
which the engine prefers when present.

The exporter points each CREA at the folder layout the pipeline scans --
`Model.MODL=r\<stem>\skeleton.nif`, `NIFZ[0]=<stem>.nif` -- and records the
source as `MorrowindModel`. The split runs at the head of `--creatures-only`:
it writes `skeleton.nif` (the tree without geometry, controllers or text
keys), `<stem>.nif` (the same tree with the skinned shapes and no controllers)
and one `.kf` per animation group, sampled at 30 fps over the group's range
and written through `kf_writer.write_skyrim_kf`, so `decode_kf`,
`classify_clips` and `read_animgroup` consume them exactly as Oblivion clips.
A group with a loop segment ships only that segment (Skyrim gaits loop whole
clips), everything else ships `Start`..`Stop`. Group names map onto the
Oblivion stems the clip tables claim (`WalkForward` -> `forward`, `RunForward`
-> `runforward`, `Hit1` -> `recoil`, `Knockdown` -> `stagger`, `Death1` ->
`death`, `SpellCast` -> `casttarget`); `SoundGen: Left/Right` become
`Enum: Left/Right` footfalls, `Attack: Hit` becomes `hit`, `Sound: X` is kept,
and the other `SoundGen` cues are covered by the CREA sound slots below.

Sound slots come from `SNDG` (per-creature sound generators), exported in the
TES4 `SoundType[i].Type/.Sound` vocabulary: LeftFoot/RightFoot keep their
slots, Moan -> Idle (4), Roar -> Attack (6), Scream -> Hit (7); the swim and
Land cues have no TES4 slot.

## <a id="scripts"></a>Scripts

**Code:** `tes4_export/record_types/morrowind_scripts.py`, `tes3_reader.script_name`.

A Morrowind SCPT carries its source text in `SCTX`, the field the script
converter already consumes, so the record exports as a TES4 script: `SCTX`,
`SCHR.Type=0` (every Morrowind script is attached like an object script or
started by name), and `Variable[i].Index/.Name` from `SCVR`, whose order is
the index. The record has no `NAME`: its id is the 32-byte name at the head of
`SCHD`, which the reader lifts into `record_id` so scripts resolve like every
other object. A record's `SCRI` becomes the TES4 `SCRI=` FormID line.

The source grammar (`Begin name` blocks, `ref->command`) is Morrowind's, not
Oblivion's. Measured on the first build: all 632 scripts "convert" and compile,
but a `Begin <name>` block is not a TES4 block type, so its body is dropped
and every script ships as declarations only (median 159 bytes of Papyrus). The
records are attached (1,474 VMAD attachments) and inert. The converter needs a
Morrowind block mode and the `->` member-call syntax before the bodies survive;
Morrowind.esm carries 632 scripts, and 1,231 across the three ESMs.

## <a id="leveled-lists"></a>Leveled lists

`LEVI` -> `LVLI` and `LEVC` -> `LVLC` (which the importer writes as LVLN). The
flag bits are NOT the same: Morrowind's item list has Each=0x01 and
AllLevels=0x02 where TES4's `LVLF` has "calculate from all levels" 0x01 and
"calculate for each item" 0x02, so the two swap; the creature list has only
AllLevels=0x01, which is TES4's 0x01. `NNAM` is `LVLD.ChanceNone` unchanged.
An entry whose object this pass does not convert is dropped rather than
written as a null FormID.

## <a id="teleport-doors"></a>Teleport doors

A Morrowind door reference stores its destination as a position and rotation
(`DODT`) plus, for an interior, the destination cell's name (`DNAM`). There is
no destination door. Skyrim's `XTEL` REQUIRES one, and the importer emits no
XTEL at all without `XTEL.Door` -- so none of Morrowind.esm's 3,133 load doors
(2,022 into named cells, 1,111 into the exterior) led anywhere.

The missing half is **authored, not synthetic**. Morrowind ships load doors in
PAIRS: the `DODT` position is where the destination cell's own door back again
stands. Measured over Morrowind.esm, all 3,127 teleport doors have another door
reference within 1,024 units of their destination, 2,946 of them within 256. So
`_partner_door` resolves the pair by position and `XTEL.Door` names it, with the
door flagged persistent (`RecordFlags=1024`) as every vanilla load door is.

An earlier pass minted an XMarker per door instead. That is wrong, and the
vanilla census is one-sided: of Skyrim.esm's 1,722 XTEL references, **1,703
point at another DOOR reference and not one points at an XMarker** (the other
19 name 5 bases outside the dump). A door whose XTEL names a marker renders and
activates, but only ever as a plain door -- the generic "open door" prompt with
no load. 27 of 3,133 doors have no convertible destination or no partner there;
they stay plain doors and the count is reported.

The destination cell has to exist in the output: an interior by name (the
plugin's own and its masters'), an exterior by the grid square under the
destination position. A door whose destination is in neither stays a plain
door, and the count is reported.

### A persistent reference may not live in an exterior grid cell

Making the doors persistent was correct -- Skyrim.esm's XTEL doors are
1,722/1,722 persistent -- but persistence also decides WHICH cell a reference
is filed under, and that is where the first attempt went wrong. Every exterior
door and its minted marker stayed parented to the grid cell it stood in, and
all 1,113 of Balmora's and everywhere else's exterior doors vanished from the
game with no red triangle: the model loads, the reference is simply never
attached.

> "For an exterior cell, the persistent references are defined in a dummy cell
> in the worldspace group." -- UESP, Mod File Format/CELL

The census agrees and is one-sided. Skyrim.esm's XTEL doors by parent cell:

| parent cell kind | vanilla | ours (before) | ours (after) |
|---|---|---|---|
| interior | 976 | 2,025 | 2,025 |
| worldspace dummy persistent cell | 746 | 0 | 1,108 |
| **exterior grid cell** | **0** | **1,108** | **0** |

The engine loads a worldspace's persistent references by worldspace out of that
one dummy cell, never by grid, so a persistent ref filed under a grid cell is
unreachable from either path. This is Morrowind-specific only because TES4
already ships such a cell and the converted plugin inherits it; the synthetic
Morrowind worldspace had none, so `persistent_cell_record` mints one
(`cell:persistent:<worldspace>`, no XCLC, `RecordFlags=1024`) and
`_rehome_persistent` moves every persistent exterior reference into it. The
importer already files a cell flagged persistent directly under the worldspace
group rather than in the block tree.

Note the flag is Persistent ONLY. Vanilla's dummy cells read `263168`, which is
`0x400` Persistent plus `0x40000` Compressed -- compression is the importer's
concern, not a property the export asserts.

This is the same class of defect as the forced Persistent flag on exterior
statics, which made buildings invisible while every record-level audit stayed
clean. See [ck_vs_game_missing_objects.md](ck_vs_game_missing_objects.md).

### DOOR also needs the FNAM flags byte

TES5 DOOR has a required `FNAM` flags byte (xEdit marks it `True`); all 235
vanilla doors carry one and 185 of them are `0`. We wrote it on 0 of 139,
because TES3 has no door-flags field to carry over at all: Morrowind's own
`FNAM` is the **display name**, a zstring, which `emit_common` already writes
as FULL. `convert_DOOR` only writes the subrecord when the export supplies
`FNAM.Flags`, so the field simply never appeared.

This is Morrowind-specific for the same reason the persistent cell was: a TES4
DOOR carries FNAM natively, so Oblivion's doors always had one.
`export_DOOR` now writes the vanilla default `FNAM.Flags=0`.

It is a real gap and worth closing, but it was **not** what restored the load
prompt -- that was the XTEL target above. Adding FNAM alone changed nothing
in game.

`MODT` was ruled out on the way: it is absent from **every** record type we
emit (0 of 3,238 STAT, 0 of 139 DOOR), including the statics that render
correctly, so it cannot explain a door-only symptom.

## <a id="sounds"></a>Sounds

`SOUN` carries a filename relative to `Sound\` and three bytes: volume, minimum
range, maximum range. Morrowind's ranges are in units of `fAudioMinDistanceMult`
(20) and `fAudioMaxDistanceMult` (50), with 0 meaning the defaults
`fAudioDefaultMinDistance` 5 and `fAudioDefaultMaxDistance` 40 -- so a typical
sound reaches from 100 to 2,000 units. TES4's `SNDX` stores minimum in units of
5 and maximum in units of 100, which the importer scales back, so the export
writes `min x 4` and `max / 2`. Volume 0-255 becomes `SNDX.StaticAttenuation`
in hundredths of a dB (`-2000 x log10(volume / 255)`), 0 at full volume.

Morrowind's sounds are LOOSE files under `Data Files\Sound`, not in the BSA,
so the extract stage copies that tree into `export/<plugin>/sound` where the
audio stage expects to find every plugin's sounds.

## <a id="tes3-bsa"></a>The TES3 BSA

A different format from every later BSA: magic `0x00000100` (not `BSA\0`), a
flat path list with no folder records, and no compression at all. Parsed from
`Morrowind.bsa`: 11,090 files — 5,798 `.nif`, 5,187 `.dds`, 97 `.kf`.

Vanilla textures are **already DDS**, so TGA/BMP decoding is a loose-mod concern
and not on the critical path.
