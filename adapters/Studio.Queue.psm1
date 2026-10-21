function ConvertTo-StudioTasks {
    param($Value)
    if ($null -eq $Value) { return }
    if ($Value.PSObject.Properties.Name -contains 'value') { $Value = $Value.value }
    $seen = @{}
    foreach ($task in @($Value)) {
        if ($null -eq $task) { continue }
        if ($task -isnot [pscustomobject]) { throw 'Queue items must be task objects.' }
        if ($task.id -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$') { throw 'Invalid task id.' }
        if ($seen.ContainsKey([string]$task.id)) { throw "Duplicate task id: $($task.id)" }
        $seen[[string]$task.id] = $true
        if ($task.PSObject.Properties.Name -contains 'schemaVersion') {
            if ($task.schemaVersion -ne 1) { throw 'Unsupported queue schemaVersion.' }
        }
        $defaults = @{
            schemaVersion = 1; status = 'Queued'; title = ''; description = ''
            attachments = @(); dependencies = @(); priority = 10
            attempt = 0; maxAttempts = 3; progressPercent = 0; progressText = ''
            pipelineStage = ''; error = ''; resultPath = ''
        }
        foreach ($key in $defaults.Keys) {
            if ($task.PSObject.Properties.Name -notcontains $key) {
                $task | Add-Member -NotePropertyName $key -NotePropertyValue $defaults[$key]
            }
        }
        if ($null -eq $task.attachments) { $task.attachments = @() }
        if ($null -eq $task.dependencies) { $task.dependencies = @() }
        $task
    }
}

function Read-StudioQueue {
    param([Parameter(Mandatory)][string]$Path)
    if (-not [IO.File]::Exists($Path)) { return }
    $raw = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8)
    if ([string]::IsNullOrWhiteSpace($raw)) { return }
    ConvertTo-StudioTasks -Value (ConvertFrom-Json -InputObject $raw)
}

function Write-StudioQueue {
    param([Parameter(Mandatory)][string]$Path, [AllowEmptyCollection()][array]$Items)
    $clean = @(ConvertTo-StudioTasks -Value $Items)
    $json = ConvertTo-Json -InputObject $clean -Depth 40
    $temporary = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    try {
        [IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding($false)))
        if ([IO.File]::Exists($Path)) { [IO.File]::Replace($temporary, $Path, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $Path) }
    } finally {
        if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
    }
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

Export-ModuleMember -Function ConvertTo-StudioTasks, Read-StudioQueue, Write-StudioQueue, Enter-StudioWorkerLock
