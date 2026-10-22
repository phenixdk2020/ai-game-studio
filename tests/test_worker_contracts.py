"""Exercise source functions only: never launch the worker or access runtime folders."""
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
class WorkerContracts(unittest.TestCase):
    def execute(self, source):
        with TemporaryDirectory() as folder:
            script = Path(folder) / "test.ps1"
            script.write_text("$ErrorActionPreference='Stop'\n" + source, encoding="utf-8-sig")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script)],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_queue_migration_utf8_array_and_lock(self):
        with TemporaryDirectory() as folder:
            source = r'''
Import-Module '__MODULE__' -Force
$path = Join-Path '__TEMP__' 'queue.json'
$legacy = '{"value":[null,{"id":"TASK-1","title":"Sværd og blåbær"}],"Count":2}'
[IO.File]::WriteAllText($path, $legacy, (New-Object Text.UTF8Encoding($true)))
$rows = @(Read-StudioQueue -Path $path)
if ($rows.Count -ne 1 -or $rows[0].schemaVersion -ne 1) { throw 'Migration failed' }
if ($rows[0].title -ne 'Sværd og blåbær') { throw 'UTF-8 corrupt' }
Write-StudioQueue -Path $path -Items $rows
$text = [IO.File]::ReadAllText($path)
if (-not $text.TrimStart().StartsWith('[')) { throw 'Not an array' }
if (@(Read-StudioQueue -Path $path).Count -ne 1) { throw 'Roundtrip failed' }
Write-StudioQueue -Path $path -Items @()
if ([IO.File]::ReadAllText($path).Trim() -ne '[]') { throw 'Empty array failed' }
$lockPath = Join-Path '__TEMP__' 'worker.lock'
$first = Enter-StudioWorkerLock -Path $lockPath
$blocked = $false
try { $second = Enter-StudioWorkerLock -Path $lockPath; $second.Dispose() } catch { $blocked = $true }
if (-not $blocked) { throw 'Duplicate worker accepted' }
$first.Dispose()
$recovered = Enter-StudioWorkerLock -Path $lockPath
$recovered.Dispose()
'''
            self.execute(source.replace("__MODULE__", str(ROOT / "adapters" / "Studio.Queue.psm1"))
                         .replace("__TEMP__", folder))

    def test_queue_rejects_duplicates_bad_ids_and_future_schema(self):
        source = r'''
Import-Module '__MODULE__' -Force
foreach ($json in @('[{"id":"../escape"}]', '[{"id":"X"},{"id":"X"}]', '[{"id":"X","schemaVersion":2}]', '[42]', '[{"id":123}]', '[{"id":"CON"}]', '[{"id":"X","schemaVersion":true}]', '[{"id":"X","schemaVersion":"1"}]')) {
    $blocked = $false
    try { $null = @(ConvertTo-StudioTasks -Value (ConvertFrom-Json -InputObject $json)) } catch { $blocked = $true }
    if (-not $blocked) { throw "Accepted bad input: $json" }
}
'''
        self.execute(source.replace("__MODULE__", str(ROOT / "adapters" / "Studio.Queue.psm1")))

    def test_stale_queue_revision_preserves_external_edits(self):
        with TemporaryDirectory() as folder:
            source = r'''
Import-Module '__MODULE__' -Force
$path = Join-Path '__TEMP__' 'queue.json'
$initial = Get-StudioQueueSnapshot -Path $path
if ($initial.Revision -ne 'missing') { throw 'Missing queue revision failed' }
$items = @([pscustomobject]@{ id='TASK-1'; title='Original' })
$written = Write-StudioQueue -Path $path -Items $items -ExpectedRevision $initial.Revision -PassThruRevision
$snapshot = Get-StudioQueueSnapshot -Path $path
if ($snapshot.Revision -ne $written) { throw 'Write/read revision mismatch' }
$external = '[{"id":"TASK-1","title":"GUI ændring"},{"id":"TASK-2"}]'
[IO.File]::WriteAllText($path, $external)
$blocked = $false
try { Write-StudioQueue -Path $path -Items $items -ExpectedRevision $snapshot.Revision } catch {
    if ($_.Exception.Message -notmatch 'revision conflict') { throw }
    $blocked = $true
}
if (-not $blocked -or [IO.File]::ReadAllText($path) -ne $external) { throw 'External queue edit was overwritten' }
if (@(Get-ChildItem '__TEMP__' -Filter '*.tmp').Count) { throw 'Temporary write files leaked' }
$latest = Get-StudioQueueSnapshot -Path $path
$latest.Tasks[0].title = 'Merged manually'
$null = Write-StudioQueue -Path $path -Items $latest.Tasks -ExpectedRevision $latest.Revision -PassThruRevision
if (@(Read-StudioQueue -Path $path).Count -ne 2) { throw 'GUI addition lost' }
[IO.File]::Delete($path)
$blocked = $false
try { Write-StudioQueue -Path $path -Items $latest.Tasks -ExpectedRevision $latest.Revision } catch { $blocked = $true }
if (-not $blocked -or (Test-Path $path)) { throw 'Deleted queue was recreated from stale data' }
'''
            self.execute(source.replace("__MODULE__", str(ROOT / "adapters" / "Studio.Queue.psm1"))
                         .replace("__TEMP__", folder))

    def test_worker_hunyuan_calls_managed_adapter_and_rejects_bad_output(self):
        with TemporaryDirectory() as folder:
            source = r'''
Import-Module '__MODULE__' -Force
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('__WORKER__',[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw 'Worker parser error'}
foreach($name in @('Invoke-HunyuanGeneration','Set-TaskProperty')){
 $definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
 Invoke-Expression $definition.Extent.Text
}
function Update-TaskProgress {param($Task,$Queue,$Progress,$Percent)}
function Invoke-TestTool {
 $script:calls++
 if($args -notcontains '--approve-launch' -or $args[0] -notlike '*hunyuan_pinokio.py'){throw 'Managed adapter not used'}
 $global:LASTEXITCODE=0
 @{status='QueuedForBlender';output=(Join-Path $jobRoot 'bad.glb');resultPath='receipt.json';ref='pinokio://localhost:42000/api/hunyuan'}|ConvertTo-Json -Compress
}
$Root='__ROOT__';$jobRoot='__TEMP__';$Python='Invoke-TestTool'
$image=Join-Path $jobRoot 'image.png';[IO.File]::WriteAllBytes($image,[byte[]](1,2,3))
[IO.File]::WriteAllText((Join-Path $jobRoot 'bad.glb'),'error response')
$task=[pscustomobject]@{id='TASK-1';attachments=@($image)};$script:calls=0;$blocked=$false
try{Invoke-HunyuanGeneration -Task $task -Queue @($task)}catch{$blocked=$true}
if(-not $blocked -or $script:calls -ne 1){throw 'Invalid output accepted or adapter not called'}
'''
            self.execute(source.replace('__MODULE__',str(ROOT/'adapters/Hunyuan.Response.psm1')).replace('__WORKER__',str(ROOT/'tools/project-manager-worker.ps1')).replace('__ROOT__',str(ROOT)).replace('__TEMP__',folder))

    def test_worker_merges_gui_additions_and_stops_on_control_or_input_edits(self):
        with TemporaryDirectory() as folder:
            source = r'''
Import-Module '__MODULE__' -Force
$path = Join-Path '__TEMP__' 'queue.json'
Write-StudioQueue -Path $path -Items @([pscustomobject]@{id='TASK-1'; status='Running'; title='Sword'})
$base = Get-StudioQueueSnapshot -Path $path
$local = @($base.Tasks | ConvertTo-Json -Depth 40 | ConvertFrom-Json)
$local[0].progressPercent = 10
$gui = Get-StudioQueueSnapshot -Path $path
$gui.Tasks[0].priority = 99
Write-StudioQueue -Path $path -Items @($gui.Tasks + [pscustomobject]@{id='TASK-2'; title='Added in GUI'}) -ExpectedRevision $gui.Revision
$merged = Write-StudioQueue -Path $path -Items $local -BaseItems $base.Tasks -ExpectedRevision $base.Revision -PassThruSnapshot
if ($merged.Tasks.Count -ne 2 -or $merged.Tasks[0].priority -ne 99 -or $merged.Tasks[0].progressPercent -ne 10) { throw 'Three-way merge lost changes' }
$nextBase = @($local | ConvertTo-Json -Depth 40 | ConvertFrom-Json)
$local[0].progressPercent = 20
$merged = Write-StudioQueue -Path $path -Items $local -BaseItems $nextBase -ExpectedRevision $merged.Revision -PassThruSnapshot
if ($merged.Tasks.Count -ne 2 -or $merged.Tasks[0].progressPercent -ne 20) { throw 'Second update lost GUI task' }
foreach ($change in @('Cancelled', 'Paused', 'Input')) {
    $base = Get-StudioQueueSnapshot -Path $path
    $local = @($base.Tasks | ConvertTo-Json -Depth 40 | ConvertFrom-Json)
    $local[0].progressPercent += 1
    $gui = Get-StudioQueueSnapshot -Path $path
    if ($change -eq 'Input') { $gui.Tasks[0].title = 'Changed input' } else { $gui.Tasks[0].status = $change }
    Write-StudioQueue -Path $path -Items $gui.Tasks -ExpectedRevision $gui.Revision
    $before = [IO.File]::ReadAllText($path)
    $blocked = $false
    try { Write-StudioQueue -Path $path -Items $local -BaseItems $base.Tasks -ExpectedRevision $base.Revision } catch { $blocked = $true }
    if (-not $blocked -or [IO.File]::ReadAllText($path) -ne $before) { throw "Control/input update was overwritten: $change" }
}
'''
            self.execute(source.replace("__MODULE__", str(ROOT / "adapters" / "Studio.Queue.psm1"))
                         .replace("__TEMP__", folder))

    def test_two_writers_share_transaction_lock(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            queue = directory / "queue.json"
            queue.write_text('[{"id":"TASK-1","title":"initial"}]')
            script = directory / "writer.ps1"
            script.write_text(r'''
param($Module, $QueuePath, $Barrier, $Name)
$ErrorActionPreference='Stop'
Import-Module $Module -Force
$snapshot = Get-StudioQueueSnapshot -Path $QueuePath
[IO.File]::WriteAllText(($Barrier + '.' + $Name), 'ready')
while (-not (Test-Path $Barrier)) { Start-Sleep -Milliseconds 20 }
$snapshot.Tasks[0].title = $Name
try { Write-StudioQueue -Path $QueuePath -Items $snapshot.Tasks -ExpectedRevision $snapshot.Revision; exit 0 }
catch { if ($_.Exception.Message -match 'revision conflict') { exit 3 }; throw }
''', encoding="utf-8-sig")
            children = [subprocess.Popen(["pwsh", "-NoProfile", "-File", str(script),
                str(ROOT / "adapters" / "Studio.Queue.psm1"), str(queue), str(directory / "go"), name],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for name in ("one", "two")]
            try:
                import time
                deadline = time.monotonic() + 15
                while not all((directory / ("go." + name)).exists() for name in ("one", "two")):
                    if time.monotonic() > deadline:
                        self.fail("Writer startup timed out")
                    time.sleep(0.02)
                (directory / "go").write_text("release")
                outputs = [child.communicate(timeout=15) for child in children]
                self.assertEqual(sorted(child.returncode for child in children), [0, 3], outputs)
                self.assertIn(json.loads(queue.read_text())[0]["title"], ("one", "two"))
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.communicate(timeout=5)

    def test_gui_uses_shared_revision_writer_and_valid_source(self):
        with TemporaryDirectory() as folder:
            source = r'''
Import-Module '__MODULE__' -Force
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile('__GUI__', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'GUI PowerShell parser error' }
foreach ($name in @('ReadQ','WriteQ','Assert-EditableTaskCurrent')) {
    $definition = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name}, $true)
    Invoke-Expression $definition.Extent.Text
}
$q = Join-Path '__TEMP__' 'queue.json'
Write-StudioQueue -Path $q -Items @([pscustomobject]@{id='TASK-1';title='Initial'})
$gui = @(ReadQ)
$worker = Get-StudioQueueSnapshot -Path $q
$worker.Tasks[0].progressPercent = 40
Write-StudioQueue -Path $q -Items $worker.Tasks -ExpectedRevision $worker.Revision
$gui[0].title = 'Unsaved edit'
$blocked = $false
try { WriteQ $gui } catch { $blocked = $true }
if (-not $blocked) { throw 'GUI stale save overwrote worker progress' }
$gui = @(ReadQ)
$gui[0].title = 'Fresh edit'
WriteQ $gui
$saved = @(Read-StudioQueue -Path $q)
if ($saved[0].title -ne 'Fresh edit' -or $saved[0].progressPercent -ne 40) { throw 'GUI roundtrip lost worker state' }
$displayed = @($saved | ConvertTo-Json -Depth 40 | ConvertFrom-Json)[0]
$saved[0].description = 'Changed while form was open'
$blocked = $false
try { Assert-EditableTaskCurrent $displayed $saved[0] } catch { $blocked = $true }
if (-not $blocked) { throw 'A stale edit form was allowed to overwrite changed input' }
'''
            self.execute(source.replace("__MODULE__", str(ROOT / "adapters" / "Studio.Queue.psm1"))
                         .replace("__GUI__", str(ROOT / "tools" / "project-manager-gui.ps1"))
                         .replace("__TEMP__", folder))

    def test_asset_worker_approval_bridge_and_result(self):
        with TemporaryDirectory() as folder:
            source = r'''
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile('__WORKER__', [ref]$tokens, [ref]$parseErrors)
foreach ($name in @('Invoke-AssetStages', 'Set-TaskProperty')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    Invoke-Expression $definition.Extent.Text
}
function Write-Queue { param($Items) }
function Fake-Python {
    if ($args -notcontains '--approve-blender' -or $args -notcontains '--resume') { throw 'Missing stage arguments' }
    if ($args -notcontains '--approve-unreal') { throw 'Unreal approval missing' }
    if ($script:SimulateFailure) {
        $global:LASTEXITCODE = 1
        return '{"schemaVersion":1,"status":"Failed","error":"Unreal collision QA failed"}'
    }
    $global:LASTEXITCODE = 0
    if ($CaptureUnrealPreview) {
        if ($args -notcontains 'unreal-qa' -or $args -notcontains '--capture') { throw 'Missing capture options' }
        return '{"status":"AwaitingVisualReview","stage":"visual-review","outputDirectory":"mock-output","qaStatus":"pass"}'
    }
    return '{"status":"ReadyForUnrealQA","stage":"unreal-qa","outputDirectory":"mock-output","qaStatus":"pass"}'
}
$Root = '__TEMP__'; $jobRoot = $Root; $Python = 'Fake-Python'; $AssetConfig = 'config.json'
$utf8 = New-Object Text.UTF8Encoding($false)
$task = [pscustomobject]@{ id='TASK-1'; hunyuanOutput='input.glb'; projectPath='project'; target_size_m=1.0 }
$ApproveBlenderWrite = $false; $ApproveUnrealWrite = $false
Invoke-AssetStages -Task $task -Queue @($task)
if ($task.status -ne 'WaitingForApproval') { throw 'Missing approval gate' }
if (Test-Path (Join-Path $Root 'TASK-1')) { throw 'Wrote before approval' }
$null = New-Item -ItemType Directory -Path (Join-Path $Root 'TASK-1')
$ApproveBlenderWrite = $true; $ApproveUnrealWrite = $true
Invoke-AssetStages -Task $task -Queue @($task)
if ($task.status -ne 'ReadyForUnrealQA' -or $task.progressPercent -ne 90) { throw 'Wrong task result' }
$job = Get-Content (Join-Path $Root 'TASK-1/asset-job.json') -Raw | ConvertFrom-Json
if ($job.target_size_m -ne 1.0) { throw 'Task scale was dropped' }
$ValidateUnreal = $true; $CaptureUnrealPreview = $true
Invoke-AssetStages -Task $task -Queue @($task)
if ($task.status -ne 'AwaitingVisualReview' -or $task.progressPercent -ne 98) { throw 'Wrong capture result' }
$script:SimulateFailure = $true
$failed = $false
try { Invoke-AssetStages -Task $task -Queue @($task) } catch {
    if ($_.Exception.Message -notmatch 'Unreal collision QA failed') { throw }
    $failed = $true
}
if (-not $failed -or -not $task.assetManifest) { throw 'Original pipeline error was not propagated' }
'''
            self.execute(source.replace("__WORKER__", str(ROOT / "tools" / "project-manager-worker.ps1"))
                         .replace("__TEMP__", folder))


if __name__ == "__main__":
    unittest.main()
