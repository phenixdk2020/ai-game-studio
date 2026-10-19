param([Parameter(Mandatory=$true)][string]$Repo,[Parameter(Mandatory=$true)][string]$TaskId,[Parameter(Mandatory=$true)][string]$Branch)
$ErrorActionPreference='Stop'
$root=Join-Path (Split-Path $Repo -Parent) 'ai-agent-worktrees'
New-Item -ItemType Directory -Force -Path $root | Out-Null
$target=Join-Path $root $TaskId
if(Test-Path $target){Write-Output $target;exit 0}
git -C $Repo worktree add -b $Branch $target
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
Write-Output $target
