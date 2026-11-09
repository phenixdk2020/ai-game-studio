"""Project isolation contracts, without external model or coding sessions."""
import copy
import json
from pathlib import Path
import subprocess
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'adapters'))
from project_bridge import Bridge, normalize_plan, pr_number


class ProjectsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.registry = self.folder / 'projects.json'
        self.projects = {'schemaVersion': 1, 'projects': {
            'space': {'name': 'Space game', 'repository': 'example/space', 'base_branch': 'main', 'validation_commands': [['python', 'space_tests.py']]},
            'racing': {'name': 'Racing', 'repository': 'example/racing', 'base_branch': 'develop', 'validation_commands': [['node', 'racing_tests.js']]}}}
        self.save()
        self.config = json.loads((ROOT / 'config/orchestrator.json').read_text())
        self.config.update(project_registry=str(self.registry), jobs_root=str(self.folder / 'jobs'), require_project=True)
        self.task = dict(id='TASK-ONE', title='Build game', description='Add controls', backend='copilot-local', role='gameplay', projectId='space')

    def save(self):
        self.registry.write_text(json.dumps(self.projects))

    def test_two_projects_use_independent_repository_branch_and_tests(self):
        first = Bridge(self.task, self.config)
        other = dict(self.task, id='TASK-TWO', projectId='racing')
        second = Bridge(other, self.config)
        self.assertEqual(first.config['repository'], 'example/space')
        self.assertEqual(second.config['repository'], 'example/racing')
        self.assertEqual(second.config['base_branch'], 'develop')
        self.assertEqual(second.config['validation_commands'], [['node', 'racing_tests.js']])
        self.assertNotEqual(first.directory, second.directory)
        self.assertEqual(self.config['repository'], 'phenixdk2020/ai-game-studio')

    def test_unknown_missing_disabled_project_refuses_before_dispatch(self):
        for value in ('', 'missing', '../space'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Bridge(dict(self.task, projectId=value), self.config)
        self.projects['projects']['space']['enabled'] = False
        self.save()
        with self.assertRaisesRegex(ValueError, 'disabled'):
            Bridge(self.task, self.config)

    def test_missing_project_plan_refused_but_unassigned_research_still_allowed(self):
        with self.assertRaisesRegex(ValueError, 'registered project'):
            Bridge(dict(self.task, projectId='', backend='ollama', kind='plan'), self.config)
        Bridge(dict(self.task, projectId='', backend='ollama', role='historical_research'), self.config)

    def test_task_cannot_override_registered_repository_or_commands(self):
        bridge = Bridge(dict(self.task, repository='attacker/other', validation_commands=[['bad']]), self.config)
        self.assertEqual(bridge.config['repository'], 'example/space')
        self.assertEqual(bridge.config['validation_commands'], [['python', 'space_tests.py']])

    def test_plan_inherits_operator_project_despite_model_override(self):
        bridge = Bridge(dict(self.task, backend='ollama', kind='plan'), self.config)
        plan = normalize_plan({'tasks': [dict(key='code', title='Code', description='Controls', role='gameplay', backend='copilot-local', projectId='racing')]},
                              self.task['id'], bridge.source, self.config['roles'])
        self.assertEqual(plan['tasks'][0]['projectId'], 'space')

    def test_switching_project_same_id_cannot_reuse_receipt(self):
        original = Bridge(self.task, self.config)
        original.path.mkdir(parents=True)
        original.save({'signature': original.signature, 'status': 'Failed'})
        switched = Bridge(dict(self.task, projectId='racing'), self.config)
        with self.assertRaisesRegex(ValueError, 'inputs changed'):
            switched.advance(True)

    def test_changing_project_tests_invalidates_existing_signature(self):
        original = Bridge(self.task, self.config)
        self.projects['projects']['space']['validation_commands'] = [['python', 'different_tests.py']]
        self.save()
        self.assertNotEqual(original.signature, Bridge(self.task, self.config).signature)

    def test_other_project_pr_rejected(self):
        bridge = Bridge(self.task, self.config)
        with self.assertRaisesRegex(ValueError, 'repository'):
            pr_number('https://github.com/example/racing/pull/1', bridge.config['repository'])

    def test_clone_uses_selected_repository(self):
        bridge = Bridge(self.task, self.config)
        with patch.object(bridge, 'tool', return_value='git'), patch.object(bridge, 'command') as command, patch.object(bridge, 'save'):
            bridge.clone({})
        self.assertIn('https://github.com/example/space.git', command.call_args.args[0])

    def test_registry_registration_and_duplicate_refusal(self):
        command = [sys.executable, str(ROOT/'tools/studio_projects.py'), '--root', str(self.folder), 'add', 'newgame', '--name', 'New game',
                   '--repository', 'example/newgame', '--validation-json', '[["python","tests.py"]]']
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
        registry = json.loads((self.folder/'config/projects.json').read_text())
        self.assertEqual(registry['projects']['newgame']['repository'], 'example/newgame')

    @unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell.exe'), 'PowerShell required')
    def test_cli_plan_preserves_project_and_queue_blocks_cross_project_dependencies(self):
        result = subprocess.run([sys.executable, str(ROOT/'tools/studio.py'), '--root', str(self.folder),
            'plan', 'Build space game', '--project-id', 'space'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        tasks = json.loads((self.folder/'tasks/queue.gui.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(tasks[0]['projectId'], 'space')
        self.assertEqual(tasks[0]['kind'], 'plan')
        host = shutil.which('pwsh') or shutil.which('powershell.exe')
        script = "Import-Module '" + str(ROOT/'adapters/Studio.Orchestrator.psm1') + "' -Force;" + """
            $parent=[pscustomobject]@{id='a';status='Completed';projectId='space';dependencies=@()}
            $child=[pscustomobject]@{id='b';status='Queued';projectId='racing';dependencies=@('a');priority=0}
            if(Get-StudioReadyTask -Tasks @($parent,$child)){exit 1}
            $child.projectId='space'
            if((Get-StudioReadyTask -Tasks @($parent,$child)).id -ne 'b'){exit 2}
        """
        result = subprocess.run([host, '-NoProfile', '-Command', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
