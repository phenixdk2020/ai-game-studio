import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "adapters"))
import blender_job


class BlenderJobTests(unittest.TestCase):
    def test_validates_skeleton_job_defaults(self):
        job = blender_job.validate_job({"type": "skeleton_stub"})

        self.assertEqual(job["output_name"], "job")
        self.assertFalse(job["write_asset"])
        self.assertEqual(job["bones"], blender_job.DEFAULT_BONES)

    def test_rejects_unsupported_or_malformed_jobs(self):
        invalid_jobs = [
            [],
            {"type": "unknown"},
            {"type": "skeleton_stub", "output_name": "..\\outside"},
            {"type": "skeleton_stub", "write_asset": "yes"},
            {"type": "skeleton_stub", "bones": ["root", "root"]},
            {"type": "skeleton_stub", "bones": ["root\nprint('injected')"]},
        ]

        for job in invalid_jobs:
            with self.subTest(job=job), self.assertRaises(ValueError):
                blender_job.validate_job(job)

    def test_script_quotes_bone_names_as_python_literals(self):
        job = blender_job.validate_job({"type": "skeleton_stub", "bones": ["root", "it's safe"]})

        script = blender_job.build_script(job, Path("output.blend"))

        self.assertIn(json.dumps("it's safe"), script)
        self.assertIn("AI_STUDIO_JOB_OK", script)

    def test_asset_write_requires_approval_before_workspace_creation(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_path = root / "job.json"
            job_path.write_text(
                json.dumps({"type": "skeleton_stub", "write_asset": True}),
                encoding="utf-8",
            )
            config = {"paths": {"blender": "blender.exe", "workspace": str(root / "workspace")}}

            with self.assertRaisesRegex(SystemExit, "Approval required"):
                blender_job.run(job_path, config=config, process_runner=self.fail_if_called)

            self.assertFalse((root / "workspace").exists())

    def test_dry_run_uses_mocked_blender_and_writes_only_to_temp_workspace(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_path = root / "job.json"
            job_path.write_text(json.dumps({"type": "skeleton_stub"}), encoding="utf-8")
            config = {"paths": {"blender": "blender.exe", "workspace": str(root / "workspace")}}
            calls = []

            def fake_runner(args, **kwargs):
                calls.append((args, kwargs))
                return SimpleNamespace(stdout="mocked Blender output", stderr="", returncode=0)

            with self.assertRaises(SystemExit) as result:
                blender_job.run(job_path, config=config, process_runner=fake_runner)

            workspace = root / "workspace" / "blender"
            self.assertEqual(result.exception.code, 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0][0], "blender.exe")
            self.assertTrue((workspace / "_job.py").is_file())
            self.assertTrue((workspace / "job-evidence.txt").is_file())
            self.assertFalse((workspace / "job.blend").exists())

    @staticmethod
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Blender must not run when asset-write approval is missing")


if __name__ == "__main__":
    unittest.main()
