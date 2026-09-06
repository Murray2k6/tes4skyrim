"""Read source NIFs, repairing bytes outside the declared block/root stream."""
import io


class TrailingNifData(ValueError):
    """A complete NIF footer was followed by bytes outside its object graph."""

    def __init__(self, end, size):
        super().__init__(f'{size - end} bytes follow the NIF root footer')
        self.end = end
        self.size = size


class _CheckedStream:
    def __init__(self, stream):
        self.stream = stream

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def finish_nif_footer(self):
        end = self.stream.tell()
        size = self.stream.seek(0, 2)
        self.stream.seek(end)
        if size != end:
            raise TrailingNifData(end, size)


def install_footer_check(nif_format):
    """Let conversion readers reject trailing data before link resolution."""
    original = nif_format.Footer.read

    def read_footer(self, stream, data):
        original(self, stream, data)
        if isinstance(stream, _CheckedStream):
            stream.finish_nif_footer()

    nif_format.Footer.read = read_footer


def read_source_nif(path, nif_format):
    """Reparse the exact declared stream after removing an invalid trailer.

    The second read must resolve every block/root link successfully; malformed
    block layouts, references, and incomplete files remain conversion errors.
    Source archives stay intact. The converted output contains only that fully
    parsed graph, and the returned byte count records the input repair.
    """
    data = nif_format.Data()
    with open(path, 'rb') as stream:
        try:
            data.read(_CheckedStream(stream))
        except TrailingNifData as error:
            stream.seek(0)
            repaired = io.BytesIO(stream.read(error.end))
            data = nif_format.Data()
            data.read(repaired)
            return data, error.size - error.end
    return data, 0
