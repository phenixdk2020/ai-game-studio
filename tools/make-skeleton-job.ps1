param([string]$Path='C:\Users\allan\Dropbox\AI-Game-Studio\workspace\jobs\skeleton_stub.json')
$dir=Split-Path $Path;New-Item -ItemType Directory -Force $dir|Out-Null
@{type='skeleton_stub';output_name='SK_1864_Human';write_asset=$true;bones=@('root','pelvis','spine_01','spine_02','neck_01','head','clavicle_l','upperarm_l','lowerarm_l','hand_l','clavicle_r','upperarm_r','lowerarm_r','hand_r','thigh_l','calf_l','foot_l','thigh_r','calf_r','foot_r')}|ConvertTo-Json -Depth 4|Set-Content $Path -Encoding UTF8
Write-Host $Path
