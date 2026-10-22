"""Canonical CLI. All queue changes use the shared PowerShell transactions."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(ROOT))
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ('status', 'setup', 'recover'):
        commands.add_parser(action)
    for action in ('add', 'plan'):
        command = commands.add_parser(action)
        command.add_argument('title')
        command.add_argument('--description', default='')
        command.add_argument('--backend', choices=('auto','asset3d','ollama','copilot-local','copilot-github'), default='auto')
        command.add_argument('--role', default='project_manager')
        command.add_argument('--attachment', action='append', default=[])
        command.add_argument('--depends-on', action='append', default=[])
        command.add_argument('--project', default='')
    command = commands.add_parser('approve'); command.add_argument('id')
    command = commands.add_parser('import-legacy'); command.add_argument('source'); command.add_argument('--apply', action='store_true')
    for action in ('run', 'run-all'):
        command = commands.add_parser(action)
        for flag in ('specialists','assets','blender','unreal','validate-unreal','capture'):
            command.add_argument('--'+flag, action='store_true')
    args = vars(parser.parse_args(argv))
    action = args['action']
    if action in ('add','plan'):
        args.update(action='add', kind='plan' if action=='plan' else 'task',
            description=args['description'] or args['title'], attachments=args.pop('attachment'),
            dependencies=args.pop('depends_on'), projectPath=args.pop('project'))
        if action=='plan': args.update(backend='ollama', role='project_manager')
    if action in ('run','run-all'):
        args.update(action='run', loop=action=='run-all', validateUnreal=args.pop('validate_unreal'))
    host = shutil.which('pwsh') or shutil.which('powershell.exe')
    if not host:
        parser.error('PowerShell is required for the shared queue')
    with TemporaryDirectory(prefix='studio-request-') as folder:
        path = Path(folder)/'request.json'
        path.write_text(json.dumps(args), encoding='utf-8')
        return subprocess.run([host,'-NoProfile','-File',str(ROOT/'tools/studio.ps1'),'-RequestFile',str(path)]).returncode


if __name__=='__main__':
    sys.exit(main())
