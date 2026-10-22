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

    def test_generate_request_and_rejected_response(self):
        with TemporaryDirectory() as folder:
            source = r'''
Import-Module '__MODULE__' -Force
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile('__WORKER__', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Worker parser error' }
$function = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-HunyuanGeneration' }, $true)
Invoke-Expression $function.Extent.Text
function Update-TaskProgress { param($Task, $Queue, $Progress, $Percent) }
function Invoke-WebRequest {
    param($Uri, $Method, $ContentType, $Body, $OutFile, [switch]$PassThru, [switch]$UseBasicParsing, $TimeoutSec)
    $script:calls++
    $request = $Body | ConvertFrom-Json
    if ($request.image -ne [Convert]::ToBase64String([byte[]](1,2,3))) { throw 'Not raw Base64' }
    [IO.File]::WriteAllText($OutFile, ('{"error":"bad request"}' * 100))
    return [pscustomobject]@{ Headers = @{ 'Content-Type' = 'application/json' } }
}
$jobRoot = '__TEMP__'
$utf8 = New-Object Text.UTF8Encoding($false)
$image = Join-Path $jobRoot 'image.png'
[IO.File]::WriteAllBytes($image, [byte[]](1,2,3))
$task = [pscustomobject]@{ id = 'TASK-1'; attachments = @($image) }
$script:calls = 0
$blocked = $false
try { Invoke-HunyuanGeneration -Task $task -Queue @($task) -Port 8081 } catch { $blocked = $true }
if (-not $blocked -or $script:calls -ne 1) { throw 'Expected a rejected generation response' }
$output = Join-Path $jobRoot 'TASK-1/hunyuan-output'
if (Test-Path (Join-Path $output 'hunyuan-model.glb')) { throw 'Error published as GLB' }
if (@(Get-ChildItem $output -Filter '*.rejected').Count -ne 1) { throw 'Rejected response missing' }
$metadataFile = Get-ChildItem $output -Filter '*.metadata.json'
$metadata = [IO.File]::ReadAllText($metadataFile.FullName) | ConvertFrom-Json
if ($metadata.status -ne 'failed' -or $metadata.taskId -ne 'TASK-1') { throw 'Missing error metadata' }
if ($metadata.parameters.PSObject.Properties.Name -contains 'image') { throw 'Base64 leaked into metadata' }
[IO.File]::WriteAllText((Join-Path $output 'hunyuan-model.glb'), 'existing')
try { Invoke-HunyuanGeneration -Task $task -Queue @($task) -Port 8081 } catch { }
if ($script:calls -ne 1) { throw 'Existing output was not protected' }
'''
            self.execute(source.replace("__MODULE__", str(ROOT / "adapters" / "Hunyuan.Response.psm1"))
                         .replace("__WORKER__", str(ROOT / "tools" / "project-manager-worker.ps1"))
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
