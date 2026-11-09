"""Local folder snapshots and explicit, conflict-checked application of code changes."""
import hashlib
import os
from pathlib import Path
import shutil

from asset_pipeline import ROOT, read_json, task_lock, write_json

# Generated caches, secrets and Studio runtime data are not agent inputs/outputs.
EXCLUDED = {'.git', '.svn', '.hg', '.venv', 'venv', 'node_modules', '__pycache__',
            '.pytest_cache', '.mypy_cache', 'binaries', 'deriveddatacache', 'intermediate',
            'saved', 'library', 'temp', 'obj',
            '.asset-pipeline.lock'}
ROOT_EXCLUDED = {'logs', 'results', 'tasks', 'state'}


def linked(path):
    # Dropbox/OneDrive placeholders also use reparse points, but do not redirect
    # names. Only name-surrogate tags (junctions/symlinks) escape the folder.
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_reparse_tag', 0) & 0x20000000)


def project_root(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Local project requires a project folder')
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('Local project folder must be an absolute path')
    if path.is_file() and path.suffix.lower() == '.uproject':
        path = path.parent
    if not path.is_dir() or linked(path):
        raise ValueError('Local project folder must exist and cannot be a link')
    path = path.resolve()
    if path == Path(path.anchor) or path == Path.home().resolve() or path == ROOT or path in ROOT.parents:
        raise ValueError('Select a game folder, not a drive, home folder or Studio installation')
    return path


def excluded(name):
    return name.lower() in EXCLUDED or name.lower() == '.env' or name.lower().startswith('.env.') or name.endswith('.pyc')


def files(root):
    root = Path(root)
    for parent, folders, names in os.walk(root, followlinks=False):
        folders[:] = sorted(name for name in folders if not excluded(name) and not (Path(parent) == root and name.lower() in ROOT_EXCLUDED))
        for name in folders + names:
            path = Path(parent) / name
            if not excluded(name) and linked(path):
                raise ValueError('Linked project files/folders are not supported: ' + str(path))
        for name in sorted(names):
            if not excluded(name) and not (Path(parent) == root and name.lower() in ROOT_EXCLUDED):
                path = Path(parent) / name
                if not path.is_file():
                    raise ValueError('Project contains a non-regular file')
                yield path.relative_to(root).as_posix(), path


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def manifest(root):
    return {name: digest(path) for name, path in files(root)}


def snapshot(source, destination):
    source, destination = project_root(str(source)), Path(destination).resolve()
    if destination == source or source in destination.parents:
        raise ValueError('Task workspace cannot be inside the game folder')
    destination.mkdir(parents=True, exist_ok=False)
    baseline = {}
    for name, path in files(source):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        baseline[name] = digest(target)
    if baseline != manifest(source):
        raise ValueError('Project changed while copying; create a fresh task')
    return baseline


def safe_path(root, name):
    relative = Path(name)
    if relative.is_absolute() or not relative.parts or relative.parts[0].lower() in ROOT_EXCLUDED or any(part in {'.', '..'} or ':' in part or '\\' in part or excluded(part) for part in relative.parts):
        raise ValueError('Unsafe local change path: ' + name)
    root = Path(root).resolve()
    path = root / relative
    for part in [path, *path.parents]:
        if part == root:
            break
        if part.exists() and linked(part):
            raise ValueError('Local change path contains a link')
    if root not in path.resolve().parents:
        raise ValueError('Local change escapes project folder')
    return path


def apply_review(source, checkout, review, backup_root):
    """Only called following explicit review approval, never during generation."""
    source, checkout = project_root(str(source)), Path(checkout)
    before, after = review['before'], review['after']
    if review['source'] != str(source):
        raise ValueError('Reviewed source folder changed')
    changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    for name in changed:
        safe_path(source, name)
        safe_path(checkout, name)
    if any(not safe_path(checkout, name).is_file() or digest(safe_path(checkout, name)) != value for name, value in after.items()):
        raise ValueError('Reviewed workspace changed; validate again')
    backup_root = Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    journal = backup_root / 'application.json'
    with task_lock(source):
        prior = read_json(journal) if journal.exists() else {}
        current = manifest(source)
        if prior.get('status') == 'Applied' and current == after:
            return
        if prior.get('status') == 'Applying':
            raise ValueError('Interrupted local application; inspect backup before recovery')
        if current != before:
            raise ValueError('Original project changed since dispatch; no files were overwritten')
        for name in changed:
            if name in before:
                target = backup_root / 'original' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(safe_path(source, name), target)
        write_json(journal, {'status': 'Applying', 'files': changed})
        applied = []
        temporaries = []
        try:
            for name in changed:
                target = safe_path(source, name)
                if (name in before and (not target.is_file() or digest(target) != before[name])) or (name not in before and target.exists()):
                    raise ValueError('Original file changed during application: ' + name)
                if name not in after:
                    target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(target.name + '.studio-apply.tmp')
                    if temporary.exists():
                        raise ValueError('Temporary application file already exists')
                    temporaries.append(temporary)
                    shutil.copy2(safe_path(checkout, name), temporary)
                    os.replace(temporary, target)
                applied.append(name)
            if manifest(source) != after:
                raise ValueError('Project changed during application')
        except Exception:
            rollback_complete = True
            for name in reversed(applied):
                target = safe_path(source, name)
                if (name in after and (not target.is_file() or digest(target) != after[name])) or (name not in after and target.exists()):
                    rollback_complete = False
                    continue  # Preserve an editor's concurrent changes, not our stale backup.
                if name in before:
                    shutil.copy2(backup_root / 'original' / name, target)
                elif target.is_file():
                    target.unlink()
            write_json(journal, {'status': 'RolledBack' if rollback_complete else 'NeedsRecovery', 'files': changed})
            raise
        finally:
            for temporary in temporaries:
                if temporary.is_file():
                    temporary.unlink()
        write_json(journal, {'status': 'Applied', 'files': changed})
