"""Portable persisted paths; absolute paths exist only at local API boundaries."""
from pathlib import Path, PurePosixPath
import copy
import stat
from .core import safe_path


def repository_path(root, name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
        or any(c in name for c in '\0*?[]') or name.startswith('/')
        or any(p in {'', '.', '..'} for p in name.split('/'))
        or PurePosixPath(name).as_posix() != name):
        raise ValueError('Canonical repository-relative path required')
    root = Path(root).resolve()
    lexical = root / name
    for part in (lexical, *lexical.parents):
        if part == root:
            break
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024)):
            raise ValueError('Linked repository path refused')
    return safe_path(root, name)


def relative_name(root, resolved):
    """Encode a local, already resolved API path without preserving host prefixes."""
    path = safe_path(root, resolved)
    name = path.relative_to(Path(root).resolve()).as_posix()
    if repository_path(root, name) != path:
        raise ValueError('Path conversion mismatch')
    return name


def portable_job(root, job):
    if set(job) != {'project', 'output', 'metadata'}:
        raise ValueError('Unexpected job fields')
    return {'project': relative_name(root, job['project']),
            'output': relative_name(root, job['output']),
            'metadata': copy.deepcopy(job['metadata'])}


def execution_job(root, job):
    if set(job) != {'project', 'output', 'metadata'}:
        raise ValueError('Unexpected job fields')
    return {'project': str(repository_path(root, job['project'])),
            'output': str(repository_path(root, job['output'])),
            'metadata': copy.deepcopy(job['metadata'])}
