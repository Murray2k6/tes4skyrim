"""Texture path normalising, shared by the converter and the shader builder.

Both are pure string/slot readers with no NIF state, so they sit below every
module that needs them.
"""

def bs_pp_texture_slots(prop):
    """Diffuse, normal and glow paths from an FO3/FNV BSShaderPPLightingProperty.

    FO3/FNV keep their paths in a BSShaderTextureSet on this property rather
    than on NiTexturingProperty, in the same slot order Skyrim uses: 0 diffuse,
    1 normal, 2 glow. All three are AUTHORED, so the normal is taken verbatim
    instead of being derived from the diffuse name.

    See: docs/commentary/asset_convert_nif.md#fo3fnv-shader-properties
    """
    tex_set = getattr(prop, 'texture_set', None)
    if tex_set is None:
        return b'', b'', b''
    slots = list(getattr(tex_set, 'textures', ()) or ())

    def slot(i):
        """The i-th texture path, or empty when absent or blank."""
        return slots[i] if i < len(slots) and slots[i] else b''

    return slot(0), slot(1), slot(2)


def rewrite_tex_path(raw_bytes):
    """Prepend tes4\\ to a texture path that doesn't already have it.

    Separators are normalised FIRST; a leading 'data\\' and a 'lowres\\'
    segment are dropped.
    See: docs/commentary/asset_convert_shader.md#rewrite-tex-path
    """
    path = raw_bytes.decode('utf-8', errors='replace').replace('/', '\\')
    if path.lower().startswith('data\\'):
        path = path[len('data\\'):]
    low = path.lower()

    if low.startswith('textures\\'):
        rest = path[len('textures\\'):]
    else:
        rest = path
    if rest.lower().startswith('lowres\\'):
        rest = rest[len('lowres\\'):]

    if rest.lower().startswith('tes4\\'):
        return 'Textures\\' + rest
    return 'Textures\\tes4\\' + rest
