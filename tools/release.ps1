param([Parameter(Mandatory=$true)][string]$Message,[string]$Repo='C:\ai-game-studio')
$ErrorActionPreference='Stop'
& git -C $Repo add --all
$bad=@(& git -C $Repo diff --cached --name-only | Where-Object {$_ -match '^(tasks|results|logs|state)/'})
if($bad.Count){& git -C $Repo reset|Out-Null;throw "Runtime state staged: $($bad -join ', ')"}
& git -C $Repo commit -m $Message
if($LASTEXITCODE -ne 0){throw 'git commit failed'}
$output=& git -C $Repo push 2>&1;$code=$LASTEXITCODE;$output|ForEach-Object{Write-Host $_};if($code -ne 0){throw 'git push failed'}
