param([Parameter(Mandatory)][string]$Root)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName System.Windows.Forms
[xml]$layout=@'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" Title="Registrer spilprojekt" Width="620" Height="720" WindowStartupLocation="CenterScreen" Background="#0F172A" Foreground="White">
<ScrollViewer VerticalScrollBarVisibility="Auto"><StackPanel Margin="20">
<TextBlock Text="Vaelg en lokal projektmappe eller et GitHub-repository. Hvert spil har sine egne tests." TextWrapping="Wrap" Margin="0,0,0,15"/>
<TextBlock Text="Projektnavn"/><TextBox Name="ProjectName" Margin="0,4,0,12"/>
<TextBlock Text="Projekt-ID (fx rumspil)"/><TextBox Name="ProjectId" Margin="0,4,0,12"/>
<TextBlock Text="Placering"/><ComboBox Name="Kind" SelectedIndex="0" Margin="0,4,0,12"><ComboBoxItem Tag="local" Content="Lokal mappe"/><ComboBoxItem Tag="github" Content="GitHub"/></ComboBox>
<TextBlock Text="GitHub-repository (ejer/navn)"/><TextBox Name="Repository" Margin="0,4,0,12"/>
<TextBlock Text="Basisgren"/><TextBox Name="Branch" Text="main" Margin="0,4,0,12"/>
<TextBlock Text="Lokal projektmappe (paakraevet ved lokal placering)"/><DockPanel><Button Name="BrowseFolder" DockPanel.Dock="Right" Content="Gennemse..." Margin="4"/><TextBox Name="LocalPath" Margin="0,4,0,12"/></DockPanel>
<TextBlock Text="Testkommandoer (JSON med argumentlister)"/><TextBox Name="Tests" Height="80" AcceptsReturn="True" TextWrapping="Wrap" Margin="0,4,0,8"/>
<TextBlock Text="Python-eksempel: [[&quot;python&quot;,&quot;-m&quot;,&quot;unittest&quot;,&quot;discover&quot;]]. Lokale kodeaendringer laves i en separat kopi og overfoeres foerst, naar du godkender resultatet. GitHub-projekter afleverer en draft-PR." TextWrapping="Wrap" Margin="0,0,0,12"/>
<TextBlock Name="Feedback" TextWrapping="Wrap" Foreground="#FBBF24" Margin="0,0,0,12"/>
<Button Name="Save" Content="Registrer projekt" Padding="12,8"/>
</StackPanel></ScrollViewer></Window>
'@
$window=[Windows.Markup.XamlReader]::Load((New-Object System.Xml.XmlNodeReader $layout))
$kind=$window.FindName('Kind')
$kind.Add_SelectionChanged({$window.FindName('Repository').IsEnabled=([string]$kind.SelectedItem.Tag -eq 'github')})
$window.FindName('Repository').IsEnabled=$false
$window.FindName('BrowseFolder').Add_Click({
    $dialog=New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description='Vaelg projektmappen til spillet'
    try {if($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){$window.FindName('LocalPath').Text=$dialog.SelectedPath}}
    finally {$dialog.Dispose()}
})
$save=$window.FindName('Save')
$save.Add_Click({
    try {
        $python=Get-Command python.exe -ErrorAction Stop
        $testsFile=[IO.Path]::GetTempFileName()
        [IO.File]::WriteAllText($testsFile,$window.FindName('Tests').Text,(New-Object Text.UTF8Encoding($false)))
        $arguments=@((Join-Path $Root 'tools/studio_projects.py'),'--root',$Root,'add',
            $window.FindName('ProjectId').Text,'--name',$window.FindName('ProjectName').Text,
            '--kind',[string]$kind.SelectedItem.Tag,'--base-branch',$window.FindName('Branch').Text,
            '--validation-file',$testsFile)
        if([string]$kind.SelectedItem.Tag -eq 'github'){
            if(-not $window.FindName('Repository').Text){throw 'Angiv GitHub-repository som ejer/navn.'}
            $arguments+=@('--repository',$window.FindName('Repository').Text)
        }
        if($window.FindName('LocalPath').Text){$arguments+=@('--project-path',$window.FindName('LocalPath').Text)}
        $response=(@(& $python.Source @arguments) -join "`n") | ConvertFrom-Json
        if($LASTEXITCODE -ne 0 -or -not $response.ok){throw $response.error}
        $window.DialogResult=$true
    } catch { $window.FindName('Feedback').Text=$_.Exception.Message }
    finally { if($testsFile -and (Test-Path -LiteralPath $testsFile)){Remove-Item -LiteralPath $testsFile} }
})
$null=$window.ShowDialog()
