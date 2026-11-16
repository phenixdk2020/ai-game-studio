import base64
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('preference_selector',ROOT/'tools/agent_selector_v192.py')
selector=importlib.util.module_from_spec(spec);spec.loader.exec_module(selector)


class LocalPreferenceTests(unittest.TestCase):
    def candidates(self, local=True):
        return [dict(backend=name,available=(local or name!='claude-ollama')) for name in
                ['claude-ollama','ollama','copilot-local','copilot-github']]

    def select(self, task, local=True, ai=None):
        return selector.select(ROOT,task,availability=self.candidates(local),history={},ollama=({'model':'test'},''),ai=ai)

    def test_unreal_task_prefers_claude_despite_available_copilot(self):
        result=self.select(dict(title='Lav HOI 5',description='Lav spillet i Unreal fra MD-filerne',routingPreference='prefer-ollama'))
        self.assertEqual(result['backend'],'claude-ollama')
        self.assertIn('Claude Code',result['reason'])

    def test_missing_local_coder_does_not_silently_choose_copilot(self):
        result=self.select(dict(title='Implement Python code',routingPreference='prefer-ollama'),local=False)
        self.assertIsNone(result['backend'])
        self.assertEqual(result['mode'],'blocked')

    def test_text_preference_does_not_let_ai_switch_to_copilot(self):
        def wrong(*args):raise AssertionError('Explicit preference should not need another model decision')
        result=self.select(dict(title='Skriv en dialog',routingPreference='prefer-ollama'),ai=wrong)
        self.assertEqual(result['backend'],'ollama')

    def test_auto_still_prefers_copilot_for_code(self):
        result=self.select(dict(title='Implement Python code',routingPreference='auto'))
        self.assertEqual(result['backend'],'copilot-local')

    def test_local_preference_in_operator_description_is_respected(self):
        result=self.select(dict(title='Implement Unreal code',description='Foretræk Ollama til denne opgave.'))
        self.assertEqual(result['backend'],'claude-ollama')
        self.assertEqual(result['routingPreference'],'prefer-ollama')

    def test_explicit_strategy_wins_over_description(self):
        result=self.select(dict(title='Implement Unreal code',description='Foretræk Ollama',routingPreference='prefer-copilot'))
        self.assertEqual(result['backend'],'copilot-local')

    @unittest.skipUnless(shutil.which('powershell.exe'),'Windows WPF required')
    def test_wpf_strategy_changes_are_dirty_and_clear_old_backend(self):
        script="""
$ErrorActionPreference='Stop';Add-Type -AssemblyName PresentationFramework
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$Agent=New-Object Windows.Controls.TextBox
$panel=New-Object Windows.Controls.StackPanel;[void]$panel.Children.Add($Agent)
$Backend=New-Object Windows.Controls.ComboBox
@('auto','copilot-local','claude-ollama')|ForEach-Object{[void]$Backend.Items.Add($_)}
$Backend.SelectedItem='copilot-local'
$Queue=New-Object Windows.Controls.ListView;$NewBtn=New-Object Windows.Controls.Button
. 'MODULE'
Set-AgentPreference 'auto'
$Backend.SelectedItem='copilot-local'
$AgentPreference.SelectedItem=@($AgentPreference.Items|Where-Object Tag -eq 'prefer-ollama')[0]
if(-not $script:StudioPreferenceDirty){throw 'Unsaved preference not marked dirty'}
if($Backend.SelectedItem -ne 'auto'){throw 'Old explicit backend was retained'}
if((Get-StudioAgentPreference) -ne 'prefer-ollama'){throw 'Local strategy was not selected'}
$gui='GUI'
$ast=[Management.Automation.Language.Parser]::ParseFile($gui,[ref]$null,[ref]$null)
$refresh=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'RefreshQ'},$true)
Invoke-Expression $refresh.Extent.Text
function ReadQ {$script:reloads++;@()}
function Update-WorkerUiStatus {}
$script:reloads=0
RefreshQ
if($script:reloads -ne 0){throw 'Timer refresh would overwrite an unsaved strategy'}
$Backend.SelectedItem='copilot-local'
if((Get-StudioFormBackend) -ne 'auto'){throw 'Save would retain the old Copilot backend'}
Set-AgentPreference 'prefer-ollama'
if($script:StudioPreferenceDirty){throw 'Programmatic selection incorrectly marked dirty'}
if($Backend.SelectedItem -ne 'copilot-local'){throw 'Loading a task must not mutate its backend'}
if([string]$AgentPreference.SelectedItem.Content -notmatch 'Claude Code'){throw 'Local code capability is not visible'}
@{passed=$true}|ConvertTo-Json -Compress
""".replace('MODULE',str(ROOT/'adapters/Studio.Preference.ps1').replace("'","''")).replace('GUI',str(ROOT/'tools/project-manager-gui.ps1').replace("'","''"))
        encoded=base64.b64encode(script.encode('utf-16le')).decode()
        result=subprocess.run([shutil.which('powershell.exe'),'-NoProfile','-STA','-EncodedCommand',encoded],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        self.assertTrue(json.loads(result.stdout.decode('utf-8-sig'))['passed'])

    def test_refresh_patch_is_idempotent(self):
        spec=importlib.util.spec_from_file_location('preference_installer',ROOT/'tools/install-local-preference.py')
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        old="function RefreshQ {\n $editing=$false\n}\nWrite-StudioQueue -Path $q -Items $snapshot.Tasks -ExpectedRevision $snapshot.Revision\n    RefreshQ\nroutingPreference=$preference\nbackend=[string]$Backend.SelectedItem"
        patched=installer.patch_gui(old)
        self.assertIn('$editing=[bool]$script:StudioPreferenceDirty',patched)
        self.assertIn('backend=(Get-StudioFormBackend)',patched)
        self.assertEqual(installer.patch_gui(patched),patched)


if __name__=='__main__':unittest.main()
