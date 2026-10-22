param([string]$Root='C:\ai-game-studio',[switch]$Loop,[int]$PollSeconds=2,
 [switch]$EnableSpecialists,[switch]$ProcessAssets,[switch]$ApproveBlenderWrite,
 [switch]$ApproveUnrealWrite,[switch]$ValidateUnreal,[switch]$CaptureUnrealPreview)
& (Join-Path $Root 'tools/project-manager-worker.ps1') -Root $Root -Once:(!$Loop) -PollSeconds $PollSeconds -EnableSpecialists:$EnableSpecialists -ProcessAssets:$ProcessAssets -ApproveBlenderWrite:$ApproveBlenderWrite -ApproveUnrealWrite:$ApproveUnrealWrite -ValidateUnreal:$ValidateUnreal -CaptureUnrealPreview:$CaptureUnrealPreview
