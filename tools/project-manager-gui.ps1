param([string]$Root='C:\ai-game-studio')
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Windows.Forms
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '..\adapters\Studio.Queue.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '..\adapters\Studio.Orchestrator.psm1') -Force
$q=Join-Path $Root 'tasks\queue.gui.json'; New-Item -ItemType Directory -Force -Path (Split-Path $q),(Join-Path $Root 'results'),(Join-Path $Root 'logs'),(Join-Path $Root 'state')|Out-Null;if(!(Test-Path $q)){try { Write-StudioQueue -Path $q -Items @() -ExpectedRevision 'missing' } catch { if(!(Test-Path $q)){throw} }}
[xml]$x=@'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" Title="AI Game Studio - Project Manager v18" Height="850" Width="1320" WindowStartupLocation="CenterScreen" Background="#0F172A" FontFamily="Segoe UI" FontSize="14">
<Window.Resources>
<Style TargetType="Button"><Setter Property="Margin" Value="4"/><Setter Property="Padding" Value="12,7"/><Setter Property="FontWeight" Value="SemiBold"/></Style>
<Style TargetType="TextBox"><Setter Property="Margin" Value="0,4,0,10"/><Setter Property="Padding" Value="7"/><Setter Property="Background" Value="White"/><Setter Property="Foreground" Value="#111827"/><Setter Property="BorderBrush" Value="#94A3B8"/></Style>
<Style TargetType="ComboBox"><Setter Property="Margin" Value="0,4,0,10"/><Setter Property="Padding" Value="6"/><Setter Property="Background" Value="White"/><Setter Property="Foreground" Value="#111827"/></Style>
<Style x:Key="LabelStyle" TargetType="TextBlock"><Setter Property="Foreground" Value="#F8FAFC"/><Setter Property="FontWeight" Value="Bold"/><Setter Property="FontSize" Value="14"/><Setter Property="Margin" Value="0,5,0,0"/></Style>
</Window.Resources>
<Grid Margin="12"><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="215"/></Grid.RowDefinitions>
<StackPanel Orientation="Horizontal" Margin="0,0,0,10"><Button Name="NewBtn" Content="Ny opgave"/><Button Name="SaveBtn" Content="Gem"/><Button Name="PauseBtn" Content="Pause/Forts&#230;t"/><Button Name="CancelBtn" Content="Annuller"/><Button Name="DeleteBtn" Content="Slet"/><Button Name="UpBtn" Content="Flyt op"/><Button Name="DownBtn" Content="Flyt ned"/><Button Name="WorkerBtn" Content="Start worker"/><Button Name="RetryBtn" Content="Pr&#248;v igen"/><Button Name="LogBtn" Content="&#197;bn worker-log"/><Button Name="RefreshBtn" Content="Opdater"/><TextBlock Name="WorkerState" Foreground="#4ADE80" FontWeight="Bold" FontSize="14" Margin="18,9"/></StackPanel>
<Grid Grid.Row="1"><Grid.ColumnDefinitions><ColumnDefinition Width="44*"/><ColumnDefinition Width="56*"/></Grid.ColumnDefinitions>
<DataGrid Name="Queue" AutoGenerateColumns="False" IsReadOnly="True" Margin="0,0,12,0" Background="#1E293B" Foreground="#F8FAFC" RowBackground="#1E293B" AlternatingRowBackground="#334155" GridLinesVisibility="Horizontal" HorizontalGridLinesBrush="#475569" HeadersVisibility="Column" ColumnHeaderHeight="36"><DataGrid.ColumnHeaderStyle><Style TargetType="DataGridColumnHeader"><Setter Property="Background" Value="#334155"/><Setter Property="Foreground" Value="White"/><Setter Property="FontWeight" Value="Bold"/><Setter Property="FontSize" Value="14"/><Setter Property="Padding" Value="8"/><Setter Property="BorderBrush" Value="#64748B"/></Style></DataGrid.ColumnHeaderStyle><DataGrid.Columns><DataGridTextColumn Header="#" Binding="{Binding priority}" Width="38"/><DataGridTextColumn Header="STATUS" Binding="{Binding status}" Width="125"/><DataGridTextColumn Header="AGENT" Binding="{Binding agent}" Width="165"/><DataGridTextColumn Header="OPGAVE" Binding="{Binding title}" Width="*"/></DataGrid.Columns></DataGrid>
<ScrollViewer Grid.Column="1" VerticalScrollBarVisibility="Auto"><StackPanel>
<TextBlock Text="PIPELINE" Style="{StaticResource LabelStyle}"/>
<UniformGrid Columns="4" Margin="0,4,0,12">
<Border Name="StageHunyuan" Background="#334155" CornerRadius="5" Margin="2" Padding="8"><TextBlock Text="1  HUNYUAN3D" Foreground="White" FontWeight="Bold" HorizontalAlignment="Center"/></Border>
<Border Name="StageBlender" Background="#334155" CornerRadius="5" Margin="2" Padding="8"><TextBlock Text="2  BLENDER" Foreground="White" FontWeight="Bold" HorizontalAlignment="Center"/></Border>
<Border Name="StageQA" Background="#334155" CornerRadius="5" Margin="2" Padding="8"><TextBlock Text="3  QA" Foreground="White" FontWeight="Bold" HorizontalAlignment="Center"/></Border>
<Border Name="StageUnreal" Background="#334155" CornerRadius="5" Margin="2" Padding="8"><TextBlock Text="4  UNREAL" Foreground="White" FontWeight="Bold" HorizontalAlignment="Center"/></Border>
</UniformGrid>
<TextBlock Text="OPGAVE" Style="{StaticResource LabelStyle}"/><TextBox Name="Title" FontWeight="SemiBold"/>
<TextBlock Text="BESKRIVELSE / PROMPT" Style="{StaticResource LabelStyle}"/><TextBox Name="Description" Height="145" AcceptsReturn="True" TextWrapping="Wrap" VerticalScrollBarVisibility="Auto"/>
<TextBlock Text="AGENT" Style="{StaticResource LabelStyle}"/><ComboBox Name="Agent" IsEditable="True"/>
<TextBlock Text="PROJECT PATH" Style="{StaticResource LabelStyle}"/><TextBox Name="ProjectPath"/><CheckBox Name="NewProject" Content="Opret nyt projekt hvis n&#248;dvendigt" Foreground="#F8FAFC" FontWeight="SemiBold" Margin="0,0,0,8"/>
<TextBlock Text="VEDH&#198;FTNINGER" Style="{StaticResource LabelStyle}"/><ListBox Name="Attachments" Height="105" Background="White" Foreground="#111827" FontSize="13"/>
<StackPanel Orientation="Horizontal"><Button Name="AddAttachmentBtn" Content="Tilf&#248;j filer"/><Button Name="RemoveAttachmentBtn" Content="Fjern valgt"/><Button Name="OpenResultBtn" Content="&#197;bn resultat"/></StackPanel>
<TextBlock Text="SP&#216;RGSM&#197;L FRA PROJECT MANAGER" Foreground="#FBBF24" FontWeight="Bold" FontSize="14" Margin="0,5,0,0"/><TextBox Name="Question" IsReadOnly="True" TextWrapping="Wrap"/>
</StackPanel></ScrollViewer></Grid>
<GroupBox Grid.Row="2" Header="FEEDBACK, LOG OG RESULTATER" Foreground="#F8FAFC" FontWeight="Bold" FontSize="14" Margin="0,10,0,0" BorderBrush="#64748B"><TextBox Name="Feedback" IsReadOnly="True" AcceptsReturn="True" TextWrapping="Wrap" VerticalScrollBarVisibility="Auto" Background="#020617" Foreground="#E2E8F0" FontFamily="Consolas" FontSize="13"/></GroupBox>
</Grid></Window>
'@
$r=New-Object System.Xml.XmlNodeReader $x;$w=[Windows.Markup.XamlReader]::Load($r)
$w.Dispatcher.Add_UnhandledException({param($sender,$eventArgs) $eventArgs.Handled=$true; [Windows.MessageBox]::Show($eventArgs.Exception.Message, 'Operation could not be saved')|Out-Null})
foreach($n in 'NewBtn SaveBtn PauseBtn CancelBtn DeleteBtn UpBtn DownBtn WorkerBtn RetryBtn LogBtn RefreshBtn WorkerState Queue Title Description Agent ProjectPath NewProject Attachments AddAttachmentBtn RemoveAttachmentBtn OpenResultBtn Question Feedback StageHunyuan StageBlender StageQA StageUnreal'.Split(' ')){Set-Variable $n $w.FindName($n)}
'auto','project-manager','pinokio-hunyuan3d-agent','unreal-agent','blender-agent','character3d-agent','rigging-agent','animation-agent','gameplay-ai-agent','hud-ui-agent','historical-research-agent','technical-research-agent','qa-agent','integration-agent'|%{[void]$Agent.Items.Add($_)};$Agent.SelectedIndex=0
function ReadQ {
    $snapshot = Get-StudioQueueSnapshot -Path $q
    $script:guiRevision = $snapshot.Revision
    $snapshot.Tasks
}
function Save-StudioForm {
    if ([string]::IsNullOrWhiteSpace($Title.Text)) { throw 'Angiv en titel.' }
    $toolArguments=ConvertFrom-Json -InputObject $ToolParameters.Text
    if($toolArguments -isnot [pscustomobject]){throw 'Værktøjsparametre skal være et JSON-objekt.'}
    $snapshot = Get-StudioQueueSnapshot -Path $q
    $selected = $Queue.SelectedItem
    if ($selected) {
        $task = @($snapshot.Tasks | Where-Object id -eq $selected.id)[0]
        Assert-EditableTaskCurrent $selected $task
    } else {
        $task = [pscustomobject]@{id=('TASK-'+[guid]::NewGuid().ToString('N').Substring(0,20).ToUpper());status='Queued';priority=10;createdAt=[DateTime]::UtcNow.ToString('o')}
        $snapshot.Tasks = @($snapshot.Tasks + $task)
    }
    foreach ($pair in @(@('title',$Title.Text),@('description',$Description.Text),@('agent',$Agent.Text),@('role',$Agent.Text),@('backend',[string]$Backend.SelectedItem),@('dependencies',@($Dependencies.Text -split '[,\s]+'|Where-Object {$_})),@('projectPath',$ProjectPath.Text),@('newProject',[bool]$NewProject.IsChecked),@('attachments',@($Attachments.Items)),@('updatedAt',[DateTime]::UtcNow.ToString('o')))) {
        $task|Add-Member -NotePropertyName $pair[0] -NotePropertyValue $pair[1] -Force
    }
    foreach($pair in @(@('toolCapability',$ToolCapability.Text),@('toolOperation',$ToolOperation.Text),@('toolAppId',$ToolAppId.Text),@('toolParameters',$toolArguments))){$task|Add-Member -NotePropertyName $pair[0] -NotePropertyValue $pair[1] -Force}
    Write-StudioQueue -Path $q -Items $snapshot.Tasks -ExpectedRevision $snapshot.Revision
    RefreshQ
}
function WriteQ($items) {
    $script:guiRevision = Write-StudioQueue -Path $q -Items $items -ExpectedRevision $script:guiRevision -PassThruRevision
}
function Assert-EditableTaskCurrent($displayed, $fresh) {
    if (-not $fresh) { throw 'The selected task was deleted. Refresh before saving.' }
    foreach ($name in @('title','description','agent','backend','dependencies','projectPath','newProject','attachments','toolCapability','toolOperation','toolAppId','toolParameters')) {
        $before = ConvertTo-Json -InputObject $displayed.$name -Depth 40 -Compress
        $current = ConvertTo-Json -InputObject $fresh.$name -Depth 40 -Compress
        if ($before -ne $current) { throw "Task input changed elsewhere ($name). Refresh before saving your edit." }
    }
}
function RefreshQ{foreach($control in @($ToolCapability,$ToolOperation,$ToolAppId,$ToolParameters)){if($control.IsKeyboardFocusWithin){return}};if($Title.IsKeyboardFocusWithin -or $Description.IsKeyboardFocusWithin -or $ProjectPath.IsKeyboardFocusWithin -or $Agent.IsKeyboardFocusWithin -or $Backend.IsKeyboardFocusWithin -or $Dependencies.IsKeyboardFocusWithin){return};$id=if($Queue.SelectedItem){$Queue.SelectedItem.id}else{$null};$items=@(ReadQ|Sort-Object priority);$Queue.ItemsSource=$null;$Queue.ItemsSource=$items;if($id){$Queue.SelectedItem=$items|?{$_.id-eq$id}|Select-Object -First 1};if($script:worker-and!$script:worker.HasExited){$WorkerState.Text="WORKER KØRER  PID $($script:worker.Id)";$WorkerBtn.Content='Stop worker'}else{$WorkerState.Text='WORKER STOPPET';$WorkerBtn.Content='Start worker'}}
function ClearForm{$Title.Text='';$Description.Text='';$Agent.Text='auto';$ProjectPath.Text='';$NewProject.IsChecked=$false;$Attachments.Items.Clear();$Question.Text='';$Feedback.Text=''}
function MoveTask([int]$d){$t=$Queue.SelectedItem;if(!$t){return};$a=@(ReadQ|Sort-Object priority);$sel=$a|?{$_.id-eq$t.id}|Select-Object -First 1;if(!$sel){return};$i=[array]::IndexOf($a,$sel);$n=$i+$d;if($n-lt 0-or$n-ge$a.Count){return};$tmp=$a[$i];$a[$i]=$a[$n];$a[$n]=$tmp;for($j=0;$j-lt$a.Count;$j++){$a[$j].priority=$j+1};WriteQ $a;RefreshQ}
function PaintPipeline($t){
 foreach($b in @($StageHunyuan,$StageBlender,$StageQA,$StageUnreal)){$b.Background='#334155'}
 if(!$t){return}
 $stage=[string]$t.pipelineStage
 if($stage -match 'hunyuan'){$StageHunyuan.Background='#2563EB'}
 elseif($stage -match 'blender'){$StageHunyuan.Background='#16A34A';$StageBlender.Background='#2563EB'}
 elseif($stage -match 'qa'){$StageHunyuan.Background='#16A34A';$StageBlender.Background='#16A34A';$StageQA.Background='#2563EB'}
 elseif($stage -match 'unreal'){$StageHunyuan.Background='#16A34A';$StageBlender.Background='#16A34A';$StageQA.Background='#16A34A';$StageUnreal.Background='#2563EB'}
 if($t.status -eq 'Completed'){foreach($b in @($StageHunyuan,$StageBlender,$StageQA,$StageUnreal)){$b.Background='#16A34A'}}
 if($t.status -eq 'Failed'){
  if($stage -match 'hunyuan'){$StageHunyuan.Background='#DC2626'}
  elseif($stage -match 'blender'){$StageBlender.Background='#DC2626'}
  elseif($stage -match 'qa'){$StageQA.Background='#DC2626'}
  elseif($stage -match 'unreal'){$StageUnreal.Background='#DC2626'}
 }
}
$Queue.Add_SelectionChanged({$t=$Queue.SelectedItem;if(!$t){return};$Title.Text=[string]$t.title;$Description.Text=[string]$t.description;$Agent.Text=[string]$t.agent;$ProjectPath.Text=[string]$t.projectPath;$NewProject.IsChecked=[bool]$t.newProject;$Attachments.Items.Clear();@($t.attachments)|%{[void]$Attachments.Items.Add($_)};$Question.Text=[string]$t.question;PaintPipeline $t;if($t.resultPath-and(Test-Path -LiteralPath $t.resultPath -PathType Leaf)){$Feedback.Text=Get-Content -LiteralPath $t.resultPath -Raw}else{$Feedback.Text="ID: $($t.id)`r`nStatus: $($t.status)`r`nAgent: $($t.agent)`r`nPipeline: $($t.pipeline)`r`nStage: $($t.pipelineStage)`r`nError: $($t.error)"}})
$NewBtn.Add_Click({$Queue.SelectedItem=$null;ClearForm})
$SaveBtn.Add_Click({Invoke-StudioUiAction {Save-StudioForm}})
$PauseBtn.Add_Click({$t=$Queue.SelectedItem;if(!$t){return};$a=@(ReadQ);$i=$a|?{$_.id-eq$t.id}|Select-Object -First 1;$i.status=if($i.status-eq'Paused'){'Queued'}else{'Paused'};WriteQ $a;RefreshQ});$CancelBtn.Add_Click({$t=$Queue.SelectedItem;if($t){$a=@(ReadQ);($a|?{$_.id-eq$t.id}).status='Cancelled';WriteQ $a;RefreshQ}});$DeleteBtn.Add_Click({$t=$Queue.SelectedItem;if($t){WriteQ @(ReadQ|?{$_.id-ne$t.id});ClearForm;RefreshQ}});$UpBtn.Add_Click({MoveTask -1});$DownBtn.Add_Click({MoveTask 1})
$RetryBtn.Add_Click({$t=$Queue.SelectedItem;if(!$t){return};$a=@(ReadQ);$i=$a|?{$_.id-eq$t.id}|Select-Object -First 1;if($i){foreach($pair in @(@('status','Queued'),@('error',''),@('question',''),@('agent','auto'),@('updatedAt',[DateTime]::Now.ToString('o')))){if($i.PSObject.Properties.Name -contains $pair[0]){$i.($pair[0])=$pair[1]}else{$i|Add-Member -NotePropertyName $pair[0] -NotePropertyValue $pair[1]}};WriteQ $a;RefreshQ}})
$LogBtn.Add_Click({$p=Join-Path $Root 'logs\\project-manager-worker.log';if(Test-Path $p){Start-Process notepad.exe $p}else{[Windows.MessageBox]::Show("Worker-log findes endnu ikke:`n$p")|Out-Null}})
$RefreshBtn.Add_Click({RefreshQ})
$AddAttachmentBtn.Add_Click({$d=New-Object Microsoft.Win32.OpenFileDialog;$d.Multiselect=$true;$d.Filter='Alle filer|*.*';if($d.ShowDialog()){$d.FileNames|%{[void]$Attachments.Items.Add($_)}}});$RemoveAttachmentBtn.Add_Click({@($Attachments.SelectedItems)|%{$Attachments.Items.Remove($_)}});$OpenResultBtn.Add_Click({$t=$Queue.SelectedItem;if($t.resultPath-and(Test-Path $t.resultPath)){Start-Process $t.resultPath}})
$WorkerBtn.Add_Click({Invoke-StudioUiAction {Start-StudioUiWorker}})
. (Join-Path $PSScriptRoot '../adapters/Studio.Gui.ps1')
$timer=New-Object Windows.Threading.DispatcherTimer;$timer.Interval=[TimeSpan]::FromSeconds(3);$timer.Add_Tick({RefreshQ});$timer.Start();$w.Add_Closed({$timer.Stop()});RefreshQ;[void]$w.ShowDialog()
