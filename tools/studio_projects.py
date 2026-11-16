"""List or register independent Studio projects without touching runtime queues."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'adapters'))
from asset_pipeline import write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('list')
    add = commands.add_parser('add')
    add.add_argument('id')
    add.add_argument('--name', required=True)
    add.add_argument('--kind', choices=('github', 'local'), default='github')
    add.add_argument('--repository', default='')
    add.add_argument('--base-branch', default='main')
    add.add_argument('--project-path', default='')
    validation = add.add_mutually_exclusive_group()
    validation.add_argument('--validation-json')
    validation.add_argument('--validation-file', type=Path)
    args = parser.parse_args(argv)
    path = args.root / 'config/projects.json'
    try:
        registry = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {'schemaVersion': 1, 'projects': {}}
        if registry.get('schemaVersion') != 1 or not isinstance(registry.get('projects'), dict):
            raise ValueError('Invalid project registry')
        if args.action == 'add':
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', args.id):
                raise ValueError('Project ID must contain letters, numbers, underscores or hyphens')
            if args.id in registry['projects']:
                raise ValueError('Project ID already exists; existing projects are not overwritten')
            if args.kind == 'github' and not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
                raise ValueError('Repository must be owner/name')
            if args.kind == 'local':
                from local_project import project_root
                project_root(args.project_path)
                if args.repository:
                    raise ValueError('Local projects do not use a GitHub repository')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*', args.base_branch) or '..' in args.base_branch:
                raise ValueError('Invalid base branch')
            raw = args.validation_file.read_text(encoding='utf-8-sig') if args.validation_file else (args.validation_json or '')
            try:
                tests = json.loads(raw) if raw.strip() else []
            except json.JSONDecodeError:
                raise ValueError('Testkommandoer skal vaere JSON med argumentlister, fx [["python","-m","unittest"]]. Du kan ogsaa lade feltet staa tomt.') from None
            if not isinstance(tests, list) or any(not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg for arg in command) for command in tests):
                raise ValueError('Testkommandoer skal vaere en liste af argumentlister. Tomt felt betyder ingen automatiske tests.')
            if not args.name.strip():
                raise ValueError('Project name is required')
            registry['projects'][args.id] = dict(name=args.name.strip(), kind=args.kind, repository=args.repository, base_branch=args.base_branch,
                project_path=args.project_path, validation_commands=tests, enabled=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, registry)
        print(json.dumps({'ok': True, **registry}, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
