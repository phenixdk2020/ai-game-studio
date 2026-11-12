param([Parameter(Mandatory)][string]$Root,[Parameter(Mandatory)][string]$Request)
$ErrorActionPreference='Stop'
$OutputEncoding=New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding=$OutputEncoding
Import-Module (Join-Path $Root 'adapters/Studio.Queue.psm1')
$inputData=Get-Content -LiteralPath $Request -Raw -Encoding UTF8|ConvertFrom-Json
$path=Join-Path $Root 'tasks/queue.gui.json'
for($attempt=0;$attempt -lt 6;$attempt++){
    $snapshot=Get-StudioQueueSnapshot -Path $path
    $parent=@($snapshot.Tasks|Where-Object id -eq $inputData.parent)
    if($parent.Count -ne 1 -or $parent[0].backend -ne 'claude-ollama'){throw 'Coding parent not found.'}
    $child=@($snapshot.Tasks|Where-Object id -eq $inputData.id)
    if($inputData.action -eq 'submit'){
        if($parent[0].status -ne 'Running'){throw 'Coding parent is not running.'}
        if($child.Count){
            if($child[0].requestedBy -ne $inputData.parent -or $child[0].toolRequestDigest -ne $inputData.task.toolRequestDigest){throw 'Request key reused with changed inputs.'}
            [pscustomobject]@{created=$false;task=$child[0]}|ConvertTo-Json -Depth 40 -Compress
            exit 0
        }
        if($inputData.task.backend -ne 'pinokio' -or $inputData.task.projectId -ne $parent[0].projectId -or $inputData.task.requestedBy -ne $inputData.parent){throw 'Invalid tool task scope.'}
        if(@($snapshot.Tasks|Where-Object requestedBy -eq $inputData.parent).Count -ge 12){throw 'At most 12 tool requests per coding task; create a follow-up task for more.'}
        $items=@($snapshot.Tasks)+@($inputData.task)
        $result=[pscustomobject]@{created=$true;task=$inputData.task}
    }else{
        if($child.Count -ne 1 -or $child[0].requestedBy -ne $inputData.parent){throw 'Tool task does not belong to this coding task.'}
        if($inputData.action -eq 'get'){
            [pscustomobject]@{task=$child[0]}|ConvertTo-Json -Depth 40 -Compress
            exit 0
        }
        if($inputData.action -ne 'update'){throw 'Unknown queue action.'}
        if($child[0].status -notin @('Running','Queued')){throw 'Tool task was changed by the operator; preserving current state.'}
        foreach($property in $inputData.update.PSObject.Properties){
            if($property.Name -notin @('status','error','question','pipelineStage','resultPath','bridgeReceipt','progressPercent')){throw 'Invalid executor update field.'}
            $child[0]|Add-Member -NotePropertyName $property.Name -NotePropertyValue $property.Value -Force
        }
        $items=@($snapshot.Tasks)
        $result=[pscustomobject]@{task=$child[0]}
    }
    try{
        Write-StudioQueue -Path $path -Items $items -ExpectedRevision $snapshot.Revision
        $result|ConvertTo-Json -Depth 40 -Compress
        exit 0
    }catch{
        if($_.Exception.Message -notmatch 'revision conflict|transaction busy' -or $attempt -eq 5){throw}
        Start-Sleep -Milliseconds (30*($attempt+1))
    }
}
