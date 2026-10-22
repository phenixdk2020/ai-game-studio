function ConvertTo-StudioTasks {
    param($Value)
    if ($null -eq $Value) { return }
    if ($Value.PSObject.Properties.Name -contains 'value') { $Value = $Value.value }
    $seen = @{}
    foreach ($task in @($Value)) {
        if ($null -eq $task) { continue }
        if ($task -isnot [pscustomobject]) { throw 'Queue items must be task objects.' }
        if ($task.id -isnot [string] -or $task.id -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$' -or
            $task.id -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$') { throw 'Invalid task id.' }
        if ($seen.ContainsKey([string]$task.id)) { throw "Duplicate task id: $($task.id)" }
        $seen[[string]$task.id] = $true
        if ($task.PSObject.Properties.Name -contains 'schemaVersion') {
            if (($task.schemaVersion -isnot [int] -and $task.schemaVersion -isnot [long]) -or
                $task.schemaVersion -ne 1) { throw 'Unsupported queue schemaVersion.' }
        }
        $defaults = @{
            schemaVersion = 1; status = 'Queued'; title = ''; description = ''
            attachments = @(); dependencies = @(); priority = 10
            attempt = 0; maxAttempts = 3; progressPercent = 0; progressText = ''
            pipelineStage = ''; error = ''; resultPath = ''
            backend = 'auto'; role = ''; kind = 'task'; projectPath = ''
        }
        foreach ($mapping in @(@('references','attachments'), @('dependsOn','dependencies'), @('result_file','resultPath'), @('lastError','error'))) {
            if ($task.PSObject.Properties.Name -contains $mapping[0] -and $task.PSObject.Properties.Name -notcontains $mapping[1]) {
                $task | Add-Member -NotePropertyName $mapping[1] -NotePropertyValue $task.($mapping[0])
            }
        }
        if ($task.priority -is [string]) {
            $rank = @{ critical=0; high=5; normal=10; low=20 }
            if ($rank.ContainsKey($task.priority)) { $task.priority = $rank[$task.priority] }
        }
        foreach ($key in $defaults.Keys) {
            if ($task.PSObject.Properties.Name -notcontains $key) {
                $task | Add-Member -NotePropertyName $key -NotePropertyValue $defaults[$key]
            }
        }
        if ($null -eq $task.attachments) { $task.attachments = @() }
        if ($null -eq $task.dependencies) { $task.dependencies = @() }
        foreach ($field in @('attachments','dependencies')) {
            if ($task.$field -is [string] -or @($task.$field | Where-Object { $_ -isnot [string] }).Count) { throw "$field must be an array of strings." }
        }
        $statusMap = @{ PENDING='Queued'; READY='Queued'; DONE='Completed'; REVIEW='AwaitingCodeReview'; FAILED='Failed'; RUNNING='Running'; COMPLETED='Completed'; QUEUED='Queued'; CANCELLED='Cancelled' }
        if ($statusMap.ContainsKey([string]$task.status)) { $task.status = $statusMap[[string]$task.status] }
        $task
    }
}

function Read-StudioQueue {
    param([Parameter(Mandatory)][string]$Path)
    (Get-StudioQueueSnapshot -Path $Path).Tasks
}

function Get-StudioBytesRevision {
    param([AllowEmptyCollection()][byte[]]$Bytes)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($hasher.ComputeHash($Bytes)).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
}

function Get-StudioQueueSnapshot {
    param([Parameter(Mandatory)][string]$Path)
    if (-not [IO.File]::Exists($Path)) {
        return [pscustomobject]@{ Tasks = @(); Revision = 'missing' }
    }
    $bytes = [IO.File]::ReadAllBytes($Path)
    $raw = [Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF)
    $tasks = @()
    if (-not [string]::IsNullOrWhiteSpace($raw)) {
        $tasks = @(ConvertTo-StudioTasks -Value (ConvertFrom-Json -InputObject $raw))
    }
    [pscustomobject]@{ Tasks = $tasks; Revision = (Get-StudioBytesRevision -Bytes $bytes) }
}

function Write-StudioQueue {
    param([Parameter(Mandatory)][string]$Path, [AllowEmptyCollection()][array]$Items,
          [string]$ExpectedRevision, [switch]$PassThruRevision,
          [AllowEmptyCollection()][array]$BaseItems, [switch]$PassThruSnapshot)
    $transaction = Enter-StudioQueueTransactionLock -Path ($Path + '.transaction.lock')
    try {
    if ($PSBoundParameters.ContainsKey('BaseItems')) {
        $latest = Get-StudioQueueSnapshot -Path $Path
        if ($latest.Revision -eq 'missing' -and $ExpectedRevision -ne 'missing') { throw 'Queue conflict: queue file was deleted.' }
        $Items = @(Merge-StudioWorkerUpdate -Base $BaseItems -Proposed $Items -Current $latest.Tasks)
        $ExpectedRevision = $latest.Revision
    }
    $clean = @(ConvertTo-StudioTasks -Value $Items)
    $json = ConvertTo-Json -InputObject $clean -Depth 40
    $temporary = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    try {
        [IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding($false)))
        if ($PSBoundParameters.ContainsKey('ExpectedRevision')) {
            $currentRevision = if ([IO.File]::Exists($Path)) {
                Get-StudioBytesRevision -Bytes ([IO.File]::ReadAllBytes($Path))
            } else { 'missing' }
            if ($currentRevision -ne $ExpectedRevision) {
                throw 'Queue revision conflict: the queue changed after this worker read it. Reload before retrying; external edits were preserved.'
            }
        }
        $writtenRevision = Get-StudioBytesRevision -Bytes ([IO.File]::ReadAllBytes($temporary))
        if ([IO.File]::Exists($Path)) { [IO.File]::Replace($temporary, $Path, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $Path) }
        if ($PassThruSnapshot) { [pscustomobject]@{ Revision = $writtenRevision; Tasks = $clean } }
        elseif ($PassThruRevision) { $writtenRevision }
    } finally {
        if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
    }
    } finally { $transaction.Dispose() }
}

function Enter-StudioQueueTransactionLock {
    param([string]$Path, [int]$TimeoutMilliseconds = 3000)
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        try { return [IO.File]::Open($Path, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch [IO.IOException] {
            if ($watch.ElapsedMilliseconds -ge $TimeoutMilliseconds) { throw "Queue transaction busy: $Path" }
            Start-Sleep -Milliseconds 20
        }
    }
}

function Get-StudioPropertyJson {
    param($Task, [string]$Name)
    if ($Task.PSObject.Properties.Name -notcontains $Name) { return '<missing>' }
    ConvertTo-Json -InputObject $Task.$Name -Depth 40 -Compress
}

function Merge-StudioWorkerUpdate {
    param([AllowEmptyCollection()][array]$Base, [AllowEmptyCollection()][array]$Proposed,
          [AllowEmptyCollection()][array]$Current)
    $baseMap = @{}; $newMap = @{}; $currentMap = @{}
    foreach ($item in @(ConvertTo-StudioTasks $Base)) { $baseMap[$item.id] = $item }
    foreach ($item in @(ConvertTo-StudioTasks $Proposed)) { $newMap[$item.id] = $item }
    foreach ($item in @(ConvertTo-StudioTasks $Current)) { $currentMap[$item.id] = $item }
    foreach ($id in $baseMap.Keys) {
        $old = $baseMap[$id]; $next = $newMap[$id]; $latest = $currentMap[$id]
        if (-not $next) { throw 'Worker updates may not delete queue tasks.' }
        $changed = @($next.PSObject.Properties.Name | Where-Object {
            (Get-StudioPropertyJson $old $_) -ne (Get-StudioPropertyJson $next $_)
        })
        if (-not $changed.Count) { continue }
        if (-not $latest) { throw "Queue conflict: task $id was deleted." }
        if ($latest.status -in @('Cancelled', 'Paused') -and $latest.status -ne $old.status) {
            throw "Queue conflict: task $id was paused or cancelled. Worker update stopped."
        }
        foreach ($name in @('title','description','attachments','projectPath','agent','newProject','backend','role','kind','dependencies')) {
            if ((Get-StudioPropertyJson $latest $name) -ne (Get-StudioPropertyJson $old $name)) {
                throw "Queue conflict: task $id input changed ($name). Reload before continuing."
            }
        }
        foreach ($name in $changed) {
            $before = Get-StudioPropertyJson $old $name
            $after = Get-StudioPropertyJson $next $name
            $present = Get-StudioPropertyJson $latest $name
            if ($present -ne $before -and $present -ne $after) { throw "Queue conflict: task $id property $name changed concurrently." }
            $latest | Add-Member -NotePropertyName $name -NotePropertyValue $next.$name -Force
        }
    }
    foreach ($id in $newMap.Keys) {
        if (-not $baseMap.ContainsKey($id)) {
            if ($currentMap.ContainsKey($id)) { throw "Queue conflict: duplicate new task $id." }
            $currentMap[$id] = $newMap[$id]
        }
    }
    # Keep current GUI order; append any new worker items afterwards.
    foreach ($item in $Current) { if ($null -ne $item) { $currentMap[$item.id]; $currentMap.Remove($item.id) } }
    foreach ($item in $currentMap.Values) { $item }
}

function Enter-StudioWorkerLock {
    param([Parameter(Mandatory)][string]$Path, [string]$Version = '17.0')
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch { throw "Worker lock unavailable: $Path. Another worker may be active. $($_.Exception.Message)" }
    try {
        $record = @{ pid = $PID; version = $Version; startedAt = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json -Compress
        $bytes = [Text.Encoding]::UTF8.GetBytes($record)
        $stream.SetLength(0)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
        return $stream
    } catch { $stream.Dispose(); throw }
}

Export-ModuleMember -Function ConvertTo-StudioTasks, Read-StudioQueue, Get-StudioQueueSnapshot, Write-StudioQueue, Enter-StudioWorkerLock
