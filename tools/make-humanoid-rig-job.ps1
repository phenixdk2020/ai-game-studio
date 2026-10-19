param(
    [string]$JobPath = 'C:\ai-game-studio-workspace\jobs\humanoid_rig_v1.json',
    [string]$OutputName = 'SK_1864_Humanoid',
    [string]$StudioRoot = 'C:\ai-game-studio',
    [string]$Python = 'C:\Users\allan\miniconda3\python.exe',
    [switch]$ApproveWrite
)

if (-not $ApproveWrite) {
    Write-Error 'Approval required: pass -ApproveWrite to create the .blend asset.'
    exit 1
}
if ($OutputName -notmatch '^[A-Za-z0-9_.-]+$' -or $OutputName -in @('.', '..')) {
    Write-Error 'OutputName must be a simple filename without path separators.'
    exit 1
}

$jobDirectory = Split-Path -Parent $JobPath
New-Item -ItemType Directory -Force $jobDirectory | Out-Null
@{
    type = 'humanoid_rig_v1'
    output_name = $OutputName
    write_asset = $true
} | ConvertTo-Json -Depth 4 | Set-Content -Path $JobPath -Encoding UTF8

$adapter = Join-Path $StudioRoot 'adapters\blender_job.py'
& $Python $adapter $JobPath --approve-write
exit $LASTEXITCODE
