"""Real local Git/filesystem flow; the Copilot process alone is simulated."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'adapters'))
from project_bridge import Bridge
from local_project import apply_review, digest, linked, manifest, project_root, safe_path, snapshot


@unittest.skipUnless(shutil.which('git'), 'Git required')
class LocalProjectsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder/'game'
        self.source.mkdir()
        (self.source/'game.py').write_text('score = 0\n')
        (self.source/'keep.txt').write_text('untouched')
        self.registry = self.folder/'projects.json'
        self.project = dict(name='Local game', kind='local', project_path=str(self.source), base_branch='main',
                            validation_commands=[['python', '-c', "from pathlib import Path; assert Path('game.py').read_text() == 'score = 1\\n'"]])
        self.save_registry()
        self.config = json.loads((ROOT/'config/orchestrator.json').read_text())
        self.config.update(project_registry=str(self.registry), jobs_root=str(self.folder/'jobs'), require_project=True)
        self.task = dict(id='TASK-LOCAL', title='Add score', description='Implement a score counter', role='gameplay', backend='copilot-local', projectId='localgame', attachments=[], projectPath='')
        self.calls = []
        self.mode = 'normal'

    def save_registry(self):
        self.registry.write_text(json.dumps(dict(schemaVersion=1, projects={'localgame': self.project})))

    def runner(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == 'fake-copilot':
            checkout = Path(args[args.index('-C')+1])
            (checkout/'game.py').write_text('score = 1\n')
            if self.mode == 'delete':
                (checkout/'keep.txt').unlink()
            if self.mode == 'add':
                (checkout/'new.py').write_text('value = 2\n')
            if self.mode == 'protected':
                (checkout/'state').mkdir()
                (checkout/'state/forbidden.py').write_text('bad')
            return SimpleNamespace(returncode=0, stdout=json.dumps({'sessionId':'local-test'}), stderr='')
        self.assertNotIn('gh', Path(args[0]).name.lower())
        self.assertNotIn('push', args)
        self.assertNotIn('clone', args)
        return subprocess.run(args, **kwargs)

    def bridge(self):
        bridge = Bridge(self.task, self.config, runner=self.runner)
        bridge.tool = lambda name: 'fake-copilot' if name == 'copilot' else shutil.which(name)
        return bridge

    def generated(self):
        bridge = self.bridge()
        result = bridge.advance(True)
        self.assertEqual(result['status'], 'AwaitingCodeReview', result)
        return bridge, result

    def test_folder_without_git_generates_review_without_original_writes_or_github(self):
        bridge, result = self.generated()
        self.assertFalse((self.source/'.git').exists())
        self.assertEqual((self.source/'game.py').read_text(), 'score = 0\n')
        self.assertEqual(result['prUrl'], '')
        self.assertIn('game.py', (bridge.path/'changes.patch').read_text())
        self.assertTrue((bridge.path/'review.md').exists())
        with self.assertRaisesRegex(ValueError, 'explicit review approval'):
            bridge.verify_review()
        with self.assertRaisesRegex(ValueError, 'expected head'):
            bridge.verify_review(apply_local=True)
        self.assertEqual((self.source/'game.py').read_text(), 'score = 0\n')

    def test_explicit_approval_applies_changes_and_backup_and_is_idempotent(self):
        bridge, result = self.generated()
        verified = bridge.verify_review(apply_local=True, expected_head=result['validatedHead'])
        self.assertTrue(verified['localApplied'])
        self.assertEqual((self.source/'game.py').read_text(), 'score = 1\n')
        self.assertEqual((self.source/'keep.txt').read_text(), 'untouched')
        self.assertEqual((bridge.path/'local-backup/original/game.py').read_text(), 'score = 0\n')
        bridge.verify_review(apply_local=True, expected_head=result['validatedHead'])
        self.assertEqual(bridge.verify_review()['status'], 'Verified')

    def test_user_changes_in_original_refuse_application_without_overwrite(self):
        bridge, result = self.generated()
        (self.source/'keep.txt').write_text('user changed this')
        with self.assertRaisesRegex(ValueError, 'Original project changed'):
            bridge.verify_review(apply_local=True, expected_head=result['validatedHead'])
        self.assertEqual((self.source/'game.py').read_text(), 'score = 0\n')
        self.assertEqual((self.source/'keep.txt').read_text(), 'user changed this')

    def test_wrong_review_head_and_modified_review_refuse_application(self):
        bridge, result = self.generated()
        with self.assertRaisesRegex(ValueError, 'head changed'):
            bridge.verify_review(apply_local=True, expected_head='b'*40)
        (bridge.path/'local-review.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'review was modified'):
            bridge.verify_review(apply_local=True, expected_head=result['validatedHead'])
        self.assertEqual((self.source/'game.py').read_text(), 'score = 0\n')

    def test_modified_workspace_refuses_application(self):
        bridge, result = self.generated()
        receipt = json.loads(bridge.receipt_path.read_text())
        (Path(receipt['checkout'])/'game.py').write_text('unreviewed')
        with self.assertRaisesRegex(ValueError, 'workspace changed'):
            bridge.verify_review(apply_local=True, expected_head=result['validatedHead'])

    def test_failed_validation_and_protected_changes_never_apply(self):
        self.project['validation_commands'] = [['python', '-c', 'raise SystemExit(1)']]
        self.save_registry()
        bridge = self.bridge()
        self.assertEqual(bridge.advance(True)['status'], 'Failed')
        self.assertEqual((self.source/'game.py').read_text(), 'score = 0\n')
        self.task['id'] = 'TASK-PROTECTED'
        self.project['validation_commands'] = [['python', '-c', 'pass']]
        self.save_registry()
        self.mode = 'protected'
        result = self.bridge().advance(True)
        self.assertEqual(result['status'], 'Failed')
        self.assertIn('protected', result['error'])

    def test_reviewed_additions_and_deletions_are_applied(self):
        for mode in ('add', 'delete'):
            with self.subTest(mode=mode):
                self.task['id'] = 'TASK-' + mode.upper()
                self.mode = mode
                bridge, result = self.generated()
                bridge.verify_review(apply_local=True, expected_head=result['validatedHead'])
                if mode == 'add':
                    self.assertTrue((self.source/'new.py').is_file())
                else:
                    self.assertFalse((self.source/'keep.txt').exists())
                (self.source/'game.py').write_text('score = 0\n')

    def test_revalidation_uses_existing_copy_without_second_copilot_call(self):
        bridge, result = self.generated()
        count = sum(args[0] == 'fake-copilot' for args in self.calls)
        self.assertEqual(bridge.advance(True, revalidate=True)['status'], 'AwaitingCodeReview')
        self.assertEqual(sum(args[0] == 'fake-copilot' for args in self.calls), count)
        self.assertEqual((self.source/'game.py').read_text(), 'score = 0\n')

    def test_rejected_removed_flag_can_retry_same_snapshot_without_duplicate_session(self):
        bridge = self.bridge()
        runner = bridge.runner
        rejected = False
        def reject_first(args, **kwargs):
            nonlocal rejected
            if args[0] == 'fake-copilot' and not rejected:
                rejected = True
                return SimpleNamespace(returncode=2, stdout='', stderr='error: --no-remote was removed. Use /remote off in a session.')
            return runner(args, **kwargs)
        bridge.runner = reject_first
        self.assertEqual(bridge.advance(True)['status'], 'NeedsInput')
        before = json.loads(bridge.receipt_path.read_text())
        self.assertTrue(bridge.rejected_cli_start(before))
        self.assertEqual(bridge.advance(True)['status'], 'AwaitingCodeReview')
        after = json.loads(bridge.receipt_path.read_text())
        self.assertEqual(before['checkout'], after['checkout'])
        self.assertEqual(before['snapshotHead'], after['snapshotHead'])
        self.assertIn('--no-remote was removed', after['cliStartRecovery']['reason'])
        count = sum(args[0] == 'fake-copilot' for args in self.calls)
        bridge.advance(True)
        self.assertEqual(sum(args[0] == 'fake-copilot' for args in self.calls), count)
        self.assertEqual((self.source/'game.py').read_text(), 'score = 0\n')

    def test_non_parser_cli_failure_never_automatically_retries(self):
        bridge = self.bridge()
        runner = bridge.runner
        def fail(args, **kwargs):
            if args[0] == 'fake-copilot':
                return SimpleNamespace(returncode=1, stdout='', stderr='network connection lost')
            return runner(args, **kwargs)
        bridge.runner = fail
        self.assertEqual(bridge.advance(True)['status'], 'NeedsInput')
        with patch.object(bridge, 'execute_copilot') as execute:
            self.assertEqual(bridge.advance(True)['status'], 'NeedsInput')
            execute.assert_not_called()

    def test_local_project_rejects_cloud_backend_and_accepts_no_repository(self):
        self.task['backend'] = 'copilot-github'
        with self.assertRaisesRegex(ValueError, 'requires copilot-local'):
            self.bridge()
        self.task['backend'] = 'copilot-local'
        self.assertEqual(self.bridge().config['repository'], '')

    def test_no_configured_tests_is_reported_truthfully_and_requires_review(self):
        self.project['validation_commands'] = []
        self.save_registry()
        bridge, result = self.generated()
        report = json.loads((bridge.path/'validation.json').read_text())
        self.assertEqual(report['status'], 'not-configured')
        self.assertEqual(report['checks'], [])
        self.assertEqual(report['gitDiffChecks'], 'pass')
        self.assertIn('INGEN AUTOMATISKE PROJEKTTESTS', result['question'])
        self.assertNotIn('tests er bestaaet', (bridge.path/'review.md').read_text())
        self.assertEqual((self.source/'game.py').read_text(), 'score = 0\n')
        with self.assertRaisesRegex(ValueError, 'explicit review approval'):
            bridge.verify_review()

    def test_registration_local_folder_does_not_require_github_or_git(self):
        result = subprocess.run([sys.executable, str(ROOT/'tools/studio_projects.py'), '--root', str(self.folder), 'add', 'another',
            '--name', 'Another', '--kind', 'local', '--project-path', str(self.source), '--validation-json', '[["python","tests.py"]]'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads((self.folder/'config/projects.json').read_text())['projects']['another']
        self.assertEqual(data['kind'], 'local')
        self.assertEqual(data['repository'], '')
        self.assertFalse((self.source/'.git').exists())

    def test_local_plan_forces_local_code_backend_despite_cloud_default(self):
        self.task.update(backend='ollama', kind='plan', role='project_manager')
        self.config['default_code_backend'] = 'copilot-github'
        plan = {'tasks': [dict(key='code', title='Code game', description='Add score', role='gameplay', backend='copilot-github')]}
        bridge = Bridge(self.task, self.config, http=lambda payload: {'choices': [{'message': {'content': json.dumps(plan)}}]})
        self.assertEqual(bridge.advance(True)['status'], 'AwaitingPlanReview')
        task = json.loads((bridge.path/'plan.json').read_text())['tasks'][0]
        self.assertEqual(task['backend'], 'copilot-local')
        self.assertEqual(task['projectId'], 'localgame')

    def test_snapshot_ignores_caches_secrets_and_retains_nested_state_code(self):
        (self.source/'node_modules').mkdir()
        (self.source/'node_modules/cache').write_text('cache')
        (self.source/'.env').write_text('secret')
        (self.source/'src/state').mkdir(parents=True)
        (self.source/'src/state/game.py').write_text('code')
        target = self.folder/'snapshot'
        snapshot(self.source, target)
        self.assertFalse((target/'.env').exists())
        self.assertFalse((target/'node_modules').exists())
        self.assertEqual((target/'src/state/game.py').read_text(), 'code')
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            safe_path(self.source, '../escape')
        with self.assertRaisesRegex(ValueError, 'inside'):
            snapshot(self.source, self.source/'inside')

    def test_cloud_placeholders_are_not_junctions_or_symbolic_links(self):
        for tag, redirected in ((0x9000001A, False), (0xA0000003, True), (0xA000000C, True)):
            path = SimpleNamespace(is_symlink=lambda: False, lstat=lambda: SimpleNamespace(st_reparse_tag=tag))
            self.assertEqual(linked(path), redirected)

    def test_failed_application_rolls_back_earlier_changes(self):
        self.mode = 'add'
        bridge, result = self.generated()
        original = __import__('local_project').os.replace
        def fail_second(source, target):
            if Path(target).name == 'new.py':
                raise OSError('simulated write failure')
            return original(source, target)
        with patch('local_project.os.replace', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'simulated'):
                bridge.verify_review(apply_local=True, expected_head=result['validatedHead'])
        self.assertEqual((self.source/'game.py').read_text(), 'score = 0\n')
        self.assertFalse((self.source/'new.py').exists())
        self.assertFalse(list(self.source.glob('*.studio-apply.tmp')))
        self.assertEqual(manifest(self.source), json.loads((bridge.path/'local-source.json').read_text()))

    def test_empty_local_folder_can_generate_new_project_files(self):
        (self.source/'game.py').unlink()
        (self.source/'keep.txt').unlink()
        bridge, result = self.generated()
        self.assertEqual(list(self.source.iterdir()), [])
        bridge.verify_review(apply_local=True, expected_head=result['validatedHead'])
        self.assertEqual((self.source/'game.py').read_text(), 'score = 1\n')

    @unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell.exe'), 'PowerShell required')
    def test_operator_queue_approval_applies_and_completes_only_unchanged_task(self):
        studio = self.folder/'studio'
        (studio/'config').mkdir(parents=True)
        self.config['jobs_root'] = str(studio/'data/pipeline-jobs')
        (studio/'config/orchestrator.json').write_text(json.dumps(self.config))
        bridge, result = self.generated()
        task_file = bridge.directory/'bridge-task.json'
        task_file.write_text(json.dumps(self.task))
        task = dict(self.task, **{key: value for key, value in result.items() if key != 'taskId'})
        queue = studio/'tasks/queue.gui.json'
        queue.parent.mkdir()
        task['projectId'] = 'wrong-project'
        queue.write_text(json.dumps([task]))
        host = shutil.which('pwsh') or shutil.which('powershell.exe')
        script = "$ErrorActionPreference='Stop';Import-Module '" + str(ROOT/'adapters/Studio.Orchestrator.psm1') + "' -Force;Approve-StudioResult -Root '" + str(studio) + "' -Id 'TASK-LOCAL'"
        failed = subprocess.run([host, '-NoProfile', '-Command', script], capture_output=True, text=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual((self.source/'game.py').read_text(), 'score = 0\n')
        task['projectId'] = 'localgame'
        queue.write_text(json.dumps([task]))
        approved = subprocess.run([host, '-NoProfile', '-Command', script], capture_output=True, text=True)
        self.assertEqual(approved.returncode, 0, approved.stdout + approved.stderr)
        self.assertEqual(json.loads(queue.read_text(encoding='utf-8-sig'))[0]['status'], 'Completed')
        self.assertEqual((self.source/'game.py').read_text(), 'score = 1\n')


if __name__ == '__main__':
    unittest.main()
