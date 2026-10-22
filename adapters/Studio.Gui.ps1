# Shared controls for the canonical project manager window.
$Backend=New-Object Windows.Controls.ComboBox
@('auto','ollama','copilot-local','copilot-github','asset3d','pinokio')|ForEach-Object{[void]$Backend.Items.Add($_)}
$Backend.SelectedIndex=0
$Backend.ToolTip='Auto bruger lokal Copilot til kode, Ollama til planer/research og Pinokio ved valg af et værktøj.'
$Dependencies=New-Object Windows.Controls.TextBox
$form=$Agent.Parent
$position=$form.Children.IndexOf($Agent)
$label=New-Object Windows.Controls.TextBlock;$label.Text='BACKEND';$label.Foreground='White'
$form.Children.Insert($position,$label);$form.Children.Insert($position+1,$Backend)
$label=New-Object Windows.Controls.TextBlock;$label.Text='AFHÆNGIGHEDER (opgave-ID adskilt med komma)';$label.Foreground='White'
$form.Children.Insert($position+2,$label);$form.Children.Insert($position+3,$Dependencies)
$toolPosition=$position+4
foreach($entry in @(@('ToolCapability','PINOKIO VÆRKTØJ (fx image_to_3d)'),@('ToolOperation','HANDLING (fx generate_shape eller inspect)'),@('ToolAppId','APP-ID (valgfrit)'),@('ToolParameters','PARAMETRE (JSON)'))){
 $label=New-Object Windows.Controls.TextBlock;$label.Text=$entry[1];$label.Foreground='White'
 $control=New-Object Windows.Controls.TextBox;Set-Variable $entry[0] $control
 $form.Children.Insert($toolPosition,$label);$form.Children.Insert($toolPosition+1,$control);$toolPosition+=2
}
$ToolParameters.Text='{}'
$toolCatalogButton=New-Object Windows.Controls.Button;$toolCatalogButton.Content='Vis Pinokio-værktøjer'
$form.Children.Insert($toolPosition,$toolCatalogButton)
$toolCatalogButton.Add_Click({Invoke-StudioUiAction {$output=@(& python (Join-Path $Root 'tools/pinokio.py') catalog);$catalog=($output -join "`n")|ConvertFrom-Json;if($LASTEXITCODE -ne 0){throw $catalog.error};$lines=@(foreach($tool in $catalog.tools){'Værktøj: '+$tool.capability;'Handlinger: '+($tool.operations -join ', ');'Roller: '+($tool.roles -join ', ');foreach($app in $tool.apps){'App: '+$app.title+' ['+$app.app_id+']  Klar: '+$app.ready};''});$Feedback.Text=$lines -join "`r`n"}})
$toolbar=$NewBtn.Parent
$toolbar.Orientation='Vertical'
$buttons=New-Object Windows.Controls.WrapPanel
$old=@($toolbar.Children);$toolbar.Children.Clear()
foreach($control in $old){[void]$buttons.Children.Add($control)}
[void]$toolbar.Children.Add($buttons)
$settings=New-Object Windows.Controls.WrapPanel
[void]$toolbar.Children.Add($settings)
foreach($entry in @(@('SpecialistsEnabled','Agenter / Pinokio / Copilot'),@('AssetsEnabled','Behandl 3D'),@('BlenderApproved','Skriv Blender'),@('UnrealApproved','Skriv Unreal'),@('UnrealValidation','Unreal QA'),@('UnrealCapture','Unreal preview'))){
 $control=New-Object Windows.Controls.CheckBox;$control.Content=$entry[1];$control.Foreground='White';$control.Margin='8,4,8,4';Set-Variable $entry[0] $control;[void]$settings.Children.Add($control)
}
function Invoke-StudioUiAction([scriptblock]$Action){try{& $Action}catch{[Windows.MessageBox]::Show($_.Exception.Message,'AI Game Studio')|Out-Null}}
function Start-StudioUiWorker {
 if($script:worker -and !$script:worker.HasExited){Stop-Process $script:worker.Id;$script:worker=$null;RefreshQ;return}
 $arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $Root 'tools/project-manager-worker.ps1')+'"'),'-Root',('"'+$Root+'"'))
 foreach($option in @(@($SpecialistsEnabled,'-EnableSpecialists'),@($AssetsEnabled,'-ProcessAssets'),@($BlenderApproved,'-ApproveBlenderWrite'),@($UnrealApproved,'-ApproveUnrealWrite'),@($UnrealValidation,'-ValidateUnreal'),@($UnrealCapture,'-CaptureUnrealPreview'))){if($option[0].IsChecked){$arguments+=$option[1]}}
 $exe=if(Get-Command pwsh.exe -ErrorAction SilentlyContinue){'pwsh.exe'}else{'powershell.exe'}
 $script:worker=Start-Process $exe -ArgumentList $arguments -PassThru -WindowStyle Hidden
 RefreshQ
}
$planButton=New-Object Windows.Controls.Button;$planButton.Content='Lav plan';[void]$buttons.Children.Add($planButton)
$planButton.Add_Click({Invoke-StudioUiAction {New-StudioTask -Root $Root -Title $Title.Text -Description $Description.Text -Backend ollama -Role project_manager -Kind plan -Attachments @($Attachments.Items) -ProjectPath $ProjectPath.Text|Out-Null;RefreshQ}})
$approveButton=New-Object Windows.Controls.Button;$approveButton.Content='Godkend resultat / plan';[void]$buttons.Children.Add($approveButton)
$approveButton.Add_Click({Invoke-StudioUiAction {if(!$Queue.SelectedItem){throw 'Vælg en opgave.'};Approve-StudioResult -Root $Root -Id $Queue.SelectedItem.id;RefreshQ}})
$prButton=New-Object Windows.Controls.Button;$prButton.Content='Åbn PR';[void]$buttons.Children.Add($prButton)
$prButton.Add_Click({Invoke-StudioUiAction {$url=[string]$Queue.SelectedItem.prUrl;if($url -notmatch '^https://github\.com/[\w.-]+/[\w.-]+/pull/[1-9][0-9]*$'){throw 'Opgaven har ingen gyldig PR.'};Start-Process $url}})
$revalidateButton=New-Object Windows.Controls.Button;$revalidateButton.Content='Validér PR igen';[void]$buttons.Children.Add($revalidateButton)
$revalidateButton.Add_Click({Invoke-StudioUiAction {if(!$Queue.SelectedItem){throw 'Vælg en opgave.'};$snapshot=Get-StudioQueueSnapshot -Path $q;$task=@($snapshot.Tasks|Where-Object id -eq $Queue.SelectedItem.id)[0];if(!$task.prUrl){throw 'Opgaven har ingen PR.'};$task.status='Queued';$task|Add-Member -NotePropertyName bridgeAction -NotePropertyValue revalidate -Force;Write-StudioQueue -Path $q -Items $snapshot.Tasks -ExpectedRevision $snapshot.Revision;RefreshQ}})
$resumeToolButton=New-Object Windows.Controls.Button;$resumeToolButton.Content='Hent værktøjsresultat igen';[void]$buttons.Children.Add($resumeToolButton)
$resumeToolButton.Add_Click({Invoke-StudioUiAction {if(!$Queue.SelectedItem){throw 'Vælg en opgave.'};$snapshot=Get-StudioQueueSnapshot -Path $q;$task=@($snapshot.Tasks|Where-Object id -eq $Queue.SelectedItem.id)[0];if($task.backend -ne 'pinokio' -or $task.status -notin @('NeedsInput','Failed','AwaitingVisualReview')){throw 'Vælg en stoppet Pinokio-opgave.'};$task.status='Queued';$task|Add-Member -NotePropertyName bridgeAction -NotePropertyValue resume-tool -Force;Write-StudioQueue -Path $q -Items $snapshot.Tasks -ExpectedRevision $snapshot.Revision;RefreshQ}})
$Queue.Add_SelectionChanged({if($Queue.SelectedItem){$Backend.SelectedItem=[string]$Queue.SelectedItem.backend;$Dependencies.Text=@($Queue.SelectedItem.dependencies)-join ', ';$ToolCapability.Text=[string]$Queue.SelectedItem.toolCapability;$ToolOperation.Text=[string]$Queue.SelectedItem.toolOperation;$ToolAppId.Text=[string]$Queue.SelectedItem.toolAppId;$ToolParameters.Text=if($Queue.SelectedItem.toolParameters){ConvertTo-Json -InputObject $Queue.SelectedItem.toolParameters -Depth 30}else{'{}'}}})
$NewBtn.Add_Click({$Backend.SelectedIndex=0;$Dependencies.Text='';$ToolCapability.Text='';$ToolOperation.Text='';$ToolAppId.Text='';$ToolParameters.Text='{}'})
