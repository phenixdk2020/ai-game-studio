param([string]$Root='C:\ai-game-studio')
$ErrorActionPreference='Stop'
$gui=Join-Path $Root 'tools\project-manager-gui.ps1'
if(!(Test-Path $gui)){ throw "GUI not found: $gui" }
$hostExe=if(Get-Command pwsh.exe -ErrorAction SilentlyContinue){'pwsh.exe'}else{'powershell.exe'}
Start-Process $hostExe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-STA','-File',('"'+$gui+'"'),'-Root',('"'+$Root+'"'))
