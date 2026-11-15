"""Task chat persistence and queue contract checks; all state is disposable."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'adapters'))
import task_chat


class TaskChatAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'config').mkdir()
        (self.root / 'tasks').mkdir()
        (self.root / 'config/orchestrator.json').write_text(json.dumps({'jobs_root': 'data/pipeline-jobs'}), encoding='utf-8')
        task = {'id': 'TASK-CHAT', 'backend': 'claude-ollama', 'status': 'AwaitingCodeReview', 'sessionId': 'session-1'}
        (self.root / 'tasks/queue.gui.json').write_text(json.dumps([task]), encoding='utf-8')
        self.bridge = self.root / 'data/pipeline-jobs/TASK-CHAT/bridge'
        self.bridge.mkdir(parents=True)
        (self.bridge / 'receipt.json').write_text(json.dumps({'sessionId': 'session-1', 'status': 'AwaitingCodeReview'}), encoding='utf-8')
        self.chat = task_chat.ChatStore(self.root, 'TASK-CHAT', self.root / 'data/task-chats')
        self.chat.start('session-1', 'initial prompt — café')

    def test_history_survives_reopen_and_send_is_idempotent(self):
        calls = []
        request_id = str(uuid.uuid4())
        def submit(*args):
            calls.append(args)
            rows = json.loads((self.root / 'tasks/queue.gui.json').read_text(encoding='utf-8'))
            rows[0]['chatRequestId'] = request_id
            (self.root / 'tasks/queue.gui.json').write_text(json.dumps(rows), encoding='utf-8')
        first = task_chat.send(self.root, 'TASK-CHAT', 'continue — æøå', request_id, submit=submit)
        again = task_chat.send(self.root, 'TASK-CHAT', 'continue — æøå', request_id, submit=submit)
        self.assertEqual(first['status'], 'Queued')
        self.assertFalse(first['duplicate'])
        self.assertTrue(again['duplicate'])
        self.assertEqual(len(calls), 1)
        history = task_chat.history(self.root, 'TASK-CHAT')
        self.assertEqual([e['text'] for e in history['events']], ['initial prompt — café', 'continue — æøå'])
        self.assertEqual(task_chat.ChatStore(self.root, 'TASK-CHAT', self.root / 'data/task-chats').read()['sessionId'], 'session-1')

    def test_pending_question_is_durable_and_answer_can_be_queued(self):
        pending = self.chat.question('session-1', 'Which platform should this target?')
        self.assertEqual(task_chat.history(self.root, 'TASK-CHAT')['pendingQuestion']['id'], pending['id'])
        request_id = str(uuid.uuid4())
        task_chat.send(self.root, 'TASK-CHAT', 'Windows and Linux', request_id, submit=lambda *args: None)
        self.assertEqual(self.chat.claim(request_id, 'session-1'), 'Windows and Linux')
        self.assertIsNone(task_chat.history(self.root, 'TASK-CHAT')['pendingQuestion'])

    def test_queue_failure_can_reconcile_with_same_id_and_rejects_reuse(self):
        request_id = str(uuid.uuid4())
        calls = []
        def fail_once(*args):
            calls.append(args)
            if len(calls) == 1:
                raise RuntimeError('transient queue failure')
        with self.assertRaisesRegex(RuntimeError, 'transient'):
            task_chat.send(self.root, 'TASK-CHAT', 'retry me', request_id, submit=fail_once)
        result = task_chat.send(self.root, 'TASK-CHAT', 'retry me', request_id, submit=fail_once)
        self.assertFalse(result['duplicate'])
        self.assertEqual(len(calls), 2)
        self.assertEqual(len([e for e in self.chat.read()['events'] if e.get('requestId') == request_id]), 1)
        with self.assertRaisesRegex(ValueError, 'different text'):
            task_chat.send(self.root, 'TASK-CHAT', 'different body', request_id, submit=fail_once)

    def test_task_state_gates_preserve_original_and_applied_work(self):
        self.assertTrue(task_chat.history(self.root, 'TASK-CHAT')['canSend'])
        (self.bridge / 'receipt.json').write_text(json.dumps({'sessionId': 'session-1', 'localApplied': True}), encoding='utf-8')
        self.assertFalse(task_chat.history(self.root, 'TASK-CHAT')['canSend'])
        with self.assertRaisesRegex(ValueError, 'applied/completed'):
            task_chat.send(self.root, 'TASK-CHAT', 'late edit', str(uuid.uuid4()), submit=lambda *args: None)

    def test_bridge_and_gui_share_the_same_history_file(self):
        # Bridge.directory is the task job root; Bridge.path is its /bridge child.
        bridge = SimpleNamespace(task={'id': 'TASK-CHAT'}, directory=self.bridge.parent,
                                 config={'jobs_root': str(self.root / 'data/pipeline-jobs')})
        from_bridge = task_chat.for_bridge(bridge)
        from_cli = task_chat.context(self.root, 'TASK-CHAT')[3]
        self.assertEqual(from_bridge.file, from_cli.file)

    def test_running_and_paused_tasks_cannot_accept_turns(self):
        queue = self.root / 'tasks/queue.gui.json'
        task = json.loads(queue.read_text(encoding='utf-8'))[0]
        for status in ('Running', 'Paused', 'Cancelled'):
            task['status'] = status
            queue.write_text(json.dumps([task]), encoding='utf-8')
            self.assertFalse(task_chat.history(self.root, 'TASK-CHAT')['canSend'], status)


if __name__ == '__main__':
    unittest.main()
