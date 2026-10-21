param(
    [string]$Root = 'C:\ai-game-studio',
    [switch]$Once
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\adapters\Hunyuan.Response.psm1') -Force

$queuePath = Join-Path $Root 'tasks\queue.gui.json'
$logDirectory = Join-Path $Root 'logs'
$jobRoot = Join-Path $Root 'data\pipeline-jobs'
$utf8 = New-Object System.Text.UTF8Encoding($false)

New-Item -ItemType Directory -Force -Path `
    (Split-Path $queuePath), $logDirectory, $jobRoot | Out-Null

$workerLog = Join-Path $logDirectory 'project-manager-worker.log'

function Write-WorkerLog {
    param(
        [string]$Message,
        [string]$Level = 'INFO'
    )

    $line = '[{0}] [{1}] {2}' -f [DateTime]::Now.ToString('o'), $Level, $Message
    $line | Tee-Object -FilePath $workerLog -Append
}

function Set-TaskProperty {
    param(
        [Parameter(Mandatory)]$Task,
        [Parameter(Mandatory)][string]$Name,
        $Value
    )

    if ($Task.PSObject.Properties.Name -contains $Name) {
        $Task.$Name = $Value
    }
    else {
        $Task | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    }
}

function Read-Queue {
    $raw = [System.IO.File]::ReadAllText($queuePath, $utf8)
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return @()
    }

    $parsed = $raw | ConvertFrom-Json
    if ($null -ne $parsed.value) {
        return @($parsed.value | Where-Object { $null -ne $_ })
    }

    return @($parsed | Where-Object { $null -ne $_ })
}

function Write-Queue {
    param([array]$Items)

    $cleanItems = @($Items | Where-Object { $null -ne $_ })
    $temporaryPath = "$queuePath.tmp"

    if ($cleanItems.Count -eq 0) {
        $json = '[]'
    }
    else {
        $jsonItems = @(
            $cleanItems | ForEach-Object {
                $_ | ConvertTo-Json -Depth 30 -Compress
            }
        )
        $json = '[' + ($jsonItems -join ',') + ']'
    }

    [System.IO.File]::WriteAllText($temporaryPath, $json, $utf8)
    Move-Item -Path $temporaryPath -Destination $queuePath -Force
}

function Test-Is3DTask {
    param($Task)
    $text = "{0} {1}" -f $Task.title, $Task.description
    return $text -match '(?i)3d|model|mesh|sword|weapon|character|prop|sv.rd|v.ben'
}

function Find-HunyuanApplication {
    $candidates = @(
        'D:\Pinokio\api\Hunyuan3d-2-lowvram.git',
        'D:\Pinokio\api\Hunyuan3D-2-lowvram.git',
        'C:\pinokio\api\Hunyuan3d-2-lowvram.git',
        'C:\pinokio\api\Hunyuan3D-2-lowvram.git',
        (Join-Path $env:USERPROFILE 'pinokio\api\Hunyuan3d-2-lowvram.git')
    )

    foreach ($candidate in $candidates) {
        if (Test-Path (Join-Path $candidate 'app\api_server.py')) {
            return $candidate
        }
    }

    foreach ($searchRoot in @('D:\Pinokio\api', 'C:\pinokio')) {
      if (Test-Path $searchRoot) {
        $apiFile = Get-ChildItem -Path $searchRoot -Filter 'api_server.py' `
            -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object {
                $_.FullName -match 'Hunyuan3D-2GP|Hunyuan3d-2-lowvram'
            } |
            Select-Object -First 1

        if ($apiFile) {
            return Split-Path (Split-Path $apiFile.FullName -Parent) -Parent
        }
      }
    }

    throw 'Hunyuan3D-2-LowVRAM app\api_server.py was not found below D:\Pinokio\api or C:\pinokio.'
}

function Find-PinokioPython {
    param([Parameter(Mandatory)][string]$ApplicationPath)

    $candidates = @(
        (Join-Path $ApplicationPath 'app\env\Scripts\python.exe'),
        (Join-Path $ApplicationPath 'env\Scripts\python.exe')
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "Pinokio Python environment not found below $ApplicationPath"
}

function Test-HunyuanApi {
    param([int]$Port)

    foreach ($path in @('/openapi.json', '/docs')) {
        try {
            $response = Invoke-WebRequest `
                -Uri "http://127.0.0.1:$Port$path" `
                -UseBasicParsing `
                -TimeoutSec 3

            if ($response.StatusCode -eq 200) {
                return $true
            }
        }
        catch {
        }
    }

    return $false
}

function Update-TaskProgress {
    param(
        [Parameter(Mandatory)]$Task,
        [Parameter(Mandatory)][array]$Queue,
        [Parameter(Mandatory)][string]$Progress,
        [int]$Percent
    )

    Set-TaskProperty -Task $Task -Name 'progressText' -Value $Progress
    Set-TaskProperty -Task $Task -Name 'progressPercent' -Value $Percent
    Set-TaskProperty -Task $Task -Name 'question' -Value $Progress
    Set-TaskProperty -Task $Task -Name 'updatedAt' -Value ([DateTime]::Now.ToString('o'))
    Write-Queue -Items $Queue
    Write-WorkerLog -Message "$($Task.id): $Progress ($Percent%)"
}

function Start-HunyuanApi {
    param(
        [Parameter(Mandatory)][string]$ApplicationPath,
        [Parameter(Mandatory)][string]$PythonPath,
        [Parameter(Mandatory)][int]$Port,
        [Parameter(Mandatory)]$Task,
        [Parameter(Mandatory)][array]$Queue
    )

    if (Test-HunyuanApi -Port $Port) {
        Update-TaskProgress -Task $Task -Queue $Queue `
            -Progress 'Hunyuan API is already ready.' -Percent 35
        return
    }

    $applicationDirectory = Join-Path $ApplicationPath 'app'
    $stdoutLog = Join-Path $logDirectory 'hunyuan-api.out.log'
    $stderrLog = Join-Path $logDirectory 'hunyuan-api.err.log'
    $arguments = @(
        'api_server.py',
        '--host', '127.0.0.1',
        '--port', "$Port",
        '--model_path', 'tencent/Hunyuan3D-2mini',
        '--device', 'cuda'
    )

    Update-TaskProgress -Task $Task -Queue $Queue `
        -Progress 'Starting local Hunyuan API.' -Percent 15

    Start-Process -FilePath $PythonPath `
        -WorkingDirectory $applicationDirectory `
        -ArgumentList $arguments `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -WindowStyle Hidden | Out-Null

    for ($poll = 1; $poll -le 180; $poll++) {
        if (Test-HunyuanApi -Port $Port) {
            Update-TaskProgress -Task $Task -Queue $Queue `
                -Progress 'Hunyuan API is ready.' -Percent 35
            return
        }

        if (($poll % 5) -eq 0) {
            $percent = [Math]::Min(34, 15 + [int]($poll / 10))
            Update-TaskProgress -Task $Task -Queue $Queue `
                -Progress "Waiting for Hunyuan API. Poll $poll of 180." `
                -Percent $percent
        }

        Start-Sleep -Seconds 2
    }

    throw "Hunyuan API did not become ready. Read $stderrLog"
}

function Invoke-HunyuanGeneration {
    param(
        [Parameter(Mandatory)]$Task,
        [Parameter(Mandatory)][array]$Queue,
        [Parameter(Mandatory)][int]$Port
    )

    $inputImage = @(
        $Task.attachments |
            Where-Object { Test-Path -LiteralPath $_ } |
            Select-Object -First 1
    )

    if (-not $inputImage) {
        throw 'No readable reference image is attached.'
    }

    $taskDirectory = Join-Path $jobRoot $Task.id
    $outputDirectory = Join-Path $taskDirectory 'hunyuan-output'
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

    $imageBytes = [System.IO.File]::ReadAllBytes($inputImage[0])
    $base64 = [Convert]::ToBase64String($imageBytes)

    $request = @{
        image = $base64
        remove_background = $true
        texture = $false
        seed = 1234
        octree_resolution = 256
        num_inference_steps = 5
        guidance_scale = 5.0
        face_count = 40000
        type = 'glb'
    }

    $requestBody = $request | ConvertTo-Json -Compress
    $outputFile = Join-Path $outputDirectory 'hunyuan-model.glb'

    Update-TaskProgress -Task $Task -Queue $Queue `
        -Progress 'Generating 3D model from the first reference image.' `
        -Percent 45

    if (Test-Path -LiteralPath $outputFile) {
        throw 'Output already exists; preserve it before retrying generation.'
    }
    $temporaryFile = Join-Path $outputDirectory ('response-' + [guid]::NewGuid().ToString('N') + '.tmp')
    $metadata = @{
        taskId = $Task.id
        endpoint = "http://127.0.0.1:$Port/generate"
        startedAt = [DateTime]::UtcNow.ToString('o')
        imageSha256 = (Get-FileHash -LiteralPath $inputImage[0] -Algorithm SHA256).Hash
        parameters = @{}
    }
    foreach ($key in $request.Keys) {
        if ($key -ne 'image') { $metadata.parameters[$key] = $request[$key] }
    }
    try {
        $response = Invoke-WebRequest `
            -Uri $metadata.endpoint -Method Post -ContentType 'application/json' `
            -Body $requestBody -OutFile $temporaryFile -PassThru `
            -UseBasicParsing -TimeoutSec 7200
        $metadata.contentType = [string]$response.Headers['Content-Type']
        Test-HunyuanGlb -Path $temporaryFile -ContentType $metadata.contentType
        [IO.File]::Move($temporaryFile, $outputFile)
        $metadata.outputSha256 = (Get-FileHash -LiteralPath $outputFile -Algorithm SHA256).Hash
        $metadata.status = 'validated'
    } catch {
        $metadata.status = 'failed'
        $metadata.error = $_.Exception.Message
        if (Test-Path -LiteralPath $temporaryFile) {
            Move-Item -LiteralPath $temporaryFile -Destination ($temporaryFile + '.rejected')
        }
        if ($_.ErrorDetails.Message) { $metadata.errorBody = $_.ErrorDetails.Message }
        throw
    } finally {
        $metadata.finishedAt = [DateTime]::UtcNow.ToString('o')
        $metadataPath = $temporaryFile + '.metadata.json'
        [IO.File]::WriteAllText($metadataPath, ($metadata | ConvertTo-Json -Depth 8), $utf8)
    }

    Update-TaskProgress -Task $Task -Queue $Queue `
        -Progress 'Hunyuan model generation completed.' -Percent 100

    return $outputFile
}

Write-WorkerLog -Message 'Pipeline worker v16.2 HUNYUAN AUTO POLLING started'

try {
    while ($true) {
        $queue = @(Read-Queue)
        $task = $queue |
            Where-Object { $_.status -eq 'Queued' } |
            Sort-Object priority, createdAt |
            Select-Object -First 1

        if (-not $task) {
            if ($Once) {
                break
            }
            Start-Sleep -Seconds 2
            continue
        }

        if (-not (Test-Is3DTask -Task $task)) {
            Set-TaskProperty -Task $task -Name 'status' -Value 'NeedsInput'
            Set-TaskProperty -Task $task -Name 'question' `
                -Value 'Worker v16.1 currently handles 3D asset jobs only.'
            Write-Queue -Items $queue
            if ($Once) { break }
            continue
        }

        try {
            Set-TaskProperty -Task $task -Name 'agent' -Value 'pinokio-hunyuan3d-agent'
            Set-TaskProperty -Task $task -Name 'pipeline' -Value 'asset3d'
            Set-TaskProperty -Task $task -Name 'pipelineStage' `
                -Value 'pinokio-hunyuan3d-lowvram'
            Set-TaskProperty -Task $task -Name 'status' -Value 'Running'
            Set-TaskProperty -Task $task -Name 'error' -Value ''
            Write-Queue -Items $queue

            Update-TaskProgress -Task $task -Queue $queue `
                -Progress 'Locating the Pinokio Hunyuan installation.' -Percent 5

            $applicationPath = Find-HunyuanApplication
            $pythonPath = Find-PinokioPython -ApplicationPath $applicationPath
            $port = 8081

            Start-HunyuanApi `
                -ApplicationPath $applicationPath `
                -PythonPath $pythonPath `
                -Port $port `
                -Task $task `
                -Queue $queue

            $outputFile = Invoke-HunyuanGeneration `
                -Task $task `
                -Queue $queue `
                -Port $port

            Set-TaskProperty -Task $task -Name 'hunyuanOutput' -Value $outputFile
            Set-TaskProperty -Task $task -Name 'pipelineStage' -Value 'blender-cleanup'
            Set-TaskProperty -Task $task -Name 'status' -Value 'QueuedForBlender'
            Set-TaskProperty -Task $task -Name 'question' `
                -Value "Hunyuan generation complete: $outputFile"
            Set-TaskProperty -Task $task -Name 'updatedAt' `
                -Value ([DateTime]::Now.ToString('o'))
            Write-Queue -Items $queue
            Write-WorkerLog -Message "$($task.id): generated $outputFile"
        }
        catch {
            Set-TaskProperty -Task $task -Name 'status' -Value 'Failed'
            Set-TaskProperty -Task $task -Name 'error' -Value $_.Exception.Message
            Set-TaskProperty -Task $task -Name 'question' `
                -Value 'Hunyuan automation failed. Open the worker log for details.'
            Set-TaskProperty -Task $task -Name 'updatedAt' `
                -Value ([DateTime]::Now.ToString('o'))
            Write-Queue -Items $queue
            Write-WorkerLog `
                -Message ($_.Exception.ToString() + "`n" + $_.ScriptStackTrace) `
                -Level 'ERROR'
        }

        if ($Once) {
            break
        }
    }
}
finally {
    Write-WorkerLog -Message 'Pipeline worker v16.2 stopped'
}
