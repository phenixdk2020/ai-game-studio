# Task strategy is an unsaved form edit, not a value to reset on each timer refresh.
if(-not $AgentPreference){
    $AgentPreference=New-Object Windows.Controls.ComboBox
    foreach($pair in @(@('auto','Auto'),@('prefer-copilot','Foretræk Copilot'),@('prefer-ollama','Foretræk Ollama / Claude Code'),@('offline-only','Kun lokale/offline værktøjer'))){
        $item=New-Object Windows.Controls.ComboBoxItem;$item.Tag=$pair[0];$item.Content=$pair[1]
        [void]$AgentPreference.Items.Add($item)
    }
    $AgentPreference.SelectedIndex=0
    $hostPanel=$Agent.Parent;$position=$hostPanel.Children.IndexOf($Agent)
    $label=New-Object Windows.Controls.TextBlock;$label.Text='AI-STRATEGI';$label.Foreground='White'
    $hostPanel.Children.Insert($position,$label);$hostPanel.Children.Insert($position+1,$AgentPreference)
    $Queue.Add_SelectionChanged({if($Queue.SelectedItem){Set-AgentPreference ([string]$Queue.SelectedItem.routingPreference)}})
    $NewBtn.Add_Click({Set-AgentPreference 'auto'})
}
foreach($item in $AgentPreference.Items){
    if([string]$item.Tag -eq 'prefer-ollama'){$item.Content='Foretræk Ollama / Claude Code (lokal kode, planer og tekst)'}
}
$AgentPreference.ToolTip='Kode: Claude Code via lokal Ollama. Planer/tekst: Ollama. Hvis den lokale agent mangler, skiftes der ikke automatisk til Copilot.'
$Backend.ToolTip='Auto følger AI-strategien. claude-ollama redigerer kode med lokal Ollama; ollama alene leverer planer og tekst.'
$script:StudioPreferenceDirty=$false
$script:StudioLoadingPreference=$false
function Set-AgentPreference($value){
    $script:StudioLoadingPreference=$true
    try{
        $found=$false
        foreach($item in $AgentPreference.Items){
            if([string]$item.Tag -eq [string]$value){$AgentPreference.SelectedItem=$item;$found=$true;break}
        }
        if(-not $found){$AgentPreference.SelectedIndex=0}
    }finally{$script:StudioLoadingPreference=$false}
    $script:StudioPreferenceDirty=$false
}
function Get-StudioAgentPreference {
    $value='auto'
    if($AgentPreference.SelectedItem -and $AgentPreference.SelectedItem.Tag){$value=[string]$AgentPreference.SelectedItem.Tag}
    if($value -eq 'auto' -and ("$($Title.Text) $($Description.Text)" -match '(?i)\b(foretræk|foretraek|brug)\s+(lokal\s+)?ollama\b')){return 'prefer-ollama'}
    return $value
}
function Get-StudioFormBackend {
    $value=[string]$Backend.SelectedItem
    if((Get-StudioAgentPreference) -eq 'prefer-ollama' -and $value -in @('copilot-local','copilot-github','ollama')){return 'auto'}
    return $value
}
$AgentPreference.Add_SelectionChanged({
    if(-not $script:StudioLoadingPreference){
        $script:StudioPreferenceDirty=$true
        # A new strategy must not inherit an explicit backend from the old task.
        $Backend.SelectedItem='auto'
    }
})
