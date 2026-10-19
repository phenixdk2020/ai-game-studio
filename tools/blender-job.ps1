param([Parameter(Mandatory=$true)][string]$Job,[switch]$ApproveWrite)
$args=@('C:\ai-game-studio\adapters\blender_job.py',$Job)
if($ApproveWrite){$args+='--approve-write'}
& 'C:\Users\allan\miniconda3\python.exe' @args
exit $LASTEXITCODE
