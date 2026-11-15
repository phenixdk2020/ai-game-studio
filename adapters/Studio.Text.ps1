function Initialize-StudioUtf8 {
    $utf8=New-Object System.Text.UTF8Encoding($false)
    $global:OutputEncoding=$utf8
    [Console]::OutputEncoding=$utf8
    $env:PYTHONIOENCODING='utf-8'
    $env:PYTHONUTF8='1'
}

function Repair-StudioDisplayText {
    param([AllowNull()][string]$Text)
    if(-not $Text){return [string]$Text}
    if(-not $script:StudioTextRepairPattern){
        $script:StudioTextRepairs=[Collections.Generic.Dictionary[string,string]]::new([StringComparer]::Ordinal)
        $ansi=[Text.Encoding]::GetEncoding(1252)
        $oem=[Text.Encoding]::GetEncoding(850)
        $utf8=New-Object Text.UTF8Encoding($false)
        # Known UI words only: preserve legitimate units such as 90 degrees or micrometres.
        $words=@('planlægning','udførsel','værktøj','værktøjer','vælg','spørgsmål',
            'afhængigheder','afhængighed','kører','køre','kør','kø','åbn','ændringer',
            'ændring','tilføj','prøv','gennemgå','færdig','på','så','når','før',
            'størrelse','næste','bekræft','tilgængelig','tilgængelige','tilføjet',
            'opgøre','udført','kræver','læs','læst','ønsket','ønsker','nødvendigt')
        foreach($word in $words){
            $title=$word.Substring(0,1).ToUpperInvariant()+$word.Substring(1)
            foreach($correct in @($word,$title,$word.ToUpperInvariant())){
                foreach($broken in @($oem.GetString($ansi.GetBytes($correct)),$ansi.GetString($utf8.GetBytes($correct)))){
                    if($broken -cne $correct){$script:StudioTextRepairs[$broken]=$correct}
                }
            }
        }
        $parts=@($script:StudioTextRepairs.Keys | Sort-Object Length -Descending | ForEach-Object {[regex]::Escape($_)})
        $script:StudioTextRepairPattern=[regex]::new(('(?<![\p{L}\p{N}_])(?:'+($parts -join '|')+')(?![\p{L}\p{N}_])'))
    }
    return $script:StudioTextRepairPattern.Replace($Text,[Text.RegularExpressions.MatchEvaluator]{param($match) $script:StudioTextRepairs[$match.Value]})
}

function Enable-StudioDisplayTextRepair {
    param([object[]]$Controls)
    foreach($control in $Controls){
        if($null -eq $control){continue}
        $repair={
            param($sender,$eventArgs)
            $corrected=Repair-StudioDisplayText -Text $sender.Text
            if($corrected -cne $sender.Text){$sender.Text=$corrected}
        }
        if($control.PSObject.Methods['Add_TextChanged']){
            $control.Add_TextChanged($repair)
        }elseif($control -is [Windows.Controls.TextBlock]){
            # TextBlock has a Text dependency property, not a TextChanged event.
            $descriptor=[ComponentModel.DependencyPropertyDescriptor]::FromProperty(
                [Windows.Controls.TextBlock]::TextProperty,$control.GetType())
            $descriptor.AddValueChanged($control,[EventHandler]$repair)
        }
    }
}
