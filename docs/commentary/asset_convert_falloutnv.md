# FO3/FNV mesh conversion

## <a id="fnv-skeleton-bones"></a>FNV skeleton bones

**Code:** `asset_convert/character/skyrim_overrides_falloutnv.py`

The FO3/FNV human skeleton (`meshes/characters/_male/skeleton.nif`) carries
**65 bones, 16 of which have no entry in `OBLIVION_TO_SKYRIM_BONE_MAP`**.
Armor weighted to an unmapped bone collapses to the origin, so those 16 were
the cause of FNV clothing deforming to a point.

FO3 kept Oblivion's `Bip01` spine, limb and finger names, so the two tables
are **merged** rather than swapped — only the renamed and added bones need
new entries:

| FO3/FNV bone | Skyrim bone | Why |
|---|---|---|
| `Bip01 L/RUpArmTwistBone` | `NPC L/R UpperarmTwist1` | FO3 renamed the twist |
| `Bip01 L/R ForeTwist` | `NPC L/R ForearmTwist1` | FO3 renamed the twist |
| `Bip01 L/R Thumb1/11/12` | `NPC L/R Finger00/01/02` | Oblivion has no thumbs |
| `Bip01 L/RPauldron` | `NPC L/R Clavicle` | shoulder plate rides the clavicle |
| `Weapon` | `WEAPON` | Skyrim's node is uppercase |

Three FO3 bones are dropped outright — they drive the FO3 rig itself and have
no Skyrim counterpart, so skinning must never target them:
`Bip01 R ForeTwistDriver` (procedural twist driver), `Camera3rd` and
`HeadAnims`.

Every target above was verified present in both
`skeleton_bones_falloutnv.json` and `skeleton_bones_skyrim_male.json` before
the table was written.

## <a id="fnv-animation-pose"></a>FNV animation pose

**Code:** `asset_convert/character/skin_retarget.py` `load_animation_deltas`

Phase B.1 of the retarget pre-deforms armor into a pose that best matches the
Skyrim rest skeleton, using per-bone delta matrices mined from the source
game's own `.kf` corpus by `kf_animation_explorer.py --build-cache`.

The deltas are only valid for the skeleton they were mined against — they are
`inv(rest_world) @ anim_world` in that skeleton's bind pose. FO3/FNV bind
poses differ from Oblivion's and the corpora are different sizes (**2,008 FNV
human clips vs Oblivion's 538**), so each source game gets its own cache:
`best_animation_pose.json` for Oblivion, `best_animation_pose_falloutnv.json`
for FO3/FNV. Which one loads is decided by the source skeleton, the same
authored-bone-name test the bone map uses.

The cache is keyed by path rather than held in a single module global, so both
can be resident when a run converts meshes from more than one source.

### <a id="selected-by-authored-bone-names"></a>Selected by authored bone names

Which table applies is decided by the **skeleton's own bone names**, never a
plugin or file name: `Bip01 L Thumb1` and `Bip01 LUpArmTwistBone` exist only
in FO3/FNV skeletons. A plugin name would break for any mod built on a
Fallout skeleton, and per the project rule the authored data is the indicator.

## <a id="fnv-body-fitting"></a>FNV body fitting: Oblivion's field, FNV's pose deltas

The body-wrap field stays Oblivion's (the torso and leg rest poses agree
within half a unit) but the wrap's FK base did not. `deform_geoms_wrap`
called `load_animation_deltas()` with no source skeleton, so it posed every
mesh with **Oblivion's** `inv(rest) @ pose` matrices. FNV's rest pose holds the
arms lower (rest hand z 85.3 vs Oblivion 100.8, forearm 94.4 vs 101.9), so
Oblivion's arm deltas rotate FNV forearms from the wrong start and both come
out horizontal at elbow height, hands drooping (render of
`armor/antagonist/outfitm.nif`; the mangled-forearm report). The FNV pose
cache itself is right: its posed hand lands at (-28.8, 2.0, 72.6) against
Skyrim's (-28.9, 1.8, 72.8).

`deform_geoms_wrap` now takes the source skeleton, loads the matching delta
cache, and aliases FNV-only bone names (`Bip01 L ForeTwist`, the thumbs, the
twist bones) to the Oblivion bone sharing their Skyrim target for the field's
bone-centroid gate (`oblivion_alias_map`), so those weights count toward the
region instead of being skipped.

The size argument that justified sharing the field still holds:

| Bone | Oblivion z | FNV z | Skyrim z |
|---|---:|---:|---:|
| `Bip01 Pelvis` | 67.41 | 67.77 | 68.91 |
| `Bip01 Head` | 112.44 | 112.82 | 120.34 |
| `Bip01 L Foot` | 6.75 | 7.07 | 6.08 |

Under half a unit apart on the torso and legs, so FNV proportions are
Oblivion's there and a separate field would fit the same shape twice. The
arms are where the two rests differ, and that is a POSE difference the deltas
own, not a shape difference for the field.

### The raw-vertex trap

FNV body meshes look wildly out of range at first: `upperbody.nif` stores
vertices spanning **z = -102 to 111**, against the field's 0.1-126 domain, and
a naive nearest-neighbour check puts the worst FNV vertex 103 units from any
field point.

That comparison is wrong. FNV stores body vertices in **bone-local** space
where Oblivion stores them already in world space (Oblivion raw == world). The
pipeline feeds `geom_world` output to the field, and in world space FNV's body
sits at **z = 0.8 to 119.9** — inside the field's domain:

| Source | World verts | dist p50 | p90 | p99 | max |
|---|---:|---:|---:|---:|---:|
| Oblivion | 885 | 0.00 | 0.00 | 0.00 | 0.00 |
| FalloutNV | 2,532 | 1.47 | 5.47 | 12.85 | 15.12 |

Oblivion is 0.00 by construction (the field is built from it). FNV's median
1.47 units is well within the field's interpolation range.

Always measure against `geom_world` output, never raw vertices.

### Why an FNV-specific field could not be built anyway

FNV does not decompose the body the way `_OB_BODY_SETS` expects. There is
**no `lowerbody.nif` and no `foot.nif`** — one `upperbody.nif` covers the whole
body head-to-toe — hands are split left/right where Oblivion has a single
`hand.nif`, and the head lives outside `characters/_male` entirely. The FNV
body mesh also carries FO3 dismemberment gore caps (`bodycaps`, `limbcaps`,
`meatneck01`, `meathead01`) as sibling shapes, which are stumps rather than
body surface and would have to be excluded.

If FNV fitting ever does prove insufficient in game, the corrective is data
derived from the measured bind poses in this sidecar — never per-piece offsets
in `ARMOR_PIECE_OFFSETS`.

## <a id="dismemberment-gore-caps"></a>Dismemberment gore caps

FO3/FNV skinned meshes carry the stumps for limb dismemberment as their own
shapes (`limbcaps`, `bodycaps`, `meatneck`, `meathead`, `GorecapsBody`) whose
`BSDismemberSkinInstance` partitions are typed 101-113 (`BP_SECTIONCAP_*`) and
201-213 (`BP_TORSOCAP_*`). The FO3 engine hides those partition types at load
and reveals one when it severs that limb. The 1000+ values
(`BP_TORSOSECTION_*`) that share shapes with ordinary partitions are visible
torso sections and need nothing.

Census over 400 FNV armor NIFs (`temp` script, `read_nif` + pyffi):

| Shapes | Count |
|---|---:|
| dismember skin, every partition a cap | 475 |
| dismember skin, caps mixed with a stray partition 0 | 4 (135/170 and 87/126 triangles are caps) |
| plain `NiSkinInstance` | 54 |

Creatures (brahmin, centaur, deathclaw ...) ship the same cap shapes.

Skyrim has no limb dismemberment and `regen_skin_partition` rebuilds every
partition from the wearing record's slot, so the caps rendered as ordinary
body geometry: the "bloody portion always visible" report, on armor and
creatures alike. `dismember_falloutnv.hide_dismember_caps` sets the NiAVObject
hidden bit on any dismember-skinned shape whose cap partitions hold at least
half its triangles, before any skin conversion runs; `converted_node_flags`
and the geometry prep carry the bit through. The geometry is kept: hidden is
exactly the FO3 engine's own load state. The caps are deliberately not mapped
to `SBP_230_HEAD`: Skyrim's beheading stump comes from the race's decapitate
armor, and typing every limb cap 230 would reveal all of them on a beheading.

## <a id="multi-line-text-keys"></a>Multi-line .kf text keys

FO3/FNV pack SEVERAL text keys into ONE `NiTextKeyExtraData` value separated by
CRLF; Oblivion always writes one key per value. `parse_kf_events` matched
`sound:` against the whole value and took everything after the first colon as
the SOUN EditorID, so a two-key value became one "EditorID" holding a newline.

`project_block_lines` writes each trigger as one line of
`animationdatasinglefile.txt`, which is positional: a count, then exactly that
many trigger lines. An embedded newline wrote 2 lines where the count promised
1, so every later project in the file read the WRONG block -- the same desync
class as the singlefile poisoning, but fatal at load rather than merely silent.

Measured over `export/FalloutNV.esm/meshes/creatures/libertyprime`: 106 text
keys, 15 of them multi-line, producing 14 malformed `Sound: ` lines in the
shipped singlefile. `_classify_key` now takes one already-split key and
`parse_kf_events` splits each value on newlines first.

## <a id="fo3-havok-enums"></a>FO3/FNV Havok enums

**Code:** `asset_convert/collision/collision_material_falloutnv.py`

FO3/FNV share Oblivion's material enum only for indices 0-13 and diverge
completely above it, so an FO3 value routed through the Oblivion table is
silently mistranslated (FNV 16 HOLLOW_METAL reads as Oblivion "Cloth Stairs",
26 TRANSPARENT_SMALL as "Line Of Sight"). The two tables are selected by
source game and never merged.

### <a id="source-game-latching"></a>Source-game latching

A material index alone does not say which enum authored it, so
`register_fallout_nif(user_version_2)` latches the source game once per NIF
from the header (`user_version_2 == 34` is FO3/FNV) and `is_fallout_source()`
routes every later material and layer lookup in that NIF to the FO3 tables.

### <a id="materials--128-values-32-bases"></a>Materials: 128 values, 32 bases

FO3 material values run 0-127: bits 0-4 pick the base material, bit 5 marks
the platform variant and bit 6 the stairs variant of the same base, so a
32-row base table plus a stairs table covers every authored value.
`fo3_material()` returns the Skyrim material CRC; stairs variants map to the
stairs CRC of their base, defaulting to stone stairs.

### <a id="layers--diverge-from-19"></a>Layers: diverge from 19

FO3 collision layers match Skyrim's numbering below 29 and are renumbered from
29 (DEADBIP) onward; `FO3_TO_SKY_LAYER` maps each FO3 layer to its Skyrim
`SKYL_*` value and passes unknown values through unchanged.

## <a id="collision-rules"></a>Collision rules that differ from Oblivion

**Code:** `asset_convert/collision/collision_falloutnv.py`

Three FO3/FNV behaviours differ from Oblivion's and were each producing an
in-game symptom. The source game is latched once per NIF from the header
(`user_version_2 == 34`) before the Skyrim version is stamped over it.

### <a id="root-rotation-ignored"></a>Root rotation is ignored, as in Skyrim

Oblivion applies a NIF root's rotation; FO3/FNV and Skyrim overwrite the
root transform with the REFR's. Rotated roots are equally common in all three
games (Oblivion architecture 22/339, FNV 24/521, vanilla Skyrim 25/489), so the
rule is per engine. Settled by a seam test (`temp/root_rot_seam_test.py`):
place each rotated-root kit piece under both hypotheses and count vertices
coinciding with unambiguous neighbours in the same cell.

| Plugin / cell | root rotation applied | root rotation ignored |
|---|---:|---:|
| Oblivion 0001C646 (castle kit) | 285 | 34 |
| FNV 000FA230 (office hall) | 5 | 31 |
| FNV 000EC3A2 (vault) | 64 | 438 |
| FNV 0013BC26 (vault) | 52 | 310 |
| FNV 00103DF9 (craftsman homes) | 25 | 268 |

So the Oblivion root-rotation wrapper is skipped for FO3/FNV: the root
rotation is simply zeroed, and nothing is baked into the collision because
FNV, like Skyrim, already placed the root body at REFR ∘ bodyT. Root
translations occur only on VATS camera rigs.

### <a id="two-sided-welding"></a>Random winding, repaired from the render mesh

FO3's `hkPackedNiTriStripsData` (20.2.0.7) has no per-triangle normal and its
winding is random: the render-skin oracle (`collision_winding_truth.py`)
scores 133 of 267 horizontal road faces inverted, 295 of 652 in nv_rocks;
the stock detector flags 265 of 290 office-kit meshes. FNV plays on these
files, so its Havok collides both sides. Skyrim's CMS carries a welding type
(`hkpWeldingUtility::WeldingType`: ANTICLOCKWISE 0, CLOCKWISE 4, TWO_SIDED 5,
NONE 6) and vanilla writes 0 in all 346 sampled blocks. Writing TWO_SIDED (5)
was tried first and the player still fell through roads and floors, so the
engine does not honour the byte; it is back to 0. FO3/FNV sources instead
always run the inference winding repair (steps 1-3, `repair_inverted_floors`),
which is otherwise gated per plugin; the render mesh is the authored surface.
Scored offline: roads 133 inverted to 0, nv_rocks 295 to 0, office/hallsmall
2 to 0.

### <a id="static-collection-parts"></a>Static-collection parts

An SCOL hangs one fixed body per part off `HavokN` child nodes carrying
translation, rotation and scale (0.77 to 1.99 in scolparkinglotchunk03b) plus
a body transform. The engine formula is
`T_node + R_node · (s · R_body · v + t_body)`: the scale applies to the shape
only, and the GECK pre-scaled the body translation (a roadchunk03 instance at
0.91 stores 0.91 × the standalone body translation). With that formula the
union of all 14 parts matches the visual bbox within 5 units on every axis;
the Oblivion composition `R·(t·s) + T` double-scales it. Every fixed packed
part is baked into one root triangle soup, which is what the GECK did to the
render geometry, so no scaled child collision node reaches Skyrim (0 of 179
vanilla child-collision meshes carry one).

### <a id="fo3-layers"></a>Collision layers

FO3 layers 0-28 are Skyrim's own and 29+ are renumbered, but the Oblivion
table sent them through Oblivion's enum: 19 DEBRIS_SMALL (truck hulks) became
31 STAIRHELPER and 26 TRANSPARENT_SMALL (CLFenceDestroyed01, scaffold grates)
became 41 LINEOFSIGHT, a pick layer with no physical collision, so the player
walked through them. Census of 1,500 FNV world meshes: layer 1 x373, 4 x32,
3 x23, 10 x13, 13 x13, 2 x12, 19 x12, 26 x9, 5 x4, 15 x2, 6/9/14 x1.
`fo3_layer()` passes 0-28 through and renumbers 29+.
