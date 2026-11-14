import base64
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('powershell.exe') or shutil.which('pwsh'),'PowerShell required')
class TaskEditTests(unittest.TestCase):
    def run_ps(self,script):
        setup="$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false);Import-Module '"+str(ROOT/'adapters/Studio.TaskEdits.psm1')+"' -Force;"
        encoded=base64.b64encode((setup+script).encode('utf-16le')).decode()
        result=subprocess.run([shutil.which('powershell.exe') or shutil.which('pwsh'),'-NoProfile','-EncodedCommand',encoded],capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace'))
        return json.loads(result.stdout.decode('utf-8-sig'))

    def test_dispatched_failed_task_gets_fresh_id_without_receipt_or_session(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);receipt=root/'data/pipeline-jobs/TASK-OLD/bridge/receipt.json'
            receipt.parent.mkdir(parents=True);receipt.write_text('{"status":"Failed","signature":"original"}')
            result=self.run_ps("$old=[pscustomobject]@{id='TASK-OLD';status='Failed';title='Old title';description='Design';projectId='game';attachments=@('reference.md');dependencies=@('TASK-PARENT');sessionId='old-session';bridgeReceipt='old-receipt';validatedHead='old-sha';resultPath='old-result';error='previous error'};$edit=New-StudioTaskEditTarget -Root '"+directory+"' -Task $old;$edit.Task.title='New title';@{old=$old;edit=$edit}|ConvertTo-Json -Depth 20 -Compress")
            old=result['old'];edit=result['edit'];new=edit['Task']
            self.assertTrue(edit['IsRevision']);self.assertNotEqual(new['id'],old['id'])
            self.assertEqual(new['revisionOf'],'TASK-OLD');self.assertEqual(new['status'],'Queued')
            self.assertEqual(new['projectId'],'game');self.assertEqual(new['dependencies'],['TASK-PARENT'])
            self.assertEqual(old['title'],'Old title');self.assertEqual(old['error'],'previous error')
            for key in ('sessionId','bridgeReceipt','validatedHead','resultPath','error'):
                self.assertNotIn(key,new)
            self.assertEqual(json.loads(receipt.read_text())['signature'],'original')
            self.assertEqual(list((root/'data/pipeline-jobs').iterdir()),[receipt.parents[1]])

    def test_undispatched_task_keeps_id(self):
        with TemporaryDirectory() as directory:
            result=self.run_ps("$edit=New-StudioTaskEditTarget -Root '"+directory+"' -Task ([pscustomobject]@{id='TASK-NEW';status='Queued'});$edit|ConvertTo-Json -Depth 5 -Compress")
            self.assertFalse(result['IsRevision']);self.assertEqual(result['Task']['id'],'TASK-NEW')

    def test_explicit_new_version_copies_inputs_without_receipt(self):
        with TemporaryDirectory() as directory:
            result=self.run_ps("$old=[pscustomobject]@{id='TASK-NEW';status='Failed';title='Game';backend='claude-ollama';projectId='one';description='Edited design';resultPath='old-file';error='old error'}; $edit=New-StudioTaskEditTarget -Root '"+directory+"' -Task $old -ForceRevision;@{edit=$edit;old=$old}|ConvertTo-Json -Depth 8 -Compress")
            edit=result['edit'];new=edit['Task']
            self.assertTrue(edit['IsRevision'])
            self.assertNotEqual(new['id'],result['old']['id'])
            self.assertEqual(new['revisionOf'],'TASK-NEW')
            self.assertEqual(new['status'],'Queued')
            self.assertEqual(new['description'],'Edited design')
            self.assertEqual(new['backend'],'claude-ollama')
            self.assertNotIn('resultPath',new)
            self.assertNotIn('error',new)
            self.assertEqual(result['old']['status'],'Failed')

    def test_explicit_version_still_rejects_active_task(self):
        with TemporaryDirectory() as directory:
            result=self.run_ps("try {New-StudioTaskEditTarget -Root '"+directory+"' -Task ([pscustomobject]@{id='TASK-LIVE';status='Running'}) -ForceRevision|Out-Null;@{blocked=$false}|ConvertTo-Json} catch {@{blocked=$true}|ConvertTo-Json}")
            self.assertTrue(result['blocked'])

    def test_active_task_is_rejected_before_edits(self):
        with TemporaryDirectory() as directory:
            result=self.run_ps("try {New-StudioTaskEditTarget -Root '"+directory+"' -Task ([pscustomobject]@{id='TASK-LIVE';status='Running'})|Out-Null;@{blocked=$false}|ConvertTo-Json} catch {@{blocked=$true}|ConvertTo-Json}")
            self.assertTrue(result['blocked'])

    def test_configured_absolute_job_root_and_paused_revision(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);jobs=root/'external-jobs';(root/'config').mkdir()
            (root/'config/orchestrator.json').write_text(json.dumps({'jobs_root':str(jobs)}))
            receipt=jobs/'TASK-OLD/bridge/receipt.json';receipt.parent.mkdir(parents=True);receipt.write_text('{}')
            result=self.run_ps("New-StudioTaskEditTarget -Root '"+directory+"' -Task ([pscustomobject]@{id='TASK-OLD';status='Paused';revisionNumber=4})|ConvertTo-Json -Depth 5 -Compress")
            self.assertTrue(result['IsRevision']);self.assertEqual(result['Task']['status'],'Paused')
            self.assertEqual(result['Task']['revisionNumber'],5)


if __name__=='__main__':unittest.main()
