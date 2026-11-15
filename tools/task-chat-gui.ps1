param([string]$Root='C:\ai-game-studio',[string]$TaskId,[string]$Title,[string]$Backend,[string]$Model,[string]$Agent,[string]$ResultPath,[string]$LogPath,[switch]$SmokeTest)
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase
$ErrorActionPreference='Stop'
$chatTool=Join-Path $Root 'adapters/task_chat.py'
$taskChatId=[string]$TaskId
[xml]$x=@'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" Title="Opgavechat" Height="680" Width="850" MinHeight="480" MinWidth="600" WindowStartupLocation="CenterOwner" Background="#0F172A" FontFamily="Segoe UI" FontSize="14">
<Grid Margin="14"><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
<StackPanel Grid.Row="0" Margin="0,0,0,10"><TextBlock Name="TaskHeader" Foreground="White" FontSize="19" FontWeight="Bold"/><TextBlock Name="TaskMeta" Foreground="#A7F3D0" Margin="0,5,0,0"/><TextBlock Name="SessionInfo" Foreground="#CBD5E1" Margin="0,4,0,0"/></StackPanel>
<ListBox Name="History" Grid.Row="1" Background="#1E293B" Foreground="#F8FAFC" BorderBrush="#475569" Padding="8" FontFamily="Segoe UI" FontSize="14" ScrollViewer.HorizontalScrollBarVisibility="Disabled"><ListBox.ItemTemplate><DataTemplate><Border Background="#334155" CornerRadius="5" Padding="10" Margin="2,4"><StackPanel><TextBlock Text="{Binding Label}" Foreground="#93C5FD" FontWeight="Bold"/><TextBlock Text="{Binding Text}" TextWrapping="Wrap" Margin="0,5,0,0"/><TextBlock Text="{Binding CreatedAt}" Foreground="#94A3B8" FontSize="11" Margin="0,5,0,0"/></StackPanel></Border></DataTemplate></ListBox.ItemTemplate></ListBox>
<StackPanel Grid.Row="2" Margin="0,12,0,0"><TextBlock Name="Notice" Foreground="#FBBF24" TextWrapping="Wrap" Margin="0,0,0,6"/><TextBox Name="Message" Height="90" AcceptsReturn="True" TextWrapping="Wrap" VerticalScrollBarVisibility="Auto" Background="White" Foreground="#111827" Padding="8"/><TextBlock Text="Ctrl+Enter sender. Svar på spørgsmål her. Når ændringer er godkendt og overført, oprettes en ny opgave/version til næste arbejde." Foreground="#CBD5E1" TextWrapping="Wrap" Margin="0,0,0,7"/><DockPanel><TextBlock Name="ErrorText" Foreground="#FCA5A5" TextWrapping="Wrap" VerticalAlignment="Center"/><Button Name="SendBtn" DockPanel.Dock="Right" Content="Send" Padding="20,8" Margin="8,0,0,0"/></DockPanel></StackPanel>
<DockPanel Grid.Row="3" Margin="0,8,0,0"><Button Name="OpenLogBtn" DockPanel.Dock="Right" Content="Åbn log" Margin="4,0,0,0" Padding="10,5"/><Button Name="OpenResultBtn" DockPanel.Dock="Right" Content="Åbn resultat" Margin="4,0,0,0" Padding="10,5"/><TextBlock Name="StatusLine" Foreground="#94A3B8" VerticalAlignment="Center"/></DockPanel>
</Grid></Window>
'@
$r=New-Object System.Xml.XmlNodeReader $x;$w=[Windows.Markup.XamlReader]::Load($r)
foreach($n in 'TaskHeader TaskMeta SessionInfo History Notice Message SendBtn ErrorText StatusLine OpenLogBtn OpenResultBtn'.Split(' ')){Set-Variable $n $w.FindName($n)}
$TaskHeader.Text=if($Title){'Opgavechat · '+$Title}else{'Opgavechat · '+$taskChatId}
$script:busy=$false;$script:proc=$null;$script:output='';$script:errorFile='';$script:messageFile='';$script:pollKind='history';$script:canSend=$false;$script:pendingMessage='';$script:pendingRequestId='';$script:outDrained=$false;$script:errDrained=$false;$script:lastEventCount=0;$script:lastEventKey=''
$sha=[Security.Cryptography.SHA256]::Create();$safeTaskHash=[BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($taskChatId))).Replace('-','').ToLowerInvariant();$sha.Dispose()
$pendingRoot=Join-Path $env:LOCALAPPDATA 'AI-Game-Studio/task-chat-pending';New-Item -ItemType Directory -Force -Path $pendingRoot|Out-Null;$script:pendingStateFile=Join-Path $pendingRoot ($safeTaskHash+'.json')
if(Test-Path -LiteralPath $script:pendingStateFile){try{$saved=Get-Content -LiteralPath $script:pendingStateFile -Raw -Encoding UTF8|ConvertFrom-Json;$script:pendingMessage=[string]$saved.message;$script:pendingRequestId=[string]$saved.requestId;$Message.Text=$script:pendingMessage}catch{}}
function Save-PendingDraft {if($script:pendingRequestId){[IO.File]::WriteAllText($script:pendingStateFile,(ConvertTo-Json -InputObject ([pscustomobject]@{requestId=$script:pendingRequestId;message=$script:pendingMessage}) -Compress),(New-Object Text.UTF8Encoding($false)))}else{Remove-Item -LiteralPath $script:pendingStateFile -Force -ErrorAction SilentlyContinue}}
function Resolve-Python { $p=Get-Command python.exe -ErrorAction SilentlyContinue;if($p){return $p.Source};$fallback=Join-Path $env:USERPROFILE 'miniconda3/python.exe';if(Test-Path $fallback){return $fallback};throw 'Python blev ikke fundet (python.exe).' }
function Quote-Arg([string]$s){'"'+($s -replace '(\\*)"','$1$1\"' -replace '(\\+)$','$1$1')+'"'}
function Start-ChatCli([string]$kind,[string]$messagePath='') {
 if($script:proc -and -not $script:proc.HasExited){return}
 if(!(Test-Path -LiteralPath $chatTool -PathType Leaf)){throw "Chat-backend mangler: $chatTool"}
 $python=Resolve-Python;$script:output=[IO.Path]::GetTempFileName();$script:errorFile=[IO.Path]::GetTempFileName()
 $args=@($chatTool,'--root',$Root,'--task-id',$taskChatId,$kind)
 if($kind -eq 'send'){$args+=@('--message-file',$messagePath,'--request-id',$script:pendingRequestId)}
 $argLine=($args|ForEach-Object {Quote-Arg ([string]$_)}) -join ' '
 $psi=New-Object Diagnostics.ProcessStartInfo;$psi.FileName=$python;$psi.Arguments=$argLine;$psi.WorkingDirectory=$Root;$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
 $script:proc=New-Object Diagnostics.Process;$script:proc.StartInfo=$psi;$script:outDrained=$false;$script:errDrained=$false
 $script:proc.add_OutputDataReceived({param($s,$e) if($null -ne $e.Data){[IO.File]::AppendAllText($script:output,$e.Data+[Environment]::NewLine,[Text.Encoding]::UTF8)}else{$script:outDrained=$true}})
 $script:proc.add_ErrorDataReceived({param($s,$e) if($null -ne $e.Data){[IO.File]::AppendAllText($script:errorFile,$e.Data+[Environment]::NewLine,[Text.Encoding]::UTF8)}else{$script:errDrained=$true}})
 [void]$script:proc.Start();$script:proc.BeginOutputReadLine();$script:proc.BeginErrorReadLine();$script:pollKind=$kind;$script:busy=$true
 $StatusLine.Text=if($kind -eq 'send'){'Sender besked…'}else{'Opdaterer historik…'}
 if($kind -eq 'send'){$SendBtn.IsEnabled=$false;$Message.IsEnabled=$false}
}
function Read-ChatResult {
 if(!$script:proc -or -not $script:proc.HasExited -or !$script:outDrained -or !$script:errDrained){return}
 $kind=$script:pollKind;$json=if(Test-Path $script:output){Get-Content -LiteralPath $script:output -Raw -Encoding UTF8}else{''};$stderr=if(Test-Path $script:errorFile){Get-Content -LiteralPath $script:errorFile -Raw -Encoding UTF8}else{''}
 Remove-Item -LiteralPath $script:output,$script:errorFile -Force -ErrorAction SilentlyContinue;$script:proc=$null;$script:busy=$false
 if($kind -eq 'send'){$SendBtn.IsEnabled=$true;$Message.IsEnabled=$true}
 try{$v=$json|ConvertFrom-Json -ErrorAction Stop;if(!$v.ok){throw ([string]$v.error)}}catch{$ErrorText.Text=if($stderr){$stderr.Trim()}elseif($_.Exception.Message){$_.Exception.Message}else{'Chat-backend returnerede et ugyldigt svar.'};$StatusLine.Text='Fejl';return}
 $ErrorText.Text=''
 $script:recoveredStatus=''
 if($kind -eq 'send'){$Message.Clear();if($script:messageFile){Remove-Item -LiteralPath $script:messageFile -Force -ErrorAction SilentlyContinue;$script:messageFile=''};$script:pendingMessage='';$script:pendingRequestId='';Save-PendingDraft}
 $modelLabel=if($Model){$Model}elseif($Agent){$Agent}else{'opgavens valgte agent'}
 $backendLabel=if($Backend){$Backend}else{'opgavens lokale backend'}
 $TaskMeta.Text='Status: '+[string]$v.status+'   ·   Model/agent: '+$modelLabel+'   ·   Backend: '+$backendLabel+'   ·   ID: '+$taskChatId
 if($v.pendingQuestion){$Notice.Text='Project Manager har et spørgsmål: '+[string]$v.pendingQuestion.text}else{$Notice.Text=''}
 if($v.events){$incoming=@($v.events);$key=[string]$incoming.Count+':'+[string]$incoming[-1].seq;if($key -ne $script:lastEventKey){$History.ItemsSource=@($incoming|ForEach-Object {$role=[string]$_.role;$label=switch($role){'user'{'Dig'}'assistant'{'Assistent'}'question'{'Spørgsmål'}'status'{'Status'}default{$role}};[pscustomobject]@{Label=$label;Text=[string]$_.text;CreatedAt=[string]$_.createdAt}});if($incoming.Count -gt $script:lastEventCount -and $History.Items.Count){$History.ScrollIntoView($History.Items[$History.Items.Count-1])};$script:lastEventCount=$incoming.Count;$script:lastEventKey=$key}}
 if($script:pendingRequestId -and $v.requests){$known=@($v.requests|Where-Object requestId -eq $script:pendingRequestId|Select-Object -First 1);if($known.Count){if($Message.Text -ceq $script:pendingMessage){$Message.Clear()};$script:pendingMessage='';$script:pendingRequestId='';Save-PendingDraft;if($known[0].status -in @('queued','dispatching')){$script:recoveredStatus='Beskeden er allerede sendt og afventer behandling.'}}}
 $sid=[string]$v.sessionId;$SessionInfo.Text=if($sid){'Fortsættelse af chatsession: '+$sid}else{'Ny chat knyttet til denne opgave'}
 $StatusLine.Text=if($script:recoveredStatus){$script:recoveredStatus}elseif($v.canSend){'Klar til besked'}elseif($v.reason){[string]$v.reason}else{'Historik opdateret'}
 $script:canSend=[bool]$v.canSend;$SendBtn.IsEnabled=$script:canSend -and -not $script:busy
}
function Refresh-Chat {if($script:busy){return};try{Start-ChatCli 'history'}catch{$ErrorText.Text=$_.Exception.Message;$StatusLine.Text='Fejl'}}
function Send-Chat {if($script:busy){return};$msg=$Message.Text;if([string]::IsNullOrWhiteSpace($msg)){return};if(!$script:canSend){$ErrorText.Text='Denne opgave kan ikke modtage beskeder. Opret eller vælg en ny opgave/version.';return};try{if($script:pendingRequestId -and $script:pendingMessage -ceq $msg -and $script:messageFile -and (Test-Path $script:messageFile)){$retryPath=$script:messageFile}else{$script:pendingMessage=$msg;$script:pendingRequestId=[guid]::NewGuid().ToString();$script:messageFile=[IO.Path]::GetTempFileName();[IO.File]::WriteAllText($script:messageFile,$msg,(New-Object Text.UTF8Encoding($false)));Save-PendingDraft;$retryPath=$script:messageFile};Start-ChatCli 'send' $retryPath}catch{$ErrorText.Text=$_.Exception.Message;$StatusLine.Text='Fejl'}}
$SendBtn.Add_Click({Send-Chat})
$OpenResultBtn.Add_Click({if($ResultPath -and (Test-Path -LiteralPath $ResultPath)){Start-Process -FilePath $ResultPath}else{$ErrorText.Text='Resultatfilen findes ikke for denne opgave.'}})
$OpenLogBtn.Add_Click({$p=$LogPath;if(!$p){$p=Join-Path $Root 'logs/project-manager-worker.log'};if(Test-Path -LiteralPath $p){Start-Process notepad.exe -ArgumentList ('"'+$p+'"')}else{$ErrorText.Text='Der findes endnu ingen log for opgaven.'}})
$Message.Add_PreviewKeyDown({if($_.Key -eq [System.Windows.Input.Key]::Enter -and ([System.Windows.Input.Keyboard]::Modifiers -band [System.Windows.Input.ModifierKeys]::Control)){$_.Handled=$true;Send-Chat}})
$timer=New-Object Windows.Threading.DispatcherTimer;$timer.Interval=[TimeSpan]::FromMilliseconds(250);$timer.Add_Tick({if($script:proc){Read-ChatResult}})
$refreshTimer=New-Object Windows.Threading.DispatcherTimer;$refreshTimer.Interval=[TimeSpan]::FromSeconds(2);$refreshTimer.Add_Tick({if(!$script:busy){Refresh-Chat}})
$w.Add_Closed({$timer.Stop();$refreshTimer.Stop();if($script:messageFile -and (!$script:proc -or $script:proc.HasExited)){Remove-Item -LiteralPath $script:messageFile -Force -ErrorAction SilentlyContinue}})
if($SmokeTest){'SmokeTest: chat XAML loaded; controls='+(@('History','Message','SendBtn','ErrorText','SessionInfo','OpenLogBtn','OpenResultBtn') -join ',');exit 0}
$timer.Start();$refreshTimer.Start();Refresh-Chat;[void]$w.ShowDialog()
