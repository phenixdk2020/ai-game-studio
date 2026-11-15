"""Task chat uses real isolated Git copies; only inference/queue submission are mocked."""
import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import test_claude_ollama as claude_tests
from asset_pipeline import task_lock, write_json
from claude_ollama import settings
from task_chat import ChatStore, for_bridge, history, send


class TaskChatTests(unittest.TestCase):
    def setup_bridge(self, mode='edit'):
        fixture, bridge = claude_tests.ClaudeOllamaTests.setup_bridge(self, mode)
        self.root = fixture.folder
        (self.root/'config').mkdir()
        (self.root/'tasks').mkdir()
        write_json(self.root/'config/orchestrator.json', fixture.config)
        self.fixture, self.bridge = fixture, bridge
        return fixture, bridge

    def run_bridge(self, **kwargs):
        with patch('claude_ollama.probe', return_value=settings(self.bridge.config)):
            return self.bridge.advance(True, **kwargs)

    def queue_state(self, result):
        self.task = {**self.fixture.task, **result}
        write_json(self.root/'tasks/queue.gui.json', [self.task])

    def submit(self, root, task_id, request_id, path):
        self.task.update(status='Queued', bridgeAction='resume-chat', chatRequestId=request_id)
        write_json(self.root/'tasks/queue.gui.json', [self.task])
        self.bridge.task.update(status='Queued', chatRequestId=request_id)
        return {'ok': True}

    def no_edit_runner(self):
        original = self.bridge.runner
        def run(args, **kwargs):
            if args[0] == 'fake-claude' and '--resume' in args:
                self.claude_calls.append((args, kwargs))
                return SimpleNamespace(returncode=0, stdout=json.dumps(dict(subtype='success',
                    is_error=False, result='The current score implementation is ready.', permission_denials=[])), stderr='')
            return original(args, **kwargs)
        self.bridge.runner = run

    def test_followup_same_session_config_signature_and_existing_code_review(self):
        self.setup_bridge()
        result = self.run_bridge()
        self.queue_state(result)
        original = copy.deepcopy(self.fixture.task)
        before = json.loads(self.bridge.receipt_path.read_text())
        self.no_edit_runner()
        request = str(uuid.uuid4())
        send(self.root, self.task['id'], 'Explain the score change without editing files.', request, self.submit)
        final = self.run_bridge(resume_chat=True)
        self.queue_state(final)
        after = json.loads(self.bridge.receipt_path.read_text())
        args, options = self.claude_calls[-1]
        self.assertEqual(args[args.index('--resume')+1], before['sessionId'])
        self.assertNotIn('--session-id', args)
        self.assertEqual(options['env']['CLAUDE_CONFIG_DIR'], str(self.bridge.path/'claude-config'))
        self.assertEqual(after['signature'], before['signature'])
        self.assertEqual(after['validatedHead'], before['validatedHead'])
        self.assertEqual(final['status'], 'AwaitingCodeReview', final)
        self.assertEqual(self.fixture.task['description'], original['description'])
        self.assertEqual((self.fixture.source/'game.py').read_text(), 'score = 0\n')
        reopened = history(self.root, self.task['id'])
        self.assertTrue(reopened['canSend'], reopened)
        self.assertEqual([event['role'] for event in reopened['events']], ['user','assistant','user','assistant'])

    def test_duplicate_request_and_overlap_do_not_create_turns(self):
        self.setup_bridge()
        self.queue_state(self.run_bridge())
        request = str(uuid.uuid4())
        first = send(self.root, self.task['id'], 'Explain.', request, self.submit)
        duplicate = send(self.root, self.task['id'], 'Explain.', request, self.submit)
        self.assertFalse(first['duplicate'])
        self.assertTrue(duplicate['duplicate'])
        with self.assertRaisesRegex(ValueError, 'different text'):
            send(self.root, self.task['id'], 'Changed.', request, self.submit)
        with self.assertRaisesRegex(ValueError, 'queued or running'):
            send(self.root, self.task['id'], 'Overlapping.', str(uuid.uuid4()), self.submit)
        self.assertEqual(len(for_bridge(self.bridge).read()['requests']), 1)

    def test_rejected_queue_rolls_back_message_and_accepts_same_id_after_retry(self):
        self.setup_bridge()
        self.queue_state(self.run_bridge())
        request = str(uuid.uuid4())
        def reject(*args): raise ValueError('Queue status changed')
        before = for_bridge(self.bridge).read()
        with self.assertRaisesRegex(ValueError, 'Queue status changed'):
            send(self.root, self.task['id'], 'Hello.', request, reject)
        self.assertEqual(for_bridge(self.bridge).read(), before)
        self.assertTrue(send(self.root, self.task['id'], 'Hello.', request, self.submit)['ok'])

    def test_concurrent_sender_is_rejected_by_process_lock(self):
        self.setup_bridge()
        self.queue_state(self.run_bridge())
        store = for_bridge(self.bridge)
        with task_lock(store.path), self.assertRaisesRegex(RuntimeError, 'locked by another'):
            send(self.root, self.task['id'], 'Hello.', str(uuid.uuid4()), self.submit)

    @unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell.exe'), 'PowerShell required')
    def test_official_queue_transaction_and_same_id_recovery_after_prequeue_crash(self):
        self.setup_bridge()
        self.queue_state(self.run_bridge())
        (self.root/'adapters').mkdir()
        source = Path(__file__).resolve().parents[1]/'adapters/Studio.Queue.psm1'
        shutil.copyfile(source, self.root/'adapters/Studio.Queue.psm1')
        request = str(uuid.uuid4())
        # Simulate termination after durable chat intent and before queue mutation.
        def crash(*args): raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            send(self.root, self.task['id'], 'Explain.', request, crash)
        self.assertFalse(history(self.root, self.task['id'])['activeRequest']['submissionConfirmed'])
        response = send(self.root, self.task['id'], 'Explain.', request)
        self.assertTrue(response['duplicate'])
        queued = json.loads((self.root/'tasks/queue.gui.json').read_text())[0]
        self.assertEqual(queued['chatRequestId'], request)
        self.assertEqual(queued['bridgeAction'], 'resume-chat')
        self.assertEqual(queued['description'], self.fixture.task['description'])

    def test_initial_question_stops_validation_and_answer_resumes_same_session(self):
        self.setup_bridge('empty')
        original = self.bridge.runner
        def ask(args, **kwargs):
            if args[0] == 'fake-claude' and '-p' in args:
                receipt = json.loads(self.bridge.receipt_path.read_text())
                for_bridge(self.bridge).question(receipt['sessionId'], 'Should the score start at one?')
            return original(args, **kwargs)
        self.bridge.runner = ask
        result = self.run_bridge()
        self.assertEqual(result['status'], 'NeedsInput', result)
        self.assertEqual(result['question'], 'Should the score start at one?')
        self.assertFalse((self.bridge.path/'validation.json').exists())
        self.queue_state(result)
        self.assertTrue(history(self.root, self.task['id'])['pendingQuestion'])
        self.no_edit_runner()
        send(self.root, self.task['id'], 'Only summarize; keep the code unchanged.', str(uuid.uuid4()), self.submit)
        final = self.run_bridge(resume_chat=True)
        self.assertEqual(final['sessionId'], result['sessionId'])
        self.assertEqual(final['status'], 'NeedsInput', final)
        self.assertIsNone(for_bridge(self.bridge).read()['pendingQuestion'])
        self.assertNotIn('no local code changes', final['error'])

    def test_failed_turn_is_not_blindly_redispatched(self):
        self.setup_bridge()
        self.queue_state(self.run_bridge())
        send(self.root, self.task['id'], 'Explain.', str(uuid.uuid4()), self.submit)
        original = self.bridge.runner
        def fail(args, **kwargs):
            if '--resume' in args: raise TimeoutError('Inference timeout')
            return original(args, **kwargs)
        self.bridge.runner = fail
        failed = self.run_bridge(resume_chat=True)
        self.assertEqual(failed['status'], 'NeedsInput')
        self.queue_state(failed)
        self.assertFalse(history(self.root, self.task['id'])['canSend'])
        with self.assertRaisesRegex(ValueError, 'active or unresolved'):
            self.run_bridge(resume_chat=True)

    def test_applied_completed_paused_cancelled_and_invalid_ids_reject(self):
        self.setup_bridge()
        result = self.run_bridge()
        self.queue_state(result)
        for status in ['Completed','Paused','Cancelled','Running']:
            self.task['status'] = status
            write_json(self.root/'tasks/queue.gui.json', [self.task])
            self.assertFalse(history(self.root, self.task['id'])['canSend'])
        self.task['status'] = 'AwaitingCodeReview'
        write_json(self.root/'tasks/queue.gui.json', [self.task])
        receipt = json.loads(self.bridge.receipt_path.read_text())
        receipt['localApplied'] = True
        write_json(self.bridge.receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, 'already applied'):
            send(self.root, self.task['id'], 'Hello.', str(uuid.uuid4()), self.submit)
        for value in ['../evil','CON','TASK/x']:
            with self.assertRaises(ValueError): ChatStore(self.root, value)

    def test_stale_failed_queue_cannot_resume_a_running_receipt(self):
        self.setup_bridge()
        self.queue_state(self.run_bridge())
        send(self.root, self.task['id'], 'Explain.', str(uuid.uuid4()), self.submit)
        receipt = json.loads(self.bridge.receipt_path.read_text())
        receipt['status'] = 'Running'
        write_json(self.bridge.receipt_path, receipt)
        self.task['status'] = 'Failed'
        write_json(self.root/'tasks/queue.gui.json', [self.task])
        self.assertFalse(history(self.root, self.task['id'])['canSend'])
        calls = len(self.claude_calls)
        with self.assertRaisesRegex(ValueError, 'active or unresolved'):
            self.run_bridge(resume_chat=True)
        self.assertEqual(len(self.claude_calls), calls)


if __name__ == '__main__': unittest.main()
