"""Danish text survives native Python/Windows PowerShell transport and legacy display."""
import base64
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('powershell.exe') or shutil.which('pwsh'),'PowerShell required')
class DanishTextTests(unittest.TestCase):
    def ps(self,script):
        host=shutil.which('powershell.exe') or shutil.which('pwsh')
        setup="$ErrorActionPreference='Stop';. '"+str(ROOT/'adapters/Studio.Text.ps1')+"';Initialize-StudioUtf8;"
        encoded=base64.b64encode((setup+script).encode('utf-16le')).decode()
        result=subprocess.run([host,'-NoProfile','-EncodedCommand',encoded],capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace'))
        return result.stdout.decode('utf-8-sig').strip()

    def test_exact_reported_oem_corruption_is_repaired(self):
        text='Copilot prioriteres til kode og planlægning; login verificeres ved udførsel.'
        broken=text.encode('cp1252').decode('cp850')
        encoded=base64.b64encode(broken.encode('utf-8')).decode()
        output=self.ps("$text=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+encoded+"'));Repair-StudioDisplayText $text")
        self.assertEqual(output,text)

    def test_utf8_mojibake_and_uppercase_words_are_repaired(self):
        text='Åbn værktøjer. VÆLG NÆSTE. Spørgsmål på kø.'
        broken=text.encode('utf-8').decode('cp1252')
        encoded=base64.b64encode(broken.encode('utf-8')).decode()
        output=self.ps("$text=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+encoded+"'));Repair-StudioDisplayText $text")
        self.assertEqual(output,text)

    def test_legitimate_units_and_correct_danish_are_unchanged(self):
        text='ÆØÅ æøå. Rotation 90°; længde 10 µm. Café, São Paulo.'
        encoded=base64.b64encode(text.encode('utf-8')).decode()
        output=self.ps("$text=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+encoded+"'));Repair-StudioDisplayText $text")
        self.assertEqual(output,text)

    def test_python_unicode_stdout_round_trips_through_windows_powershell(self):
        script="& python -c \"import json; print(json.dumps({'text':'\\u00c6\\u00d8\\u00c5 \\u00e6\\u00f8\\u00e5'},ensure_ascii=False))\" | ConvertFrom-Json | ForEach-Object {$_.text}"
        self.assertEqual(self.ps(script),'ÆØÅ æøå')

    def test_wpf_text_changed_repairs_view_without_editing_input_data(self):
        script="Add-Type -AssemblyName PresentationFramework;$box=New-Object Windows.Controls.TextBox;Enable-StudioDisplayTextRepair @($box);$value='planl'+[char]0xB5+'gning';$box.Text=$value;@{display=$box.Text;original=$value}|ConvertTo-Json -Compress"
        result=json.loads(self.ps(script))
        self.assertEqual(result['display'],'planlægning')
        self.assertEqual(result['original'],'planlµgning')

    def test_monitor_textbox_and_status_textblock_both_work(self):
        script="Add-Type -AssemblyName PresentationFramework;$box=New-Object Windows.Controls.TextBox;$status=New-Object Windows.Controls.TextBlock;Enable-StudioDisplayTextRepair @($box,$status);$broken='k'+[char]0xF8+'rer';$box.Text=$broken;$status.Text='planl'+[char]0xB5+'gning';@{box=$box.Text;status=$status.Text}|ConvertTo-Json -Compress"
        result=json.loads(self.ps(script))
        self.assertEqual(result['box'],'kører')
        self.assertEqual(result['status'],'planlægning')

    def test_optional_or_non_text_controls_do_not_break_startup(self):
        script="Add-Type -AssemblyName PresentationFramework;$button=New-Object Windows.Controls.Button;Enable-StudioDisplayTextRepair @($null,$button);'OK'"
        self.assertEqual(self.ps(script),'OK')


if __name__=='__main__':unittest.main()
