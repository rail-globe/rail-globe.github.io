"""Reject inherited output links before a generator can overwrite another copy."""
from pathlib import Path
import json
import os
import tempfile


def require_owned(directory, names):
    directory = Path(directory).absolute()
    if directory.is_symlink():
        raise ValueError(f'Output directory is a symlink: {directory}')
    for name in names:
        target = Path(os.path.abspath(directory / name))
        if not target.absolute().is_relative_to(directory):
            raise ValueError(f'Output escapes its directory: {target}')
        for part in (target, *target.parents):
            if part.is_symlink():
                raise ValueError(f'Output follows a symlink: {part}')
            if part == directory:
                break


def atomic_json(target, value):
    target = Path(target)
    require_owned(target.parent, [target.name])
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name+'.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
