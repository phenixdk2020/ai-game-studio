import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'adapters'))
from studio_agent_tools import StudioTools, serve, execute_child, verify_tool_reviews


@unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell.exe'),'PowerShell required')
class AgentToolsTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        for directory in ['adapters','tasks','config','checkout','jobs/PARENT/bridge']:
            (self.root/directory).mkdir(parents=True)
        shutil.copy2(ROOT/'adapters/Studio.Queue.psm1',self.root/'adapters/Studio.Queue.psm1')
        self.parent=dict(id='PARENT',title='Code',description='Implement game',backend='claude-ollama',projectId='game',status='Running')
        self.queue_path=self.root/'tasks/queue.gui.json'
        self.queue_path.write_text(json.dumps([self.parent]))
        self.catalog={'tools':{'image_generation':{'roles':['integration'],'operations':{'generate_image':{'artifact_extensions':['.png']}}}}}
        (self.root/'config/pinokio-tools.json').write_text(json.dumps(self.catalog))
        self.folder=self.root/'jobs/PARENT/bridge'
        self.context=self.folder/'studio-tools-context.json'
        self.config=dict(jobs_root=str(self.root/'jobs'),claude_ollama=dict(model='test',base_url='http://127.0.0.1:11434',tool_capabilities=['image_generation']))
        self.context.write_text(json.dumps(dict(root=str(self.root),checkout=str(self.root/'checkout'),parent=self.parent,session='session-1',config=self.config)))
        (self.folder/'receipt.json').write_text(json.dumps(dict(taskId='PARENT',backend='claude-ollama',status='Running',sessionId='session-1')))
        self.service=StudioTools(self.context,spawn=False)

    def submit(self, key='icon', **values):
        return self.service.call('studio_submit_tool',dict(request_key=key,capability='image_generation',operation='generate_image',parameters={'prompt':'a cube'},**values))

    def test_queue_submission_is_idempotent_and_project_scoped(self):
        first=self.submit();second=self.submit()
        self.assertTrue(first['created']);self.assertFalse(second['created'])
        tasks=json.loads(self.queue_path.read_text())
        self.assertEqual(len(tasks),2)
        self.assertEqual(tasks[1]['projectId'],'game')
        self.assertEqual(tasks[1]['backend'],'pinokio')
        self.assertEqual(tasks[1]['requestedBy'],'PARENT')
        self.assertEqual(self.service.status(first['task_id'])['status'],'Running')
        with self.assertRaisesRegex(ValueError,'changed inputs'):
            self.submit(title='Changed request')

    def test_unknown_tool_and_external_input_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'not registered'):
            self.service.call('studio_submit_tool',dict(request_key='x',capability='shell',operation='run'))
        with self.assertRaises(ValueError):
            self.service.parameters({'image':{'local_file':'../outside.png'}})
        self.assertEqual(len(json.loads(self.queue_path.read_text())),1)

    def test_stale_session_and_cross_parent_status_are_rejected(self):
        first=self.submit()
        tasks=json.loads(self.queue_path.read_text());tasks[1]['requestedBy']='OTHER'
        self.queue_path.write_text(json.dumps(tasks))
        with self.assertRaisesRegex(ValueError,'does not belong'):
            self.service.status(first['task_id'])
        (self.folder/'receipt.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'no longer active'):
            self.service.call('studio_list_tools',{})

    def tool_result(self):
        job=self.submit();folder=self.root/'jobs'/job['task_id']/'bridge';folder.mkdir(parents=True)
        source=folder/'artifact-0.png';source.write_bytes(b'image-test-content')
        result=folder/'tool-result.json'
        result.write_text(json.dumps(dict(artifacts=[dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest())])))
        self.service.queue('update',job['task_id'],update=dict(status='AwaitingVisualReview',resultPath=str(result)))
        return job,source

    def test_artifact_copy_stays_in_checkout_and_requires_tool_approval(self):
        job,source=self.tool_result()
        result=self.service.call('studio_copy_artifact',dict(task_id=job['task_id'],artifact_index=0,destination='Content/cube.png'))
        self.assertTrue(result['review_required'])
        self.assertEqual((self.root/'checkout/Content/cube.png').read_bytes(),source.read_bytes())
        with self.assertRaisesRegex(ValueError,'Approve tool result'):
            verify_tool_reviews(SimpleNamespace(path=self.folder))
        tasks=json.loads(self.queue_path.read_text());tasks[1]['status']='Completed';self.queue_path.write_text(json.dumps(tasks))
        verify_tool_reviews(SimpleNamespace(path=self.folder))

    def test_artifact_hash_and_protected_destination_are_checked(self):
        job,source=self.tool_result()
        for destination in ['../outside.png','.git/test.png','tasks/test.png']:
            with self.assertRaises(ValueError):
                self.service.call('studio_copy_artifact',dict(task_id=job['task_id'],artifact_index=0,destination=destination))
        source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            self.service.copy_artifact(dict(task_id=job['task_id'],artifact_index=0,destination='cube.png'))

    def test_executor_uses_bridge_and_leaves_visual_review_pending(self):
        job=self.service.call('studio_submit_tool',dict(request_key='inspect',capability='image_generation',operation='inspect'))
        fake=SimpleNamespace(advance=lambda approved:dict(status='AwaitingVisualReview',pipelineStage='pinokio-review',resultPath='',bridgeReceipt='',error='',question='Review output'))
        with patch('project_bridge.Bridge',return_value=fake) as bridge:
            execute_child(self.service,job['task_id'])
        self.assertEqual(bridge.call_args.args[0]['backend'],'pinokio')
        self.assertEqual(self.service.status(job['task_id'])['status'],'AwaitingVisualReview')

    def test_gpu_executor_releases_ollama_and_our_comfy_cache(self):
        job=self.submit()
        def advance(approved):
            folder=self.root/'jobs'/job['task_id']/'bridge';folder.mkdir(parents=True,exist_ok=True)
            (folder/'pinokio-readiness.jsonl').write_text(json.dumps(dict(stage='API_READY',readyUrl='http://127.0.0.1:8188'))+'\n')
            return dict(status='AwaitingVisualReview',pipelineStage='pinokio-review',resultPath='',bridgeReceipt='',error='',question='Review')
        fake=SimpleNamespace(advance=advance)
        with patch('project_bridge.Bridge',return_value=fake),patch('studio_agent_tools.urllib.request.urlopen') as opened:
            execute_child(self.service,job['task_id'])
        self.assertEqual([call.args[0].full_url for call in opened.call_args_list],
                         ['http://127.0.0.1:11434/api/generate','http://127.0.0.1:8188/free'])
        self.assertEqual(self.service.status(job['task_id'])['status'],'AwaitingVisualReview')

    def test_executor_does_not_overwrite_operator_cancellation(self):
        job=self.service.call('studio_submit_tool',dict(request_key='inspect',capability='image_generation',operation='inspect'))
        def advance(approved):
            tasks=json.loads(self.queue_path.read_text());tasks[1]['status']='Cancelled';self.queue_path.write_text(json.dumps(tasks))
            return dict(status='AwaitingVisualReview')
        with patch('project_bridge.Bridge',return_value=SimpleNamespace(advance=advance)):
            with self.assertRaisesRegex(ValueError,'operator'):
                execute_child(self.service,job['task_id'])
        self.assertEqual(self.service.status(job['task_id'])['status'],'Cancelled')

    def test_parent_worker_merge_keeps_concurrent_tool_task(self):
        base=self.root/'worker-base.json';base.write_text(self.queue_path.read_text())
        job=self.submit()
        script=self.root/'merge.ps1'
        script.write_text("param($Root)\nImport-Module (Join-Path $Root 'adapters/Studio.Queue.psm1')\n"
            "$base=@(Get-Content (Join-Path $Root 'worker-base.json') -Raw|ConvertFrom-Json)\n"
            "$proposed=@($base|ConvertTo-Json -Depth 20|ConvertFrom-Json)\n"
            "$proposed[0].status='AwaitingCodeReview'\n"
            "Write-StudioQueue -Path (Join-Path $Root 'tasks/queue.gui.json') -Items $proposed -BaseItems $base -ExpectedRevision stale\n")
        result=subprocess.run([shutil.which('pwsh') or shutil.which('powershell.exe'),'-NoProfile','-File',str(script),str(self.root)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        tasks=json.loads(self.queue_path.read_text())
        self.assertEqual(len(tasks),2)
        self.assertEqual(next(t for t in tasks if t['id']==job['task_id'])['status'],'Running')

    def test_mcp_stdio_protocol_and_error_response(self):
        messages=[dict(jsonrpc='2.0',id=1,method='initialize',params={'protocolVersion':'2024-11-05'}),
                  dict(jsonrpc='2.0',method='notifications/initialized'),dict(jsonrpc='2.0',id=2,method='tools/list'),
                  dict(jsonrpc='2.0',id=3,method='tools/call',params={'name':'studio_list_tools','arguments':{}}),
                  dict(jsonrpc='2.0',id=4,method='tools/call',params={'name':'unknown','arguments':{}})]
        result=subprocess.run([sys.executable,str(ROOT/'adapters/studio_agent_tools.py'),'--context',str(self.context)],
                              input='\n'.join(json.dumps(row) for row in messages)+'\n',capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        responses=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses),4)
        self.assertEqual(len(responses[1]['result']['tools']),5)
        self.assertTrue(responses[-1]['result']['isError'])


if __name__=='__main__':unittest.main()
