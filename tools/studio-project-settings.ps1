param([Parameter(Mandatory)][string]$Root)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationFramework
[xml]$layout=@'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" Title="Registrer spilprojekt" Width="620" Height="650" WindowStartupLocation="CenterScreen" Background="#0F172A" Foreground="White">
<ScrollViewer VerticalScrollBarVisibility="Auto"><StackPanel Margin="20">
<TextBlock Text="Hvert spil har sit eget repository og sine egne tests." TextWrapping="Wrap" Margin="0,0,0,15"/>
<TextBlock Text="Projektnavn"/><TextBox Name="ProjectName" Margin="0,4,0,12"/>
<TextBlock Text="Projekt-ID (fx rumspil)"/><TextBox Name="ProjectId" Margin="0,4,0,12"/>
<TextBlock Text="GitHub-repository (ejer/navn)"/><TextBox Name="Repository" Margin="0,4,0,12"/>
<TextBlock Text="Basisgren"/><TextBox Name="Branch" Text="main" Margin="0,4,0,12"/>
<TextBlock Text="Lokal projektmappe eller .uproject (valgfrit)"/><TextBox Name="LocalPath" Margin="0,4,0,12"/>
<TextBlock Text="Testkommandoer (JSON med argumentlister)"/><TextBox Name="Tests" Height="80" AcceptsReturn="True" TextWrapping="Wrap" Margin="0,4,0,8"/>
<TextBlock Text="Python-eksempel: [[&quot;python&quot;,&quot;-m&quot;,&quot;unittest&quot;,&quot;discover&quot;]]. Brug tests, der passer til netop dette projekt. Repositoryet skal allerede findes paa GitHub." TextWrapping="Wrap" Margin="0,0,0,12"/>
<TextBlock Name="Feedback" TextWrapping="Wrap" Foreground="#FBBF24" Margin="0,0,0,12"/>
<Button Name="Save" Content="Registrer projekt" Padding="12,8"/>
</StackPanel></ScrollViewer></Window>
'@
$window=[Windows.Markup.XamlReader]::Load((New-Object System.Xml.XmlNodeReader $layout))
$save=$window.FindName('Save')
$save.Add_Click({
    try {
        $python=Get-Command python.exe -ErrorAction Stop
        $testsFile=[IO.Path]::GetTempFileName()
        [IO.File]::WriteAllText($testsFile,$window.FindName('Tests').Text,(New-Object Text.UTF8Encoding($false)))
        $arguments=@((Join-Path $Root 'tools/studio_projects.py'),'--root',$Root,'add',
            $window.FindName('ProjectId').Text,'--name',$window.FindName('ProjectName').Text,
            '--repository',$window.FindName('Repository').Text,'--base-branch',$window.FindName('Branch').Text,
            '--validation-file',$testsFile)
        if($window.FindName('LocalPath').Text){$arguments+=@('--project-path',$window.FindName('LocalPath').Text)}
        $response=(@(& $python.Source @arguments) -join "`n") | ConvertFrom-Json
        if($LASTEXITCODE -ne 0 -or -not $response.ok){throw $response.error}
        $window.DialogResult=$true
    } catch { $window.FindName('Feedback').Text=$_.Exception.Message }
    finally { if($testsFile -and (Test-Path -LiteralPath $testsFile)){Remove-Item -LiteralPath $testsFile} }
})
$null=$window.ShowDialog()
