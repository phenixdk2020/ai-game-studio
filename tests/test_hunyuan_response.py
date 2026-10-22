import json
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'adapters' / 'Hunyuan.Response.psm1'

@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 required')
class HunyuanResponseTests(unittest.TestCase):
    def validate(self, data, content_type='model/gltf-binary'):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'response.glb'
            path.write_bytes(data)
            command = "$ErrorActionPreference='Stop'; Import-Module '" + str(MODULE).replace("'", "''") + "'; Test-HunyuanGlb -Path '" + str(path).replace("'", "''") + "' -ContentType '" + content_type + "' -MinimumBytes 20"
            return subprocess.run(['pwsh', '-NoProfile', '-Command', command], capture_output=True).returncode

    def glb(self):
        body = json.dumps({'asset': {'version': '2.0'}}).encode()
        body += b' ' * (-len(body) % 4)
        return struct.pack('<4sIIII', b'glTF', 2, 20 + len(body), len(body), 0x4E4F534A) + body

    def test_valid_glb(self):
        self.assertEqual(self.validate(self.glb()), 0)
        self.assertEqual(self.validate(self.glb(), 'application/octet-stream'), 0)

    def test_error_responses_and_corruption(self):
        valid = self.glb()
        cases = [b'{"error":"generation failed"}' * 100,
                 b'HTML' + valid[4:], valid[:-1],
                 valid[:4] + struct.pack('<I', 1) + valid[8:],
                 valid[:12] + struct.pack('<I', 999999) + valid[16:],
                 valid + b'x', valid[:16] + b'BIN\x00' + valid[20:]]
        for data in cases:
            with self.subTest(data=data[:20]):
                self.assertNotEqual(self.validate(data), 0)
        self.assertNotEqual(self.validate(valid, 'application/json'), 0)
