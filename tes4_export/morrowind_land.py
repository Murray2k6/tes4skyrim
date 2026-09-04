"""
Morrowind LAND terrain, resampled onto Oblivion's cell grid.

A Morrowind LAND is 65x65 vertices over 8192 units; an Oblivion LAND is 33x33
over 4096. Vertex spacing is therefore 128 units in BOTH games, so one
Morrowind cell splits into four Oblivion cells by taking 33x33 sub-grids with a
shared edge row and column -- no resampling and no interpolation.

Both games delta-encode heights the same way (a running offset per row, then
per column, times eight), so a quadrant is re-encoded straight back into the
TES4 form the importer already reads.

See: docs/commentary/tes4_export_morrowind.md#land-terrain
"""

import struct

#: Vertices per side: Morrowind LAND, and the Oblivion LAND it splits into.
TES3_LAND_SIZE = 65
TES4_LAND_SIZE = 33

#: Both games store heights as deltas scaled by this.
HEIGHT_SCALE = 8.0

#: LAND.DATA bits saying which payloads a record carries.
DATA_VNML = 0x01
DATA_VHGT = 0x02
DATA_VTEX = 0x04

#: Morrowind texture indices per side, and per Oblivion quadrant.
TES3_TEX_SIZE = 16
TES4_TEX_SIZE = 8

#: VTEX stores an LTEX index plus one; zero means "no texture, use default".
VTEX_INDEX_BIAS = 1

#: Texture patches per side of a TES4 layer quadrant, and its VTXT vertex grid.
QUAD_TEX_SIZE = TES4_TEX_SIZE // 2
QUAD_VERTS = 17

#: Vertex cells one texture patch spans: 16 cells across 4 patches.
PATCH_VERTS = (QUAD_VERTS - 1) // QUAD_TEX_SIZE


def decode_heights(vhgt: bytes) -> list:
    """The 65x65 absolute heights in a Morrowind VHGT subrecord.

    VHGT is a float offset followed by 65*65 signed byte deltas: each row
    accumulates from the previous row's first column, each column from its own
    row start.
    """
    offset = struct.unpack_from('<f', vhgt, 0)[0]
    deltas = struct.unpack_from('<%db' % (TES3_LAND_SIZE * TES3_LAND_SIZE),
                                vhgt, 4)
    heights = [0.0] * (TES3_LAND_SIZE * TES3_LAND_SIZE)
    row = offset
    for y in range(TES3_LAND_SIZE):
        base = y * TES3_LAND_SIZE
        row += deltas[base]
        heights[base] = row * HEIGHT_SCALE
        col = row
        for x in range(1, TES3_LAND_SIZE):
            col += deltas[base + x]
            heights[base + x] = col * HEIGHT_SCALE
    return heights


def encode_heights(heights: list, quadrant: tuple) -> bytes:
    """One 33x33 quadrant of a 65x65 height field, in TES4 VHGT form.

    `quadrant` is the (x, y) corner in Morrowind cell halves. Morrowind's own
    deltas are already whole bytes, so the round trip is exact: measured at
    zero height error over 22 LAND records times four quadrants.
    """
    qx, qy = quadrant
    x0, y0 = qx * (TES4_LAND_SIZE - 1), qy * (TES4_LAND_SIZE - 1)
    grid = [[heights[(y0 + y) * TES3_LAND_SIZE + x0 + x] / HEIGHT_SCALE
             for x in range(TES4_LAND_SIZE)] for y in range(TES4_LAND_SIZE)]

    offset = grid[0][0]
    deltas = []
    prev_row = offset
    for y in range(TES4_LAND_SIZE):
        row_start = grid[y][0]
        deltas.append(_clamp_delta(row_start - prev_row))
        prev_row = row_start
        prev_col = row_start
        for x in range(1, TES4_LAND_SIZE):
            deltas.append(_clamp_delta(grid[y][x] - prev_col))
            prev_col = grid[y][x]
    return struct.pack('<f', offset) + struct.pack(
        '<%db' % len(deltas), *deltas) + b'\x00\x00\x00'


def _clamp_delta(value: float) -> int:
    """A height delta as the signed byte the format allows."""
    return max(-128, min(127, int(round(value))))


def decode_normals(vnml: bytes) -> bytes:
    """Pass through a 65x65x3 normal field; empty when absent or short."""
    expected = TES3_LAND_SIZE * TES3_LAND_SIZE * 3
    return vnml if len(vnml) >= expected else b''


def quadrant_normals(vnml: bytes, quadrant: tuple) -> bytes:
    """The 33x33x3 normal sub-grid for one Oblivion cell."""
    if not vnml:
        return b''
    qx, qy = quadrant
    x0, y0 = qx * (TES4_LAND_SIZE - 1), qy * (TES4_LAND_SIZE - 1)
    out = bytearray()
    for y in range(TES4_LAND_SIZE):
        row = (y0 + y) * TES3_LAND_SIZE
        for x in range(TES4_LAND_SIZE):
            off = (row + x0 + x) * 3
            out += vnml[off:off + 3]
    return bytes(out)


def decode_textures(vtex: bytes) -> list:
    """Morrowind's 16x16 texture indices, de-swizzled to row-major order.

    VTEX ships as a 4x4 grid of 4x4 blocks; OpenMW's transposeTextureData
    unpicks it and this mirrors that traversal exactly.
    """
    count = TES3_TEX_SIZE * TES3_TEX_SIZE
    if len(vtex) < count * 2:
        return []
    packed = struct.unpack_from('<%dH' % count, vtex, 0)
    out = [0] * count
    read = 0
    for y1 in range(4):
        for x1 in range(4):
            for y2 in range(4):
                for x2 in range(4):
                    out[(y1 * 4 + y2) * TES3_TEX_SIZE + (x1 * 4 + x2)] = packed[read]
                    read += 1
    return out


def ltex_index(vtex_value: int):
    """The LTEX index a VTEX entry names, or None for the default texture.

    See: docs/commentary/tes4_export_morrowind.md#land-terrain
    """
    return None if vtex_value == 0 else vtex_value - VTEX_INDEX_BIAS


def quadrant_textures(textures: list, quadrant: tuple) -> list:
    """The 8x8 texture indices covering one Oblivion cell."""
    if not textures:
        return []
    qx, qy = quadrant
    x0, y0 = qx * TES4_TEX_SIZE, qy * TES4_TEX_SIZE
    return [textures[(y0 + y) * TES3_TEX_SIZE + x0 + x]
            for y in range(TES4_TEX_SIZE) for x in range(TES4_TEX_SIZE)]


def opacity_grid(patch: list, value: int) -> list:
    """VTXT (position, opacity) pairs for one texture over a 4x4 patch.

    Each of the quadrant's 17x17 vertices takes the share of the one to four
    patches meeting at it that use `value`. Zero-opacity entries are omitted.
    See: docs/commentary/tes4_export_morrowind.md#terrain-texture-blending
    """
    out = []
    for vy in range(QUAD_VERTS):
        for vx in range(QUAD_VERTS):
            hits = total = 0
            for py in _touching_patches(vy):
                for px in _touching_patches(vx):
                    total += 1
                    hits += patch[py * QUAD_TEX_SIZE + px] == value
            if hits:
                out.append((vy * QUAD_VERTS + vx, hits / total))
    return out


def _touching_patches(vertex: int) -> range:
    """The patch indices along one axis that share a given vertex."""
    lo = (vertex - 1) // PATCH_VERTS
    hi = vertex // PATCH_VERTS
    return range(max(lo, 0), min(hi, QUAD_TEX_SIZE - 1) + 1)


def layer_lines(index: int, quadrant: int, form_id: str, rank: int,
                patch: list, value: int) -> list:
    """One texture layer's export lines; rank 0 is the BASE, later ranks ALPHA.

    See: docs/commentary/tes4_export_morrowind.md#terrain-texture-blending
    """
    pfx = f'Layer[{index}]'
    if rank == 0:
        return [f'{pfx}.Type=BASE', f'{pfx}.BTXT.Texture={form_id}',
                f'{pfx}.BTXT.Quadrant={quadrant}']
    grid = opacity_grid(patch, value)
    lines = [f'{pfx}.Type=ALPHA', f'{pfx}.ATXT.Texture={form_id}',
             f'{pfx}.ATXT.Quadrant={quadrant}', f'{pfx}.ATXT.Layer={rank - 1}',
             f'{pfx}.VTXTCount={len(grid)}']
    for i, (pos, opacity) in enumerate(grid):
        lines.append(f'{pfx}.VT[{i}].Pos={pos}')
        lines.append(f'{pfx}.VT[{i}].Opacity={opacity:.6f}')
    return lines
