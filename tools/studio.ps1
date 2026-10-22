param([Parameter(Mandatory)][string]$RequestFile)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$request=Get-Content -LiteralPath $RequestFile -Raw -Encoding UTF8 | ConvertFrom-Json
$Root=[string]$request.root
Import-Module (Join-Path $PSScriptRoot '../adapters/Studio.Queue.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '../adapters/Studio.Orchestrator.psm1') -Force
switch ($request.action) {
    'status' { ConvertTo-Json -InputObject @((Get-StudioQueueSnapshot -Path (Join-Path $Root 'tasks/queue.gui.json')).Tasks) -Depth 40 }
    'setup' { Get-Content -LiteralPath (Join-Path $Root 'config/orchestrator.json') -Raw }
    'add' {
        New-StudioTask -Root $Root -Title $request.title -Description $request.description -Backend $request.backend -Role $request.role -Attachments @($request.attachments) -ProjectPath $request.projectPath -Dependencies @($request.dependencies) -Kind $request.kind -ToolCapability $request.toolCapability -ToolOperation $request.toolOperation -ToolParameters $request.toolParameters -ToolAppId $request.toolAppId | ConvertTo-Json -Depth 40
    }
    'approve' { Approve-StudioResult -Root $Root -Id $request.id }
    'import-legacy' { Import-StudioLegacyQueue -Root $Root -Source $request.source -Apply:([bool]$request.apply) | ConvertTo-Json -Depth 40 }
    'recover' {
        $path=Join-Path $Root 'tasks/queue.gui.json';$snapshot=Get-StudioQueueSnapshot -Path $path
        foreach($task in $snapshot.Tasks){if($task.status -eq 'Running'){$task.status='NeedsInput';$task|Add-Member -NotePropertyName question -NotePropertyValue 'Interrupted run: inspect receipt and remaining processes before retrying.' -Force}}
        Write-StudioQueue -Path $path -Items $snapshot.Tasks -ExpectedRevision $snapshot.Revision
    }
    'run' {
        & (Join-Path $PSScriptRoot 'project-manager-worker.ps1') -Root $Root -Once:(!$request.loop) -EnableSpecialists:([bool]$request.specialists) -ProcessAssets:([bool]$request.assets) -ApproveBlenderWrite:([bool]$request.blender) -ApproveUnrealWrite:([bool]$request.unreal) -ValidateUnreal:([bool]$request.validateUnreal) -CaptureUnrealPreview:([bool]$request.capture)
    }
    default { throw 'Unknown studio action.' }
}
