"""Morph emulation: NiGeomMorpherController rebuilt as baked shape swaps.

Skyrim has no morph-controller class, so each animated target is baked into a
hidden sibling copy and the sequence gains NiVisController entries swapping
base -> target as the weight curve crosses 0.5.  The block-cloning machinery
that bake needs lives here too, as does the NiBlend*Interpolator header fixup
that must run after every pass which synthesizes one.

See: docs/commentary/asset_convert_nif.md#morph-emulation
"""

from pyffi.object_models.xml.array import Array as _Arr

from asset_convert.nif.pyffi_monkey_patch import apply_patches
apply_patches()
from pyffi.formats.nif import NifFormat

from asset_convert.nif.sequences import CB_OFFSETS


def _all_attr_names(cls):
    """Attribute names of a PyFFI struct class INCLUDING inherited ones.

    Walked MRO base-first so counts still precede their arrays.
    See: docs/commentary/asset_convert_nif.md#morph-swap-block-mechanics
    """
    names = []
    for klass in reversed(cls.__mro__):
        for a in klass.__dict__.get('_attrs', ()):
            if a.name not in names:
                names.append(a.name)
    return names


def _copy_block_fields(src, dst):
    """Field-by-field copy of a PyFFI block (scalars, compounds, arrays).

    Reference-typed fields are copied as POINTERS (shared blocks); the caller
    overrides the ones the clone must own (data, controller, collision).
    See: docs/commentary/asset_convert_nif.md#morph-swap-block-mechanics
    """
    def _copy_value(sv, dv, setter):
        """Recursively copy one field, descending arrays and compounds."""
        if isinstance(dv, _Arr):
            if hasattr(dv, 'update_size'):
                try:
                    dv.update_size()
                except Exception:
                    pass
            for i in range(min(len(sv), len(dv))):
                _copy_value(sv[i], dv[i],
                            lambda v, _dv=dv, _i=i: _dv.__setitem__(_i, v))
        elif hasattr(dv, '_attrs'):
            for name in _all_attr_names(type(dv)):
                try:
                    _copy_value(getattr(sv, name), getattr(dv, name),
                                lambda v, _dv=dv, _n=name: setattr(_dv, _n, v))
                except Exception:
                    pass
        else:
            try:
                setter(sv)
            except Exception:
                pass

    for name in _all_attr_names(type(dst)):
        try:
            sv = getattr(src, name)
            dv = getattr(dst, name)
        except Exception:
            continue
        if isinstance(dv, _Arr) or hasattr(dv, '_attrs'):
            _copy_value(sv, dv, lambda v, _n=name: setattr(dst, _n, v))
        else:
            try:
                setattr(dst, name, sv)
            except Exception:
                pass


def _morph_weight_curve(interp):
    """(time, value) list of a morph target's weight keys, or []."""
    data = getattr(interp, 'data', None)
    kg = getattr(data, 'data', None)
    keys = getattr(kg, 'keys', None)
    if not keys:
        return []
    return [(k.time, k.value) for k in keys]


def _vis_toggle_times(curve):
    """Times at which a weight curve crosses 0.5, plus the initial state.

    Returns (initially_on, [t0, t1, ...]) — each t toggles the state.
    """
    if not curve:
        return False, []
    on = curve[0][1] >= 0.5
    times = []
    state = on
    for (t0, v0), (t1, v1) in zip(curve, curve[1:]):
        nxt = v1 >= 0.5
        if nxt != state:
            if v1 != v0:
                tc = t0 + (0.5 - v0) * (t1 - t0) / (v1 - v0)
            else:
                tc = t1
            times.append(max(t0, min(tc, t1)))
            state = nxt
    return on, times


#: unknown_short = Flags 0x01 | Array Size 0x02. See: docs/commentary/asset_convert_nif.md#blend-interp-flags
BLEND_INTERP_FLAGS_ARRAYSIZE = 0x0201


def _init_blend_interpolator(blend):
    """Give a synthesized NiBlend*Interpolator vanilla's manager-driven header."""
    blend.unknown_short = BLEND_INTERP_FLAGS_ARRAYSIZE
    blend.unknown_int = 0
    return blend


_BLEND_INTERP_TYPES = tuple(
    t for t in (getattr(NifFormat, n, None) for n in (
        'NiBlendBoolInterpolator', 'NiBlendFloatInterpolator',
        'NiBlendPoint3Interpolator', 'NiBlendTransformInterpolator',
        'NiBlendColorInterpolator')) if t is not None)


def normalize_blend_interpolators(root, stats=None):
    """Force every NiBlend*Interpolator to vanilla's manager-driven header.

    Blocks COPIED from an Oblivion source hit the same trap as synthesized ones:
    the flags do not survive PyFFI's round trip.
    See: docs/commentary/asset_convert_nif.md#blend-interp-flags
    """
    fixed = 0
    if not _BLEND_INTERP_TYPES:
        return fixed
    for blk in root.tree():
        if not isinstance(blk, _BLEND_INTERP_TYPES):
            continue
        if getattr(blk, 'unknown_short', None) != BLEND_INTERP_FLAGS_ARRAYSIZE:
            blk.unknown_short = BLEND_INTERP_FLAGS_ARRAYSIZE
            blk.unknown_int = 0
            fixed += 1
    if fixed and stats is not None:
        stats['blend_interp_fixed'] = stats.get('blend_interp_fixed', 0) + fixed
    return fixed


def _palette_add(pal, obj):
    """Register a synthesized block in the manager's object palette."""
    if pal is None:
        return
    pal.num_objs += 1
    pal.objs.update_size()
    entry = pal.objs[pal.num_objs - 1]
    entry.name = bytes(obj.name)
    entry.av_object = obj


def _vis_controller(geom):
    """The shape's NiVisController, created on the vanilla pattern if absent.

    See: docs/commentary/asset_convert_nif.md#morph-swap-block-mechanics
    """
    ctrl = geom.controller
    while ctrl is not None:
        if isinstance(ctrl, NifFormat.NiVisController):
            return ctrl
        ctrl = ctrl.next_controller
    ctrl = NifFormat.NiVisController()
    ctrl.flags = 108
    ctrl.frequency = 1.0
    ctrl.phase = 0.0
    ctrl.start_time = 0.0
    ctrl.stop_time = 0.0
    blend = NifFormat.NiBlendBoolInterpolator()
    _init_blend_interpolator(blend)
    blend.bool_value = 2
    ctrl.interpolator = blend
    ctrl.target = geom
    ctrl.next_controller = geom.controller
    geom.controller = ctrl
    return ctrl


def _bool_key_data(initially_on, toggles):
    """Step-keyed NiBoolData toggling from `initially_on` at each time.

    Keys MUST be CONST_KEY (5).
    See: docs/commentary/asset_convert_nif.md#morph-swap-block-mechanics
    """
    bd = NifFormat.NiBoolData()
    kg = bd.data
    times = [0.0] + [t for t in toggles if t > 0.0]
    state = initially_on
    values = [1 if state else 0]
    for _ in times[1:]:
        state = not state
        values.append(1 if state else 0)
    kg.interpolation = 5
    kg.num_keys = len(times)
    kg.keys.update_size()
    for i, (t, v) in enumerate(zip(times, values)):
        kg.keys[i].time = t
        kg.keys[i].value = v
    return bd, values[0]


def _add_vis_cb(seq, geom, initially_on, toggles):
    """Append a NiVisController entry swapping `geom` on and off."""
    bd, first = _bool_key_data(initially_on, toggles)
    ip = NifFormat.NiBoolInterpolator()
    ip.bool_value = bool(first)
    ip.data = bd
    ctrl = _vis_controller(geom)
    ctrl.stop_time = max(ctrl.stop_time, seq.stop_time)
    seq.num_controlled_blocks += 1
    seq.controlled_blocks.update_size()
    cb = seq.controlled_blocks[seq.num_controlled_blocks - 1]
    cb.interpolator = ip
    cb.controller = ctrl
    if hasattr(cb, 'priority'):
        cb.priority = 0
    cb.node_name = bytes(geom.name)
    cb.property_type = b''
    cb.controller_type = b'NiVisController'
    cb.variable_1 = b''
    cb.variable_2 = b''
    for off in CB_OFFSETS:
        if hasattr(cb, off):
            try:
                setattr(cb, off, -1)
            except Exception:
                pass


def _morph_target_index(entry, morphs):
    """Which morph target this entry drives, by frame name then ordinal."""
    idx = entry['ordinal']
    frame = entry['frame']
    if frame:
        for i in range(len(morphs)):
            fn = getattr(morphs[i], 'frame_name', None)
            if fn is not None and bytes(fn) == frame:
                return i
    return idx


def _bake_morph_clone(geom, md, vectors, name, frame, idx, parents, pal):
    """A hidden sibling shape carrying the morph target's vertex positions."""
    gdata = geom.data
    clone = geom.__class__()
    _copy_block_fields(geom, clone)
    cdata = gdata.__class__()
    _copy_block_fields(gdata, cdata)
    relative = bool(getattr(md, 'relative_targets', 1))
    for i in range(getattr(gdata, 'num_vertices', 0)):
        v = cdata.vertices[i]
        d = vectors[i]
        if relative:
            v.x += d.x
            v.y += d.y
            v.z += d.z
        else:
            v.x, v.y, v.z = d.x, d.y, d.z
    try:
        cdata.update_center_radius()
    except Exception:
        pass
    clone.data = cdata
    suffix = frame if frame else str(idx).encode('ascii')
    clone.name = bytes(name) + b'Mrph' + suffix
    clone.controller = None
    clone.collision_object = None
    clone.flags = int(geom.flags) | 0x01
    parent = parents.get(id(geom))
    if parent is not None:
        parent.add_child(clone)
    _palette_add(pal, clone)
    return clone


def _curve_value_at(curve, t):
    """The morph weight at time `t`, linearly interpolated."""
    for (t0, v0), (t1, v1) in zip(curve, curve[1:]):
        if t0 <= t <= t1:
            span = ((t - t0) / (t1 - t0)) if t1 > t0 else 0.0
            return v0 + (v1 - v0) * span
    if curve:
        return curve[0][1] if t <= curve[0][0] else curve[-1][1]
    return None


def _base_visibility(curves):
    """(initial state, toggle times) for a base shape under `curves`.

    The base is visible exactly while NO target weight is >= 0.5.
    """
    cut = sorted({t for c in curves for t in _vis_toggle_times(c)[1]})
    probes = [0.0] + cut
    states = []
    for i, t in enumerate(probes):
        nxt = cut[i] if i < len(cut) else (t + 0.001)
        mid = (t + nxt) / 2 if nxt > t else t
        on = any((_curve_value_at(c, mid) or 0.0) >= 0.5 for c in curves)
        states.append(not on)
    toggles = [cut[i] for i in range(len(cut))
               if states[i + 1] != states[i]]
    return states[0], toggles


def _morph_geometry_index(root):
    """({name: geometry}, {id(geometry): parent}) for every shape."""
    geoms, parents = {}, {}
    for blk in root.tree():
        if isinstance(blk, NifFormat.NiNode):
            for ch in blk.children:
                if isinstance(ch, NifFormat.NiTriBasedGeom):
                    geoms[bytes(ch.name)] = ch
                    parents[id(ch)] = blk
    return geoms, parents


def _morph_swap_plan(entry, geoms):
    """(geometry, morph data, target index, vectors) for a swap, or None.

    None whenever the entry cannot be rebuilt: unknown shape, no morph data, an
    index outside the target list, or a vector count the geometry disagrees with.
    """
    geom = geoms.get(entry['shape'])
    if geom is None:
        return None
    md = getattr(entry['morpher'], 'data', None)
    morphs = getattr(md, 'morphs', None)
    if md is None or not morphs:
        return None
    idx = _morph_target_index(entry, morphs)
    if idx <= 0 or idx >= len(morphs):
        return None
    nverts = getattr(geom.data, 'num_vertices', 0)
    vectors = morphs[idx].vectors
    if nverts == 0 or len(vectors) != nverts:
        return None
    return geom, md, idx, vectors


def _collect_morph_swaps(root):
    """Every swap request the retargeting pass harvested onto the tree."""
    swaps = []
    for blk in root.tree():
        got = getattr(blk, '_morph_swaps', None)
        if got:
            swaps.extend(got)
    return swaps


def _emit_target_swaps(swaps, geoms, parents, pal):
    """Bake each morph target and add its show/hide entry.

    ({(shape, index): clone}, {(sequence id, shape): [weight curve]}).
    """
    made = {}
    base_toggles = {}
    for entry in swaps:
        plan = _morph_swap_plan(entry, geoms)
        if plan is None:
            continue
        geom, md, idx, vectors = plan
        curve = _morph_weight_curve(entry['interp'])
        on, toggles = _vis_toggle_times(curve)
        if not on and not toggles:
            continue
        key = (entry['shape'], idx)
        clone = made.get(key)
        if clone is None:
            clone = _bake_morph_clone(geom, md, vectors, entry['shape'],
                                      entry['frame'], idx, parents, pal)
            made[key] = clone
        _add_vis_cb(entry['seq'], clone, on, toggles)
        base_toggles.setdefault((id(entry['seq']), entry['shape']),
                                []).append(curve)
    return made, base_toggles


def emulate_morphs(root, stats=None):
    """Rebuild dropped NiGeomMorpherController animation as shape swaps.

    See: docs/commentary/asset_convert_nif.md#morph-emulation
    """
    swaps = _collect_morph_swaps(root)
    if not swaps:
        return

    geoms, parents = _morph_geometry_index(root)
    mgr = root.controller
    pal = (mgr.object_palette
           if isinstance(mgr, NifFormat.NiControllerManager) else None)
    made, base_toggles = _emit_target_swaps(swaps, geoms, parents, pal)

    seq_by_id = {id(e['seq']): e['seq'] for e in swaps}
    for (sid, name), curves in base_toggles.items():
        geom = geoms.get(name)
        seq = seq_by_id.get(sid)
        if geom is None or seq is None:
            continue
        first, toggles = _base_visibility(curves)
        _add_vis_cb(seq, geom, first, toggles)
    if stats is not None:
        stats['morph_swaps'] = stats.get('morph_swaps', 0) + len(made)
