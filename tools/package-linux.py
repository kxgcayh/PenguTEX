#!/usr/bin/env python3
"""Package the published Linux desktop and CLI as a ZIP with Unix permissions."""
from pathlib import Path
import subprocess
import sys
import zipfile


def package_linux(payload, output):
    if not payload.is_dir() or payload.name != 'linux-x64':
        raise ValueError('Expected a linux-x64 package directory')
    paths = [payload, *sorted(payload.rglob('*'))]
    for path in paths:
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(f'Unsupported entry in Linux package: {path}')
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in paths:
            archive.write(path, path.relative_to(payload.parent).as_posix())
    return output


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    version = subprocess.check_output([sys.executable, str(root / 'tools/version.py')], text=True).strip()
    output = root / 'dist' / f'PenguTEX-{version}-linux-x64.zip'
    package_linux(root / 'dist/linux-x64', output)
    print(f'Packaged {output.name}')
