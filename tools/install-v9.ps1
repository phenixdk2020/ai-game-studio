param([string]$Source = $PSScriptRoot + '\..', [string]$Target = 'C:\ai-game-studio')
$ErrorActionPreference='Stop'
$source=(Resolve-Path $Source).Path
if(!(Test-Path $Target)){New-Item -ItemType Directory -Path $Target -Force|Out-Null}
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $Target "state-backup-$stamp"
New-Item -ItemType Directory -Path $backup -Force|Out-Null
foreach($rel in @('tasks\queue.json','results')){
 $p=Join-Path $Target $rel
 if(Test-Path $p){Copy-Item $p (Join-Path $backup ($rel -replace '[\\/:]','_')) -Recurse -Force}
}
$exclude=@('tasks','results')
Get-ChildItem $source -Force | Where-Object {$exclude -notcontains $_.Name} | ForEach-Object {
 $dest=Join-Path $Target $_.Name
 if($_.PSIsContainer){Copy-Item $_.FullName $dest -Recurse -Force}else{Copy-Item $_.FullName $dest -Force}
}
Write-Host "V9 program files installed. State preserved." -ForegroundColor Green
Write-Host "Backup: $backup" -ForegroundColor DarkGray
