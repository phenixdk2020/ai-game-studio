"""Add explicit task version saving to existing Project Manager versions."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil


def patch_gui(text):
    if 'Name="SaveVersionBtn"' not in text:
        anchor='<Button Name="SaveBtn" Content="Gem"/>'
        if text.count(anchor)!=1:raise ValueError('Cannot locate Save button')
        text=text.replace(anchor,anchor+'<Button Name="SaveVersionBtn" Content="Gem som ny version" ToolTip="Gemmer de aktuelle felter som en ny opgave med nyt ID. Den tidligere opgave bevares."/>')
    text=text.replace("'NewBtn SaveBtn PauseBtn", "'NewBtn SaveBtn SaveVersionBtn PauseBtn")
    if 'param([switch]$AsNewVersion)' not in text:
        text=text.replace('function Save-StudioForm {','function Save-StudioForm {\n    param([switch]$AsNewVersion)\n    if($AsNewVersion -and -not $Queue.SelectedItem){throw \'Vælg en opgave, der skal gemmes som ny version.\'}')
    if 'Studio.TaskEdits.psm1' not in text:
        anchor="Import-Module (Join-Path $PSScriptRoot '..\\adapters\\Studio.Orchestrator.psm1') -Force"
        if anchor not in text:raise ValueError('Cannot locate module imports')
        text=text.replace(anchor,anchor+"\nImport-Module (Join-Path $PSScriptRoot '..\\adapters\\Studio.TaskEdits.psm1') -Force")
    if '$editTarget=New-StudioTaskEditTarget' not in text:
        anchor='        Assert-EditableTaskCurrent $selected $task'
        if anchor not in text:raise ValueError('Cannot locate selected task save')
        text=text.replace(anchor,anchor+"\n        $editTarget=New-StudioTaskEditTarget -Root $Root -Task $task\n        if($editTarget.IsRevision){$task=$editTarget.Task;$snapshot.Tasks=@($snapshot.Tasks + $task)}")
        text=text.replace('    $selected = $Queue.SelectedItem','    $selected = $Queue.SelectedItem\n    $editTarget=$null',1)
        anchor='    Write-StudioQueue -Path $q -Items $snapshot.Tasks -ExpectedRevision $snapshot.Revision\n    RefreshQ'
        if anchor not in text:raise ValueError('Cannot locate queue save completion')
        text=text.replace(anchor,anchor+"\n    if($editTarget -and $editTarget.IsRevision){\n        $Queue.SelectedItem=@($Queue.ItemsSource|Where-Object id -eq $task.id)[0]\n        $Feedback.Text='Gemt som ny version: '+$task.id+\"`r`nTidligere opgave bevaret: \"+$editTarget.PreviousId\n    }",1)
    text=text.replace('New-StudioTaskEditTarget -Root $Root -Task $task\n', 'New-StudioTaskEditTarget -Root $Root -Task $task -ForceRevision:$AsNewVersion\n')
    if '$SaveVersionBtn.Add_Click' not in text:
        anchor='$SaveBtn.Add_Click({Invoke-StudioUiAction {Save-StudioForm}})'
        if anchor not in text:raise ValueError('Cannot locate Save event binding')
        text=text.replace(anchor,anchor+'\n$SaveVersionBtn.Add_Click({Invoke-StudioUiAction {Save-StudioForm -AsNewVersion}})')
    return text


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    root=args.root.resolve();source=Path(__file__).resolve().parents[1]
    gui=root/'tools/project-manager-gui.ps1'
    updated=patch_gui(gui.read_text(encoding='utf-8-sig'))
    backup=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'AI-Game-Studio/backups'/('task-versions-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    for rel in ['tools/project-manager-gui.ps1','adapters/Studio.TaskEdits.psm1']:
        path=root/rel
        if path.exists():
            (backup/rel).parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,backup/rel)
    module=source/'adapters/Studio.TaskEdits.psm1'
    target=root/'adapters/Studio.TaskEdits.psm1'
    if module.resolve()!=target.resolve():shutil.copy2(module,target)
    gui.write_text(updated,encoding='utf-8-sig')
    print('Installed Gem som ny version. Backup: '+str(backup))


if __name__=='__main__':main()
