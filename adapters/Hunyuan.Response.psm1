function Test-HunyuanGlb {
    param([Parameter(Mandatory)][string]$Path, [string]$ContentType,
          [int]$MinimumBytes = 1024)
    $mediaType = ($ContentType -split ';')[0].Trim().ToLowerInvariant()
    if ($mediaType -notin @('model/gltf-binary', 'application/octet-stream')) {
        throw "Unexpected Hunyuan content type: $ContentType"
    }
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -lt [Math]::Max(20, $MinimumBytes)) { throw 'GLB is too small.' }
    if ([Text.Encoding]::ASCII.GetString($bytes, 0, 4) -ne 'glTF') { throw 'Invalid GLB magic.' }
    if ([BitConverter]::ToUInt32($bytes, 4) -ne 2) { throw 'Unsupported GLB version.' }
    if ([BitConverter]::ToUInt32($bytes, 8) -ne $bytes.Length) { throw 'GLB length mismatch.' }
    $offset = 12
    $first = $true
    while ($offset -lt $bytes.Length) {
        if ($offset + 8 -gt $bytes.Length) { throw 'Truncated GLB chunk header.' }
        $size = [BitConverter]::ToUInt32($bytes, $offset)
        $kind = [BitConverter]::ToUInt32($bytes, $offset + 4)
        if ($size % 4 -ne 0 -or [long]$offset + 8 + $size -gt $bytes.Length) {
            throw 'Invalid GLB chunk length.'
        }
        if ($first) {
            if ($kind -ne 0x4E4F534A) { throw 'GLB must start with JSON.' }
            $json = [Text.Encoding]::UTF8.GetString($bytes, $offset + 8, $size) | ConvertFrom-Json
            if ($json.asset.version -ne '2.0') { throw 'Invalid glTF asset version.' }
            $first = $false
        }
        $offset += 8 + $size
    }
    if ($first) { throw 'Missing GLB JSON chunk.' }
}
Export-ModuleMember -Function Test-HunyuanGlb
