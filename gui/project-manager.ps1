param([string]$Root="C:\ai-game-studio")
& powershell.exe -STA -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "tools/project-manager-gui.ps1") -Root $Root
