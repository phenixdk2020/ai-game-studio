import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import sys

ROOT=Path(__file__).resolve().parents[1]
HOST=shutil.which('pwsh') or shutil.which('powershell.exe')

@unittest.skipUnless(HOST,'PowerShell required')
class OrchestratorTests(unittest.TestCase):
    def ps(self,script):
        command="$ErrorActionPreference='Stop';Import-Module '"+str(ROOT/'adapters/Studio.Queue.psm1')+"' -Force;Import-Module '"+str(ROOT/'adapters/Studio.Orchestrator.psm1')+"' -Force;"+script
        result=subprocess.run([HOST,'-NoProfile','-Command',command],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result.stdout.strip()

    def test_dependencies_require_completed_and_polling_does_not_starve_new_tasks(self):
        output=self.ps("$tasks=@([pscustomobject]@{id='parent';status='AwaitingCodeReview'},[pscustomobject]@{id='child';status='Queued';priority=5;dependencies=@('parent')},[pscustomobject]@{id='remote';status='WaitingForRemote';priority=0},[pscustomobject]@{id='new';status='Queued';priority=10});(Get-StudioReadyTask -Tasks $tasks).id;$tasks[0].status='Completed';(Get-StudioReadyTask -Tasks $tasks).id")
        self.assertEqual(output.splitlines(),['new','child'])

    def test_cli_uses_canonical_queue_and_preserves_unicode(self):
        with TemporaryDirectory() as folder:
            result=subprocess.run([shutil.which('python') or 'python',str(ROOT/'tools/studio.py'),'--root',folder,'add','Historisk café','--backend','ollama','--role','historical_research'],capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            path=Path(folder)/'tasks/queue.gui.json';tasks=json.loads(path.read_text(encoding='utf-8-sig'))
            self.assertEqual(tasks[0]['title'],'Historisk café')
            self.assertFalse((Path(folder)/'data/queue.json').exists())

    def test_legacy_preview_then_explicit_import_is_idempotent(self):
        with TemporaryDirectory() as folder:
            source=Path(folder)/'legacy.json';source.write_text(json.dumps({'tasks':[{'id':'OLD-1','title':'Old task','description':'Research','status':'PENDING','priority':'high','dependsOn':[],'references':['ref.png']}]}))
            output=self.ps(f"$root='{folder}';$source='{source}';$preview=Import-StudioLegacyQueue -Root $root -Source $source;if(Test-Path (Join-Path $root 'tasks/queue.gui.json')){{throw 'Preview wrote queue'}};$first=Import-StudioLegacyQueue -Root $root -Source $source -Apply;$second=Import-StudioLegacyQueue -Root $root -Source $source -Apply;@($preview.imported,$first.imported,$second.imported)|ConvertTo-Json -Compress")
            self.assertEqual(json.loads(output),[1,1,0])
            row=json.loads((Path(folder)/'tasks/queue.gui.json').read_text())[0]
            self.assertEqual(row['status'],'Queued');self.assertEqual(row['priority'],5);self.assertEqual(row['attachments'],['ref.png'])

    def test_real_worker_queue_adapter_http_and_review_round_trip(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.server.payload=payload
                body=json.dumps({'choices':[{'message':{'content':'Research result with references to review.'}}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with TemporaryDirectory() as folder:
                root=Path(folder)
                for directory in ('adapters','config','agents'):shutil.copytree(ROOT/directory,root/directory,ignore=shutil.ignore_patterns('__pycache__'))
                studio=json.loads((root/'config/studio.json').read_text())
                studio['llm']['base_url']=f'http://127.0.0.1:{server.server_port}/v1'
                (root/'config/studio.json').write_text(json.dumps(studio))
                self.ps(f"New-StudioTask -Root '{root}' -Title 'Research' -Description 'Find references' -Backend ollama -Role historical_research|Out-Null")
                result=subprocess.run([HOST,'-NoProfile','-File',str(ROOT/'tools/project-manager-worker.ps1'),'-Root',str(root),'-Once','-EnableSpecialists','-Python',sys.executable],capture_output=True,text=True,errors='replace',timeout=45)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                task=json.loads((root/'tasks/queue.gui.json').read_text())[0]
                self.assertEqual(task['status'],'AwaitingVisualReview',task)
                self.assertTrue(Path(task['resultPath']).is_file())
                self.assertEqual(server.payload['model'],studio['llm']['models']['light'])
                self.ps(f"Approve-StudioResult -Root '{root}' -Id '{task['id']}'")
                self.assertEqual(json.loads((root/'tasks/queue.gui.json').read_text())[0]['status'],'Completed')
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

    def test_plan_approval_adds_children_once_and_validates_dependency_graph(self):
        with TemporaryDirectory() as folder:
            output=self.ps(f"$root='{folder}';$parent=New-StudioTask -Root $root -Title 'Plan' -Description 'Build' -Backend ollama -Kind plan;$path=Join-Path $root 'tasks/queue.gui.json';$snapshot=Get-StudioQueueSnapshot -Path $path;$task=$snapshot.Tasks[0];$task.status='AwaitingPlanReview';Write-StudioQueue -Path $path -Items $snapshot.Tasks -ExpectedRevision $snapshot.Revision;$directory=Join-Path $root ('data/pipeline-jobs/'+$parent.id+'/bridge');New-Item -ItemType Directory -Force $directory|Out-Null;$plan=@{{schemaVersion=1;parentId=$parent.id;source=@{{title='Plan';description='Build';attachments=@();projectPath=''}};tasks=@(@{{id='CHILD-1';parentId=$parent.id;title='Research';description='Find';backend='ollama';role='historical_research';status='Queued';dependencies=@()}},@{{id='CHILD-2';parentId=$parent.id;title='Code';description='Build';backend='copilot-github';role='gameplay';status='Queued';dependencies=@('CHILD-1')}})}};$plan|ConvertTo-Json -Depth 30|Set-Content -LiteralPath (Join-Path $directory 'plan.json') -Encoding UTF8;Approve-StudioResult -Root $root -Id $parent.id;$rows=(Get-StudioQueueSnapshot -Path $path).Tasks;if($rows.Count -ne 3 -or $rows[0].status -ne 'Completed'){{throw 'Plan not applied'}};try{{Approve-StudioResult -Root $root -Id $parent.id;throw 'Duplicate approval accepted'}}catch{{if($_.Exception.Message -eq 'Duplicate approval accepted'){{throw}}}};'ok'")
            self.assertEqual(output,'ok')

if __name__=='__main__':unittest.main()
