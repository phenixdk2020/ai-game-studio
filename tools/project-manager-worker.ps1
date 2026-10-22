param(
    [string]$Root = 'C:\ai-game-studio',
    [switch]$Once,
    [switch]$EnableSpecialists,
    [int]$PollSeconds = 2,
    [string]$OrchestratorConfig = '',
    [switch]$ProcessAssets,
    [switch]$ApproveBlenderWrite,
    [switch]$ApproveUnrealWrite,
    [switch]$ValidateUnreal,
    [switch]$CaptureUnrealPreview,
    [string]$Python = 'python',
    [string]$AssetConfig = ''
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\adapters\Hunyuan.Response.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '..\adapters\Studio.Queue.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '..\adapters\Studio.Orchestrator.psm1') -Force
if (-not $OrchestratorConfig) { $OrchestratorConfig = Join-Path $Root 'config\orchestrator.json' }
if ($PollSeconds -lt 1) { throw 'PollSeconds must be positive.' }
if (-not $AssetConfig) { $AssetConfig = Join-Path $Root 'config\asset-pipeline.json' }
if (($ValidateUnreal -or $CaptureUnrealPreview) -and (-not $ProcessAssets -or -not $ApproveUnrealWrite)) {
    throw 'Unreal validation/capture requires -ProcessAssets and -ApproveUnrealWrite.'
}

$queuePath = Join-Path $Root 'tasks\queue.gui.json'
$logDirectory = Join-Path $Root 'logs'
$jobRoot = Join-Path $Root 'data\pipeline-jobs'
$utf8 = New-Object System.Text.UTF8Encoding($false)

New-Item -ItemType Directory -Force -Path `
    (Split-Path $queuePath), $logDirectory, $jobRoot | Out-Null

$workerLog = Join-Path $logDirectory 'project-manager-worker.log'

function Write-WorkerLog {
    param(
        [string]$Message,
        [string]$Level = 'INFO'
    )

    $line = '[{0}] [{1}] {2}' -f [DateTime]::Now.ToString('o'), $Level, $Message
    $line | Tee-Object -FilePath $workerLog -Append
}

function Set-TaskProperty {
    param(
        [Parameter(Mandatory)]$Task,
        [Parameter(Mandatory)][string]$Name,
        $Value
    )

    if ($Task.PSObject.Properties.Name -contains $Name) {
        $Task.$Name = $Value
    }
    else {
        $Task | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    }
}

function Read-Queue {
    $snapshot = Get-StudioQueueSnapshot -Path $queuePath
    $script:queueRevision = $snapshot.Revision
    $script:queueBaseJson = ConvertTo-Json -InputObject @($snapshot.Tasks) -Depth 40 -Compress
    $snapshot.Tasks
}

function Write-Queue {
    param([array]$Items)
    $base = @($script:queueBaseJson | ConvertFrom-Json)
    $written = Write-StudioQueue -Path $queuePath -Items $Items -ExpectedRevision $script:queueRevision -BaseItems $base -PassThruSnapshot
    $script:queueRevision = $written.Revision
    $script:queueBaseJson = ConvertTo-Json -InputObject @($Items) -Depth 40 -Compress
}

function Invoke-SpecialistTask {
    param($Task, [array]$Queue, [string]$Backend)
    Set-TaskProperty $Task 'backend' $Backend
    if (-not $EnableSpecialists) {
        Set-TaskProperty $Task 'status' 'WaitingForApproval'
        Set-TaskProperty $Task 'question' 'Enable agent/Pinokio/Copilot backends and retry to dispatch this task.'
        Write-Queue -Items $Queue
        return
    }
    $taskDirectory = Join-Path $jobRoot $Task.id
    if ($Task.id -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$') { throw 'Invalid task id.' }
    $dependencyResults = @(foreach ($dependencyId in $Task.dependencies) {
        $dependency = @($Queue | Where-Object id -eq $dependencyId)[0]
        $content = ''
        if ($dependency.resultPath -and (Test-Path -LiteralPath $dependency.resultPath -PathType Leaf)) {
            $content = Get-Content -LiteralPath $dependency.resultPath -Raw -Encoding UTF8
            if ($content.Length -gt 16000) { $content = $content.Substring(0,16000) }
        }
        [pscustomobject]@{id=$dependencyId;title=$dependency.title;prUrl=$dependency.prUrl;result=$content}
    })
    Set-TaskProperty $Task 'dependencyResults' $dependencyResults
    New-Item -ItemType Directory -Force -Path $taskDirectory | Out-Null
    $taskFile = Join-Path $taskDirectory 'bridge-task.json'
    Set-TaskProperty $Task 'toolProgressPath' (Join-Path $taskDirectory 'bridge/tool-progress.json')
    [IO.File]::WriteAllText($taskFile, ($Task | ConvertTo-Json -Depth 40), $utf8)
    if ($Task.status -eq 'Queued') {
        Set-TaskProperty $Task 'attempt' ([int]$Task.attempt + 1)
        Set-TaskProperty $Task 'status' 'Running'
        Set-TaskProperty $Task 'pipelineStage' 'specialist-dispatch'
        Write-Queue -Items $Queue
    }
    $arguments = @((Join-Path $Root 'adapters\project_bridge.py'), $taskFile, '--config', $OrchestratorConfig, '--approve-dispatch')
    if ($Task.bridgeAction -eq 'revalidate') { $arguments += '--revalidate' }
    if ($Task.bridgeAction -eq 'resume-tool') { $arguments += '--resume-tool' }
    $lines = @(& $Python @arguments)
    $response = ($lines -join "`n") | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw $response.error }
    Set-TaskProperty $Task 'bridgeAction' ''
    foreach ($name in @('status','backend','role','pipelineStage','resultPath','bridgeReceipt','prUrl','sessionId','validatedHead','error','question','nextPollAt')) {
        if ($response.PSObject.Properties.Name -contains $name) { Set-TaskProperty $Task $name $response.$name }
    }
    Set-TaskProperty $Task 'updatedAt' ([DateTime]::UtcNow.ToString('o'))
    [IO.File]::WriteAllText($taskFile, ($Task | ConvertTo-Json -Depth 40), $utf8)
    Write-Queue -Items $Queue
}

function Invoke-AssetStages {
    param($Task, [array]$Queue)
    Set-TaskProperty $Task 'error' ''
    if (-not $ApproveBlenderWrite) {
        Set-TaskProperty $Task 'status' 'WaitingForApproval'
        Set-TaskProperty $Task 'question' 'Blender asset writes require -ApproveBlenderWrite; requeue as QueuedForBlender after approval.'
        Write-Queue -Items $Queue
        return
    }
    if ($Task.id -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$') { throw 'Invalid task id.' }
    $taskDirectory = Join-Path $jobRoot $Task.id
    $job = @{
        schemaVersion = 1; taskId = $Task.id; asset_name = 'SM_Prop'
        input = $Task.hunyuanOutput; pivot = 'bottom'
        project = $Task.projectPath
    }
    foreach ($name in @('asset_name', 'target_size_m', 'rotation_x_degrees', 'pivot')) {
        if ($Task.PSObject.Properties.Name -contains $name) { $job[$name] = $Task.$name }
    }
    $jobPath = Join-Path $taskDirectory 'asset-job.json'
    [IO.File]::WriteAllText($jobPath, ($job | ConvertTo-Json -Depth 10), $utf8)
    Set-TaskProperty $Task 'status' 'Running'
    Set-TaskProperty $Task 'pipelineStage' 'blender-cleanup'
    Set-TaskProperty $Task 'workerVersion' '17.0'
    $manifestPath = Join-Path $taskDirectory 'asset-manifest.json'
    Set-TaskProperty $Task 'assetManifest' $manifestPath
    Write-Queue -Items $Queue
    $arguments = @((Join-Path $Root 'adapters\asset_pipeline.py'), $jobPath,
        '--config', $AssetConfig, '--approve-blender', '--resume')
    if ($ApproveUnrealWrite) {
        $target = if ($ValidateUnreal -or $CaptureUnrealPreview) { 'unreal-qa' } else { 'unreal' }
        $arguments += @('--target', $target, '--approve-unreal')
        if ($CaptureUnrealPreview) { $arguments += '--capture' }
    }
    $resultLines = @(& $Python @arguments)
    if ($LASTEXITCODE -ne 0) {
        $detail = ''
        try {
            $failure = ($resultLines -join "`n") | ConvertFrom-Json
            if ($failure.status -eq 'Failed' -and $failure.error) { $detail = ': ' + $failure.error }
        } catch { $detail = ' (no structured failure response was returned)' }
        throw ('Asset pipeline failed' + $detail + '. See asset-manifest.json and per-attempt logs.')
    }
    $result = ($resultLines -join "`n") | ConvertFrom-Json
    Set-TaskProperty $Task 'status' $result.status
    Set-TaskProperty $Task 'pipelineStage' $result.stage
    Set-TaskProperty $Task 'resultPath' $result.outputDirectory
    Set-TaskProperty $Task 'qaStatus' $result.qaStatus
    Set-TaskProperty $Task 'progressPercent' $(if ($result.status -eq 'AwaitingVisualReview') { 98 } elseif ($result.status -eq 'AwaitingScreenshot') { 95 } elseif ($result.status -eq 'ReadyForUnrealQA') { 90 } else { 80 })
    Set-TaskProperty $Task 'assetManifest' (Join-Path $taskDirectory 'asset-manifest.json')
    Set-TaskProperty $Task 'question' $(if ($result.status -eq 'AwaitingVisualReview') { 'Unreal QA, test map and preview recorded; operator visual review remains.' } elseif ($result.status -eq 'AwaitingScreenshot') { 'Unreal QA and test map recorded; screenshot and operator review remain.' } else { 'Asset stages finished; Unreal QA, test level and screenshot remain pending.' })
    Set-TaskProperty $Task 'updatedAt' ([DateTime]::Now.ToString('o'))
    Write-Queue -Items $Queue
}

function Update-TaskProgress {
    param(
        [Parameter(Mandatory)]$Task,
        [Parameter(Mandatory)][array]$Queue,
        [Parameter(Mandatory)][string]$Progress,
        [int]$Percent
    )

    Set-TaskProperty -Task $Task -Name 'progressText' -Value $Progress
    Set-TaskProperty -Task $Task -Name 'progressPercent' -Value $Percent
    Set-TaskProperty -Task $Task -Name 'question' -Value $Progress
    Set-TaskProperty -Task $Task -Name 'updatedAt' -Value ([DateTime]::Now.ToString('o'))
    Write-Queue -Items $Queue
    Write-WorkerLog -Message "$($Task.id): $Progress ($Percent%)"
}

function Invoke-HunyuanGeneration {
    param($Task, [array]$Queue)
    $image=@($Task.attachments|Where-Object {Test-Path -LiteralPath $_ -PathType Leaf}|Select-Object -First 1)
    if(-not $image.Count){throw 'No readable reference image is attached.'}
    Update-TaskProgress -Task $Task -Queue $Queue -Progress 'Starting Hunyuan through Pinokio and calling its documented API.' -Percent 15
    $evidence=Join-Path $jobRoot ($Task.id+'/hunyuan-output')
    $arguments=@((Join-Path $Root 'adapters/hunyuan_pinokio.py'),'--image',$image[0],'--evidence',$evidence,'--approve-launch')
    $lines=@(& $Python @arguments)
    $result=($lines -join "`n")|ConvertFrom-Json
    if($LASTEXITCODE -ne 0){throw $result.error}
    Test-HunyuanGlb -Path $result.output -ContentType 'model/gltf-binary'
    Set-TaskProperty $Task 'pinokioRef' $result.ref
    Set-TaskProperty $Task 'toolResultPath' $result.resultPath
    return $result.output
}

$workerLock = Enter-StudioWorkerLock -Path ($queuePath + '.worker.lock') -Version '18.0'
try {
    Write-WorkerLog -Message 'Studio orchestrator v18.0 started'
    while ($true) {
        $queue = @(Read-Queue)
        $task = Get-StudioReadyTask -Tasks $queue -ProcessAssets:$ProcessAssets -ApproveUnrealWrite:$ApproveUnrealWrite -ValidateUnreal:$ValidateUnreal -CaptureUnrealPreview:$CaptureUnrealPreview

        if (-not $task) {
            if ($Once) {
                break
            }
            Start-Sleep -Seconds $PollSeconds
            continue
        }

        try {
            Set-TaskProperty $task 'workerVersion' '18.0'
            $backend = Get-StudioBackend -Task $task -Root $Root
            if ($backend -ne 'asset3d') {
                Invoke-SpecialistTask -Task $task -Queue $queue -Backend $backend
                if ($Once) { break }
                Start-Sleep -Seconds $PollSeconds
                continue
            }
            if (-not $ProcessAssets) {
                Set-TaskProperty $task 'status' 'WaitingForApproval'
                Set-TaskProperty $task 'question' 'Enable 3D processing and retry this task.'
                Write-Queue -Items $queue
                if ($Once) { break }
                continue
            }
            if ($ProcessAssets -and ($task.status -in @('QueuedForBlender', 'ReadyForUnreal', 'ReadyForUnrealQA', 'AwaitingScreenshot') -or
                ($task.hunyuanOutput -and (Test-Path -LiteralPath $task.hunyuanOutput)))) {
                Invoke-AssetStages -Task $task -Queue $queue
                if ($Once) { break }
                continue
            }
            Set-TaskProperty -Task $task -Name 'agent' -Value 'pinokio-hunyuan3d-agent'
            Set-TaskProperty -Task $task -Name 'pipeline' -Value 'asset3d'
            Set-TaskProperty -Task $task -Name 'pipelineStage' `
                -Value 'pinokio-hunyuan3d-lowvram'
            Set-TaskProperty -Task $task -Name 'status' -Value 'Running'
            Set-TaskProperty -Task $task -Name 'error' -Value ''
            Write-Queue -Items $queue

            Update-TaskProgress -Task $task -Queue $queue `
                -Progress 'Discovering the Hunyuan tool through Pinokio.' -Percent 5

            $outputFile = Invoke-HunyuanGeneration -Task $task -Queue $queue

            Set-TaskProperty -Task $task -Name 'hunyuanOutput' -Value $outputFile
            Set-TaskProperty -Task $task -Name 'pipelineStage' -Value 'blender-cleanup'
            Set-TaskProperty -Task $task -Name 'status' -Value 'QueuedForBlender'
            Set-TaskProperty -Task $task -Name 'question' `
                -Value "Hunyuan generation complete: $outputFile"
            Set-TaskProperty -Task $task -Name 'updatedAt' `
                -Value ([DateTime]::Now.ToString('o'))
            Write-Queue -Items $queue
            Write-WorkerLog -Message "$($task.id): generated $outputFile"
            if ($ProcessAssets) { Invoke-AssetStages -Task $task -Queue $queue }
        }
        catch {
            Set-TaskProperty -Task $task -Name 'status' -Value 'Failed'
            Set-TaskProperty -Task $task -Name 'error' -Value $_.Exception.Message
            Set-TaskProperty -Task $task -Name 'question' `
                -Value 'Orchestrator task failed. Open the worker log and task receipt/manifest for details.'
            Set-TaskProperty -Task $task -Name 'updatedAt' `
                -Value ([DateTime]::Now.ToString('o'))
            Write-Queue -Items $queue
            Write-WorkerLog `
                -Message ($_.Exception.ToString() + "`n" + $_.ScriptStackTrace) `
                -Level 'ERROR'
        }

        if ($Once) {
            break
        }
    }
}
finally {
    $workerLock.Dispose()
    Write-WorkerLog -Message 'Studio orchestrator v18.0 stopped'
}
