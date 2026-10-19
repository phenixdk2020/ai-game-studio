param([string]$Repo='C:\ai-game-studio')
$ErrorActionPreference='Stop'
if(!(Test-Path (Join-Path $Repo '.git'))){throw 'Not a Git repository.'}
$dirty=@(& git -C $Repo status --porcelain --untracked-files=no)
if($dirty.Count){throw "Tracked local changes detected. Commit/stash first:`n$($dirty -join "`n")"}
& git -C $Repo pull --ff-only 2>&1 | ForEach-Object {Write-Host $_}
if($LASTEXITCODE -ne 0){throw 'git pull failed'}
& 'C:\Users\allan\miniconda3\python.exe' (Join-Path $Repo 'core\studio.py') setup
& 'C:\Users\allan\miniconda3\python.exe' (Join-Path $Repo 'core\studio.py') status
