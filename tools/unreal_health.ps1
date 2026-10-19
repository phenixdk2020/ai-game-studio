$exe='I:\Spil\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe';if(Test-Path $exe){Write-Host "UNREAL_CMD_OK $exe";exit 0}else{Write-Error "UnrealEditor-Cmd.exe not found: $exe";exit 1}
