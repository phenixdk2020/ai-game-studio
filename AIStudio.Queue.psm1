# Compatibility facade: no separate data/queue.json writer remains.
Import-Module (Join-Path $PSScriptRoot 'adapters/Studio.Queue.psm1')
Import-Module (Join-Path $PSScriptRoot 'adapters/Studio.Orchestrator.psm1')
function Get-AIStudioRoot {param([string]$Root) if($Root){[IO.Path]::GetFullPath($Root)}else{$PSScriptRoot}}
function Initialize-AIStudio {param([string]$Root) Get-AIStudioRoot $Root}
function Read-AIQueue {param([string]$Root) [pscustomobject]@{schemaVersion=1;tasks=@((Get-StudioQueueSnapshot -Path (Join-Path (Get-AIStudioRoot $Root) 'tasks/queue.gui.json')).Tasks)}}
function Get-AITasks {param([string]$Root,[string]$Status) $tasks=@((Read-AIQueue $Root).tasks);if($Status){$tasks|Where-Object status -eq $Status}else{$tasks}}
function New-AITask {
 param([string]$Root,[Parameter(Mandatory)][string]$Title,[Parameter(Mandatory)][string]$Description,[ValidateSet('low','normal','high','critical')][string]$Priority='normal',[string[]]$References=@(),[string]$ParentId,[string[]]$DependsOn=@(),[string]$RequestedAgent)
 $rootPath=Get-AIStudioRoot $Root
 $task=New-StudioTask -Root $rootPath -Title $Title -Description $Description -Attachments $References -Dependencies $DependsOn -Role $(if($RequestedAgent){$RequestedAgent}else{'project_manager'})
 Set-AITask -Root $rootPath -Id $task.id -Values @{priority=@{critical=0;high=5;normal=10;low=20}[$Priority];parentId=$ParentId}
}
function Set-AITask {
 param([string]$Root,[string]$Id,[hashtable]$Values)
 if($Values.status -in @('COMPLETED','Completed','done')){throw 'Use Complete-AITask to validate and approve a result.'}
 $path=Join-Path (Get-AIStudioRoot $Root) 'tasks/queue.gui.json';$snapshot=Get-StudioQueueSnapshot -Path $path
 $task=@($snapshot.Tasks|Where-Object id -eq $Id)[0];if(!$task){throw 'Task not found.'}
 foreach($key in $Values.Keys){$task|Add-Member -NotePropertyName $key -NotePropertyValue $Values[$key] -Force}
 Write-StudioQueue -Path $path -Items $snapshot.Tasks -ExpectedRevision $snapshot.Revision
 $task
}
function Get-NextAITask {param([string]$Root) Get-StudioReadyTask -Tasks @(Get-AITasks $Root)}
function Invoke-ProjectManagerOnce {param([string]$Root,[switch]$EnableSpecialists) & (Join-Path $PSScriptRoot 'tools/project-manager-worker.ps1') -Root (Get-AIStudioRoot $Root) -Once -EnableSpecialists:$EnableSpecialists}
function Complete-AITask {param([string]$Root,[string]$Id) Approve-StudioResult -Root (Get-AIStudioRoot $Root) -Id $Id}
function Requeue-AITask {param([string]$Root,[string]$Id,[string]$Reason='Rework requested') Set-AITask -Root $Root -Id $Id -Values @{status='Queued';question=$Reason}}
function Set-AIQueuePaused {param([string]$Root,[bool]$Paused) throw 'Use the project-manager GUI to pause selected tasks and stop the worker.'}
Export-ModuleMember -Function Get-AIStudioRoot,Initialize-AIStudio,Read-AIQueue,Get-AITasks,New-AITask,Set-AITask,Get-NextAITask,Invoke-ProjectManagerOnce,Complete-AITask,Requeue-AITask,Set-AIQueuePaused
