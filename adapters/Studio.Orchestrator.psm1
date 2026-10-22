Import-Module (Join-Path $PSScriptRoot 'Studio.Queue.psm1')

function New-StudioTask {
    param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$Title,
          [Parameter(Mandatory)][string]$Description,
          [ValidateSet('auto','asset3d','ollama','copilot-local','copilot-github','pinokio')][string]$Backend='auto',
          [string]$Role='project_manager', [string[]]$Attachments=@(), [string]$ProjectPath='',
          [string[]]$Dependencies=@(), [ValidateSet('task','plan')][string]$Kind='task',
          [string]$ToolCapability='', [string]$ToolOperation='', $ToolParameters=@{}, [string]$ToolAppId='')
    $path = Join-Path $Root 'tasks/queue.gui.json'
    $snapshot = Get-StudioQueueSnapshot -Path $path
    $task = [pscustomobject]@{
        schemaVersion=1; id=('TASK-'+[guid]::NewGuid().ToString('N').Substring(0,20).ToUpper())
        title=$Title; description=$Description; backend=$Backend; role=$Role; agent=$Role
        attachments=@($Attachments); projectPath=$ProjectPath; dependencies=@($Dependencies)
        kind=$Kind; status='Queued'; priority=10; createdAt=[DateTime]::UtcNow.ToString('o')
        toolCapability=$ToolCapability;toolOperation=$ToolOperation;toolParameters=$ToolParameters;toolAppId=$ToolAppId
    }
    $null = New-Item -ItemType Directory -Force -Path (Split-Path $path)
    Write-StudioQueue -Path $path -Items @($snapshot.Tasks + $task) -ExpectedRevision $snapshot.Revision
    $task
}

function Get-StudioBackend {
    param($Task)
    if ($Task.backend -and $Task.backend -ne 'auto') { return [string]$Task.backend }
    if ($Task.toolCapability) { return 'pinokio' }
    if ($Task.kind -eq 'plan') { return 'ollama' }
    $text = "$($Task.title) $($Task.description)"
    if ($text -match '(?i)3d|mesh|sword|character|prop|sv.rd|model af|blender') { return 'asset3d' }
    if ($text -match '(?i)research|historisk|kilder|specifikation|planl.g') { return 'ollama' }
    'copilot-github'
}

function Get-StudioReadyTask {
    param([array]$Tasks, [switch]$ProcessAssets, [switch]$ApproveUnrealWrite,
          [switch]$ValidateUnreal, [switch]$CaptureUnrealPreview)
    $statuses = @{}
    foreach ($task in $Tasks) { $statuses[$task.id] = $task.status }
    $ready = foreach ($task in $Tasks) {
        $waiting = @(@($task.dependencies) | Where-Object { $_ -and $statuses[$_] -ne 'Completed' })
        if ($waiting.Count) { continue }
        if ($task.status -eq 'WaitingForRemote' -and $task.nextPollAt) {
            $due = [DateTimeOffset]::MinValue
            if ([DateTimeOffset]::TryParse([string]$task.nextPollAt, [ref]$due) -and $due -gt [DateTimeOffset]::UtcNow) { continue }
        }
        if ($task.status -in @('Queued','WaitingForRemote')) { $task; continue }
        if (-not $ProcessAssets) { continue }
        if ($task.status -eq 'QueuedForBlender' -or
            ($ApproveUnrealWrite -and ($task.status -eq 'ReadyForUnreal' -or
             (($ValidateUnreal -or $CaptureUnrealPreview) -and $task.status -eq 'ReadyForUnrealQA') -or
             ($CaptureUnrealPreview -and $task.status -eq 'AwaitingScreenshot')))) { $task }
    }
    $ready | Sort-Object @{Expression={if ($_.status -eq 'WaitingForRemote') {1} else {0}}}, priority, createdAt | Select-Object -First 1
}

function Approve-StudioResult {
    param([string]$Root, [Parameter(Mandatory)][string]$Id)
    $path = Join-Path $Root 'tasks/queue.gui.json'
    $snapshot = Get-StudioQueueSnapshot -Path $path
    $task = @($snapshot.Tasks | Where-Object id -eq $Id)[0]
    if (-not $task) { throw 'Task not found.' }
    if ($Id -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$') { throw 'Invalid task id.' }
    if ($task.backend -eq 'pinokio' -and $task.status -eq 'AwaitingVisualReview') {
        $taskFile=Join-Path $Root "data/pipeline-jobs/$Id/bridge-task.json"
        $original=Get-Content -LiteralPath $taskFile -Raw -Encoding UTF8|ConvertFrom-Json
        foreach($name in @('title','description','backend','role','attachments','projectPath','toolCapability','toolOperation','toolAppId','toolParameters')) {
            if ((ConvertTo-Json -InputObject $original.$name -Depth 40 -Compress) -ne (ConvertTo-Json -InputObject $task.$name -Depth 40 -Compress)) { throw 'Tool task inputs changed after execution; create a new task.' }
        }
    }
    if ($task.status -eq 'AwaitingCodeReview') {
        $taskFile=Join-Path $Root "data/pipeline-jobs/$Id/bridge-task.json"
        $response=& python (Join-Path $PSScriptRoot 'project_bridge.py') $taskFile --config (Join-Path $Root 'config/orchestrator.json') --verify-review
        if ($LASTEXITCODE -ne 0) { throw ($response -join "`n") }
        $verified=($response -join "`n")|ConvertFrom-Json
        if ($verified.validatedHead -ne $task.validatedHead) { throw 'Validated head changed.' }
        $original=Get-Content -LiteralPath $taskFile -Raw -Encoding UTF8|ConvertFrom-Json
        foreach($name in @('title','description','backend','role','attachments','projectPath')) {
            if ((ConvertTo-Json -InputObject $original.$name -Depth 40 -Compress) -ne (ConvertTo-Json -InputObject $task.$name -Depth 40 -Compress)) { throw 'Task changed since validation.' }
        }
    }
    if ($task.status -eq 'AwaitingPlanReview') {
        $jobsRoot='data/pipeline-jobs'
        $configPath=Join-Path $Root 'config/orchestrator.json'
        if(Test-Path -LiteralPath $configPath){$jobsRoot=[string]((Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json).jobs_root)}
        if(-not [IO.Path]::IsPathRooted($jobsRoot)){$jobsRoot=Join-Path $Root $jobsRoot}
        $planPath = Join-Path $jobsRoot "$Id/bridge/plan.json"
        $plan = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($plan.schemaVersion -ne 1 -or $plan.parentId -ne $Id -or @($plan.tasks).Count -lt 1 -or @($plan.tasks).Count -gt 12) { throw 'Invalid plan contract.' }
        foreach ($name in @('title','description','attachments','projectPath')) {
            if ((ConvertTo-Json -InputObject $task.$name -Depth 40 -Compress) -ne
                (ConvertTo-Json -InputObject $plan.source.$name -Depth 40 -Compress)) { throw 'Task inputs changed after planning.' }
        }
        $children = @(ConvertTo-StudioTasks -Value $plan.tasks)
        $ids = @($children | ForEach-Object id)
        foreach ($child in $children) {
            if ($child.parentId -ne $Id -or $child.status -ne 'Queued' -or $child.backend -notin @('ollama','asset3d','copilot-local','copilot-github','pinokio') -or
                @($child.dependencies | Where-Object { $_ -notin $ids }).Count) { throw 'Invalid child task.' }
        }
        $resolved = @()
        while ($resolved.Count -lt $ids.Count) {
            $next = @($children | Where-Object { $_.id -notin $resolved -and @($_.dependencies | Where-Object { $_ -notin $resolved }).Count -eq 0 } | ForEach-Object id)
            if (-not $next.Count) { throw 'Cyclic plan dependencies.' }
            $resolved += $next
        }
        $snapshot.Tasks = @($snapshot.Tasks + $children)
    } elseif ($task.status -notin @('AwaitingCodeReview','AwaitingVisualReview')) { throw 'Task is not ready for approval.' }
    $task.status = 'Completed'
    $task | Add-Member -NotePropertyName approvedAt -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
    Write-StudioQueue -Path $path -Items $snapshot.Tasks -ExpectedRevision $snapshot.Revision
}

function Import-StudioLegacyQueue {
    param([string]$Root, [Parameter(Mandatory)][string]$Source, [switch]$Apply)
    # Explicitly invoked only. Existing runtime queues are never migrated on startup.
    $raw = Get-Content -LiteralPath $Source -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($raw.PSObject.Properties.Name -contains 'tasks') { $raw = $raw.tasks }
    $incoming = @(ConvertTo-StudioTasks -Value $raw)
    $path = Join-Path $Root 'tasks/queue.gui.json'
    $snapshot = Get-StudioQueueSnapshot -Path $path
    $ids = @($snapshot.Tasks | ForEach-Object id)
    $new = @($incoming | Where-Object { $_.id -notin $ids })
    if ($Apply) {
        $null = New-Item -ItemType Directory -Force -Path (Split-Path $path)
        Write-StudioQueue -Path $path -Items @($snapshot.Tasks + $new) -ExpectedRevision $snapshot.Revision
    }
    [pscustomobject]@{ imported=$new.Count; skipped=($incoming.Count-$new.Count); applied=[bool]$Apply; tasks=$new }
}

Export-ModuleMember -Function New-StudioTask, Get-StudioBackend, Get-StudioReadyTask, Approve-StudioResult, Import-StudioLegacyQueue
