param([string]$Root='C:\ai-game-studio',[int]$PollSeconds=2,[switch]$EnableSpecialists,
 [switch]$ProcessAssets,[switch]$ApproveBlenderWrite,[switch]$ApproveUnrealWrite,
 [switch]$ValidateUnreal,[switch]$CaptureUnrealPreview)
$worker=Join-Path $Root 'tools/project-manager-worker.ps1'
$arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$worker+'"'),'-Root',('"'+$Root+'"'),'-PollSeconds',$PollSeconds)
foreach($flag in @('EnableSpecialists','ProcessAssets','ApproveBlenderWrite','ApproveUnrealWrite','ValidateUnreal','CaptureUnrealPreview')){if(Get-Variable $flag -ValueOnly){$arguments+='-'+$flag}}
Start-Process powershell.exe -ArgumentList $arguments -WindowStyle Hidden -PassThru
