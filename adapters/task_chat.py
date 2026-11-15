"""Durable task-scoped Claude conversation and explicit asynchronous continuation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from asset_pipeline import ROOT, contained, read_json, task_lock, write_json

MAX_MESSAGE = 24000
SEND_STATUSES = {'AwaitingCodeReview', 'NeedsInput', 'Failed'}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def validate_id(value):
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', value)
            or re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]', value, re.I)):
        raise ValueError('Invalid task id')
    return value


class ChatStore:
    def __init__(self, root, task_id, base=None):
        self.root = Path(root).resolve()
        self.task_id = validate_id(task_id)
        base = Path(base or self.root/'data/task-chats').resolve()
        self.path = contained(base/self.task_id, base)
        self.file = self.path/'state.json'

    def read(self):
        return read_json(self.file) if self.file.exists() else dict(schemaVersion=1, taskId=self.task_id,
            sessionId='', events=[], requests={}, activeTurn=None, pendingQuestion=None)

    def edit(self, callback):
        self.path.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic()+35
        while True:
            try:
                with task_lock(self.path):
                    state = self.read()
                    result = callback(state)
                    write_json(self.file, state)
                    return result
            except RuntimeError as error:
                if 'locked by another' not in str(error) or time.monotonic() >= deadline: raise
                time.sleep(.05)

    @staticmethod
    def event(state, role, text, kind='message', **extra):
        text = str(text)[:64000]
        state['events'].append(dict(seq=len(state['events'])+1, role=role, text=text,
                                   createdAt=stamp(), kind=kind, **extra))

    def start(self, session, prompt):
        def update(state):
            if state['sessionId'] and state['sessionId'] != session:
                raise ValueError('Task chat already belongs to a different session')
            state['sessionId'] = session
            if not state['events']:
                self.event(state, 'user', prompt, 'initial-task')
        self.edit(update)

    def question(self, session, question):
        if not isinstance(question, str) or not question.strip() or len(question)>8000:
            raise ValueError('Question must contain 1..8000 characters')
        def update(state):
            if state['sessionId'] != session: raise ValueError('Session identity changed')
            if state['pendingQuestion']:
                return state['pendingQuestion']
            pending = dict(id=str(uuid.uuid4()), text=question, createdAt=stamp())
            state['pendingQuestion'] = pending
            self.event(state, 'assistant', question, 'question')
            return pending
        return self.edit(update)

    def tool_event(self, name, failed=False):
        self.edit(lambda state: self.event(state, 'tool', name + (' failed' if failed else ' completed'), 'tool-summary'))

    def finish(self, text=None, error=None):
        def update(state):
            if text: self.event(state, 'assistant', text)
            if error: self.event(state, 'system', error, 'error')
            active = state.get('activeTurn')
            if active:
                state['requests'][active]['status'] = 'failed' if error else 'complete'
                state['requests'][active]['finishedAt'] = stamp()
                state['activeTurn'] = None
        self.edit(update)

    def claim(self, request_id, session):
        def update(state):
            if state['sessionId'] != session: raise ValueError('Session identity changed')
            if state.get('activeTurn') != request_id: raise ValueError('No matching queued chat turn')
            request = state['requests'][request_id]
            if request['status'] != 'queued':
                raise ValueError('Chat turn was already dispatched; reconcile the existing session before continuing')
            request['status'] = 'dispatching'
            request['startedAt'] = stamp()
            state['pendingQuestion'] = None
            return request['message']
        return self.edit(update)


def chat_base(config, root):
    jobs = Path(config.get('jobs_root', 'data/pipeline-jobs'))
    if not jobs.is_absolute(): jobs = Path(root)/jobs
    return jobs.parent/'task-chats'


def for_bridge(bridge):
    return ChatStore(ROOT, bridge.task['id'], base=chat_base(bridge.config, ROOT))


def load_task(root, task_id):
    rows = read_json(Path(root)/'tasks/queue.gui.json')
    if isinstance(rows, dict): rows = rows.get('value', rows.get('tasks', []))
    matches = [task for task in rows if task.get('id') == validate_id(task_id)]
    if len(matches) != 1: raise ValueError('Task not found')
    return matches[0]


def context(root, task_id):
    root = Path(root).resolve()
    task = load_task(root, task_id)
    config = read_json(root/'config/orchestrator.json')
    jobs = Path(config.get('jobs_root', 'data/pipeline-jobs'))
    if not jobs.is_absolute(): jobs = root/jobs
    bridge_path = contained(jobs/task_id/'bridge', jobs)
    receipt = read_json(bridge_path/'receipt.json') if (bridge_path/'receipt.json').exists() else {}
    return task, receipt, bridge_path, ChatStore(root, task_id, chat_base(config, root))


def reason(task, receipt, state):
    if task.get('backend') != 'claude-ollama': return 'Ongoing chat requires a Claude/Ollama task.'
    if receipt.get('checkout') and not receipt.get('snapshotHead'):
        return 'Ongoing chat currently requires a local folder project. Create a local task.'
    if receipt.get('localApplied') or task.get('status') == 'Completed': return 'Changes were already applied/completed. Create a new task or version.'
    if task.get('status') in {'Paused', 'Cancelled'}: return 'Task is paused or cancelled; its state is preserved.'
    if not receipt.get('sessionId'): return 'Save and start this task first to create its Claude session.'
    if receipt.get('status') not in SEND_STATUSES:
        return 'The saved Claude execution is still active or unresolved. Inspect its existing session first.'
    if state.get('activeTurn'): return 'A chat turn is queued or running. Wait for it to finish.'
    if task.get('status') not in SEND_STATUSES: return 'Task is running or not ready for a chat continuation.'
    # A failed/aborted inference is ambiguous. An explicit new turn must never hide a duplicate dispatch.
    if receipt.get('chatRecoveryRequired'): return 'Inspect the saved Claude session before continuing; the previous turn was interrupted.'
    return ''


def history(root, task_id):
    task, receipt, folder, store = context(root, task_id)
    state = store.read()
    events = list(state['events'])
    if not events and (folder/'claude-result.md').is_file():
        events = [dict(seq=1, role='assistant', text=(folder/'claude-result.md').read_text(encoding='utf-8')[:64000],
                       createdAt=receipt.get('updatedAt', ''), kind='existing-result')]
    blocked = reason(task, receipt, state)
    active = state.get('activeTurn')
    active_request = state['requests'].get(active) if active else None
    return dict(ok=True, taskId=task_id, status=task.get('status', ''), sessionId=receipt.get('sessionId', ''),
                canSend=not blocked, reason=blocked, events=events, pendingQuestion=state.get('pendingQuestion'),
                activeTurn=active, activeRequest=(dict(requestId=active, status=active_request['status'],
                    message=active_request['message'], submissionConfirmed=task.get('chatRequestId') == active) if active_request else None),
                requests=[dict(requestId=key, status=value['status']) for key,value in state['requests'].items()])


def queue_turn(root, task_id, request_id, request_file):
    shell = shutil.which('pwsh') or shutil.which('powershell.exe')
    if not shell: raise ValueError('PowerShell is required for Studio queue transactions')
    result = subprocess.run([shell, '-NoProfile', '-File', str(Path(__file__).with_name('Studio.TaskChat.Queue.ps1')),
                             '-Root', str(root), '-Id', task_id, '-RequestId', request_id,
                             '-Request', str(request_file)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
    if result.returncode: raise ValueError(result.stderr.strip()[-1600:] or 'Queue submission failed')
    return json.loads(result.stdout)


def send(root, task_id, message, request_id, submit=queue_turn):
    try: request_id = str(uuid.UUID(request_id))
    except (ValueError, TypeError, AttributeError): raise ValueError('request-id must be a UUID') from None
    if not isinstance(message, str) or not message.strip() or len(message)>MAX_MESSAGE:
        raise ValueError('Message must contain 1..24000 characters')
    task, receipt, folder, store = context(root, task_id)
    store.path.mkdir(parents=True, exist_ok=True)
    with task_lock(store.path):
        state = store.read()
        existing = state['requests'].get(request_id)
        digest = hashlib.sha256(message.encode('utf-8')).hexdigest()
        if existing:
            if existing['digest'] != digest: raise ValueError('Request id reused with different text')
            # A submission whose response was lost can be reconciled with the same id only.
            if existing['status'] in {'submitting','queued'} and task.get('chatRequestId') != request_id:
                submit(root, task_id, request_id, store.file)
                existing['status'] = 'queued'
                write_json(store.file, state)
            return dict(ok=True, taskId=task_id, requestId=request_id, duplicate=True, status=existing['status'])
        blocked = reason(task, receipt, state)
        if blocked: raise ValueError(blocked)
        state['sessionId'] = receipt['sessionId']
        if not state['events'] and (folder/'claude-result.md').is_file():
            store.event(state, 'assistant', (folder/'claude-result.md').read_text(encoding='utf-8'), 'existing-result')
        state['requests'][request_id] = dict(message=message, digest=digest, status='queued', createdAt=stamp())
        state['activeTurn'] = request_id
        store.event(state, 'user', message, requestId=request_id)
        write_json(store.file, state)  # Durable intent before the queue transaction.
        try:
            submit(root, task_id, request_id, store.file)
        except Exception:
            # Verify whether the queue commit happened before a response was lost.
            # Keep ambiguous intent durable; only remove an explicitly unqueued send.
            current = load_task(root, task_id)
            if current.get('chatRequestId') != request_id:
                del state['requests'][request_id]
                state['activeTurn'] = None
                state['events'].pop()
                write_json(store.file, state)
            raise
    return dict(ok=True, taskId=task_id, requestId=request_id, duplicate=False, status='Queued')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--task-id', required=True)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('history')
    sender = commands.add_parser('send')
    sender.add_argument('--message-file', required=True, type=Path)
    sender.add_argument('--request-id', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'history': result = history(args.root, args.task_id)
        else:
            if not args.message_file.is_absolute() or args.message_file.stat().st_size>MAX_MESSAGE*4:
                raise ValueError('Use an absolute UTF-8 message file, at most 96 KB')
            result = send(args.root, args.task_id, args.message_file.read_text(encoding='utf-8-sig'), args.request_id)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as error:
        print(json.dumps(dict(ok=False, taskId=args.task_id, error=str(error))))
        return 1


if __name__ == '__main__': sys.exit(main())
