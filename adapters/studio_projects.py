"""Operator-owned project registry; model output cannot select a repository."""
import copy
import re
from pathlib import Path
from asset_pipeline import ROOT, read_json


def project_config(task, config):
    effective = copy.deepcopy(config)
    project_id = task.get('projectId', '')
    if not project_id:
        if config.get('require_project') and (task.get('backend') in {'copilot-local', 'copilot-github'} or task.get('kind') == 'plan'):
            raise ValueError('Select a registered project before planning or coding; no Studio repository fallback is allowed')
        return effective
    if not isinstance(project_id, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', project_id):
        raise ValueError('Invalid projectId')
    path = Path(config.get('project_registry', 'config/projects.json'))
    registry = read_json(path if path.is_absolute() else ROOT / path)
    if registry.get('schemaVersion') != 1 or not isinstance(registry.get('projects'), dict):
        raise ValueError('Invalid project registry')
    project = registry['projects'].get(project_id)
    if not isinstance(project, dict) or project.get('enabled', True) is not True:
        raise ValueError('Unknown or disabled project: ' + project_id)
    kind = project.get('kind', 'github')
    if kind not in {'github', 'local'}:
        raise ValueError('Project kind must be github or local')
    effective['project_kind'] = kind
    for key in ('base_branch', 'validation_commands'):
        if key not in project:
            raise ValueError('Project requires ' + key)
        effective[key] = copy.deepcopy(project[key])
    if kind == 'github':
        if not project.get('repository'):
            raise ValueError('GitHub project requires repository')
        effective['repository'] = project['repository']
    else:
        from local_project import project_root
        effective['local_project_root'] = str(project_root(project.get('project_path', '')))
        effective['repository'] = ''
        if task.get('backend') == 'copilot-github':
            raise ValueError('A local project requires copilot-local; GitHub cloud cannot access its folder')
    # Executables, job paths and permissions cannot be overridden by a project.
    effective['project_id'] = project_id
    return effective
