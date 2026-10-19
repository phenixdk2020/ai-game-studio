$ErrorActionPreference='SilentlyContinue'
$checks=@(
 @{Name='Python';Exe='C:\Users\allan\miniconda3\python.exe'},
 @{Name='Git';Exe='C:\Program Files\Git\cmd\git.exe'},
 @{Name='Pinokio';Exe='C:\Users\allan\AppData\Local\Programs\Pinokio\Pinokio.exe'},
 @{Name='Blender';Exe='C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'},
 @{Name='Unreal';Exe='I:\Spil\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe'},
 @{Name='Node';Exe='C:\Program Files\nodejs\node.exe'},
 @{Name='.NET';Exe='C:\Program Files\dotnet\dotnet.exe'}
)
$checks|ForEach-Object{[PSCustomObject]@{Program=$_.Name;Status=$(if(Test-Path $_.Exe){'OK'}else{'MANGLER'});Path=$_.Exe}}|Format-Table -AutoSize
