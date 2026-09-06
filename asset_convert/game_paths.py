"""Resolving Bethesda-format relative paths against a real filesystem root.

Model, texture and BSA-internal paths that come out of the game's own binary
formats (MODL/ICON/TX00 subrecords, NIF texture strings, BSA folder+file
records) are ALWAYS backslash-separated, because that is the format's own
convention -- it has nothing to do with the OS the converter runs on.

`root / rel` (pathlib) and `os.path.join(root, rel)` only split on the HOST's
separator.  On Windows that happens to be a backslash, so those work by
coincidence; on Linux/Mac the whole `rel` survives as ONE filename with literal
embedded backslashes, and every lookup silently misses or every write lands in a
single flat file.  `win_join` splits explicitly instead, so a multi-segment
relative path becomes real nested directories on any platform.

This lives in its own module rather than in `lod_gen` so that the terrain-LOD,
grass and _far.nif code can share one implementation without importing a heavy
sibling module for a three-line path helper.
"""
from pathlib import Path
from fnmatch import fnmatchcase

__all__ = ["win_join", "matches_path_scope", "scoped_files"]


def matches_path_scope(relative_path, selections):
    """Match complete path components against optional folder/file prefixes."""
    if selections is None:
        return True
    parts = tuple(p for p in str(relative_path).replace('\\', '/').lower().split('/') if p)
    for selected in selections:
        prefix = tuple(p for p in str(selected).replace('\\', '/').lower().split('/') if p)
        if prefix and parts[:len(prefix)] == prefix:
            return True
    return False


def scoped_files(root, pattern, paths=None):
    """Select files under a root, without walking the tree for explicit paths."""
    root = Path(root)
    candidates = root.rglob('*') if paths is None else map(Path, paths)
    return sorted(p for p in candidates if p.is_relative_to(root)
                  and fnmatchcase(p.name.lower(), pattern.lower()) and p.is_file())


def win_join(root, rel: str) -> Path:
    """Join a backslash-form (game-format) relative path onto `root`.

    Accepts either separator in `rel` and treats both as path separators, which
    is what the game's own loaders do.  Empty segments (a leading separator, or
    a doubled one) are dropped, so `rel` can never escape `root` the way
    `Path(root) / '\\abs.nif'` would.
    """
    parts = [p for p in str(rel).replace('/', '\\').split('\\') if p]
    return Path(root).joinpath(*parts)
