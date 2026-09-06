"""Convert the scene templates referenced by mesh-particle modifiers."""


def convert_templates(system, fix_textures, stats):
    from . import nif_converter as c

    N = c.NifFormat
    converted = stats.setdefault('_particle_templates', {})
    for modifier in system.modifiers:
        if not isinstance(modifier, N.NiPSysMeshUpdateModifier):
            continue
        for index, template in enumerate(modifier.meshes):
            if template is None:
                continue
            key = id(template)
            if key not in converted:
                # A template may be geometry itself; a parent is needed for
                # the baked morph targets to remain in the particle template.
                root = template
                if not isinstance(root, N.NiNode):
                    root = N.NiNode()
                    root.add_child(template)
                converted[key] = root
                swaps = []
                for block in root.tree():
                    if not isinstance(block, N.NiTriBasedGeom):
                        continue
                    ctrl = block.controller
                    while ctrl is not None:
                        if isinstance(ctrl, N.NiGeomMorpherController):
                            for ordinal, interp in enumerate(ctrl.interpolators):
                                if getattr(interp, 'data', None) is not None:
                                    swaps.append(dict(seq=ctrl, shape=bytes(block.name),
                                                      frame=b'', ordinal=ordinal,
                                                      interp=interp, morpher=ctrl))
                        ctrl = ctrl.next_controller
                root._morph_swaps = swaps
                c._walk_node(None, root, fix_textures, stats)
                c._emulate_morphs(root, stats)
                # The outer graph's morph pass must not bake these twice.
                for block in root.tree():
                    if hasattr(block, '_morph_swaps'):
                        block._morph_swaps = []
            modifier.meshes[index] = converted[key]


def copy_mesh_data(source, target):
    """Keep mesh-particle pool configuration alongside the fresh base data."""
    target.unknown_int_2 = source.unknown_int_2
    target.unknown_byte_3 = source.unknown_byte_3
    target.num_unknown_ints_1 = source.num_unknown_ints_1
    target.unknown_ints_1.update_size()
    for index, value in enumerate(source.unknown_ints_1):
        target.unknown_ints_1[index] = value
    target.unknown_node = source.unknown_node
