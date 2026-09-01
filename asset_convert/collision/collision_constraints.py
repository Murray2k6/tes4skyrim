"""Havok constraint passes: demote, rescale, reverse, rebuild the tree.

Split out of collision.py, which held the shape and rigid-body conversion
alongside the constraint rewriting in one 1784-line file.  These passes run
over an already-converted NIF and touch only bhk*Constraint blocks plus the
rigid bodies' `constraints` arrays.

Constraint ORDER is a hard engine contract: the engine overwrites hkx
constraint[i-1] with NIF constraint[j-1] by DFS index with NO bounds check,
so the hkx and NIF orders must match, the first body is bare, and every other
body carries exactly one joint to an EARLIER body.
See: docs/commentary/asset_convert_creature.md#2--the-real-never-falls-over-cause-the-nif-ragdoll-tree-had-orphan-bodies
"""

import math

from asset_convert.nif.pyffi_monkey_patch import apply_patches
apply_patches()

from pyffi.formats.nif import NifFormat

_HAVOK_SCALE = 0.1


def _vec_cross(a, b):
    """Cross product of two PyFFI Vector4s (xyz), returned as a tuple."""
    return (a.y * b.z - a.z * b.y,
            a.z * b.x - a.x * b.z,
            a.x * b.y - a.y * b.x)


def _vec_set_unit(dst, xyz, w=0.0):
    """Normalise xyz and store into a PyFFI Vector4."""
    x, y, z = xyz
    mag = math.sqrt(x * x + y * y + z * z)
    if mag > 1e-6:
        x /= mag; y /= mag; z /= mag
    dst.x = x
    dst.y = y
    dst.z = z
    dst.w = w


def _copy_field(dst, name, sv, dv):
    """Copy one field: Vector4 by component, compound recursively, else set."""
    if hasattr(dv, 'x') and hasattr(dv, 'w'):
        dv.x = sv.x; dv.y = sv.y; dv.z = sv.z; dv.w = sv.w
    elif hasattr(dv, '_attrs'):
        _copy_struct(sv, dv)
    elif isinstance(dv, (int, float, bool)):
        try:
            setattr(dst, name, sv)
        except Exception:
            pass


def _copy_struct(src, dst):
    """Copy a PyFFI compound field-by-field (Vector4s by component)."""
    done = set()
    for a in dst._attrs:
        name = a.name
        if name in done:
            continue
        done.add(name)
        try:
            sv, dv = getattr(src, name), getattr(dst, name)
        except Exception:
            continue
        _copy_field(dst, name, sv, dv)


#: SubConstraint.type -> (plain constraint block class, descriptor attribute).
_MALLEABLE_INNER = {
    0: ('bhkBallAndSocketConstraint', 'ball_and_socket'),
    1: ('bhkHingeConstraint', 'hinge'),
    2: ('bhkLimitedHingeConstraint', 'limited_hinge'),
    6: ('bhkPrismaticConstraint', 'prismatic'),
    7: ('bhkRagdollConstraint', 'ragdoll'),
    8: ('bhkStiffSpringConstraint', 'stiff_spring'),
}


def _demote_malleable_constraints(data):
    """Replace each bhkMalleableConstraint with its inner constraint type.

    Returns the new blocks: they are referenced from the rigid bodies but
    not yet present in data.blocks.
    See: docs/commentary/asset_convert_collision.md#malleable-demotion
    """
    new_blocks = []
    replacements = {}
    for block in data.blocks:
        if not isinstance(block, NifFormat.bhkMalleableConstraint):
            continue
        sub = block.sub_constraint
        inner = _MALLEABLE_INNER.get(sub.type)
        if inner is None:
            continue
        cls_name, desc_attr = inner
        new_block = getattr(NifFormat, cls_name)()
        new_block.num_entities = block.num_entities
        new_block.entities.update_size()
        for i in range(block.num_entities):
            new_block.entities[i] = block.entities[i]
        new_block.priority = block.priority
        _copy_struct(getattr(sub, desc_attr), getattr(new_block, desc_attr))
        replacements[block] = new_block
        new_blocks.append(new_block)

    if replacements:
        for block in data.blocks:
            constraints = getattr(block, 'constraints', None)
            if constraints is None:
                continue
            for i, c in enumerate(constraints):
                if c in replacements:
                    constraints[i] = replacements[c]
    return new_blocks


def _fix_limited_hinge(d, clamp_friction=True, friction_target=0.01):
    """Derive perp_2_axle_in_b_1 and clamp friction (pivots already scaled).

    See: docs/commentary/asset_convert_collision.md#limited-hinge-fix
    """
    perp_b1 = getattr(d, 'perp_2_axle_in_b_1', None)
    if perp_b1 is not None:
        _vec_set_unit(perp_b1, _vec_cross(d.perp_2_axle_in_b_2, d.axle_b), w=-1.0)

    perp_a1 = getattr(d, 'perp_2_axle_in_a_1', None)
    if perp_a1 is not None:
        perp_a1.w = -1.0

    if clamp_friction and d.max_friction > friction_target:
        d.max_friction = friction_target


def _fix_ragdoll(d, clamp_friction=True, friction_target=0.01):
    """Derive the motor axes (motor = twist x plane) and clamp friction.

    `friction_target` is 0.01 for props and 0.0 for creature blend joints.
    See: docs/commentary/asset_convert_collision.md#ragdoll-descriptor-fix
    """
    if clamp_friction and d.max_friction > friction_target:
        d.max_friction = friction_target
    for twist_name, plane_name, motor_name in (('twist_a', 'plane_a', 'motor_a'),
                                               ('twist_b', 'plane_b', 'motor_b')):
        motor = getattr(d, motor_name, None)
        if motor is None:
            continue
        if math.sqrt(motor.x ** 2 + motor.y ** 2 + motor.z ** 2) > 1e-6:
            continue
        _vec_set_unit(motor, _vec_cross(getattr(d, twist_name),
                                        getattr(d, plane_name)))


def _fix_hinge(d):
    """Derive axle_a and the B-side perpendiculars Skyrim needs.

    See: docs/commentary/asset_convert_collision.md#hinge-descriptor-fix
    """
    axle_a = getattr(d, 'axle_a', None)
    if axle_a is not None:
        L = math.sqrt(axle_a.x ** 2 + axle_a.y ** 2 + axle_a.z ** 2)
        if L < 1e-6:
            _vec_set_unit(axle_a, _vec_cross(d.perp_2_axle_in_a_1,
                                             d.perp_2_axle_in_a_2))

    perp_b1 = getattr(d, 'perp_2_axle_in_b_1', None)
    perp_b2 = getattr(d, 'perp_2_axle_in_b_2', None)
    if perp_b1 is None or perp_b2 is None:
        return
    L1 = math.sqrt(perp_b1.x ** 2 + perp_b1.y ** 2 + perp_b1.z ** 2)
    L2 = math.sqrt(perp_b2.x ** 2 + perp_b2.y ** 2 + perp_b2.z ** 2)
    if L1 > 1e-6 and L2 > 1e-6:
        return
    ab = d.axle_b
    ref = d.perp_2_axle_in_a_1
    rx, ry, rz = ref.x, ref.y, ref.z
    dot = rx * ab.x + ry * ab.y + rz * ab.z
    px, py, pz = rx - dot * ab.x, ry - dot * ab.y, rz - dot * ab.z
    if px * px + py * py + pz * pz < 1e-9:
        for rx, ry, rz in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)):
            dot = rx * ab.x + ry * ab.y + rz * ab.z
            px, py, pz = rx - dot * ab.x, ry - dot * ab.y, rz - dot * ab.z
            if px * px + py * py + pz * pz > 1e-9:
                break
    _vec_set_unit(perp_b1, (px, py, pz))
    _vec_set_unit(perp_b2, _vec_cross(ab, perp_b1))


def _fix_prismatic(d):
    """Copy the B-frame axes into sliding_a/plane_a and scale distances.

    See: docs/commentary/asset_convert_collision.md#prismatic-descriptor-fix
    """
    for src_name, dst_name in (('sliding_b', 'sliding_a'), ('plane_b', 'plane_a')):
        src = getattr(d, src_name, None)
        dst = getattr(d, dst_name, None)
        if src is None or dst is None:
            continue
        if math.sqrt(dst.x ** 2 + dst.y ** 2 + dst.z ** 2) < 1e-6:
            dst.x = src.x; dst.y = src.y; dst.z = src.z; dst.w = src.w
    for attr in ('min_distance', 'max_distance'):
        v = getattr(d, attr, None)
        if v is not None:
            setattr(d, attr, v * _HAVOK_SCALE)


def _constraint_descriptors(block):
    """Yield (kind, descriptor) for a plain bhkConstraint block."""
    for kind in ('limited_hinge', 'ragdoll', 'hinge', 'prismatic',
                 'stiff_spring', 'ball_and_socket'):
        d = getattr(block, kind, None)
        if d is not None:
            yield kind, d


def strip_marker_collision_bodies(data, root):
    """Drop collision-TOGGLE proxy bodies so they never become ragdoll bodies.

    Runs BEFORE collision conversion, so `is_marker_body` sees the same
    source units extract_ragdoll does; `plan_ragdoll_tree` excludes the same
    bodies from the .hkx and the engine matches the two files body-for-body.
    The NiNode itself is KEPT -- animations bind to it.  Returns the count.
    """
    from asset_convert.havok.hkx_ragdoll import is_marker_body

    doomed = []
    for block in data.blocks:
        if block.__class__.__name__ != 'NiNode':
            continue
        co = getattr(block, 'collision_object', None)
        body = getattr(co, 'body', None) if co is not None else None
        if body is None:
            continue
        if is_marker_body(block, body):
            doomed.append((block, body))
    if not doomed:
        return 0

    dead_bodies = {id(b) for _n, b in doomed}
    for block in data.blocks:
        if block.__class__.__name__ not in ('bhkRigidBody', 'bhkRigidBodyT'):
            continue
        if id(block) in dead_bodies:
            continue
        cons = list(getattr(block, 'constraints', []))
        keep = [c for c in cons
                if not any(id(e) in dead_bodies
                           for e in getattr(c, 'entities', []))]
        if len(keep) != len(cons):
            block.num_constraints = len(keep)
            block.constraints.update_size()
            for i, c in enumerate(keep):
                block.constraints[i] = c

    for node, _body in doomed:
        node.collision_object = None
    return len(doomed)


#: Per kind: fields that swap on an end exchange, then limits that negate.
_JOINT_END_SWAPS = {
    'ragdoll': ((('twist_a', 'twist_b'), ('plane_a', 'plane_b'),
                 ('motor_a', 'motor_b'), ('pivot_a', 'pivot_b')),
                (('plane_min_angle', 'plane_max_angle'),
                 ('twist_min_angle', 'twist_max_angle'))),
    'limited_hinge': ((('axle_a', 'axle_b'),
                       ('perp_2_axle_in_a_1', 'perp_2_axle_in_b_1'),
                       ('perp_2_axle_in_a_2', 'perp_2_axle_in_b_2'),
                       ('pivot_a', 'pivot_b')),
                      (('min_angle', 'max_angle'),)),
    'hinge': ((('axle_a', 'axle_b'),
               ('perp_2_axle_in_a_1', 'perp_2_axle_in_b_1'),
               ('perp_2_axle_in_a_2', 'perp_2_axle_in_b_2'),
               ('pivot_a', 'pivot_b')),
              ()),
}
_JOINT_KIND_OF_BLOCK = {'bhkRagdollConstraint': 'ragdoll',
                        'bhkLimitedHingeConstraint': 'limited_hinge',
                        'bhkHingeConstraint': 'hinge'}
_JOINT_KIND_OF_SUBTYPE = {7: 'ragdoll', 2: 'limited_hinge', 1: 'hinge'}


def joint_descriptor(con):
    """(kind, descriptor) of a ragdoll-tree joint block, looking through a
    bhkMalleableConstraint wrapper; (None, None) for other kinds."""
    name = con.__class__.__name__
    if name == 'bhkMalleableConstraint':
        sub = con.sub_constraint
        kind = _JOINT_KIND_OF_SUBTYPE.get(int(sub.type))
        return kind, (getattr(sub, kind) if kind else None)
    kind = _JOINT_KIND_OF_BLOCK.get(name)
    return kind, (getattr(con, kind) if kind else None)


def _vec_is_zero(v):
    """True when `v` exists and its xyz are all exactly zero."""
    return v is not None and v.x == 0.0 and v.y == 0.0 and v.z == 0.0


def reverse_constraint_ends(con):
    """Re-express a constraint block with its entities exchanged: the same
    physical joint, now held by the other body.  Frames/pivots swap sides
    and the relative-rotation limits negate (mirrors
    hkx_ragdoll._swap_joint_ends).  Works on the Skyrim layout the creature
    path reaches it in, and on an unconverted Oblivion block (whose hinge
    descriptors lack axle_a / perp_2_axle_in_b_1 -- derived here exactly as
    _fix_hinge / _fix_limited_hinge derive them)."""
    kind, d = joint_descriptor(con)
    if kind is None:
        raise ValueError(f'cannot reverse a {con.__class__.__name__}')
    if kind != 'ragdoll':
        axle_a = getattr(d, 'axle_a', None)
        if _vec_is_zero(axle_a):
            _vec_set_unit(axle_a, _vec_cross(d.perp_2_axle_in_a_1,
                                             d.perp_2_axle_in_a_2))
        perp_b1 = getattr(d, 'perp_2_axle_in_b_1', None)
        if _vec_is_zero(perp_b1):
            _vec_set_unit(perp_b1, _vec_cross(d.perp_2_axle_in_b_2, d.axle_b),
                          w=-1.0)
    vec_pairs, limit_pairs = _JOINT_END_SWAPS[kind]
    for na, nb in vec_pairs:
        va, vb = getattr(d, na, None), getattr(d, nb, None)
        if va is None or vb is None:
            continue
        ta = (va.x, va.y, va.z, getattr(va, 'w', None))
        tb = (vb.x, vb.y, vb.z, getattr(vb, 'w', None))
        va.x, va.y, va.z = tb[:3]
        vb.x, vb.y, vb.z = ta[:3]
        if ta[3] is not None and tb[3] is not None:
            va.w, vb.w = tb[3], ta[3]
    for lo, hi in limit_pairs:
        l, h = float(getattr(d, lo)), float(getattr(d, hi))
        setattr(d, lo, -h)
        setattr(d, hi, -l)
    con.entities[0], con.entities[1] = con.entities[1], con.entities[0]
    sub = getattr(con, 'sub_constraint', None)
    if sub is not None and int(getattr(sub, 'num_entities', 0)) == 2:
        sub.entities[0], sub.entities[1] = sub.entities[1], sub.entities[0]


def _chosen_joints(plan):
    """The constraint list each body should end up with, plus the kept set.

    A joint the plan marks reversed is re-expressed here, in place, so the
    caller only has to write the lists out.
    """
    new_lists, kept = {}, set()
    for n in plan['body_nodes']:
        pick = plan['edge_con'].get(id(n))
        if pick is None:
            new_lists[id(n)] = []
            continue
        con, reversed_ = pick
        if reversed_:
            reverse_constraint_ends(con)
        new_lists[id(n)] = [con]
        kept.add(id(con))
    return new_lists, kept


def enforce_ragdoll_tree(data, root):
    """Rebuild each ragdoll body's constraint list to match the .hkx tree.

    `plan_ragdoll_tree` chooses the joints; this makes the NIF agree, so the
    first body in pre-order DFS has 0 constraints and every later body
    exactly 1, to an earlier body.  Returns the number of bodies changed.
    See: docs/commentary/asset_convert_collision.md#enforce-ragdoll-tree
    """
    from asset_convert.havok.hkx_ragdoll import plan_ragdoll_tree

    plan = plan_ragdoll_tree(data, exclude_markers=False)
    if plan is None:
        return 0
    body_of = {id(n): n.collision_object.body for n in plan['body_nodes']}
    before = {nid: list(getattr(b, 'constraints', []) or [])
              for nid, b in body_of.items()}

    new_lists, kept = _chosen_joints(plan)

    changed = 0
    for n in plan['body_nodes']:
        body = body_of[id(n)]
        lst = new_lists[id(n)]
        if [id(c) for c in before[id(n)]] != [id(c) for c in lst]:
            changed += 1
        body.num_constraints = len(lst)
        body.constraints.update_size()
        for i, c in enumerate(lst):
            body.constraints[i] = c
    for child, parent in plan['synthetic']:
        _add_synth_ragdoll_constraint(data, body_of[id(child)],
                                      body_of[id(parent)])
        changed += 1

    dead = {id(c) for lst in before.values() for c in lst} - kept
    if dead:
        data.blocks = [blk for blk in data.blocks if id(blk) not in dead]
    return changed


#: Vanilla atronach rock-joint template, shared with hkx_ragdoll._SYNTH_*.
_SYNTH_CONE = 0.872665
_SYNTH_PLANE = 1.570796
_SYNTH_TWIST = 0.087266


def _add_synth_ragdoll_constraint(data, child_body, parent_body):
    """Append a bhkRagdollConstraint joining child_body to parent_body.

    Pivots at the child body's own centre expressed in each body's local space
    (both bodies' `center` fields are already in Skyrim Havok units at this
    point, so the pivot needs no further scaling).  Frames are axis-aligned:
    twist = X, plane = Y, motor = Z — the orthonormal basis Skyrim's 2010
    layout requires (a zero motor ships a singular basis).
    """
    con = NifFormat.bhkRagdollConstraint()
    con.num_entities = 2
    con.entities.update_size()
    con.entities[0] = child_body
    con.entities[1] = parent_body
    con.priority = 1

    d = con.ragdoll
    for name, (x, y, z) in (('twist_a', (1.0, 0.0, 0.0)),
                            ('plane_a', (0.0, 1.0, 0.0)),
                            ('motor_a', (0.0, 0.0, 1.0)),
                            ('twist_b', (1.0, 0.0, 0.0)),
                            ('plane_b', (0.0, 1.0, 0.0)),
                            ('motor_b', (0.0, 0.0, 1.0))):
        v = getattr(d, name, None)
        if v is not None:
            v.x, v.y, v.z = x, y, z
            if hasattr(v, 'w'):
                v.w = 0.0
    for name, src in (('pivot_a', child_body.center),
                      ('pivot_b', child_body.center)):
        v = getattr(d, name, None)
        if v is not None:
            v.x, v.y, v.z = src.x, src.y, src.z
            if hasattr(v, 'w'):
                v.w = 0.0
    d.cone_max_angle = _SYNTH_CONE
    d.plane_min_angle = -_SYNTH_PLANE
    d.plane_max_angle = _SYNTH_PLANE
    d.twist_min_angle = -_SYNTH_TWIST
    d.twist_max_angle = _SYNTH_TWIST
    d.max_friction = 0.0

    n = child_body.num_constraints
    child_body.num_constraints = n + 1
    child_body.constraints.update_size()
    child_body.constraints[n] = con
    data.blocks.append(con)
    return con


def _scale_stiff_spring(d, friction_target=None):
    """A stiff spring's rest length is a length, so it scales."""
    length = getattr(d, 'length', None)
    if length is not None:
        d.length = length * _HAVOK_SCALE


#: Descriptor kind -> the completion pass that finishes its Skyrim fields.
_DESCRIPTOR_FIX = {
    'limited_hinge': _fix_limited_hinge,
    'ragdoll': _fix_ragdoll,
    'hinge': lambda d, friction_target=None: _fix_hinge(d),
    'prismatic': lambda d, friction_target=None: _fix_prismatic(d),
    'stiff_spring': _scale_stiff_spring,
}


def _scale_descriptor(kind, d, friction_target):
    """Scale one descriptor's pivots and lengths, then complete its fields."""
    for pivot_attr in ('pivot_a', 'pivot_b'):
        pivot = getattr(d, pivot_attr, None)
        if pivot is None:
            continue
        pivot.x *= _HAVOK_SCALE
        pivot.y *= _HAVOK_SCALE
        pivot.z *= _HAVOK_SCALE
    fix = _DESCRIPTOR_FIX.get(kind)
    if fix is not None:
        fix(d, friction_target=friction_target)


def scale_constraint_pivots(data):
    """Demote, rescale and complete every constraint descriptor in `data`.

    Pivots and lengths scale by _HAVOK_SCALE; axis vectors are unit vectors
    and must NOT.  Inertia is deliberately NOT rescaled here -- the
    collision conversion already applies the full factor.
    See: docs/commentary/asset_convert_collision.md#constraint-descriptors
    """
    constraint_blocks = [b for b in data.blocks
                         if isinstance(b, NifFormat.bhkConstraint)]
    constraint_blocks += _demote_malleable_constraints(data)

    blend_ids = {id(b.body) for b in data.blocks
                 if isinstance(b, NifFormat.bhkBlendCollisionObject)
                 and b.body is not None}

    for block in constraint_blocks:
        if isinstance(block, NifFormat.bhkMalleableConstraint):
            continue
        is_blend = any(e is not None and id(e) in blend_ids
                       for e in block.entities)
        for kind, d in _constraint_descriptors(block):
            _scale_descriptor(kind, d, 0.0 if is_blend else 0.01)
        for e in block.entities:
            if e is not None and e.mass > 0.0 and id(e) not in blend_ids:
                e.unknown_byte = 10
