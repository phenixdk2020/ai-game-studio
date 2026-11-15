param([Parameter(Mandatory)][string]$Root,[Parameter(Mandatory)][string]$Id,
      [Parameter(Mandatory)][string]$RequestId,[Parameter(Mandatory)][string]$Request)
$ErrorActionPreference='Stop'
$OutputEncoding=New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding=$OutputEncoding
Import-Module (Join-Path $Root 'adapters/Studio.Queue.psm1')
if($Id -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$'){throw 'Invalid task id.'}
if($Id -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$'){throw 'Invalid task id.'}
$parsedGuid=[guid]::Empty
if(-not [guid]::TryParseExact($RequestId,'D',[ref]$parsedGuid)){throw 'Invalid request id.'}
$config=Get-Content -LiteralPath (Join-Path $Root 'config/orchestrator.json') -Raw -Encoding UTF8|ConvertFrom-Json
$jobs=[string]$config.jobs_root
if(-not $jobs){$jobs='data/pipeline-jobs'}
if(-not [IO.Path]::IsPathRooted($jobs)){$jobs=Join-Path $Root $jobs}
$jobs=[IO.Path]::GetFullPath($jobs)
$canonical=[IO.Path]::GetFullPath((Join-Path (Split-Path $jobs -Parent) "task-chats/$Id/state.json"))
if([IO.Path]::GetFullPath($Request) -ne $canonical){throw 'Chat request must use this task canonical state file.'}
$state=Get-Content -LiteralPath $Request -Raw -Encoding UTF8|ConvertFrom-Json
if($state.taskId -ne $Id -or $state.activeTurn -ne $RequestId){throw 'Chat request identity mismatch.'}
$turn=$state.requests.PSObject.Properties[$RequestId].Value
if(-not $turn -or $turn.status -notin @('queued','submitting') -or -not $turn.message -or $turn.message.Length -gt 24000){throw 'Invalid pending chat turn.'}
$sha=[Security.Cryptography.SHA256]::Create()
try{$digest=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$turn.message)))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
if($digest -ne $turn.digest){throw 'Chat turn digest mismatch.'}
$receipt=Get-Content -LiteralPath (Join-Path $jobs "$Id/bridge/receipt.json") -Raw -Encoding UTF8|ConvertFrom-Json
if($receipt.taskId -ne $Id -or $receipt.sessionId -ne $state.sessionId -or $receipt.localApplied -or
   $receipt.chatRecoveryRequired -or -not $receipt.snapshotHead -or $receipt.status -notin @('AwaitingCodeReview','NeedsInput','Failed')){throw 'Saved Claude session is not ready for continuation.'}
$path=Join-Path $Root 'tasks/queue.gui.json'
for($attempt=0;$attempt -lt 6;$attempt++){
    $snapshot=Get-StudioQueueSnapshot -Path $path
    $task=@($snapshot.Tasks|Where-Object id -eq $Id)
    if($task.Count -ne 1 -or $task[0].backend -ne 'claude-ollama'){throw 'Claude task not found.'}
    $task=$task[0]
    if($task.chatRequestId -eq $RequestId){[pscustomobject]@{ok=$true;duplicate=$true}|ConvertTo-Json -Compress;exit 0}
    if($task.status -notin @('AwaitingCodeReview','NeedsInput','Failed')){throw 'Task status changed; chat continuation was not queued.'}
    if($task.sessionId -ne $state.sessionId){throw 'Claude session identity changed.'}
    foreach($pair in @(@('bridgeAction','resume-chat'),@('chatRequestId',$RequestId),@('status','Queued'),@('error',''),@('question','Chat continuation queued.'),@('updatedAt',[DateTime]::UtcNow.ToString('o')))){
        $task|Add-Member -NotePropertyName $pair[0] -NotePropertyValue $pair[1] -Force
    }
    try{
        Write-StudioQueue -Path $path -Items @($snapshot.Tasks) -ExpectedRevision $snapshot.Revision
        [pscustomobject]@{ok=$true;duplicate=$false}|ConvertTo-Json -Compress;exit 0
    }catch{
        if($_.Exception.Message -notmatch 'revision conflict|transaction busy' -or $attempt -eq 5){throw}
        Start-Sleep -Milliseconds (30*($attempt+1))
    }
}
