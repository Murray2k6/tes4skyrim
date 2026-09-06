"""Select current assets for delivery and replace ZIPs only after success."""
import json
from pathlib import Path
import zipfile

RECEIPT = '.bsa-pack.json'
PLUGIN_EXTENSIONS = {'.esm', '.esp', '.esl'}


def asset_files(root):
    """Use the same directory ownership as the BSA packer; SKSE stays loose."""
    return sorted(path for directory in Path(root).iterdir()
                  if directory.is_dir()
                  and directory.name.lower() != 'skse'
                  and not directory.name.startswith('_bsa_staging_')
                  for path in directory.rglob('*') if path.is_file())


def file_state(root, files):
    """Local build receipt, never a shared cache key or shipped metadata."""
    result = {}
    for path in files:
        stat = path.stat()
        result[path.relative_to(root).as_posix()] = [stat.st_size, stat.st_mtime_ns]
    return result


def record_pack(root, sources, archives):
    receipt = Path(root) / RECEIPT
    temporary = receipt.with_suffix('.json.part')
    try:
        temporary.write_text(json.dumps({
            'sources': sources,
            'archives': file_state(root, [Path(p) for p in archives]),
        }, sort_keys=True), encoding='utf-8')
        temporary.replace(receipt)
    finally:
        temporary.unlink(missing_ok=True)


def current_archives(root, assets):
    try:
        receipt = json.loads((root / RECEIPT).read_text(encoding='utf-8'))
        if receipt['sources'] != file_state(root, assets):
            return []
        names = receipt['archives']
        if not isinstance(names, dict) or not names:
            return []
        # A receipt only names root-level BSA outputs from the packer.
        if any(Path(name).name != name or Path(name).suffix.lower() != '.bsa'
               for name in names):
            return []
        archives = [root / name for name in sorted(names)]
        return archives if file_state(root, archives) == names else []
    except (OSError, ValueError, KeyError, TypeError):
        return []


def write_zip(root, destination):
    root, destination = Path(root), Path(destination)
    root_files = sorted(p for p in root.iterdir() if p.is_file())
    plugins = [p for p in root_files if p.suffix.lower() in PLUGIN_EXTENSIONS]
    assets = asset_files(root)
    archives = current_archives(root, assets) if plugins else []
    if not assets and not archives and not (root / RECEIPT).exists():
        archives = [p for p in root_files if p.suffix.lower() == '.bsa']
        if archives and not plugins:
            raise ValueError('An asset-only mod needs loose assets; its BSAs have no loader plugin')
    files = plugins + (archives or assets)
    files += [p for p in root_files if p.suffix.lower() in {'.ini', '.txt'}]
    files += sorted(p for d in root.iterdir() if d.is_dir() and d.name.lower() == 'skse'
                    for p in d.rglob('*') if p.is_file())
    if not files:
        return 0
    print(f'  ZIP: {"current BSAs" if archives else "loose assets"}, {len(files)} files', flush=True)
    temporary = destination.with_suffix('.zip.part')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for index, path in enumerate(files, 1):
                archive.write(path, path.relative_to(root).as_posix())
                if index % 500 == 0:
                    print(f'    ZIP: {index}/{len(files)} files', flush=True)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return len(files)
