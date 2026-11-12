import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import importlib.util

import test_local_projects as local_tests
from project_bridge import Bridge
from claude_ollama import settings
from local_project import apply_review


class ClaudeOllamaTests(unittest.TestCase):
    def setup_bridge(self, mode='edit'):
        fixture = local_tests.LocalProjectsTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.task['backend'] = 'claude-ollama'
        fixture.config['claude_executable'] = 'fake-claude'
        fixture.config['claude_ollama'] = dict(base_url='http://127.0.0.1:11434', model='test-code')
        self.claude_calls = []
        def runner(args, **kwargs):
            if args[0] == 'fake-claude':
                if '--help' in args:
                    return SimpleNamespace(returncode=0, stdout='--restricted', stderr='')
                self.claude_calls.append((args, kwargs))
                self.assertEqual(kwargs['env']['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:11434')
                self.assertEqual(kwargs['env']['ANTHROPIC_API_KEY'], '')
                self.assertIn('Implement a score counter', kwargs['input'])
                if mode == 'timeout':
                    raise subprocess.TimeoutExpired(args, 1)
                if mode != 'empty':
                    (Path(kwargs['cwd'])/'game.py').write_text('score = 1\n')
                data=dict(subtype='success', is_error=False, result='Edited file.', permission_denials=[])
                if mode == 'denied': data['permission_denials']=[{'tool_name':'Bash'}]
                return SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr='')
            return fixture.runner(args, **kwargs)
        bridge = Bridge(fixture.task, fixture.config, runner=runner)
        bridge.tool = lambda name: 'fake-claude' if name == 'claude' else __import__('shutil').which(name)
        return fixture, bridge

    def run_bridge(self, bridge):
        with patch('claude_ollama.probe', return_value=settings(bridge.config)):
            return bridge.advance(True)

    def test_real_git_flow_waits_for_review_and_explicit_application(self):
        fixture, bridge = self.setup_bridge()
        result = self.run_bridge(bridge)
        self.assertEqual(result['status'], 'AwaitingCodeReview', result)
        self.assertEqual((fixture.source/'game.py').read_text(), 'score = 0\n')
        args, kwargs = self.claude_calls[0]
        self.assertIn('--restricted', args)
        self.assertNotIn('Bash', args[args.index('--tools')+1])
        self.assertNotIn('--dangerously-skip-permissions', args)
        self.assertEqual(result['backend'], 'claude-ollama')
        review = json.loads((bridge.path/'local-review.json').read_text())
        apply_review(fixture.source, Path(json.loads(bridge.receipt_path.read_text())['checkout']), review, fixture.folder/'backups')
        self.assertEqual((fixture.source/'game.py').read_text(), 'score = 1\n')

    def test_interruption_keeps_session_and_never_redispatches(self):
        fixture, bridge = self.setup_bridge('timeout')
        result = self.run_bridge(bridge)
        self.assertEqual(result['status'], 'NeedsInput', result)
        self.assertTrue(result['sessionId'])
        self.run_bridge(bridge)
        self.assertEqual(len(self.claude_calls), 1)

    def test_denied_tools_do_not_produce_success(self):
        _, bridge = self.setup_bridge('denied')
        result = self.run_bridge(bridge)
        self.assertEqual(result['status'], 'NeedsInput', result)
        self.assertIn('denied tools', result['error'])

    def test_configuration_rejects_cloud_and_external_server(self):
        for value in [dict(base_url='https://example.com',model='code'),
                      dict(base_url='http://127.0.0.1:11434',model='code:cloud')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings({'claude_ollama':value})

    def test_changed_model_invalidates_original_receipt(self):
        fixture, bridge = self.setup_bridge()
        self.run_bridge(bridge)
        fixture.config['claude_ollama']['model']='another-code-model'
        other = Bridge(fixture.task, fixture.config, runner=bridge.runner)
        with self.assertRaisesRegex(ValueError, 'Task inputs changed'):
            other.advance(True)

    def test_automatic_offline_code_selection_uses_claude(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('claude_test_selector', root/'tools/agent_selector_v192.py')
        selector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(selector)
        items = [{'backend':b,'available':True} for b in ['copilot-local','claude-ollama','ollama']]
        for preference in ['offline-only','prefer-ollama']:
            task = dict(title='Implement Python code',description='Write a function',routingPreference=preference)
            need, available = selector.eligible(task, items)
            self.assertEqual(need, 'code')
            self.assertEqual(selector.fallback(need, {v['backend'] for v in available}, preference), 'claude-ollama')

    def test_new_backend_requires_a_registered_project(self):
        fixture, _ = self.setup_bridge()
        fixture.task.pop('projectId')
        with self.assertRaisesRegex(ValueError, 'Select a registered project'):
            Bridge(fixture.task, fixture.config)


if __name__ == '__main__':
    unittest.main()
