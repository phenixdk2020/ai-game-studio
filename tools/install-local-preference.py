"""Preserve local strategy edits in older and current Project Manager GUIs."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil


def patch_gui(text):
    if '$editing=$false' in text:
        text=text.replace('$editing=$false','$editing=[bool]$script:StudioPreferenceDirty')
        text=text.replace('$ToolCapability,$ToolOperation,$ToolAppId,$ToolParameters))',
                          '$ToolCapability,$ToolOperation,$ToolAppId,$ToolParameters,$AgentPreference))')
    elif 'function RefreshQ{' in text and 'if($script:StudioPreferenceDirty){return}' not in text:
        text=text.replace('function RefreshQ{','function RefreshQ{if($script:StudioPreferenceDirty){return};',1)
    if '$script:StudioPreferenceDirty=$false\n    RefreshQ' not in text:
        anchor='Write-StudioQueue -Path $q -Items $snapshot.Tasks -ExpectedRevision $snapshot.Revision\n    RefreshQ'
        if anchor not in text:raise ValueError('Cannot locate form save completion')
        text=text.replace(anchor,anchor.replace('\n    RefreshQ','\n    $script:StudioPreferenceDirty=$false\n    RefreshQ'),1)
    # Current GUI has a shared form serializer; earlier ones use an inline list.
    if 'routingPreference=' not in text:
        text=text.replace("@('backend',[string]$Backend.SelectedItem)",
                          "@('backend',[string]$Backend.SelectedItem),@('routingPreference',(Get-StudioAgentPreference))")
    text=text.replace('backend=[string]$Backend.SelectedItem','backend=(Get-StudioFormBackend)')
    text=text.replace("@('backend',[string]$Backend.SelectedItem)","@('backend',(Get-StudioFormBackend))")
    if '$preference=Get-StudioAgentPreference' not in text and '$agentName=[string]$Agent.Text' in text:
        text=text.replace('$agentName=[string]$Agent.Text','$preference=Get-StudioAgentPreference\n    $agentName=[string]$Agent.Text',1)
    return text


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    target=parser.parse_args().root.resolve();source=Path(__file__).resolve().parents[1]
    gui=target/'tools/project-manager-gui.ps1';module=target/'adapters/Studio.Gui.ps1'
    text=patch_gui(gui.read_text(encoding='utf-8-sig'));host=module.read_text(encoding='utf-8-sig')
    host=host.replace('-Backend ollama -Role project_manager -Kind plan -Attachments',
                      '-Backend ollama -Role project_manager -Kind plan -RoutingPreference (Get-StudioAgentPreference) -Attachments')
    orchestrator=target/'adapters/Studio.Orchestrator.psm1'
    orchestration=orchestrator.read_text(encoding='utf-8-sig')
    if '[string]$RoutingPreference=' not in orchestration:
        orchestration=orchestration.replace("[ValidateSet('task','plan')][string]$Kind='task',",
            "[ValidateSet('task','plan')][string]$Kind='task',\n          [ValidateSet('auto','prefer-ollama','prefer-copilot','offline-only')][string]$RoutingPreference='auto',",1)
        orchestration=orchestration.replace('kind=$Kind; status=', 'kind=$Kind; routingPreference=$RoutingPreference; status=',1)
    if 'Studio.Preference.ps1' not in host:
        host+="\n. (Join-Path $PSScriptRoot 'Studio.Preference.ps1')\n"
    backup=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'AI-Game-Studio/backups'/('local-preference-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    for rel in ['tools/project-manager-gui.ps1','adapters/Studio.Gui.ps1','adapters/Studio.Preference.ps1','tools/agent_selector_v192.py','adapters/project_bridge.py','adapters/Studio.Orchestrator.psm1']:
        path=target/rel
        if path.exists():
            (backup/rel).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,backup/rel)
    for rel in ['adapters/Studio.Preference.ps1','tools/agent_selector_v192.py','adapters/project_bridge.py']:
        if (source/rel).resolve()!=(target/rel).resolve():shutil.copy2(source/rel,target/rel)
    gui.write_text(text,encoding='utf-8-sig');module.write_text(host,encoding='utf-8-sig')
    orchestrator.write_text(orchestration,encoding='utf-8-sig')
    print('Installed local preference fix; backup: '+str(backup))


if __name__=='__main__':main()
