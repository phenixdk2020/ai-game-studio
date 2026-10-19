param([string]$Repo='C:\ai-game-studio')
$ErrorActionPreference='Stop'
if(!(Test-Path (Join-Path $Repo '.git'))){throw 'Not a Git repository.'}
$dirty=@(& git -C $Repo status --porcelain --untracked-files=no)
if($LASTEXITCODE -ne 0){throw 'git status failed'}
if($dirty.Count){throw "Tracked local changes detected. Commit/stash first:`n$($dirty -join "`n")"}
# Git pull only touches tracked program files; runtime dirs remain ignored/local.
& git -C $Repo pull --ff-only
if($LASTEXITCODE -ne 0){throw 'git pull --ff-only failed'}
& python (Join-Path $Repo 'core\studio.py') setup
if($LASTEXITCODE -ne 0){throw 'Post-update setup check failed'}
& python (Join-Path $Repo 'core\studio.py') status
