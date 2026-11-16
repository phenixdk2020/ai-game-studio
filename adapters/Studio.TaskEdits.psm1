function New-StudioTaskEditTarget {
    param([Parameter(Mandatory)][string]$Root,[Parameter(Mandatory)]$Task,[switch]$ForceRevision)
    if([string]$Task.id -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$'){throw 'Invalid task ID.'}
    if([string]$Task.status -in @('Running','Dispatching','WaitingForRemote')){
        throw 'Opgaven kører stadig. Vent på afslutning, eller stop den, før du redigerer.'
    }
    $jobsRoot='data/pipeline-jobs'
    $config=Join-Path $Root 'config/orchestrator.json'
    if(Test-Path -LiteralPath $config -PathType Leaf){
        $value=Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json
        if($value.jobs_root){$jobsRoot=[string]$value.jobs_root}
    }
    if(-not [IO.Path]::IsPathRooted($jobsRoot)){$jobsRoot=Join-Path $Root $jobsRoot}
    $receipt=Join-Path $jobsRoot ([string]$Task.id+'/bridge/receipt.json')
    if(-not $ForceRevision -and -not(Test-Path -LiteralPath $receipt -PathType Leaf)){
        return [pscustomobject]@{Task=$Task;IsRevision=$false;PreviousId=''}
    }
    # Copy user inputs only. Execution paths, session IDs and results belong to
    # the old task and must never be inherited by a fresh dispatch.
    $new=[ordered]@{
        schemaVersion=1;id=('TASK-'+[guid]::NewGuid().ToString('N').Substring(0,20).ToUpper())
        status=$(if($Task.status -eq 'Paused'){'Paused'}else{'Queued'})
        createdAt=[DateTime]::UtcNow.ToString('o');revisionOf=[string]$Task.id
        revisionNumber=2;priority=10
    }
    foreach($name in @('title','description','agent','role','backend','kind','projectId',
        'projectPath','outputPath','newProject','attachments','dependencies','priority',
        'routingPreference','toolCapability','toolOperation','toolAppId','toolParameters')){
        if($Task.PSObject.Properties.Name -contains $name){$new[$name]=$Task.$name}
    }
    if($Task.revisionNumber){$new.revisionNumber=[int]$Task.revisionNumber+1}
    $copy=([pscustomobject]$new | ConvertTo-Json -Depth 40 -Compress | ConvertFrom-Json)
    return [pscustomobject]@{Task=$copy;IsRevision=$true;PreviousId=[string]$Task.id}
}
Export-ModuleMember -Function New-StudioTaskEditTarget
