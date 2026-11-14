"""Check the GUI view without executing its queue/runtime initialization."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import xml.etree.ElementTree as ET

GUI = Path(__file__).resolve().parents[1] / "tools" / "project-manager-gui.ps1"


def view_source():
    source = GUI.read_text(encoding="utf-8-sig")
    match = re.search(r"\[xml\]\$x=@'\r?\n(.*?)\r?\n'@", source, re.S)
    if not match:
        raise AssertionError("GUI XAML literal missing")
    return match.group(1)


class GuiViewTests(unittest.TestCase):
    def test_xml_and_unique_controls(self):
        document = ET.fromstring(view_source())
        names = [node.attrib["Name"] for node in document.iter() if "Name" in node.attrib]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({"Queue", "WorkerBtn", "SaveBtn", "Feedback", "Title"}.issubset(names))

    @unittest.skipUnless(sys.platform == "win32" and shutil.which("powershell.exe"), "Windows WPF required")
    def test_hidden_wpf_view_loads(self):
        with TemporaryDirectory() as folder:
            xaml = Path(folder) / "view.xaml"
            xaml.write_text(view_source(), encoding="utf-8-sig")
            command = (
                "$ErrorActionPreference='Stop'; Add-Type -AssemblyName PresentationFramework; "
                "[xml]$view=Get-Content -LiteralPath '" + str(xaml).replace("'", "''") + "' -Raw; "
                "$reader=New-Object Xml.XmlNodeReader $view; "
                "$window=[Windows.Markup.XamlReader]::Load($reader); "
                "foreach($name in @('Queue','WorkerBtn','SaveBtn','SaveVersionBtn','Feedback','Title')) { "
                "if($null -eq $window.FindName($name)){throw ('Missing control: '+$name)} }; "
                "if($window.IsVisible){throw 'Unexpected visible window'}; "
                "foreach($name in @('Agent','NewBtn','SaveBtn','WorkerBtn','Queue','Title','Description','Attachments','ProjectPath')){Set-Variable $name $window.FindName($name)}; "
                ". '" + str(GUI.parents[1]/'adapters/Studio.Gui.ps1').replace("'", "''") + "'; "
                "foreach($backendName in @('auto','ollama','copilot-local','copilot-github','claude-ollama','asset3d','pinokio')) { "
                "if(-not $Backend.Items.Contains($backendName)){throw ('Missing backend: '+$backendName)} }; "
                "if($null -eq $Dependencies -or $null -eq $SpecialistsEnabled -or $null -eq $ToolCapability -or $ToolParameters.Text -ne '{}'){throw 'Unified controls missing'}; "
                "$SaveVersionBtn=$window.FindName('SaveVersionBtn'); "
                "function Save-StudioForm {param([switch]$AsNewVersion);$script:versionRequested=[bool]$AsNewVersion}; "
                "function Invoke-StudioUiAction([scriptblock]$Action){& $Action}; "
                "$source=Get-Content -LiteralPath '"+str(GUI).replace("'","''")+"' -Encoding UTF8; "
                "$binding=@($source|Where-Object { $_.StartsWith('$SaveVersionBtn.Add_Click') }); "
                "if($binding.Count -ne 1){throw 'New version handler missing'}; Invoke-Expression $binding[0]; "
                "$SaveVersionBtn.RaiseEvent((New-Object Windows.RoutedEventArgs ([Windows.Controls.Button]::ClickEvent))); "
                "if(-not $script:versionRequested){throw 'Button did not request a new version'}; $window.Close()"
            )
            result = subprocess.run(["powershell.exe", "-NoProfile", "-STA", "-Command", command],
                                    capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
