"""Legacy geometry field widths (niftools/nifxml: NiGeometryData)."""
import struct

from pyffi.object_models.common import UShort


class GeometryUVCount(UShort):
    """The shared UV count is ushort through 4.2.2.0, byte thereafter."""

    @classmethod
    def get_size(cls, data=None):
        """Select the serialized width from the file version."""
        return 2 if data is not None and data.version <= 0x04020200 else 1

    def read(self, stream, data):
        """Read the historical field without shifting subsequent geometry."""
        size = self.get_size(data)
        self._value = struct.unpack(data._byte_order + ('H' if size == 2 else 'B'),
                                    stream.read(size))[0]

    def write(self, stream, data):
        """Preserve legacy flags and modern byte serialization."""
        size = self.get_size(data)
        stream.write(struct.pack(data._byte_order + ('H' if size == 2 else 'B'),
                                 self._value))


def install_geometry_uv_count(nif_format):
    """Unify duplicate PyFFI attributes whose original types disagree."""
    for attr in nif_format.NiGeometryData._attrs:
        if attr.name == 'num_uv_sets':
            attr.type_ = GeometryUVCount


def prepare_legacy_geometry(data, nif_format):
    """Make implicit pre-10.0.1.3 triangle/strip presence explicit for TES5."""
    if data.version > 0x0A000102:
        return
    for block in data.get_global_iterator():
        if isinstance(block, nif_format.NiTriShapeData):
            block.has_triangles = bool(block.num_triangles)
        elif isinstance(block, nif_format.NiTriStripsData):
            block.has_points = bool(block.num_strips)


def prepare_legacy_controllers(data, nif_format):
    """Move direct keyframe data into the TES5 transform interpolator layout."""
    if data.version > 0x0A010067:
        return
    from .nif_links import retarget_links

    replacements = {}
    blocks = list(data.get_global_iterator())
    for old in blocks:
        if type(old) is not nif_format.NiKeyframeController:
            continue
        new = nif_format.NiTransformController()
        for name in ('next_controller', 'flags', 'frequency', 'phase',
                     'start_time', 'stop_time', 'target'):
            setattr(new, name, getattr(old, name))
        if old.data is not None:
            keys = nif_format.NiTransformData()
            keys.deepcopy(old.data)
            interpolator = nif_format.NiTransformInterpolator()
            interpolator.data = keys
            new.interpolator = interpolator
        replacements[id(old)] = new
    for root in data.roots:
        retarget_links(root, replacements, data)
