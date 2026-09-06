"""Bake authored affine transforms in static branches into their geometry."""
import numpy as np


def repair_static_affine(data, nif_format):
    """Keep world geometry exact while removing non-rotation matrix fields.

    Animated, skinned, colliding, and multiply parented branches require their
    local frames and are not flattened. Their diagnostics remain visible.
    """
    N = nif_format
    blocks = list(data.get_global_iterator())
    protected = set()
    animated_names = set()
    parents = {}
    for block in blocks:
        for child in getattr(block, 'children', ()):
            if child is not None:
                parents[id(child)] = parents.get(id(child), 0) + 1
        if isinstance(block, N.NiTimeController):
            protected.add(id(block.target))
            protected.update(id(target) for target in getattr(block, 'extra_targets', ()))
        if isinstance(block, N.NiControllerSequence):
            animated_names.update(entry.node_name for entry in block.controlled_blocks)
        if isinstance(block, N.NiSkinInstance):
            protected.add(id(block.skeleton_root))
            protected.update(id(bone) for bone in block.bones)

    allowed = (N.NiNode, N.BSFadeNode, N.NiTriShape, N.NiTriStrips)

    def safe(node):
        if (type(node) not in allowed or id(node) in protected
                or node.name in animated_names or parents.get(id(node), 0) > 1
                or node.controller is not None or node.collision_object is not None
                or getattr(node, 'skin_instance', None) is not None):
            return False
        return all(safe(child) for child in getattr(node, 'children', ()) if child is not None)

    def transform_vectors(values, matrix, normalize=False):
        for vector in values:
            value = np.array((vector.x, vector.y, vector.z)) @ matrix
            if normalize:
                length = np.linalg.norm(value)
                if length:
                    value /= length
            vector.x, vector.y, vector.z = map(float, value)

    def bake(node, inherited):
        matrix = float(node.scale) * np.array(node.rotation.as_list()) @ inherited
        translation = np.array(node.translation.as_tuple()) @ inherited
        node.translation.x, node.translation.y, node.translation.z = map(float, translation)
        if isinstance(node, N.NiTriBasedGeom) and node.data is not None:
            # Geometry data can be instanced by an unaffected sibling.
            geometry = type(node.data)()
            geometry.deepcopy(node.data)
            node.data = geometry
            transform_vectors(geometry.vertices, matrix)
            if geometry.has_normals:
                transform_vectors(geometry.normals, np.linalg.inv(matrix).T, True)
                for name in ('tangents', 'bitangents'):
                    transform_vectors(getattr(geometry, name), matrix, True)
            geometry.update_center_radius()
        for child in getattr(node, 'children', ()):
            if child is not None:
                bake(child, matrix)
        node.rotation.set_identity()
        node.scale = 1.0

    repaired = 0
    for block in blocks:
        if isinstance(block, N.NiAVObject) and not block.rotation.is_rotation() and safe(block):
            bake(block, np.eye(3))
            repaired += 1
    return repaired
