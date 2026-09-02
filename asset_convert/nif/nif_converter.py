"""PyFFI-based Oblivion → Skyrim NIF converter.

Replaces mesh_convert/nif_converter.py for the asset_convert pipeline.
Uses PyFFI to read/write NIF files and handles all conversions in-place.
Source files are NEVER modified; converted output is written to dst_path only.

Supported:
  - NiTriStrips → NiTriShape
  - NiTexturingProperty → BSLightingShaderProperty + BSShaderTextureSet
  - NiNode root → BSFadeNode
  - Root rotation baking into children (non-skinned)
  - Inline tangents from NiBinaryExtraData
  - NiControllerManager string palette resolution
  - Havok collision conversion (bhkNiTriStripsShape→bhkCompressedMeshShape via cms_builder)
  - NiParticleSystem removal

Skip reason codes (printed in skip list at end of batch_convert):
  VER   — NIF version is unsupported (too old, unrecognised)
  SKY   — Already Skyrim version, copied as-is
  RD    — Read failed (corrupt/truncated/unknown blocks)
  WR    — Write failed (version-incompatible blocks like NiGeomMorpherController)

`apply_patches()` must run before NifFormat is imported: it fixes
time.clock and the nif.xml conditions PyFFI reads at import time.
`landscape_normals` owns the shared stand-in normal map's path.
"""

import collections as _collections
import json as _json
import io as _io
import logging as _logging
import os
import re
import shutil
import struct
from pathlib import Path

import numpy as np

from asset_convert import paths
from asset_convert.nif.geometry_sanitize import sanitize_geometry_data
from asset_convert.nif.tex_paths import rewrite_tex_path
from asset_convert.nif.shaders import (ALPHA_BLEND_ENABLED,
                                       ALPHA_DST_ONE, ALPHA_DST_SHIFT,
                                       APPLY_HILIGHT2,
                                       DEFAULT_DIFFUSE_TEXTURE,
                                       DEFAULT_GLOSSINESS,
                                       DEFAULT_NORMAL_TEXTURE,
                                       LIGHTING_EMISSIVE_ONLY, SPEC_STRENGTH,
                                       apply_fx_soft_effect, apply_glow,
                                       apply_parallax,
                                       attach_tex_transform_ctrls,
                                       collect_shader_inputs,
                                       collect_uv_ctrls, has_spec_mask,
                                       plan_flipbook_atlas,
                                       resolve_normal_for)
from asset_convert.character.skin_replacement import (apply_armor_offset,
                                                     collect_skin_info,
                                                     splice_body_geometry,
                                                     strip_body_skin_geometry)
from asset_convert.nif.head_gear import (fit_prn_head_blocks,
                                         is_ground_model,
                                         remap_bone_names,
                                         strip_gnd_skin)
from asset_convert.nif.nif_passes import (add_animobject_bged,
                                          add_bsx_flags,
                                          collect_sequence_names,
                                          convert_sound_text_keys,
                                          fix_controller_flags,
                                          resolve_palette_strings,
                                          strip_empty_text_keys)
from asset_convert.nif.prn_skin import (BODY_PART_FALLBACK_PRN_BONE,
                                       add_prn_skin,
                                       bake_node_transforms_into_verts,
                                       bake_root_transform_into_verts,
                                       get_prn_bone,
                                       upgrade_skin_instances)
from asset_convert.nif.morphs import (emulate_morphs,
                                      normalize_blend_interpolators)
from asset_convert.nif.sequences import (apply_rest_visibility,
                                         attach_seq_shader_controllers,
                                         autoplay_ambient_sequences,
                                         match_seq_shader_types,
                                         process_controller_manager)
from asset_convert.character.wearable_plan import (body_part_for_flags,
                                                   body_parts_for_flags)
from asset_convert.havok.hkx_skeleton import BONE_RENAMES
from asset_convert.character import wearable_plan as wp
from asset_convert.character.body_wrap import morph_converted_to_weight1
from asset_convert.havok.hkx_animobject import generate_animobject_project
from asset_convert.nif.particles import (convert_particle_system,
                                        skyrimize_billboard,
                                        wrap_in_billboard)
from asset_convert.nif.nif_flags import NIF_FLAGS
from asset_convert.character.skyrim_overrides import (
    ARMOR_DEFAULT_BODY_PART,
    ARMOR_GEOMETRY_BODY_PARTS,
    ARMOR_GND_INV_MARKER_ROT_X,
    ARMOR_GND_INV_MARKER_ROT_Y,
    ARMOR_GND_INV_MARKER_ROT_Z,
    ARMOR_GND_INV_MARKER_ZOOM,
    ARMOR_PIECE_OFFSETS,
    ARMOR_PIECE_OFFSETS_PRN,
    OBLIVION_TO_SKYRIM_BONE_MAP,
    SHIELD_INV_MARKER_ROT_X,
    SHIELD_INV_MARKER_ROT_Y,
    SHIELD_INV_MARKER_ROT_Z,
    SHIELD_INV_MARKER_ZOOM,
    TORCH_INV_MARKER_ROT_X,
    TORCH_INV_MARKER_ROT_Y,
    TORCH_INV_MARKER_ROT_Z,
    TORCH_INV_MARKER_ZOOM,
    WEAPON_INV_MARKER_ROT_X,
    WEAPON_INV_MARKER_ROT_Y,
    WEAPON_INV_MARKER_ROT_Z,
    WEAPON_INV_MARKER_ZOOM,
)
from asset_convert.collision.collision import (bake_node_transform_into_body, convert_all_collisions,
                        hoist_collision, remove_empty_collision_nodes)
from asset_convert.collision.collision_constraints import (enforce_ragdoll_tree,
                        scale_constraint_pivots, strip_marker_collision_bodies)
from asset_convert.nif.tri_reconstruct import (clear_match_groups, fix_missing_triangles,
                              UnreconstructibleGeometry)

from asset_convert.nif.pyffi_monkey_patch import apply_patches
apply_patches()
from asset_convert.texture.texture_prune import texture_refs_in
from asset_convert.nif.nif_flames import convert_flame_nodes

try:
    from pyffi.formats.nif import NifFormat
    _PYFFI = True
    try:
        from pyffi.spells.nif.fix import SpellAddTangentSpace as _SpellAddTangentSpace
        from pyffi.spells.nif import NifToaster as _NifToaster
        _TANGENT_SPELL = True
    except ImportError:
        _TANGENT_SPELL = False
except ImportError:
    _PYFFI = False


# ---------------------------------------------------------------------------
# CONSTANTS — edit these to change conversion behaviour
# ---------------------------------------------------------------------------

OUTPUT_VERSION       = 0x14020007  # Skyrim SE NIF version
OUTPUT_USER_VERSION  = 12
OUTPUT_USER_VERSION_2 = 83


# BSLightingShaderProperty flags (default preset)
# SLSF1: Specular | Receive_Shadows | Cast_Shadows | Own_Emit | Remappable | ZBufferTest
_SF1_SPECULAR           = 0x00000001
_SF1_RECIEVE_SHADOWS    = 0x00000100
_SF1_CAST_SHADOWS       = 0x00000200
_SF1_OWN_EMIT           = 0x00400000
_SF1_REMAPPABLE         = 0x00800000
_SF1_Z_BUFFER_TEST      = 0x80000000
SHADER_FLAGS_1 = (_SF1_SPECULAR | _SF1_RECIEVE_SHADOWS | _SF1_CAST_SHADOWS |
                  _SF1_OWN_EMIT | _SF1_REMAPPABLE | _SF1_Z_BUFFER_TEST)

# SLSF2: ZBufferWrite | VertexColors | EnvMapLightFade
_SF2_Z_BUFFER_WRITE     = 0x00000001
_SF2_VERTEX_COLORS      = 0x00000020
_SF2_ENV_MAP_LIGHT_FADE = 0x00008000
_SF2_DOUBLE_SIDED       = 0x00000010
SHADER_FLAGS_2 = _SF2_Z_BUFFER_WRITE | _SF2_VERTEX_COLORS | _SF2_ENV_MAP_LIGHT_FADE


# --- Sky meshes ------------------------------------------------------------
# Sky geometry is NOT a world object.  Skyrim draws it through a dedicated sky
SKY_TEXTURE, SKY_SUNGLARE, SKY_BASE = 0, 1, 2
SKY_CLOUDS, SKY_STARS, SKY_MOON_STARS_MASK = 3, 5, 7

# Oblivion's Sky/ meshes, keyed by lowercase basename, mapped to the sky object
# type Skyrim's sky pass expects.  Oblivion had no such enum — it identified sky
# geometry by which slot of the climate/weather record referenced it — so this
# table is the mapping between the two models and cannot be derived from the
# NIF itself.
_SKY_MESH_TYPES = {
    'stars.nif':            SKY_STARS,
    'stars_oblivion.nif':   SKY_STARS,
    'sestars.nif':          SKY_STARS,
    'clouds.nif':           SKY_CLOUDS,
    'clouds_oblivion.nif':  SKY_CLOUDS,
    'atmosphere.nif':       SKY_BASE,
    'sky.nif':              SKY_BASE,
    'sunbeam01.nif':        SKY_SUNGLARE,
    'sunbeam02.nif':        SKY_SUNGLARE,
    'sunbeam03.nif':        SKY_SUNGLARE,
}


def sky_object_type_for(src_path):
    """Return the BSSkyShaderProperty sky object type for a mesh, else None.

    Only meshes living under a `sky/` directory are eligible: the basenames
    alone are generic enough to collide with ordinary clutter.
    """
    if not src_path:
        return None
    norm = str(src_path).replace('\\', '/').lower()
    parts = norm.rsplit('/', 2)
    if len(parts) < 2 or parts[-2] != 'sky':
        return None
    return _SKY_MESH_TYPES.get(parts[-1])

#: Convertible source versions; anything else is skipped, not copied.
_SUPPORTED_VERSIONS = {
    0x14000004,  # Gamebryo 20.0.0.4 - the primary Oblivion format
    0x14000005,  # Gamebryo 20.0.0.5
    0x14020007,  # Gamebryo 20.2.0.7 - FO3/FNV
    0x0a020000,  # Gamebryo 10.2.0.0
    0x0a01006a,  # Gamebryo 10.1.0.106
    0x0a010065,  # Gamebryo 10.1.0.101
    0x0a000100,  # NetImmerse 10.0.1.0
    0x0a000102,  # NetImmerse 10.0.1.2
}

#: Already-Skyrim (version, user_version_2), copied out unchanged.
_SKYRIM_VERSIONS = {
    (0x14020007, 83),  # FO3/FNV share the version, differing only in uv2
}

#: Havok unit scale, Oblivion to Skyrim: bodies, mass centres, primitive dims.
_HAVOK_SCALE = 0.1

# ---------------------------------------------------------------------------
# Oblivion → Skyrim attachment point (Prn) name remapping.
# ---------------------------------------------------------------------------
_PRN_REMAP: dict[str, str] = {
    'BackWeapon':  'WeaponBack',    # 2H weapons (bows refined to WeaponBow below)
    'SideWeapon':  'WeaponSword',   # 1H swords / generic 1H (refined by filename below)
    'Quiver':      'QUIVER',        # arrow quivers
    'Weapon':      'Weapon',        # already valid (keeps as-is)
    'Shield':      'SHIELD',        # shields
    # Skyrim carries the torch in the OFF-HAND, on the shield node: vanilla
    # meshes\weapons\torch\torch.nif ships Prn='SHIELD' (the static sconce
    # torches under clutter\ carry no Prn at all -- they are placed world
    # objects).  'NPC L MagicNode [LMag]' is the spell-CAST node: its axes
    # point outward from the open palm, so a torch attached there renders
    # rotated ~90deg with the flame off to the left.
    'Torch':       'SHIELD',
    # Shields: Oblivion uses the forearm bone; Skyrim has a dedicated SHIELD node
    'Bip01 L ForearmTwist': 'SHIELD',
    # Helmets: Oblivion attaches helmets to 'Bip01 Head'; Skyrim uses 'NPC Head [Head]'
    'Bip01 Head': 'NPC Head [Head]',
}

# Filename keyword → Skyrim Prn for 1H weapons (overrides 'WeaponSword' default).
# Oblivion uses 'SideWeapon' for all 1H weapons; Skyrim has per-type nodes.
# Checked against Skyrim skeleton.nif weapon node names.
_WEAPON_FILENAME_PRN: list[tuple[str, str]] = [
    ('dagger',    'WeaponDagger'),
    # NOTE: shortswords deliberately NOT listed — they stay on WeaponSword.
    # The record converter maps TES4 Blade1H → Skyrim OneHandSword, and the
    # draw animation only finds the weapon at the node matching the record's
    # AnimationType (see convert_WEAP axe/mace comment).  Prn=WeaponDagger on
    # a Sword-type record = invisible when held.
    ('mace',      'WeaponMace'),
    ('waraxe',    'WeaponAxe'),
    ('axe',       'WeaponAxe'),
    ('club',      'WeaponMace'),     # clubs → mace node (closest 1H blunt)
    ('staff',     'WeaponStaff'),
    ('hammer',    'WeaponMace'),
    # 'sword', 'longsword', 'claymore', etc. → WeaponSword (default)
]

# Oblivion Prn values that indicate weapon/equipment (will also get BSInvMarker)
_WEAPON_PRN_VALUES = frozenset({
    'SideWeapon', 'BackWeapon', 'Weapon', 'WeaponSword', 'WeaponBack',
    'WeaponMace', 'WeaponAxe', 'WeaponDagger', 'WeaponStaff', 'QUIVER',
    'Quiver',
})

# Skyrim-side (post-_remap_prn) Prn values of skeleton-attached equipment.
# These meshes are normalized into vanilla attachment frames during
# conversion, so the vanilla-derived BSInvMarker constants are exact — the
# per-mesh inventory-rotation pass must not override them.
_EQUIPPED_PRN_VALUES = frozenset({
    'Weapon', 'WeaponSword', 'WeaponDagger', 'WeaponMace', 'WeaponAxe',
    'WeaponStaff', 'WeaponBack', 'WeaponBow', 'SHIELD', 'QUIVER', 'Quiver',
})


def _remap_prn(oblivion_prn: str, nif_filename: str) -> str:
    """Map an Oblivion Prn value to the correct Skyrim skeleton node name.

    For 'SideWeapon' (all Oblivion 1H weapons), refines to per-type node by
    looking for weapon type keywords in the NIF filename.

    For 'BackWeapon' (all Oblivion 2H weapons AND bows), bows must go to
    'WeaponBow' — with 'WeaponBack' the draw animation never reparents the
    mesh to the hand, so an equipped bow stays glued to the back and the
    hands look empty.  Vanilla Skyrim bow NIFs all carry Prn=WeaponBow.
    """
    skyrim_prn = _PRN_REMAP.get(oblivion_prn, oblivion_prn)
    lower = nif_filename.lower()
    if oblivion_prn == 'SideWeapon':
        for keyword, prn in _WEAPON_FILENAME_PRN:
            if keyword in lower:
                return prn
    elif oblivion_prn == 'BackWeapon' and 'bow' in lower:
        return 'WeaponBow'
    return skyrim_prn


_SHIELD_ATTACH_T = None


def shield_attach_transform():
    """4x4 mapping shield geometry from Oblivion attach space to Skyrim's.

    Oblivion shields attach to 'Bip01 L ForearmTwist' (strapped across the
    forearm, identity root transform); Skyrim attaches the NIF root to the
    'SHIELD' bone (child of the left hand, at the grip).  To keep the shield
    sitting on the arm EXACTLY as it did in Oblivion, we map between the two
    attach frames through an anatomical hand frame built from the same three
    landmarks on each skeleton (hand joint, middle-finger base, thumb base):

        T = W_obForearmTwist @ F_ob^-1 @ F_sk @ W_SHIELD^-1

    (row-vector convention, matching skeleton_bones_*.json).  Applying T as
    the shield NIF's root transform reproduces the Oblivion placement
    relative to the arm; validated against vanilla ironshield.nif — the
    result lands on the Skyrim convention (face in XY plane, dome toward -Z,
    grip near the origin) within a few units.

    Returns a 4x4 numpy array (rotation rows 0-2, translation row 3), or
    None if the skeleton JSONs are unavailable.
    """
    global _SHIELD_ATTACH_T
    if _SHIELD_ATTACH_T is not None:
        return _SHIELD_ATTACH_T

    try:
        with open(paths.GENERATED / 'skeleton_bones_oblivion.json') as f:
            ob = {k: np.array(v, dtype=np.float64) for k, v in _json.load(f).items()}
        with open(paths.GENERATED / 'skeleton_bones_skyrim_male.json') as f:
            sk = {k: np.array(v, dtype=np.float64) for k, v in _json.load(f).items()}

        def _anat_hand_frame(hand, mid_base, thumb_base):
            """Rows: [finger-dir, thumb-dir, cross, hand-origin] anatomy->world."""
            h = hand[3, :3]
            fdir = mid_base[3, :3] - h
            fdir /= np.linalg.norm(fdir)
            tdir = thumb_base[3, :3] - h
            tdir = tdir - (tdir @ fdir) * fdir
            tdir /= np.linalg.norm(tdir)
            q = np.cross(fdir, tdir)
            q /= np.linalg.norm(q)
            F = np.eye(4)
            F[0, :3] = fdir
            F[1, :3] = tdir
            F[2, :3] = q
            F[3, :3] = h
            return F

        f_ob = _anat_hand_frame(ob['Bip01 L Hand'], ob['Bip01 L Finger2'],
                                ob['Bip01 L Finger0'])
        f_sk = _anat_hand_frame(sk['NPC L Hand [LHnd]'], sk['NPC L Finger20 [LF20]'],
                                sk['NPC L Finger00 [LF00]'])
        T = (ob['Bip01 L ForearmTwist'] @ np.linalg.inv(f_ob)
             @ f_sk @ np.linalg.inv(sk['SHIELD']))

        # Forearm-clearance correction.  T preserves the shield's pose
        # relative to the OBLIVION forearm, but the Skyrim forearm leaves the
        # hand at a different angle (~16° out of the strap plane, elbow at
        # SHIELD-local z=+7.2 vs the shield back face at z≈+2) — the arm pokes
        # through the shield.  Rotate about the grip (origin) so the mapped
        # Oblivion forearm axis lands on the actual Skyrim forearm axis: the
        # shield lies along the real arm, hand position unchanged.
        w_s_inv = np.linalg.inv(sk['SHIELD'])[:3, :3]
        d_ob = ob['Bip01 L Forearm'][3, :3] - ob['Bip01 L Hand'][3, :3]
        d_ob /= np.linalg.norm(d_ob)
        d_ob = d_ob @ (np.linalg.inv(f_ob) @ f_sk)[:3, :3] @ w_s_inv
        d_ob /= np.linalg.norm(d_ob)
        d_sk = sk['NPC L Forearm [LLar]'][3, :3] - sk['NPC L Hand [LHnd]'][3, :3]
        d_sk /= np.linalg.norm(d_sk)
        d_sk = d_sk @ w_s_inv
        d_sk /= np.linalg.norm(d_sk)
        axis = np.cross(d_ob, d_sk)
        s = np.linalg.norm(axis)
        if s > 1e-6:
            axis /= s
            c = float(np.clip(d_ob @ d_sk, -1.0, 1.0))
            K = np.array([[0, -axis[2], axis[1]],
                          [axis[2], 0, -axis[0]],
                          [-axis[1], axis[0], 0]])
            # Rodrigues in row-vector convention (v @ R): transpose of the
            # standard column form.
            r_fix = np.eye(3) + s * K.T + (1 - c) * (K.T @ K.T)
            fix4 = np.eye(4)
            fix4[:3, :3] = r_fix
            T = T @ fix4

        _SHIELD_ATTACH_T = T
    except (OSError, KeyError, ValueError) as e:
        print(f'  WARNING: shield attach transform unavailable ({e}); '
              f'shield keeps Oblivion orientation')
        _SHIELD_ATTACH_T = None
    return _SHIELD_ATTACH_T


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_identity(rotation):
    """Return True if a PyFFI Matrix33 is the identity matrix."""
    return (abs(rotation.m_11 - 1.0) < 1e-4 and abs(rotation.m_22 - 1.0) < 1e-4 and
            abs(rotation.m_33 - 1.0) < 1e-4 and abs(rotation.m_12) < 1e-4 and
            abs(rotation.m_13) < 1e-4 and abs(rotation.m_21) < 1e-4 and
            abs(rotation.m_23) < 1e-4 and abs(rotation.m_31) < 1e-4 and
            abs(rotation.m_32) < 1e-4)


def _identity_matrix():
    m = NifFormat.Matrix33()
    m.m_11 = 1.0; m.m_22 = 1.0; m.m_33 = 1.0
    return m


# --- Furniture marker conversion ------------------------------------------
# The full algorithm and data-verified ref/heading/z relations live in
from asset_convert.nif.furniture_markers import (
    ENTRY_BEHIND as _ENTRY_BEHIND,
    ENTRY_FRONT as _ENTRY_FRONT,
    ENTRY_LEFT as _ENTRY_LEFT,
    ENTRY_RIGHT as _ENTRY_RIGHT,
    cluster_seats as _cluster_seats,
    extract_entries as _extract_furniture_entries,
    geometry_center_xy as _geometry_center_xy,
    origin_shift as _furniture_origin_shift,
)


def _convert_furniture_markers(markers, root):
    """Convert Oblivion BSFurnitureMarker blocks (entry points) into one
    Skyrim BSFurnitureMarkerNode (seat positions).

    Returns (frn, origin_shift) — origin_shift is the +z translation that
    re-origins the model to the vanilla floor-origin convention.  The
    engine anchors the seated actor to the REFR z (not the marker z), so
    the model must be wrapped in an inner NiNode translated by this amount
    and the importer lowers the REFRs to match (see furniture_markers.py).
    Returns (None, 0.0) if the markers contain no positions."""
    entries = _extract_furniture_entries(markers)
    if not entries:
        return None, 0.0
    shift = _furniture_origin_shift(entries)
    seats = _cluster_seats(entries, lambda: _geometry_center_xy(root))

    frn = NifFormat.BSFurnitureMarkerNode()
    frn.name = b'FRN'
    frn.num_positions = len(seats)
    frn.positions.update_size()
    for ci, seat in enumerate(seats):
        dst = frn.positions[ci]
        dst.offset.x = seat['x']
        dst.offset.y = seat['y']
        dst.offset.z = seat['z'] + shift  # re-origined coords (floor = 0)
        dst.heading = seat['heading']
        dst.animation_type = 2 if seat['sleep'] else 1
        ep = dst.entry_properties
        ep.front = 1 if seat['entry_flags'] & _ENTRY_FRONT else 0
        ep.behind = 1 if seat['entry_flags'] & _ENTRY_BEHIND else 0
        ep.right = 1 if seat['entry_flags'] & _ENTRY_RIGHT else 0
        ep.left = 1 if seat['entry_flags'] & _ENTRY_LEFT else 0
    return frn, shift


def _norm_tex_ref(raw):
    """Normalise a NIF texture path to a key relative to the textures root.

    'Textures\\tes4\\foo\\Bar.DDS' -> 'tes4/foo/bar.dds'.  Returns None for
    anything that isn't a texture (file_name also carries non-DDS paths).
    """
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', errors='replace')
    p = raw.strip().lower().replace('\\', '/').lstrip('/')
    if not p.endswith('.dds'):
        return None
    if p.startswith('textures/'):
        p = p[len('textures/'):]
    return p or None


def _harvest_textures(data, out):
    """Add every texture path the converted NIF references to the set *out*.

    Walks the finished blocks rather than the paths we rewrote, so it also picks
    up textures written by the particle/effect/flip-book branches and by any
    block we pass through untouched.
    """
    def add(raw):
        p = _norm_tex_ref(raw)
        if p:
            out.add(p)

    for root in data.roots:
        if root is None:
            continue
        for block in root.tree():
            tex_set = getattr(block, 'texture_set', None)
            if tex_set is not None:
                for t in tex_set.textures:
                    add(t)
            add(getattr(block, 'source_texture', None))
            add(getattr(block, 'greyscale_texture', None))
            add(getattr(block, 'file_name', None))


def _harvest_texture_bytes(raw: bytes, out):
    """Scrape texture paths out of a NIF we copied through without parsing.

    Uses texture_prune's scanner rather than a local regex: the equivalent
    `[A-Za-z0-9_\\\\/ .()&+-]{3,200}?\\.dds` pattern opens with a lazy star, so
    it retried at every offset of every mesh (22.8x slower, measured).
    """
    for match in texture_refs_in(raw):
        p = _norm_tex_ref(match)
        if p:
            out.add(p)


def _has_skin(data):
    """Return True if any block in the NIF is a NiSkinInstance."""
    for root in data.roots:
        if root is None:
            continue
        for block in root.tree():
            if isinstance(block, NifFormat.NiSkinInstance):
                return True
    return False


def _extract_inline_tangents(ed, nv):
    """Extract (binormals, tangents) from a NiBinaryExtraData 'Tangent space...' block.

    Returns (list_of_bitangent_tuples, list_of_tangent_tuples) or (None, None).
    The binary layout is: nv*12 bytes binormals, then nv*12 bytes tangents.
    """
    raw = bytes(ed.binary_data)
    expected = nv * 12 * 2
    if len(raw) < expected:
        return None, None
    binormals = [struct.unpack_from('<fff', raw, i * 12) for i in range(nv)]
    tangents  = [struct.unpack_from('<fff', raw, nv * 12 + i * 12) for i in range(nv)]
    return binormals, tangents


def _clamp_uv_sets(ts_data):
    """Reduce geometry data to the single UV set Skyrim reads.

    On disk the u16 "BS Data Flags" packs the UV-set COUNT in its low 6 bits
    (PyFFI exposes that half as num_uv_sets and bit 12 as extra_vectors_flags).
    That count is the only thing telling the engine how many TexCoord arrays
    follow the vertex colors, so a mesh that stores 2 sets while
    BSLightingShaderProperty binds 1 leaves the engine's vertex buffer a whole
    array short: the copy runs past the end of the allocation and faults on a
    non-temporal store (vmovntdq) at the next page boundary.

    Oblivion authors the extra set for detail/overlay passes that Skyrim has no
    slot for; set 0 is the diffuse UVs every shader samples, so the surplus is
    dropped rather than remapped.  Census: 2,233 vanilla shapes carry 0 or 1 UV
    sets and NEVER 2.
    """
    n = int(getattr(ts_data, 'num_uv_sets', 0) or 0)
    if n <= 1:
        return 0
    keep = list(ts_data.uv_sets[0]) if len(ts_data.uv_sets) else []
    ts_data.num_uv_sets = 1
    ts_data.uv_sets.update_size()
    if keep and len(ts_data.uv_sets):
        for dst, src in zip(ts_data.uv_sets[0], keep):
            dst.u = src.u
            dst.v = src.v
    return n - 1


def _set_tangents(ts_data, bitangents, tangents):
    """Write inline tangents/bitangents into NiTriShapeData.

    PyFFI Array elements must be mutated in-place (no item assignment).
    """
    nv = ts_data.num_vertices
    if len(tangents) != nv or len(bitangents) != nv:
        return
    ts_data.extra_vectors_flags = 16  # must set before update_size so arrays are sized
    ts_data.tangents.update_size()
    ts_data.bitangents.update_size()
    for i in range(nv):
        ts_data.tangents[i].x, ts_data.tangents[i].y, ts_data.tangents[i].z = tangents[i]
        ts_data.bitangents[i].x, ts_data.bitangents[i].y, ts_data.bitangents[i].z = bitangents[i]


# ---------------------------------------------------------------------------
# Node-level conversion
# ---------------------------------------------------------------------------

def _strip_dead_geometry_controllers(geom):
    """Remove NiGeomMorpherController / NiMaterialColorController from a
    geometry node's controller chain.

    Neither block type exists in vanilla Skyrim (0 of 17,216 meshes use
    NiGeomMorpherController — it's the Oblivion bow/flex morph system, which
    PyFFI also mis-serializes NiGeomMorpherController across the 20.0→20.2
    bump, aborting the write. NiUVController goes for a different reason, and
    its curves must be harvested by collect_uv_ctrls BEFORE this runs.
    See: docs/commentary/asset_convert_shader.md#niuvcontroller-has-no-rtti
    """
    prev = None
    ctrl = getattr(geom, 'controller', None)
    while ctrl is not None:
        nxt = getattr(ctrl, 'next_controller', None)
        if isinstance(ctrl, (NifFormat.NiGeomMorpherController,
                             NifFormat.NiMaterialColorController,
                             NifFormat.NiUVController)):
            if prev is None:
                geom.controller = nxt
            else:
                prev.next_controller = nxt
        else:
            prev = ctrl
        ctrl = nxt


def _prune_orphan_roots(data):
    """Drop entries from data.roots that are not scene-graph roots.

    Many Nehrim meshes were authored by tools that leave dangling blocks —
    NiTriShapeData, NiTriStripsData, NiBinaryExtraData, bhkCollisionObject,
    NiTexturingProperty — in the block list with nothing referencing them.
    PyFFI reports every unreferenced block as a root, so data.roots comes back
    as [NiNode, NiTriShapeData, ...].  Every pass here assumes a root is a
    scene node and reads root.controller / root.children, which raises
    AttributeError on those orphans (the castle\\*_far.nif and
    artilleryduell\\flamecannonballnew.nif failures).

    The orphans are unreachable from the real root, so they are dead weight:
    dropping them both fixes the crash and shrinks the output.  Keeps every
    NiAVObject root, and keeps a non-NiAVObject root only if it is the sole
    root (nothing to fall back to — let the later passes deal with it).

    Returns the number of roots removed.
    """
    roots = [r for r in data.roots if r is not None]
    if len(roots) < 2:
        return 0

    keep = [r for r in roots if isinstance(r, NifFormat.NiAVObject)]
    if not keep:
        return 0

    # An orphan is only safe to drop if nothing we keep still references it.
    reachable = set()
    for r in keep:
        for block in r.tree():
            reachable.add(id(block))
    keep_ids = set(id(r) for r in keep)
    keep += [r for r in roots
             if id(r) not in keep_ids and id(r) in reachable]

    removed = len(roots) - len(keep)
    if removed <= 0:
        return 0

    data.roots = keep
    return removed


# Equip/sheath nodes Skyrim looks up by hard-coded name, and where each one
# hangs on a vanilla weapon-using creature rig (Draugr skeleton.nif node order:
# WeaponAxe/Sword/Mace sit by the pelvis, WeaponBack/Bow/QUIVER after the left
# pauldron on the upper spine, WEAPON under the right hand, SHIELD under the
# left).
#
# Oblivion rigs have only three attachment points — Weapon, Torch, Quiver —
# which the BONE_RENAMES pass turns into WEAPON/SHIELD/QUIVER.  The per-type
# SHEATH nodes have no Oblivion counterpart at all, so the converted rig simply
# lacked them: a converted weapon carries Prn=WeaponMace (the sheathed node,
# which is what vanilla Skyrim weapon meshes use), the engine could not find a
# node by that name, and the mesh fell back to the actor root — the weapon
# visibly slid around at the creature's feet instead of sitting in its hand,
# and no draw animation could ever reparent it.
#
# 'anchor' is the node to hang it under, in preference order (the first that
# exists on this rig wins); 'source' is the node whose LOCAL transform is
# copied, so the new node lands somewhere sensible for a rig of any size
# rather than at a hardcoded human offset.
#
# Oblivion creatures do NOT sheathe: every one of the 41 armed creature folders
# ships equip/unequip clips whose text keys are `attach`/`detach` (the AnimObject
# mechanism) -- the weapon is created in the hand and destroyed, never parked on
# the body.  38 of those 41 rigs accordingly carry NO Quiver/Shield/BackWeapon
# node at all.  So the per-type SHEATH nodes below exist only to give the ENGINE
# a node of the name it looks up; nothing is ever displayed at them, and the
# creature's own rig is the authority on what it needs.
#
# An earlier pass synthesized "proportionate" offsets for them from vanilla
# Skyrim ratios.  That was wrong on two counts: the placements disagreed with
# vanilla anyway (axe/mace hang on the RIGHT hip in Skyrim, the guessed offset
# put them on the left), and no Oblivion creature has anything to place there.
# The node is created at the anchor's origin, which is what a node nothing
# renders at should be.
_CREATURE_EQUIP_NODES = (
    # name,           anchors (first match wins),               source
    ('WeaponSword',  ('Bip01 Pelvis', 'Bip01 Spine'),           'WEAPON'),
    ('WeaponDagger', ('Bip01 Pelvis', 'Bip01 Spine'),           'WEAPON'),
    ('WeaponAxe',    ('Bip01 Pelvis', 'Bip01 Spine'),           'WEAPON'),
    ('WeaponMace',   ('Bip01 Pelvis', 'Bip01 Spine'),           'WEAPON'),
    ('WeaponBack',   ('Bip01 Spine2', 'Bip01 Spine1',
                      'Bip01 Spine'),                           'QUIVER'),
    ('WeaponBow',    ('Bip01 Spine2', 'Bip01 Spine1',
                      'Bip01 Spine'),                           'QUIVER'),
    ('WeaponStaff',  ('Bip01 Spine2', 'Bip01 Spine1',
                      'Bip01 Spine'),                           'QUIVER'),
)

# Spell-cast nodes. Vanilla rigs carry one per hand plus a body-centre node;
# without them a casting creature's effect art has nowhere to attach.
_CREATURE_MAGIC_NODES = (
    ('NPC L MagicNode [LMag]', ('Bip01 L Hand',),               'SHIELD'),
    ('NPC R MagicNode [RMag]', ('Bip01 R Hand',),               'WEAPON'),
    ('MagicEffectsNode',       ('Bip01 Spine', 'Bip01 Spine1'), None),
)


def _add_creature_equip_nodes(data):
    """Give a converted creature rig the equip/sheath nodes Skyrim expects.

    Returns the number of nodes added.  Runs AFTER the BONE_RENAMES pass so the
    renamed WEAPON/SHIELD/QUIVER nodes are available as transform sources, and
    is a no-op for any node the rig already has (so re-running is safe and a rig
    that legitimately ships one keeps its own).
    """
    added = 0
    for root in data.roots:
        if root is None:
            continue
        by_name, parent_of = {}, {}
        for block in root.tree():
            if not isinstance(block, NifFormat.NiNode):
                continue
            by_name.setdefault(
                bytes(block.name).rstrip(b'\x00').decode(
                    'cp1252', 'replace'), block)
            for child in block.children or []:
                if isinstance(child, NifFormat.NiNode):
                    parent_of[id(child)] = block

        for name, anchors, source in (_CREATURE_EQUIP_NODES
                                      + _CREATURE_MAGIC_NODES):
            if name in by_name:
                continue
            parent = next((by_name[a] for a in anchors if a in by_name), None)
            if parent is None:
                continue
            node = NifFormat.NiNode()
            node.name = name.encode('latin-1')
            # Copy a sibling attachment point's local transform where we have
            # one; otherwise sit at the anchor's origin.  Either way the node
            # is scaled to THIS creature, not to a human.
            src = by_name.get(source) if source else None
            if src is not None and parent_of.get(id(src)) is parent:
                node.translation.x = src.translation.x
                node.translation.y = src.translation.y
                node.translation.z = src.translation.z
                node.rotation = src.rotation
            node.scale = 1.0
            node.flags = parent.flags
            parent.add_child(node)
            by_name[name] = node
            added += 1
    return added


def _strip_creature_bone_controllers(data):
    """Remove Oblivion-runtime controllers from creature NIF node chains.

    Oblivion creature skeletons carry an active (flags=12) but DATALESS
    NiTransformController on every bone plus a bhkBlendController on every
    ragdoll bone and a NiBSBoneLODController on Bip01 — all driven by
    Oblivion's engine at runtime.  Vanilla Skyrim creature skeletons ship
    NONE of these (bhkBlendController: 0 of all vanilla actor meshes; their
    only NiTransformControllers have a real interpolator+data — e.g. the
    dog's jaw/tongue idle).  Skyrim drives bones from the behavior graph, so
    these leftovers are at best dead weight and at worst engine hazards
    (an active controller with a null interpolator on every bone).

    Keeps NiTransformControllers that have an interpolator (real embedded
    animation).  Returns the number of controllers removed.
    """
    removed = 0
    for root in data.roots:
        if root is None:
            continue
        for block in root.tree():
            if not hasattr(block, 'controller'):
                continue
            prev = None
            ctrl = getattr(block, 'controller', None)
            while ctrl is not None:
                nxt = getattr(ctrl, 'next_controller', None)
                dead = isinstance(ctrl, (NifFormat.bhkBlendController,
                                         NifFormat.NiBSBoneLODController)) \
                    or (isinstance(ctrl, NifFormat.NiTransformController)
                        and getattr(ctrl, 'interpolator', None) is None)
                if dead:
                    if prev is None:
                        block.controller = nxt
                    else:
                        prev.next_controller = nxt
                    removed += 1
                else:
                    prev = ctrl
                ctrl = nxt
    return removed


def _normal_slot(diffuse, authored_normal, fix_textures, stats):
    """The normal map path for a shape whose diffuse is `diffuse`.

    Prefers the authored path, then what resolve_normal_for finds, and falls
    back to the shared flat normal rather than a dangling derived path.
    See: docs/commentary/asset_convert_shader.md#texture-slots-never-empty
    """
    base = diffuse.rsplit('.', 1)[0] if '.' in diffuse else diffuse
    if authored_normal:
        return (rewrite_tex_path(authored_normal) if fix_textures
                else authored_normal.decode('utf-8', errors='replace'))
    if stats is None:
        return base + '_n.dds'
    found = resolve_normal_for(diffuse, stats)
    if found is None:
        stats['spec_normal_defaulted'] = \
            stats.get('spec_normal_defaulted', 0) + 1
        return DEFAULT_NORMAL_TEXTURE
    if found != base + '_n.dds':
        stats['spec_normal_from_base'] = \
            stats.get('spec_normal_from_base', 0) + 1
    return found


def _fill_texture_slots(tex_set, diffuse_path, authored_normal,
                        fix_textures, stats):
    """Write the diffuse and normal slots, neither ever left empty.

    Skyrim binds the diffuse unconditionally, so a null slot 0 is an access
    violation; slot 1 is null-checked but vanilla never ships it empty.
    See: docs/commentary/asset_convert_shader.md#texture-slots-never-empty
    """
    if not diffuse_path:
        tex_set.textures[0] = DEFAULT_DIFFUSE_TEXTURE
        if stats is not None:
            stats['untextured_diffuse_defaulted'] = (
                stats.get('untextured_diffuse_defaulted', 0) + 1)
        return
    diffuse = (rewrite_tex_path(diffuse_path) if fix_textures
               else diffuse_path.decode('utf-8', errors='replace'))
    tex_set.textures[0] = diffuse.encode('utf-8')
    tex_set.textures[1] = _normal_slot(
        diffuse, authored_normal, fix_textures, stats).encode('utf-8')


def _build_sky_shader(ts, tex_set, diffuse_path, sky_type, stats):
    """Give sky geometry the dedicated sky shader and return the shape.

    Skyrim's sky pass draws these before the world, unlit and unfogged, with
    the horizon blend the weather record drives; routing them through
    BSLightingShaderProperty made the stars ordinary world geometry that drew
    over the terrain.  The pass does its own blending and vanilla sky meshes
    carry no NiAlphaProperty, so the Oblivion one is dropped.
    """
    sky_shader = NifFormat.BSSkyShaderProperty()
    sky_shader.shader_flags_1.slsf_1_z_buffer_test = 1
    ssf2 = sky_shader.shader_flags_2
    ssf2.slsf_2_z_buffer_write = 1
    if getattr(ts.data, 'has_vertex_colors', False):
        ssf2.slsf_2_vertex_colors = 1
    sky_shader.uv_offset.u = 0.0
    sky_shader.uv_offset.v = 0.0
    sky_shader.uv_scale.u = 1.0
    sky_shader.uv_scale.v = 1.0
    sky_shader.source_texture = tex_set.textures[0] if diffuse_path else b''
    sky_shader.sky_object_type = sky_type
    ts.bs_properties[0] = sky_shader
    ts.bs_properties[1] = None
    if stats is not None:
        stats['sky_shaders'] = stats.get('sky_shaders', 0) + 1
    return ts


def _set_material_defaults(shader):
    """Stamp vanilla's modal glossiness, specular colour and strength.

    Oblivion's own glossiness is deliberately not carried across.
    See: docs/commentary/asset_convert_shader.md#shader-material-defaults
    """
    shader.glossiness = DEFAULT_GLOSSINESS
    shader.specular_color.r = 1.0
    shader.specular_color.g = 1.0
    shader.specular_color.b = 1.0
    shader.specular_strength = SPEC_STRENGTH


def _is_additive(alpha_prop):
    """Whether the alpha property blends with dst=ONE, i.e. adds its colour."""
    if alpha_prop is None:
        return False
    flags = int(alpha_prop.flags)
    return bool(flags & ALPHA_BLEND_ENABLED) and (
        ((flags >> ALPHA_DST_SHIFT) & 0xF) == ALPHA_DST_ONE)


def _is_fx_surface(alpha_prop, vertex_lighting_mode):
    """Whether a shape belongs on the Effect shader rather than Lighting.

    Two AUTHORED indicators, never the texture path: Oblivion's own
    emissive-only lighting mode, and additive blending.
    See: docs/commentary/asset_convert_shader.md#fx-shader-discriminator
    """
    if vertex_lighting_mode == LIGHTING_EMISSIVE_ONLY:
        return True
    if _is_additive(alpha_prop):
        return True
    return False


def _set_emissive(shader, sf1, r, g, b, animated):
    """Carry NiMaterialProperty's emissive colour onto the Skyrim shader.

    Skyrim MULTIPLIES the colour by emissive_multiple, so a zero there leaves
    the surface black whatever the animation does; vanilla shapes with an
    emissive colour controller set own_emit in 133/133 cases and never pair it
    with a 0 multiple.  Clearing the flag when there is no emissive reduces
    overdraw on ordinary objects.
    """
    if not (r > 0.0 or g > 0.0 or b > 0.0 or animated):
        sf1.slsf_1_own_emit = 0
        return
    sf1.slsf_1_own_emit = 1
    shader.emissive_color.r = r
    shader.emissive_color.g = g
    shader.emissive_color.b = b
    shader.emissive_multiple = 1.0


def _as_tri_shape(strips_or_shape):
    """(shape to write, source shape) for a NiTriStrips or NiTriShape.

    Strips convert to a shape only when nothing controls them: a controller
    still references the original node by block index, so converting a
    controlled strip breaks the NIF.
    """
    if not isinstance(strips_or_shape, NifFormat.NiTriStrips):
        return strips_or_shape, strips_or_shape
    if strips_or_shape.controller is not None:
        return strips_or_shape, strips_or_shape
    return (strips_or_shape.get_interchangeable_tri_shape(), strips_or_shape)


def _inline_tangents(src):
    """(bitangents, tangents) from NiBinaryExtraData, or (None, None)."""
    for ed in list(src.extra_data_list):
        if (isinstance(ed, NifFormat.NiBinaryExtraData)
                and ed.name == b'Tangent space (binormal & tangent vectors)'):
            return _extract_inline_tangents(ed, src.data.num_vertices)
    return None, None


def _prepare_geometry_data(ts, src, stats):
    """Repair the mesh data Skyrim reads, before any shader is built.

    Carries the AUTHORED hidden bit across, clears Oblivion extra data,
    rebuilds absent triangle arrays, and clamps the UV sets.
    See: docs/commentary/asset_convert_nif.md#geometry-preparation
    """
    ts.flags = NIF_FLAGS | (int(getattr(src, 'flags', 0)) & 0x0001)
    bitangents, tangents = _inline_tangents(src)

    ts.num_extra_data_list = 0
    ts.extra_data_list.update_size()
    if hasattr(ts.data, 'consistency_flags'):
        ts.data.consistency_flags = 0x4000
    fix_missing_triangles(ts.data)
    clear_match_groups(ts.data)
    if hasattr(ts.data, 'extra_vectors_flags'):
        ts.data.extra_vectors_flags = 0

    dropped_uv = _clamp_uv_sets(ts.data)
    if dropped_uv and stats is not None:
        stats['uv_sets_dropped'] = stats.get('uv_sets_dropped', 0) + dropped_uv
    if tangents is not None and hasattr(ts.data, 'tangents'):
        _set_tangents(ts.data, bitangents, tangents)


def _flip_frames(flip_ctrl, fix_textures):
    """Every resolvable texture path a NiFlipController steps through."""
    if flip_ctrl is None:
        return []
    return [(rewrite_tex_path(s.file_name) if fix_textures
             else s.file_name.decode('utf-8', errors='replace'))
            for s in flip_ctrl.sources if s is not None and s.file_name]


def _atlas_controller(eff_shader, flip_ctrl, atlas):
    """Drive a frame-strip atlas from a stepped U-Offset controller.

    Frame duration comes from NiFlipController.delta, else its cycle spread
    over the frames, else Oblivion's ~15fps default.  Keys are CONST so the
    frames step rather than smear.
    """
    atlas_path, n_pad, n_real = atlas
    eff_shader.source_texture = atlas_path.encode('utf-8')
    eff_shader.uv_scale.u = 1.0 / n_pad
    delta = float(getattr(flip_ctrl, 'delta', 0.0) or 0.0)
    if delta <= 0.0:
        span = float(flip_ctrl.stop_time) - float(flip_ctrl.start_time)
        delta = span / n_real if span > 0 else 1.0 / 15.0

    fc = NifFormat.BSEffectShaderPropertyFloatController()
    fc.flags = 0x48
    fc.frequency = 1.0
    fc.phase = 0.0
    fc.start_time = 0.0
    fc.stop_time = n_real * delta
    fc.type_of_controlled_variable = 6
    fc.target = eff_shader
    interp = NifFormat.NiFloatInterpolator()
    interp.float_value = 0.0
    fdata = NifFormat.NiFloatData()
    kg = fdata.data
    kg.interpolation = 5
    kg.num_keys = n_real
    kg.keys.update_size()
    for k in range(n_real):
        kg.keys[k].time = k * delta
        kg.keys[k].value = k / float(n_pad)
    interp.data = fdata
    fc.interpolator = interp
    eff_shader.controller = fc


def _effect_emissive(eff_shader, si):
    """Carry the AUTHORED emissive onto an effect shader; white if none.

    Oblivion dims an FX surface through NiMaterialProperty.emissive_color --
    fxmist01 ships (0.47, 0.47, 0.47) -- and forcing white doubled every such
    effect, which on an additive quad accumulates per layer.  The material
    alpha rides in the emissive alpha, which is what the engine multiplies the
    sampled texel by.  1.0 for the multiple is vanilla's value on 852/1164
    blended FX shapes.
    """
    eff_shader.emissive_multiple = 1.0
    authored = (si.emissive_r > 0.0 or si.emissive_g > 0.0
                or si.emissive_b > 0.0)
    if authored:
        eff_shader.emissive_color.r = si.emissive_r
        eff_shader.emissive_color.g = si.emissive_g
        eff_shader.emissive_color.b = si.emissive_b
    else:
        eff_shader.emissive_color.r = 1.0
        eff_shader.emissive_color.g = 1.0
        eff_shader.emissive_color.b = 1.0
    eff_shader.emissive_color.a = si.material_alpha
    return ((si.emissive_r, si.emissive_g, si.emissive_b) if authored
            else None)


def _build_effect_shader(ts, tex_set, si, flip_ctrl, diffuse_path,
                         has_double_sided, fix_textures, stats):
    """The BSEffectShaderProperty for a flip-book or static FX surface.

    pyffi defaults UV scale to (0,0), which collapses every UV onto the
    texture's top-left texel and renders the quad invisible; vanilla is offset
    (0,0), scale (1,1).
    See: docs/commentary/asset_convert_shader.md#flipbook-to-atlas
    """
    frames = _flip_frames(flip_ctrl, fix_textures)
    atlas = plan_flipbook_atlas(frames, stats) if len(frames) >= 2 else None
    if frames:
        effective_path = frames[0].encode('utf-8')
    else:
        effective_path = tex_set.textures[0] if diffuse_path else b''

    eff_shader = NifFormat.BSEffectShaderProperty()
    eff_shader.uv_offset.u = 0.0
    eff_shader.uv_offset.v = 0.0
    eff_shader.uv_scale.u = 1.0
    eff_shader.uv_scale.v = 1.0
    esf1 = eff_shader.shader_flags_1
    esf1.slsf_1_own_emit = 1
    esf1.slsf_1_z_buffer_test = 1
    esf2 = eff_shader.shader_flags_2
    esf2.slsf_2_z_buffer_write = 0
    if has_double_sided:
        esf2.slsf_2_double_sided = 1
    if getattr(ts.data, 'has_vertex_colors', False):
        esf2.slsf_2_vertex_colors = 1
        esf1.slsf_1_vertex_alpha = 1
    eff_shader.source_texture = effective_path
    eff_shader.texture_clamp_mode = 3

    authored = _effect_emissive(eff_shader, si)
    if apply_fx_soft_effect(eff_shader, si.alpha_prop,
                            authored) and stats is not None:
        stats['fx_soft_effect'] = stats.get('fx_soft_effect', 0) + 1
    if atlas is not None:
        _atlas_controller(eff_shader, flip_ctrl, atlas)
    return eff_shader


def process_geometry(strips_or_shape, fix_textures, stats=None, sky_type=None):
    """Convert a NiTriStrips or NiTriShape into a ready Skyrim NiTriShape.

    Returns the shape, which is a NEW object when the input was uncontrolled
    strips.  UV curves are harvested before the controller strip, because
    NiUVController lives on the chain that strip removes.
    See: docs/commentary/asset_convert_nif.md#geometry-preparation
    """
    uv_transforms = collect_uv_ctrls(strips_or_shape)
    _strip_dead_geometry_controllers(strips_or_shape)
    ts, src = _as_tri_shape(strips_or_shape)
    _prepare_geometry_data(ts, src, stats)

    _si = collect_shader_inputs(src, uv_transforms)
    diffuse_path = _si.diffuse_path
    glow_path = _si.glow_path
    authored_normal = _si.authored_normal
    has_double_sided = _si.has_double_sided
    alpha_prop = _si.alpha_prop
    tex_apply_mode = _si.tex_apply_mode
    emissive_r = _si.emissive_r
    emissive_g = _si.emissive_g
    emissive_b = _si.emissive_b
    material_alpha = _si.material_alpha
    emissive_animated = _si.emissive_animated
    vertex_lighting_mode = _si.vertex_lighting_mode
    flip_ctrl = _si.flip_ctrl
    tex_transforms = _si.tex_transforms
    # Clear old properties
    ts.num_properties = 0
    ts.properties.update_size()

    # Build BSShaderTextureSet
    tex_set = NifFormat.BSShaderTextureSet()
    tex_set.num_textures = 9
    tex_set.textures.update_size()

    _fill_texture_slots(tex_set, diffuse_path, authored_normal,
                        fix_textures, stats)
    _spec_mask = has_spec_mask(tex_set.textures[1], stats)

    if sky_type is not None:
        return _build_sky_shader(ts, tex_set, diffuse_path, sky_type, stats)

    shader = NifFormat.BSLightingShaderProperty()
    _set_material_defaults(shader)

    sf1 = shader.shader_flags_1
    sf1.slsf_1_specular = 1
    sf1.slsf_1_recieve_shadows = 1
    sf1.slsf_1_cast_shadows = 1
    sf1.slsf_1_own_emit = 1
    sf1.slsf_1_remappable_textures = 1
    sf1.slsf_1_z_buffer_test = 1

    sf2 = shader.shader_flags_2
    sf2.slsf_2_z_buffer_write = 1
    sf2.slsf_2_env_map_light_fade = 1
    if has_double_sided:
        sf2.slsf_2_double_sided = 1
    if ts.data.has_vertex_colors:
        sf2.slsf_2_vertex_colors = 1

    shader.texture_clamp_mode = 3   # WRAP_S | WRAP_T
    shader.uv_scale.u = 1.0
    shader.uv_scale.v = 1.0
    shader.texture_set = tex_set

    _set_emissive(shader, sf1, emissive_r, emissive_g, emissive_b,
                  emissive_animated)
    shader.alpha = material_alpha

    is_static_fx = (flip_ctrl is None and diffuse_path
                    and _is_fx_surface(alpha_prop, vertex_lighting_mode))
    if flip_ctrl is not None or is_static_fx:
        ts.bs_properties[0] = _build_effect_shader(
            ts, tex_set, _si, flip_ctrl, diffuse_path, has_double_sided,
            fix_textures, stats)
    else:
        if not apply_glow(shader, tex_set, glow_path, stats):
            apply_parallax(ts, shader, tex_set, tex_apply_mode, stats)
        elif tex_apply_mode == APPLY_HILIGHT2 and stats is not None:
            stats['parallax_skipped_glow'] = \
                stats.get('parallax_skipped_glow', 0) + 1
        ts.bs_properties[0] = shader

    if tex_apply_mode == APPLY_HILIGHT2 and stats is not None:
        _overlay_key = _norm_tex_ref(tex_set.textures[0])
        if _overlay_key:
            stats.setdefault('overlay_diffuses', set()).add(_overlay_key)

    if alpha_prop is not None:
        if tex_apply_mode == APPLY_HILIGHT2 and (int(alpha_prop.flags) & 0x0001):
            stats['hilight2_alpha_dropped'] = \
                stats.get('hilight2_alpha_dropped', 0) + 1
        else:
            ts.bs_properties[1] = alpha_prop
            _dif = tex_set.textures[0] if tex_set.textures else None
            if _dif and stats is not None:
                if isinstance(_dif, bytes):
                    _dif = _dif.decode('utf-8', errors='replace')
                stats.setdefault('_alpha_opacity_diffuse', set()).add(
                    _dif.replace('/', '\\').lower())

    attach_tex_transform_ctrls(ts.bs_properties[0], tex_transforms)

    if getattr(ts, 'skin_instance', None) is not None:
        active_shader = ts.bs_properties[0]
        if isinstance(active_shader, NifFormat.BSLightingShaderProperty):
            active_shader.shader_flags_1.slsf_1_skinned = 1

    if hasattr(ts, 'data') and ts.data is not None:
        ts.data.unknown_int_2 = 0

    return ts


#: PyFFI defaults endian_type to 0 (BIG); Skyrim NIFs are little-endian.
ENDIAN_LITTLE = 1


#: Node-name prefixes Oblivion uses for geometry that must not ship.
_STRIPPED_NODE_PREFIXES = (b'SecretBigger', b'Secret Bigger', b'EditorMarker')


def _is_stripped_node(node):
    """Whether this node is editor-only or a load-distance hack.

    SecretBigger* are tiny triangles parked far below the origin to inflate
    the bounding sphere; EditorMarker* are hidden in Oblivion by a flag our
    conversion overwrites.  Both render as stray geometry in Skyrim.
    See: docs/commentary/asset_convert_nif.md#nodes-stripped-by-name
    """
    name = getattr(node, 'name', b'') or b''
    if not name:
        return False
    return any(name.startswith(p) for p in _STRIPPED_NODE_PREFIXES)


def _walk_geometry(node, fix_textures, stats):
    """Convert one shape, or None when it has no usable topology."""
    try:
        ts = process_geometry(node, fix_textures, stats,
                              sky_type=(stats or {}).get('_sky_type'))
    except UnreconstructibleGeometry as e:
        name = (node.name.decode('latin-1', 'replace')
                if isinstance(node.name, bytes) else str(node.name))
        print(f"  [warn] dropping triangle-less shape '{name}': {e}")
        stats['shapes_dropped'] = stats.get('shapes_dropped', 0) + 1
        return None
    if (isinstance(node, NifFormat.NiTriStrips)
            and not isinstance(ts, NifFormat.NiTriStrips)):
        stats['strips_fixed'] += 1
    stats['properties_converted'] += 1
    if ts is not node:
        stats.setdefault('_block_map', {})[id(node)] = ts
    return ts


def _string_palette(node):
    """The first NiStringPalette in the subtree, or None."""
    for block in node.tree():
        if isinstance(block, NifFormat.NiStringPalette):
            return block.palette
    return None


def _compact_children(node):
    """Drop the None slots stripped nodes left behind.

    pyffi writes a None ref as -1, but a non-zero num_children with null slots
    can confuse Skyrim.
    """
    keep = [c for c in node.children if c is not None]
    if len(keep) >= node.num_children:
        return
    node.num_children = len(keep)
    node.children.update_size()
    for i, child in enumerate(keep):
        node.children[i] = child


def _walk_ninode(node, fix_textures, stats):
    """Convert a NiNode in place and recurse into its children."""
    node.flags = NIF_FLAGS
    if getattr(node, 'num_effects', 0) > 0:
        node.num_effects = 0
        node.effects.update_size()

    if isinstance(getattr(node, 'controller', None),
                  NifFormat.NiControllerManager):
        process_controller_manager(node, _string_palette(node))

    for i in range(len(node.children)):
        result = walk_node(node, node.children[i], fix_textures, stats)
        if isinstance(result, NifFormat.NiBillboardNode):
            result = skyrimize_billboard(result)
        node.children[i] = result
    _compact_children(node)


def walk_node(parent, node, fix_textures, stats):
    """Convert a node and its children; the node that takes the parent's slot.

    None means the node is dropped: an editor marker, a load-distance hack, a
    dynamic effect, or a shape with no reconstructible topology.
    See: docs/commentary/asset_convert_nif.md#nodes-stripped-by-name
    """
    if node is None or _is_stripped_node(node):
        return None

    if isinstance(node, NifFormat.NiParticleSystem):
        convert_particle_system(node, fix_textures)
        node.flags = NIF_FLAGS
        return node

    if isinstance(node, NifFormat.NiDynamicEffect):
        stats['dynamic_effects_stripped'] = \
            stats.get('dynamic_effects_stripped', 0) + 1
        return None

    if isinstance(node, (NifFormat.NiTriStrips, NifFormat.NiTriShape)):
        return _walk_geometry(node, fix_textures, stats)

    if isinstance(node, NifFormat.NiNode):
        _walk_ninode(node, fix_textures, stats)
    return node


def _wrap_root_transform(root, has_skin, furn_shift):
    """Move a static root's rotation onto an inner NiNode; True when wrapped.

    Skyrim ignores BSFadeNode root rotation for static placement but honours a
    child NiNode's, so the transform moves down one level and the root is
    zeroed.  Collision STAYS on the root -- a bhkCollisionObject on a child
    node intermittently crashes hkpCollisionDispatcher -- so the rigid body
    absorbs the vanishing transform instead.  The furniture origin shift rides
    the same wrapper.
    See: docs/commentary/asset_convert_nif.md#root-rotation-wrapper
    """
    if has_skin or not (hasattr(root, 'rotation') and hasattr(root, 'children')):
        return False
    if _is_identity(root.rotation) and abs(furn_shift) <= 1e-4:
        return False

    inner = NifFormat.NiNode()
    inner.name = root.name
    inner.flags = NIF_FLAGS
    r = root.rotation
    for row in (1, 2, 3):
        for col in (1, 2, 3):
            setattr(inner.rotation, f'm_{row}{col}',
                    getattr(r, f'm_{row}{col}'))
    inner.translation.x = root.translation.x
    inner.translation.y = root.translation.y
    inner.translation.z = root.translation.z + furn_shift
    inner.scale = root.scale

    if getattr(root, 'collision_object', None) is not None:
        bake_node_transform_into_body(root.collision_object, root,
                                      extra_z=furn_shift)

    inner.num_children = root.num_children
    inner.children.update_size()
    for j in range(root.num_children):
        inner.children[j] = root.children[j]

    root.rotation = _identity_matrix()
    root.translation.x = 0.0
    root.translation.y = 0.0
    root.translation.z = 0.0
    root.scale = 1.0
    root.num_children = 1
    root.children.update_size()
    root.children[0] = inner
    return True


def _run_animation_passes(root, stats):
    """The sequence passes that must follow the geometry walk, in order.

    Order is the contract: morph emulation clones CONVERTED shapes, so it
    follows the walk and precedes rest visibility and sequence-name
    collection; the autoplay split precedes collect_sequence_names so the
    behaviour graph is built from the final names; shader controllers attach
    after the type match; interpolator normalising runs last.
    See: docs/commentary/asset_convert_nif.md#post-walk-animation-passes
    """
    match_seq_shader_types(root)
    emulate_morphs(root, stats)
    autoplay_ambient_sequences(root, stats)
    apply_rest_visibility(root, stats)
    attach_seq_shader_controllers(root, stats)
    normalize_blend_interpolators(root, stats)


def _wrap_geometry_root(data, i, root, stats):
    """Put a NiNode above a bare geometry root; the root to carry on with.

    Skyrim never ships a geometry root -- a 400-mesh vanilla census found 0
    (BSFadeNode 340, NiNode 55, BSMasterParticleSystem 2, BSLeafAnimNode 3) --
    and LODGenx64 hard-crashes with "Unable to cast NiTriShape to NiNode",
    abandoning the ENTIRE worldspace's object LOD rather than the one mesh.
    The geometry keeps its transform, so the wrap is visually identity.
    """
    if not isinstance(root, (NifFormat.NiTriShape, NifFormat.NiTriStrips)):
        return root
    holder = NifFormat.NiNode()
    holder.name = root.name
    holder.flags = NIF_FLAGS
    holder.num_children = 1
    holder.children.update_size()
    holder.children[0] = root
    data.roots[i] = holder
    stats['geometry_roots_wrapped'] = \
        stats.get('geometry_roots_wrapped', 0) + 1
    return holder


def _demote_billboard_root(root, bb_mode):
    """A plain NiNode carrying the billboard root's children and transform.

    The rotation is IDENTITY, not the billboard's: a NiBillboardNode discards
    its own rotation at runtime, so copying it onto the replacement revives a
    value the engine never used and skews the whole subtree.  Direct geometry
    children are re-wrapped in child billboards so the quads still face the
    camera.
    See: docs/commentary/asset_convert_nif.md#billboard-roots
    """
    plain = NifFormat.NiNode()
    plain.name = root.name
    plain.flags = NIF_FLAGS
    plain.translation = root.translation
    plain.rotation.set_identity()
    plain.scale = root.scale
    plain.num_children = root.num_children
    plain.children.update_size()
    for j, c in enumerate(root.children):
        plain.children[j] = c
    plain.num_extra_data_list = root.num_extra_data_list
    plain.extra_data_list.update_size()
    for j, ed in enumerate(root.extra_data_list):
        plain.extra_data_list[j] = ed
    if root.controller is not None:
        plain.controller = root.controller
    for j in range(len(plain.children)):
        c = plain.children[j]
        if isinstance(c, (NifFormat.NiTriShape, NifFormat.NiTriStrips)):
            plain.children[j] = wrap_in_billboard(c, bb_mode)
    return plain


def _normalise_billboard_root(data, i, root):
    """Demote a billboard root over particles, else wrap it; the new root.

    A NiBillboardNode re-orients its ENTIRE subtree every frame, which
    scrambles world-space particle emission -- the invisible flames.
    See: docs/commentary/asset_convert_nif.md#billboard-roots
    """
    if not isinstance(root, NifFormat.NiBillboardNode):
        return root
    has_psys = any(isinstance(b, NifFormat.NiParticleSystem)
                   for b in root.tree())
    if has_psys:
        bb_mode = int(getattr(root, 'billboard_mode', 1)) or 1
        new_root = _demote_billboard_root(root, bb_mode)
    else:
        new_root = NifFormat.NiNode()
        new_root.flags = NIF_FLAGS
        new_root.num_children = 1
        new_root.children.update_size()
        new_root.children[0] = root
    data.roots[i] = new_root
    return new_root


def _add_inv_marker(node, rot_x, rot_y, rot_z, zoom):
    """Append a BSInvMarker so the item is visible in the inventory viewer."""
    inv = NifFormat.BSInvMarker()
    inv.name = b'INV'
    inv.rotation_x = rot_x
    inv.rotation_y = rot_y
    inv.rotation_z = rot_z
    inv.zoom = zoom
    node.num_extra_data_list += 1
    node.extra_data_list.update_size()
    node.extra_data_list[node.num_extra_data_list - 1] = inv


def _repoint_root_refs(root, old_root):
    """Move every back-reference from the replaced root onto the new one.

    old_root leaves data.roots, so pyffi writes any surviving link to it as
    null and Skyrim null-derefs on load.  Three kinds of link point back:
    controller targets (including a NiMultiTargetTransformController's
    extra_targets array), NiDefaultAVObjectPalette entries, and a skinned
    shape's NiSkinInstance.skeleton_root.
    See: docs/commentary/asset_convert_nif.md#dangling-root-back-references
    """
    ctrl = root.controller
    while ctrl is not None:
        if getattr(ctrl, 'target', None) is old_root:
            ctrl.target = root
        for k in range(len(getattr(ctrl, 'extra_targets', ()) or ())):
            if ctrl.extra_targets[k] is old_root:
                ctrl.extra_targets[k] = root
        ctrl = getattr(ctrl, 'next_controller', None)

    mgr = root.controller
    palette = getattr(mgr, 'object_palette', None) if mgr is not None else None
    if palette is not None and hasattr(palette, 'num_objs'):
        for entry in palette.objs:
            if entry.av_object is old_root:
                entry.av_object = root

    for blk in root.tree():
        si = getattr(blk, 'skin_instance', None)
        if si is not None and si.skeleton_root is old_root:
            si.skeleton_root = root


def _prn_value(root):
    """The root's authored `Prn` attachment string, or None."""
    for ed in getattr(root, 'extra_data_list', ()):
        if not isinstance(ed, NifFormat.NiStringExtraData):
            continue
        if bytes(ed.name).rstrip(b'\x00') != b'Prn':
            continue
        return bytes(ed.string_data).rstrip(b'\x00').decode(
            'latin-1', errors='replace')
    return None


def _apply_shield_transform(fade):
    """Seat a shield on the forearm exactly where Oblivion had it.

    Oblivion straps the shield to 'Bip01 L ForearmTwist' with an identity root
    transform; Skyrim glues the NIF root to the 'SHIELD' bone at the hand grip.
    The mapping goes through anatomically corresponding hand frames of both
    skeletons, so no per-mesh bbox heuristic is involved.
    See: docs/commentary/asset_convert_armor.md#shield-attachment
    """
    t = shield_attach_transform()
    if t is None:
        return
    for r in range(3):
        for c in range(3):
            setattr(fade.rotation, f'm_{r + 1}{c + 1}', float(t[r, c]))
    fade.translation.x = float(t[3, 0])
    fade.translation.y = float(t[3, 1])
    fade.translation.z = float(t[3, 2])


def _apply_axe_flip(fade):
    """Rotate a side-carried weapon 180 degrees about the handle-blade axis.

    See: docs/commentary/asset_convert_armor.md#weapon-attachment
    """
    fade.rotation.m_11, fade.rotation.m_12, fade.rotation.m_13 = -1.0, 0.0, 0.0
    fade.rotation.m_21, fade.rotation.m_22, fade.rotation.m_23 = 0.0, 1.0, 0.0
    fade.rotation.m_31, fade.rotation.m_32, fade.rotation.m_33 = 0.0, 0.0, -1.0


def _convert_prn(root, fade, src_path):
    """Carry the authored Prn onto the new root, remapped to a Skyrim node.

    Weapons, shields and torches also gain the BSInvMarker Skyrim needs to
    resolve the equipped model.  A TORCH also hangs off the SHIELD node but is
    NOT a shield: it is authored at the grip in both games, so it must not get
    the shield's attach transform.
    See: docs/commentary/asset_convert_armor.md#shield-attachment
    """
    prn_val = _prn_value(root)
    if prn_val is None:
        return
    remapped = _remap_prn(prn_val, os.path.basename(src_path))

    if prn_val in _WEAPON_PRN_VALUES:
        _add_inv_marker(fade, WEAPON_INV_MARKER_ROT_X,
                        WEAPON_INV_MARKER_ROT_Y, WEAPON_INV_MARKER_ROT_Z,
                        WEAPON_INV_MARKER_ZOOM)
        if remapped != 'WeaponBow':
            _apply_axe_flip(fade)
    elif remapped == 'SHIELD' and prn_val == 'Torch':
        _add_inv_marker(fade, TORCH_INV_MARKER_ROT_X, TORCH_INV_MARKER_ROT_Y,
                        TORCH_INV_MARKER_ROT_Z, TORCH_INV_MARKER_ZOOM)
    elif remapped == 'SHIELD':
        _add_inv_marker(fade, SHIELD_INV_MARKER_ROT_X,
                        SHIELD_INV_MARKER_ROT_Y, SHIELD_INV_MARKER_ROT_Z,
                        SHIELD_INV_MARKER_ZOOM)
        _apply_shield_transform(fade)

    new_prn = NifFormat.NiStringExtraData()
    new_prn.name = b'Prn'
    new_prn.string_data = remapped.encode('latin-1')
    fade.num_extra_data_list += 1
    fade.extra_data_list.update_size()
    fade.extra_data_list[fade.num_extra_data_list - 1] = new_prn


def _prepare_creature_rig(data):
    """Rename the rig to Skyrim's contract and add the equip nodes.

    The rig root MUST be 'NPC Root [Root]': the engine binds the graph to the
    actor through that name, so a 'Bip01' root spawns an invisible actor.  The
    rename covers every body part too, since skin bones resolve by node name.

    Oblivion-runtime bone controllers go first: vanilla Skyrim creature assets
    have none, because the behaviour graph drives the bones.
    """
    _strip_creature_bone_controllers(data)
    renames = {k.encode('latin-1'): v.encode('latin-1')
               for k, v in BONE_RENAMES.items()}
    for root in data.roots:
        if root is None:
            continue
        for block in root.tree():
            nm = getattr(block, 'name', None)
            if nm is None:
                continue
            key = bytes(nm).rstrip(b'\x00')
            if key in renames:
                block.name = renames[key]
    _add_creature_equip_nodes(data)


def _rigid_skin_creature_parts(data):
    """Rigid-skin Prn-attached creature parts to their original bone.

    Heads, eyes and tails: the verts are baked into bone-local space first
    because add_prn_skin writes an identity bind, and the bone keeps its
    OBLIVION name, since the converted creature skeleton does too.
    See: docs/commentary/asset_convert_armor.md#rigid-prn-skinning
    """
    for root in data.roots:
        if root is not None and get_prn_bone(root) is not None:
            bake_node_transforms_into_verts(root)
            add_prn_skin(data, root, keep_bone_names=True, plain=True)


def _prepare_worn_armor(data, has_skin, is_shield, authored_bp):
    """Give worn armor a dismember skin; the updated has_skin.

    A non-skinned piece is rigid-skinned after baking the ROOT transform into
    the verts; the geometry node's own transform is deliberately NOT baked,
    because skin_retarget composes it with the Skyrim bone position.
    See: docs/commentary/asset_convert_armor.md#rigid-prn-skinning
    """
    if not has_skin and not is_shield:
        fallback = BODY_PART_FALLBACK_PRN_BONE.get(authored_bp)
        for root in data.roots:
            if root is not None:
                bake_root_transform_into_verts(root)
                add_prn_skin(data, root, fallback_bone=fallback)
        has_skin = _has_skin(data)
    if has_skin:
        upgrade_skin_instances(data)
    return has_skin


#: Vanilla creature skeleton BSXFlags: Havok | Ragdoll | Dynamic | Articulated.
_CREATURE_SKELETON_BSX = 198


def _set_bsx_value(root, value):
    """Force the root's BSXFlags to `value`, adding the block if absent."""
    if not hasattr(root, 'extra_data_list'):
        return
    bsx = next((ed for ed in root.extra_data_list
                if isinstance(ed, NifFormat.BSXFlags)), None)
    if bsx is None:
        bsx = NifFormat.BSXFlags()
        bsx.name = b'BSX'
        root.num_extra_data_list += 1
        root.extra_data_list.update_size()
        root.extra_data_list[root.num_extra_data_list - 1] = bsx
    bsx.integer_data = value


def _convert_root_collision(data, root, creature, nif_basename,
                            has_constraints):
    """Convert every collision object under `root`; the updated flag.

    Child-node collisions need the same Skyrim-format fields as the root's.
    A creature skeleton drops its marker proxies BEFORE the conversion, while
    the bodies still carry SOURCE units, so hkx_ragdoll's predicate agrees
    body for body.
    See: docs/commentary/asset_convert_creature.md#creature-mesh-merge
    """
    if creature and 'skeleton' in nif_basename:
        strip_marker_collision_bodies(data, root)
    convert_all_collisions(root, keep_blend=creature)
    if has_constraints:
        scale_constraint_pivots(data)
    if creature and 'skeleton' in nif_basename:
        if enforce_ragdoll_tree(data, root):
            has_constraints = True

    add_bsx_flags(root, has_constraints=has_constraints)
    if creature and 'skeleton' in nif_basename:
        _set_bsx_value(root, _CREATURE_SKELETON_BSX)
    return has_constraints


def _regen_creature_skins(data, authored_bp, authored_allowed):
    """Rebuild every creature skin partition in Skyrim triangle format.

    Creature skins keep their Oblivion bones, weights and bind matrices
    verbatim -- the skeleton is the same -- so only the partition changes.  It
    must run after the strips-to-shapes pass, which is what gives
    update_skin_partition triangles to read.  The 80-bone cap is applied later,
    in merge_creature_body, because part NIFs store bones flat.
    """
    from asset_convert.character.skin_retarget import regen_skin_partition
    for root in data.roots:
        if root is None:
            continue
        for block in list(root.tree()):
            if not isinstance(block, (NifFormat.NiTriShape,
                                      NifFormat.NiTriStrips)):
                continue
            skin = getattr(block, 'skin_instance', None)
            if skin is None:
                continue
            geom_name = bytes(block.name).rstrip(b'\x00').decode(
                'latin-1', errors='replace')
            regen_skin_partition(block, skin, geom_name,
                                 authored_body_part=authored_bp,
                                 authored_allowed=authored_allowed)


#: Biped slot -> the offset table entry that fits a piece on that slot.
_BP_TO_PIECE = {131: 'helmet', 32: 'cuirass', 44: 'greaves',
                33: 'gauntlets', 37: 'boots'}


def _offset_slot(data, single_slot, slot_for_offset, authored_allowed):
    """Which offset entry fits this NIF: the stated slot, or the vertex mass.

    ONE offset applies to the whole NIF, so a record claiming a SINGLE slot
    answers it outright.  A multi-slot record has no stated answer, and taking
    its head-ward slot lifted a whole suit by the helmet's dz.
    See: docs/commentary/asset_convert_armor.md#armor-offset-slot
    """
    if single_slot:
        return slot_for_offset
    from asset_convert.character.skin_retarget import dominant_body_part
    return dominant_body_part(data, allowed=authored_allowed)


def _apply_head_and_offsets(data, src_path, piece_type, prn_block_ids,
                            prn_head_ids, hair):
    """Fit rigid head gear by measurement, then apply the fallback offsets.

    The two skulls differ in SHAPE, not by a factor, so head gear is fitted
    per vertex rather than scaled.  Skinned geometry is exact under the wrap
    once the field carries a head surface; the FK constants remain the
    fallback whenever the fit data is unavailable.
    See: docs/commentary/asset_convert_armor.md#head-gear-fit
    """
    from asset_convert.character.body_wrap import wrap_available, wrap_has_head
    skinned_head_ok = wrap_has_head(src_path)
    if not wrap_available(src_path) or (piece_type == 'helmet'
                                        and not skinned_head_ok):
        cfg = ARMOR_PIECE_OFFSETS.get(piece_type,
                                      ARMOR_PIECE_OFFSETS['default'])
        apply_armor_offset(data, cfg, exclude_block_ids=prn_block_ids)
    legacy = prn_block_ids - prn_head_ids
    if legacy:
        cfg_prn = ARMOR_PIECE_OFFSETS_PRN.get(
            piece_type, ARMOR_PIECE_OFFSETS_PRN['default'])
        apply_armor_offset(data, cfg_prn, only_block_ids=legacy)


def _retarget_worn_armor(data, stats, src_path, weight, race, hair, has_skin,
                         authored_bp, authored_allowed, single_slot,
                         slot_for_offset):
    """Retarget a worn piece onto the Skyrim skeleton; (slot, body splices).

    Bones are renamed only AFTER the skin transforms are correct, and the body
    skin is collected after that, when the verts sit in Skyrim space.
    See: docs/commentary/asset_convert_armor.md#head-gear-fit
    """
    from asset_convert.character.skin_retarget import retarget_skin_to_skyrim

    slot_for_offset = _offset_slot(data, single_slot, slot_for_offset,
                                   authored_allowed)
    piece_type = _BP_TO_PIECE.get(slot_for_offset, 'default')

    prn_block_ids = set()
    retarget_skin_to_skyrim(data, src_path=src_path, prn_out=prn_block_ids,
                            weight=weight, authored_body_part=authored_bp,
                            authored_allowed=authored_allowed, race=race)
    stats['bones_remapped'] += remap_bone_names(data)

    body_nibs = collect_skin_info(data, src_path=src_path)
    strip_body_skin_geometry(data)

    prn_head_ids = set()
    if prn_block_ids and not hair:
        prn_head_ids = fit_prn_head_blocks(data, prn_block_ids, src_path,
                                            race=race)
    if not hair:
        _apply_head_and_offsets(data, src_path, piece_type, prn_block_ids,
                                prn_head_ids, hair)
    if piece_type == 'helmet' and (prn_head_ids or has_skin):
        stats['_head_gear'] = True
    return slot_for_offset, body_nibs


def _add_bow_rig(data, stats, string_masks):
    """Graft the vanilla 7-bone bend rig and its BGED onto a converted bow.

    Runs LAST: it needs the final NiTriShape geometry and a BSFadeNode root
    whose Prn is already remapped to WeaponBow.
    """
    from asset_convert.character.bow_rig import add_bow_rig
    for root in data.roots:
        if root is not None and get_prn_bone(root) == 'WeaponBow':
            stats['bow_rig_shapes'] = add_bow_rig(data, string_masks)
            return


def _destripify_skin_partitions(data, stats):
    """Rewrite any skin partition still in STRIP format as triangles.

    Skyrim's renderer draws a skinned shape from the partition, not the
    NiTriShapeData, so a strip partition gives it no triangles at all and the
    shape renders as the red missing-geometry marker.
    See: docs/commentary/asset_convert_nif.md#strip-format-skin-partitions
    """
    from asset_convert.character.skin_retarget import regen_skin_partition
    for root in data.roots:
        if root is None:
            continue
        for block in list(root.tree()):
            if not isinstance(block, (NifFormat.NiTriShape,
                                      NifFormat.NiTriStrips)):
                continue
            skin = getattr(block, 'skin_instance', None)
            if skin is None or skin.skin_partition is None:
                continue
            if not any(pb.num_strips > 0
                       for pb in skin.skin_partition.skin_partition_blocks):
                continue
            geom_name = bytes(block.name).rstrip(b'\x00').decode(
                'latin-1', errors='replace')
            regen_skin_partition(block, skin, geom_name)
            stats['skin_partitions_destripified'] = \
                stats.get('skin_partitions_destripified', 0) + 1


def _inv_marker_of(root):
    """The root's existing BSInvMarker, or None."""
    for ed in getattr(root, 'extra_data_list', []) or []:
        if isinstance(ed, NifFormat.BSInvMarker):
            return ed
    return None


def _finalise_inv_markers(data, stats):
    """Orient every inventory-visible mesh from its finished geometry.

    Weapons and shields already sit in Skyrim's normalised attachment frames,
    so their constant markers are exact and are left alone.  Everything else
    is still in an arbitrary Oblivion modelling frame, where a fixed rotation
    shows a random side.
    See: docs/commentary/asset_convert_nif.md#inventory-marker-orientation
    """
    from asset_convert.nif.inv_marker import compute_inv_rotation
    skinned = _has_skin(data)
    for root in data.roots:
        if root is None or type(root).__name__ != 'BSFadeNode':
            continue
        if get_prn_bone(root) in _EQUIPPED_PRN_VALUES:
            continue
        marker = _inv_marker_of(root)
        if marker is None and skinned:
            continue
        rot = compute_inv_rotation(root)
        if rot is None:
            continue
        if marker is None:
            marker = NifFormat.BSInvMarker()
            marker.name = b'INV'
            marker.zoom = 1.0
            root.num_extra_data_list += 1
            root.extra_data_list.update_size()
            root.extra_data_list[root.num_extra_data_list - 1] = marker
        marker.rotation_x, marker.rotation_y, marker.rotation_z = rot
        stats['inv_markers_computed'] = \
            stats.get('inv_markers_computed', 0) + 1


def _prepare_armor_root(root):
    """Ready a worn-armor NiNode root, which stays a NiNode.

    Skyrim positions worn armor from the ARMA's biped slot, so a `Prn` naming
    an Oblivion bone only mis-attaches it and is stripped.
    """
    root.flags = NIF_FLAGS
    if getattr(root, 'num_effects', 0) > 0:
        root.num_effects = 0
        root.effects.update_size()
    if not hasattr(root, 'extra_data_list'):
        return
    keep = [ed for ed in root.extra_data_list
            if not (isinstance(ed, NifFormat.NiStringExtraData)
                    and bytes(ed.name).rstrip(b'\x00') == b'Prn')]
    if len(keep) < root.num_extra_data_list:
        root.num_extra_data_list = len(keep)
        root.extra_data_list.update_size()
        for i, ed in enumerate(keep):
            root.extra_data_list[i] = ed


def _walk_root_children(root, fix_textures, stats):
    """Convert every child of the root, then compact the stripped slots."""
    if not hasattr(root, 'children'):
        return
    for j in range(len(root.children)):
        res = walk_node(root, root.children[j], fix_textures, stats)
        if isinstance(res, NifFormat.NiBillboardNode):
            res = skyrimize_billboard(res)
        root.children[j] = res
    _compact_children(root)


def _remap_replaced_blocks(root, block_map):
    """Re-point second links at the shapes that replaced their strips.

    A NiDefaultAVObjectPalette entry and a NiPSysMeshEmitter's emitter_meshes
    both reference geometry OUTSIDE the children arrays the walk rewrites, so
    each still names the orphaned NiTriStrips.  pyffi re-serialises that block
    because it is still reachable, leaving raw Oblivion strips in a Skyrim
    file, and the engine fails the whole NIF.
    See: docs/commentary/asset_convert_nif.md#second-links-to-replaced-geometry
    """
    if not block_map:
        return
    mgr = root.controller
    palette = getattr(mgr, 'object_palette', None) if mgr is not None else None
    if palette is not None and hasattr(palette, 'num_objs'):
        for entry in palette.objs:
            replacement = block_map.get(id(entry.av_object))
            if replacement is not None:
                entry.av_object = replacement

    for block in root.tree():
        if not isinstance(block, NifFormat.NiPSysMeshEmitter):
            continue
        for mi in range(len(block.emitter_meshes)):
            replacement = block_map.get(id(block.emitter_meshes[mi]))
            if replacement is not None:
                block.emitter_meshes[mi] = replacement


def _hide_emitter_sources(root, stats):
    """Hide the shapes that only say where particles spawn.

    Oblivion hides them with NiMaterialProperty.alpha 0; Skyrim has no such
    property and the conversion forces every node visible, so they shipped as
    solid untextured boxes over the effect.
    See: docs/commentary/asset_convert_nif.md#helper-geometry-must-not-draw
    """
    for block in root.tree():
        if not isinstance(block, NifFormat.NiPSysMeshEmitter):
            continue
        for mesh in block.emitter_meshes:
            if mesh is None:
                continue
            mesh.flags = int(mesh.flags) | 0x0001
            for pi in range(len(mesh.bs_properties)):
                mesh.bs_properties[pi] = None
            stats['emitter_meshes_hidden'] = \
                stats.get('emitter_meshes_hidden', 0) + 1


def _hide_uvless_lit_shapes(root, stats):
    """Drop the shader and hide any lit shape with no UVs.

    A BSLightingShaderProperty ALWAYS samples a diffuse texcoord, so UV-less
    geometry makes it read past the vertex buffer.  Genuine geometry always
    has UVs, so this can only catch helper volumes.
    See: docs/commentary/asset_convert_nif.md#helper-geometry-must-not-draw
    """
    for block in root.tree():
        if not isinstance(block, NifFormat.NiTriBasedGeom):
            continue
        geom_data = getattr(block, 'data', None)
        if geom_data is None or int(getattr(geom_data, 'num_uv_sets', 0) or 0):
            continue
        props = getattr(block, 'bs_properties', None)
        if props is None:
            continue
        lit = [pi for pi, p in enumerate(props)
               if isinstance(p, NifFormat.BSLightingShaderProperty)]
        if not lit:
            continue
        for pi in lit:
            props[pi] = None
        block.flags = int(block.flags) | 0x0001
        stats['uvless_lit_shapes_hidden'] = \
            stats.get('uvless_lit_shapes_hidden', 0) + 1


def _hide_helper_geometry(root, stats):
    """Hide the Oblivion helper volumes that must never be drawn."""
    _hide_emitter_sources(root, stats)
    _hide_uvless_lit_shapes(root, stats)


def _hoist_root_collision(root, wrapped, root_is_animated, has_constraints,
                          creature):
    """Move a child's collision onto the root, where Skyrim wants it.

    Skipped when the root was wrapped (hoisting from under the wrapper would
    have to compose the WRAPPER's transform too, and the wrap path already
    absorbs it), for animated objects (the keyframed body must follow the
    animated child), for constrained NIFs (the spatial relationship is the
    constraint), and for creatures (ragdoll collision lives on the bones).
    """
    if wrapped or root_is_animated or has_constraints or creature:
        return
    if not hasattr(root, 'collision_object') or root.collision_object is not None:
        return
    if hoist_collision(root):
        remove_empty_collision_nodes(root)


def _run_source_fixups(data):
    """Repair the source tree before the version upgrade changes how it reads.

    See: docs/commentary/asset_convert_nif.md#pre-upgrade-source-fixups
    """
    _prune_orphan_roots(data)
    resolve_palette_strings(data)
    convert_sound_text_keys(data)
    fix_controller_flags(data)
    sanitize_geometry_data(data)


def _classify_wearable(src_path, nif_basename, worn, biped_flags):
    """What the plugin says this mesh IS: armor, shield, and which slots.

    The wearing record's biped flags are AUTHORED data and always beat the
    filename or the folder.  Folder alone is never enough -- Nehrim files its
    armor under eyren/, spinat/, nehrim/ and skeletonk/, and would lose the
    dismember skin, the NiNode root and the retarget on all 88 of them.
    Bit 13 of BMDT is Shield, and it catches what a filename check misses:
    'towersheild.nif' is misspelled.
    See: docs/commentary/asset_convert_armor.md#armor-offset-slot
    """
    lowered = src_path.lower().replace('\\', '/')
    in_armor_dir = worn or 'armor' in lowered or 'clothes' in lowered
    is_shield = (bool(biped_flags & (1 << 13)) if biped_flags
                 else 'shield' in nif_basename)
    authored_bp = body_part_for_flags(biped_flags) if biped_flags else None
    allowed = body_parts_for_flags(biped_flags) if biped_flags else None
    single_slot = allowed is not None and len(allowed) == 1
    return {
        'in_armor_dir': in_armor_dir,
        'is_shield': is_shield,
        'authored_bp': authored_bp,
        'authored_allowed': allowed,
        'single_slot': single_slot,
        'slot_for_offset': authored_bp if single_slot else None,
    }


def _capture_bow_masks(data, nif_basename, is_gnd, in_armor_dir):
    """(is a bow, string vertex masks) read before the morpher is stripped.

    Detection mirrors _remap_prn: Prn='BackWeapon' plus 'bow' in the filename.
    """
    if 'bow' not in nif_basename or is_gnd or in_armor_dir:
        return False, {}
    for root in data.roots:
        if root is not None and get_prn_bone(root) == 'BackWeapon':
            from asset_convert.character.bow_rig import capture_string_masks
            return True, capture_string_masks(data)
    return False, {}


def _copy_root_frame(fade, root):
    """Copy the root's transform, children, controller and collision across."""
    fade.name = root.name
    fade.flags = NIF_FLAGS
    fade.translation = root.translation
    fade.rotation = root.rotation
    fade.scale = root.scale
    if hasattr(root, 'collision_object'):
        fade.collision_object = root.collision_object
        if fade.collision_object is not None:
            fade.collision_object.target = fade
    fade.num_children = root.num_children
    fade.children.update_size()
    for j, child in enumerate(root.children):
        fade.children[j] = child
    if root.controller is not None:
        fade.controller = root.controller


def _append_extra(node, block):
    """Append one extra-data block to `node`."""
    node.num_extra_data_list += 1
    node.extra_data_list.update_size()
    node.extra_data_list[node.num_extra_data_list - 1] = block


def _carry_bsbound(fade, root, stats):
    """Carry the actor bounding box across, if the source has one.

    The engine uses BSBound as the actor's physical bounds, so a creature
    skeleton without one has nothing for the ragdoll handoff to land on.  Its
    values are NIF object space, not Havok space, so they copy verbatim.
    See: docs/commentary/asset_convert_nif.md#dangling-root-back-references
    """
    for ed in root.extra_data_list:
        if isinstance(ed, NifFormat.BSBound):
            _append_extra(fade, ed)
            stats['bsbound_kept'] = stats.get('bsbound_kept', 0) + 1
            return


def _carry_furniture_markers(fade, root, stats):
    """Convert Oblivion floor entry points into Skyrim seat positions."""
    markers = [ed for ed in root.extra_data_list
               if isinstance(ed, NifFormat.BSFurnitureMarker)
               and not isinstance(ed, NifFormat.BSFurnitureMarkerNode)]
    if not markers:
        return
    frn, furn_shift = _convert_furniture_markers(markers, root)
    if frn is None:
        return
    _append_extra(fade, frn)
    stats['furniture_markers'] = stats.get('furniture_markers', 0) + 1
    stats['_furn_origin_shift'] = furn_shift


def _to_fade_node(data, i, root, stats, src_path, wants_gnd_marker):
    """Replace a NiNode root with a BSFadeNode; the new root.

    Extra data is carried SELECTIVELY -- a bulk copy breaks animated objects.
    See: docs/commentary/asset_convert_nif.md#dangling-root-back-references
    """
    old_root = root
    fade = NifFormat.BSFadeNode()
    _copy_root_frame(fade, root)
    if hasattr(root, 'extra_data_list'):
        _carry_bsbound(fade, root, stats)
        _carry_furniture_markers(fade, root, stats)
        _convert_prn(root, fade, src_path)

    data.roots[i] = fade
    stats['root_converted'] += 1
    if wants_gnd_marker:
        _add_inv_marker(fade, ARMOR_GND_INV_MARKER_ROT_X,
                        ARMOR_GND_INV_MARKER_ROT_Y,
                        ARMOR_GND_INV_MARKER_ROT_Z,
                        ARMOR_GND_INV_MARKER_ZOOM)
    _repoint_root_refs(fade, old_root)
    return fade


def _convert_one_root(data, i, root, stats, fix_textures, src_path, creature,
                      nif_basename, has_skin, is_worn_armor, wants_gnd_marker):
    """Convert one root in place.

    Root normalisation, the NiNode->BSFadeNode swap (or the worn-armor
    equivalent), the tree walk, the animation passes and the collision work,
    in the order each depends on the last.
    """
    root = _wrap_geometry_root(data, i, root, stats)
    root = _normalise_billboard_root(data, i, root)

    is_sky = stats.get('_sky_type') is not None
    if type(root).__name__ == 'NiNode' and not is_worn_armor and not is_sky:
        root = _to_fade_node(data, i, root, stats, src_path, wants_gnd_marker)
    elif type(root).__name__ == 'NiNode' and is_worn_armor:
        _prepare_armor_root(root)

    if isinstance(getattr(root, 'controller', None),
                  NifFormat.NiControllerManager):
        process_controller_manager(root, None)

    furn_shift = stats.pop('_furn_origin_shift', 0.0)
    wrapped = _wrap_root_transform(root, has_skin, furn_shift)
    if wrapped:
        stats['root_rotation_baked'] += 1

    _walk_root_children(root, fix_textures, stats)
    _remap_replaced_blocks(root, stats.get('_block_map', {}))
    _run_animation_passes(root, stats)
    _hide_helper_geometry(root, stats)

    root_is_animated = isinstance(getattr(root, 'controller', None),
                                  NifFormat.NiControllerManager)
    has_constraints = any(isinstance(b, NifFormat.bhkConstraint)
                          for b in data.blocks)
    _hoist_root_collision(root, wrapped, root_is_animated, has_constraints,
                          creature)
    _convert_root_collision(data, root, creature, nif_basename,
                            has_constraints)


def _convert_nif(data, fix_textures=True, src_path='', weight=0,
                 creature=False, worn=False, parallax=False, biped_flags=0,
                 tex_fallback=(), hair=False, race=None):
    """Convert a PyFFI NifFormat.Data in-place to Skyrim format; stats dict.

    worn, parallax and creature each select a different path.
    See: docs/commentary/asset_convert_nif.md#convert-nif-path-flags
    Worn gear keeps a NiNode root; shields and _gnd take BSFadeNode, and a
    _gnd model's cloth-physics bones are stripped first.
    See: docs/commentary/asset_convert_armor.md#nif-worn-armor-conversion
    Body geometry is spliced after the retarget.
    See: docs/commentary/asset_convert_armor.md#body-splice-fill-partition
    """
    stats = {
        'strips_fixed': 0,
        'properties_converted': 0,
        'root_converted': 0,
        'root_rotation_baked': 0,
        'tangents_injected': 0,
        'bones_remapped': 0,
        'textures_fixed': 0,
        '_src_path': str(src_path),
        '_tex_fallback': tex_fallback or (),
        '_parallax': bool(parallax),
        '_sky_type': sky_object_type_for(src_path),
    }

    _run_source_fixups(data)
    has_skin = _has_skin(data)

    nif_basename = os.path.basename(src_path).lower()
    _is_gnd = is_ground_model(nif_basename)
    _cls = _classify_wearable(src_path, nif_basename, worn, biped_flags)
    _in_armor_dir = _cls['in_armor_dir']
    _is_shield = _cls['is_shield']
    _authored_bp = _cls['authored_bp']
    _authored_allowed = _cls['authored_allowed']
    _single_slot = _cls['single_slot']
    _slot_for_offset = _cls['slot_for_offset']

    _is_bow_weapon, _bow_string_masks = _capture_bow_masks(
        data, nif_basename, _is_gnd, _in_armor_dir)

    if _is_gnd and has_skin:
        strip_gnd_skin(data)
        has_skin = False

    _body_nibs_to_splice: dict = {}

    if creature:
        _prepare_creature_rig(data)
    if creature and not has_skin:
        _rigid_skin_creature_parts(data)
        has_skin = _has_skin(data)
    if not creature and not _is_gnd and _in_armor_dir:
        has_skin = _prepare_worn_armor(data, has_skin, _is_shield,
                                       _authored_bp)

    data.version = OUTPUT_VERSION
    data.user_version = OUTPUT_USER_VERSION
    data.user_version_2 = OUTPUT_USER_VERSION_2
    data.header.endian_type = ENDIAN_LITTLE

    _is_creature_body = creature and has_skin
    _is_worn_armor = (not _is_gnd and _in_armor_dir and not _is_shield) \
        or _is_creature_body

    for i, root in enumerate(data.roots):
        if root is not None:
            _convert_one_root(data, i, root, stats, fix_textures, src_path,
                              creature, nif_basename, has_skin,
                              _is_worn_armor, _is_gnd and _in_armor_dir)

    if creature and has_skin:
        _regen_creature_skins(data, _authored_bp, _authored_allowed)

    if not creature and not _is_gnd and _in_armor_dir and has_skin:
        _slot_for_offset, _body_nibs_to_splice = _retarget_worn_armor(
            data, stats, src_path, weight, race, hair, has_skin,
            _authored_bp, _authored_allowed, _single_slot, _slot_for_offset)

    if _body_nibs_to_splice:
        _fill_bp = (_authored_bp if _single_slot else _slot_for_offset) or 32
        splice_body_geometry(data, _body_nibs_to_splice, fill_body_part=_fill_bp)

    if _is_bow_weapon:
        _add_bow_rig(data, stats, _bow_string_masks)
    _destripify_skin_partitions(data, stats)
    if not creature:
        _finalise_inv_markers(data, stats)

    stats['tangents_injected'] = stats['properties_converted']

    return stats


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def convert_nif(src_path, dst_path, *, fix_textures=True, remap_skeleton=None,
                src_meshes_dir=None, creature=False, wearable_plan=None,
                parallax=False, textures_only=False, tex_fallback=(),
                hair=False, race=None):
    """Convert a single Oblivion NIF to Skyrim format.

    Already-Skyrim versions are copied to dst_path unchanged.
    Unsupported/incompatible versions are skipped (not written to dst_path).
    Returns a result dict compatible with batch_convert's _update() expectations.

    src_meshes_dir: root of the source mesh tree (passed through by
    batch_convert), used to key a NIF against the wearable plan.

    wearable_plan: mapping from asset_convert.character.wearable_plan.build_plan, naming
    the _0/_1/plain variants each armor/clothing mesh is referenced as.  None
    disables weight-variant output entirely.

    parallax: carry Oblivion's parallax across (opt-in — see apply_parallax).

    textures_only: read and analyse every mesh, write NONE of them.  The
    height maps still get built, because the decision to build one needs the
    mesh's own APPLY_HILIGHT2 flag — see the mode's rationale in batch_convert.

    hair: this NIF is an Oblivion hair head part (asset_convert.character.hair_pipeline).
    Hair lives outside meshes\armor and no ARMO/CLOT record names it, so the
    wearable plan cannot mark it worn — but it is rigid Prn-attached geometry
    that needs exactly the same treatment as a helmet: a dismember skin bound
    to the head bone in slot 131.  Without this the mesh ships unskinned and
    also picks up a meaningless BSInvMarker (hair is never an inventory item).

    race: fit head gear to a BEAST race's skull instead of the shared human
    one (head_fit.BEAST_RACES).  Set only by the beast-variant pass below,
    which re-runs this conversion once per race; None is the normal path.
    """
    result = {
        'converted': False,
        'skipped': False,
        'copied': False,           # already-Skyrim, copied as-is
        'skip_reason': None,       # VER | RD | WR
        'error': None,
        'strips_fixed': False,
        'properties_converted': False,
        'root_converted': False,
        'root_rotation_baked': False,
        'version_upgraded': False,
        'textures': set(),         # texture paths this mesh references
        'overlay_diffuses': set(), # of those, the APPLY_HILIGHT2 overlays
    }

    if not _PYFFI:
        result['error'] = 'pyffi not installed'
        return result

    # Inspect version without full read
    data = NifFormat.Data()
    try:
        with open(src_path, 'rb') as f:
            data.inspect(f)
    except Exception:
        result['error'] = 'RD'
        return result

    if (data.version, data.user_version_2) in _SKYRIM_VERSIONS:
        # Already Skyrim — copy as-is.  Nothing rewrote its texture paths, so
        # scan the bytes for them; the prune must not drop what this still uses.
        dst_dir = os.path.dirname(dst_path)
        if dst_dir:
            os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        with open(src_path, 'rb') as f:
            _harvest_texture_bytes(f.read(), result['textures'])
        result['copied'] = True
        return result

    if data.version not in _SUPPORTED_VERSIONS:
        # Too old or unrecognised — skip, do not copy
        result['error'] = 'VER'
        return result

    # Full read (fresh Data object so inspect state is clean)
    data = NifFormat.Data()
    try:
        with open(src_path, 'rb') as f:
            data.inspect(f)
            data.read(f)
    except Exception:
        result['error'] = 'RD'
        return result

    # Standalone animation files (e.g. creatures/*/idleanims/*.nif) hold only a
    # NiControllerSequence — no scene graph at all.  There is nothing to convert
    # and every pass below assumes a NiAVObject root, so skip rather than crash.
    if not any(isinstance(r, NifFormat.NiAVObject) for r in data.roots):
        result['error'] = 'NOGEO'
        return result

    # Does the plugin itself wear this mesh?  Asked before the conversion so the
    # armor rules (dismember skin, NiNode root, skeleton retarget) apply to gear
    # filed outside meshes\armor and meshes\clothes.
    _worn = bool(hair)
    # Biped bit 1 (Hair) — the same authored slot a helmet-bearing record
    # would carry, so the converter resolves body part 131 without guessing.
    _biped_flags = 0x02 if hair else 0
    if wearable_plan is not None and src_meshes_dir is not None and not creature             and not hair:
        from asset_convert.character import wearable_plan as _wp
        _worn = _wp.is_worn(wearable_plan, src_path, src_meshes_dir)
        # What the plugin says this mesh IS (head/body/hands/feet/shield), so
        # the converter never has to guess the slot from the filename.
        _biped_flags = _wp.biped_flags_for(wearable_plan, src_path,
                                           src_meshes_dir)

    stats = _convert_nif(data, fix_textures=fix_textures,
                         src_path=str(src_path), creature=creature,
                         worn=_worn, parallax=parallax,
                         biped_flags=_biped_flags,
                         tex_fallback=tex_fallback, hair=hair, race=race)

    _run_post_passes(data, stats, result, src_path, dst_path, textures_only)

    _harvest_textures(data, result['textures'])
    result['overlay_diffuses'] = stats.get('overlay_diffuses', set())
    if textures_only:
        return _finish_result(result, stats)

    buf = _io.BytesIO()
    try:
        data.write(buf)
    except Exception:
        result['error'] = 'WR'
        return result

    dst_dir = os.path.dirname(dst_path)
    if dst_dir:
        os.makedirs(dst_dir, exist_ok=True)
    with open(dst_path, 'wb') as f:
        f.write(buf.getvalue())

    _write_weight_variants(data, buf, src_path, dst_path, src_meshes_dir,
                           wearable_plan, creature, race)
    if stats.get('_head_gear') and not creature and not hair and race is None:
        _write_beast_head_variants(
            src_path, dst_path,
            fix_textures=fix_textures, src_meshes_dir=src_meshes_dir,
            wearable_plan=wearable_plan, parallax=parallax)
    return _finish_result(result, stats)


def _output_root(dst_path):
    """(tree root, meshes root, model path) around `dst_path`'s meshes/.

    Only convert_nif knows where the output tree is, so the texture passes
    that write beside it resolve their roots here.  All three are None when
    the destination is not inside a meshes/ tree.
    """
    dstn = str(dst_path).replace('/', os.sep).replace('\\', os.sep)
    key = os.sep + 'meshes' + os.sep
    i = dstn.lower().rfind(key)
    if i < 0:
        return None, None, None
    return dstn[:i] + os.sep, dstn[:i + len(key)], dstn[i + len(key):]


def _build_flip_atlases(stats, dst_path):
    """Compose the frame-strip atlases process_geometry planned."""
    jobs = stats.pop('_flipbook_atlases', {})
    if not jobs:
        return
    out_root = _output_root(dst_path)[0]
    if out_root is None:
        return
    from asset_convert.nif import flipbook
    for job in jobs.values():
        out = out_root + job['atlas_rel'].replace('\\', os.sep)
        if os.path.isfile(out):
            continue
        try:
            flipbook.build_flip_atlas(job['files'], out)
        except Exception:
            pass


def _build_height_maps(stats, dst_path):
    """Write the BC4 height maps apply_parallax planned.

    Each map is written once: the file test skips the other meshes sharing
    that diffuse, and 2359 flagged shapes share just 163 textures.
    """
    jobs = stats.pop('_parallax_maps', {})
    if not jobs:
        return
    out_root = _output_root(dst_path)[0]
    if out_root is None:
        return
    from asset_convert.texture import parallax
    for job in jobs.values():
        out = out_root + job['height_rel'].replace('\\', os.sep)
        if not os.path.isfile(out):
            parallax.build_height_map(job['src'], out)


def _build_animobject_graph(data, stats, result, dst_path):
    """Give an animated object the behaviour graph PlayAnimation needs.

    Runs AFTER the conversion so stripped sequences cannot become dead states,
    and before the write so the BGED ships in the file.
    See: docs/commentary/asset_convert_nif.md#animated-object-graphs
    """
    seq_names = collect_sequence_names(data)
    if not seq_names:
        return
    stripped = strip_empty_text_keys(data)
    if stripped:
        stats['empty_text_keys_stripped'] = stripped

    _, meshes_root, model_rel = _output_root(dst_path)
    if meshes_root is None:
        return
    try:
        bged = generate_animobject_project(meshes_root, model_rel, seq_names)
        if bged and add_animobject_bged(data, bged):
            result['animobject_graph'] = bged
            stats['animobject_sequences'] = len(seq_names)
    except Exception as e:
        result['animobject_error'] = str(e)


def _add_tangent_space(data):
    """Generate tangent space where a shape lacks it.

    Missing tangents light normal maps wrongly in Skyrim -- the "rainbow
    shaders" on architecture.
    """
    if not _TANGENT_SPELL:
        return
    try:
        spell = _SpellAddTangentSpace(data=data, toaster=_NifToaster())
        spell.recurse()
    except Exception:
        pass


def _run_post_passes(data, stats, result, src_path, dst_path, textures_only):
    """Everything that runs on the converted tree before it is written."""
    for root in data.roots:
        if root is not None:
            convert_flame_nodes(root, src_path, _convert_nif, stats)
    _build_flip_atlases(stats, dst_path)
    _build_height_maps(stats, dst_path)
    if not textures_only:
        _build_animobject_graph(data, stats, result, dst_path)
    _add_tangent_space(data)


def _write_weight_variants(data, buf, src_path, dst_path, src_meshes_dir,
                           wearable_plan, creature, race):
    """Write the _0/_1 weight-slider pair the plugin actually references.

    The _1 file is NEVER a second conversion: the engine lerps the pair
    per-vertex and that REQUIRES identical topology, so it is the finished
    weight-0 mesh post-morphed by the fitted body morph.
    See: docs/commentary/asset_convert_armor.md#weight-slider-variants
    """
    srcl = str(src_path).lower().replace('\\', '/')
    wearable = (not creature and race is None
                and not is_ground_model(srcl.rsplit('/', 1)[-1]))
    if not (wearable and wearable_plan is not None):
        return

    want = wp.variants_for(wearable_plan, src_path, src_meshes_dir)
    root, ext = os.path.splitext(str(dst_path))

    if not want & wp.BASE:
        try:
            os.remove(dst_path)
        except OSError:
            pass
    if want & wp.W0:
        with open(root + '_0' + ext, 'wb') as f:
            f.write(buf.getvalue())
    if not want & wp.W1:
        return

    w1_bytes = None
    try:
        if morph_converted_to_weight1(data, '/f/' in srcl):
            buf1 = _io.BytesIO()
            data.write(buf1)
            w1_bytes = buf1.getvalue()
    except Exception:
        w1_bytes = None
    with open(root + '_1' + ext, 'wb') as f:
        f.write(w1_bytes if w1_bytes is not None else buf.getvalue())


def _write_beast_head_variants(src_path, dst_path, *, fix_textures,
                               src_meshes_dir, wearable_plan, parallax):
    """Write the per-beast-race copies of a head-gear NIF.

    The whole conversion is RE-RUN per race from the source file rather than
    the finished mesh being re-fitted.  A hood is multi-bone SKINNED geometry
    (Bip01 Head + Neck + Clavicles), so its head fit happens inside the
    retarget wrap -- there is no later point at which the head verts can be
    displaced again without redoing the skin solve.  Re-reading also keeps
    each variant a FIRST fit through its race's field, never a second
    displacement stacked on the human result.

    A variant that fails for any reason is simply not written: the ARMA for it
    then points at a missing mesh, which the engine falls back from to the
    default armature -- the pre-existing behaviour, never worse than it.
    """
    from asset_convert.character import head_fit
    female = '/f/' in str(src_path).replace(chr(92), '/').lower()
    races = head_fit.beast_races_available(female)
    if not races:
        return

    root, ext = os.path.splitext(str(dst_path))
    for race in races:
        out = root + head_fit.beast_variant_suffix(race) + ext
        try:
            convert_nif(src_path, out, fix_textures=fix_textures,
                        src_meshes_dir=src_meshes_dir,
                        wearable_plan=wearable_plan, parallax=parallax,
                        race=race)
        except Exception:
            try:
                if os.path.isfile(out):
                    os.remove(out)
            except OSError:
                pass


def _finish_result(result, stats):
    """Roll `stats` up into the worker's result dict.

    Its own function because --textures-only returns before the mesh is ever
    written, and both exits owe batch_convert the same accounting.
    """
    result['converted'] = True
    result['strips_fixed'] = stats['strips_fixed'] > 0
    result['properties_converted'] = stats['properties_converted'] > 0
    result['root_converted'] = stats['root_converted'] > 0
    result['root_rotation_baked'] = stats['root_rotation_baked'] > 0
    result['version_upgraded'] = True
    result['bones_remapped'] = stats['bones_remapped'] > 0
    result['textures_fixed'] = stats['properties_converted'] > 0  # proxy: every property conversion rewrites textures
    # Parallax accounting.  Carried up per CATEGORY, because "skipped" on its
    # own sends the next person back to all 163 flagged textures with no lead —
    # over half of them legitimately have no height data to carry.
    # `spec_` rides in the same bucket: both are per-category counters merged
    # with Counter.update(), and both answer "why was this shape left alone".
    _px = {k: v for k, v in stats.items()
           if k.startswith('parallax_') or k.startswith('spec_')
           or k.startswith('glow_')}
    if _px:
        result['parallax'] = _px
    # Carried separately from the counters above: this one is a SET of texture
    # paths, and `parallax` is merged with Counter.update().
    _au = stats.get('_alpha_opacity_diffuse')
    if _au:
        result['alpha_opacity_diffuse'] = _au
    return result
