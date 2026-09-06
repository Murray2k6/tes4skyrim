"""Retarget NIF links when conversion replaces a scene block."""


def retarget_links(root, replacements, data):
    """Rewrite strong and weak links by identity, including nested arrays.

    Follow only owning references, as PyFFI's writer does. Pointer targets
    are updated without pulling an old, discarded graph back into the file.
    Geometry's vertex arrays contain no links and are never traversed.
    """
    from pyffi.formats.nif import NifFormat as N
    from pyffi.object_models.xml.array import Array

    visited = set()

    def visit(value):
        if isinstance(value, N.Ref):
            target = value.get_value()
            replacement = replacements.get(id(target))
            while replacement is not None and replacement is not target:
                target = replacement
                replacement = replacements.get(id(target))
            if target is not value.get_value():
                value.set_value(target)
            if target is not None and not isinstance(value, N.Ptr):
                visit(target)
            return
        if id(value) in visited:
            return
        visited.add(id(value))
        if isinstance(value, Array):
            for element in value._elementList():
                visit(element)
        else:
            for attribute in value._get_filtered_attribute_list(data):
                if attribute.type_._has_links:
                    visit(value.get_attribute(attribute.name))

    if replacements:
        visit(root)
