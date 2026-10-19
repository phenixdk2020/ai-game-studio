import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "adapters"))

import runtime
import studio
import blender_job


class StudioConfigTests(unittest.TestCase):
    def test_studio_config_parses_and_has_expected_profiles(self):
        config = json.loads((ROOT / "config" / "studio.json").read_text(encoding="utf-8"))
        self.assertEqual(config["project"], "AI Game Studio 1864")
        self.assertEqual(set(config["llm"]["models"]), {"light", "heavy"})
        self.assertTrue(config["llm"]["base_url"].endswith("/v1"))

    def test_roles_route_to_light_and_heavy_models(self):
        with patch.object(runtime, "CFG_PATH", ROOT / "config" / "studio.json"):
            self.assertEqual(runtime.route("historical_research"), ("light", "qwen3.5-9b-gpu:latest"))
            self.assertEqual(runtime.route("technical_research"), ("heavy", "qwen3.6:35b-a3b-coding"))
            self.assertEqual(runtime.route("unknown_role")[0], "light")


class RuntimeQueueTests(unittest.TestCase):
    def test_dependency_readiness_requires_all_dependencies_done(self):
        rows = [
            {"id": "research", "status": "done", "dependencies": []},
            {"id": "technical", "status": "queued", "dependencies": []},
            {"id": "ready", "status": "queued", "dependencies": ["research"]},
            {"id": "waiting", "status": "queued", "dependencies": ["research", "technical"]},
            {"id": "unknown", "status": "queued", "dependencies": ["missing"]},
            {"id": "running", "status": "running", "dependencies": []},
        ]
        self.assertEqual([task["id"] for task in studio.ready_tasks(rows)], ["technical", "ready"])

    def _load_queue_text(self, text, expected):
        with tempfile.TemporaryDirectory() as temp:
            isolated_root = Path(temp)
            queue_path = isolated_root / "tasks" / "queue.json"
            queue_path.parent.mkdir()
            queue_path.write_text(text, encoding="utf-8")
            with (
                patch.object(studio, "ROOT", isolated_root),
                patch.object(studio, "Q", queue_path),
                patch.object(studio, "R", isolated_root / "results"),
            ):
                rows = studio.load()
            self.assertEqual(rows, expected)
            self.assertTrue((isolated_root / "results").is_dir())
            self.assertTrue((isolated_root / "logs").is_dir())
            self.assertTrue((isolated_root / "state").is_dir())

    def test_loads_utf8_queue(self):
        expected = [{"id": "Éclairage", "name": "café"}]
        self._load_queue_text(json.dumps(expected, ensure_ascii=False), expected)

    def test_loads_utf8_bom_queue(self):
        expected = [{"id": "Éclairage", "name": "café"}]
        self._load_queue_text('\ufeff' + json.dumps(expected, ensure_ascii=False), expected)

    def test_protected_runtime_directories_are_not_tracked(self):
        result = subprocess.run(
            ["git", "ls-files", "--", "tasks/", "results/", "logs/", "state/"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), "")


class BlenderJobTests(unittest.TestCase):
    def test_validates_supported_blender_job(self):
        self.assertIsNone(blender_job.validate_job({
            "type": "skeleton_stub",
            "write_asset": True,
            "output_name": "SK_1864_Human",
            "bones": ["root", "pelvis"],
        }))

    def test_rejects_unsafe_or_malformed_jobs(self):
        invalid_jobs = [
            [],
            {},
            {"type": "unknown"},
            {"type": "skeleton_stub", "write_asset": "true"},
            {"type": "skeleton_stub", "output_name": "../outside"},
            {"type": "skeleton_stub", "bones": []},
            {"type": "skeleton_stub", "bones": ["root", "root"]},
        ]
        for job in invalid_jobs:
            with self.subTest(job=job), self.assertRaises(ValueError):
                blender_job.validate_job(job)

    def test_denied_asset_write_creates_no_workspace_files_or_runs_blender(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job_path = root / "job.json"
            job_path.write_text(
                json.dumps({"type": "skeleton_stub", "write_asset": True}),
                encoding="utf-8",
            )
            workspace = root / "workspace"
            config = {"paths": {"blender": str(root / "blender.exe"), "workspace": str(workspace)}}
            with patch.object(blender_job, "CFG", config), patch.object(
                blender_job.subprocess, "run", side_effect=AssertionError("Blender must not run")
            ):
                with self.assertRaisesRegex(SystemExit, "Approval required"):
                    blender_job.run(job_path)
            self.assertFalse(workspace.exists())

    def test_approved_asset_write_invokes_only_the_mocked_blender_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job_path = root / "job.json"
            job_path.write_text(
                json.dumps({"type": "skeleton_stub", "write_asset": True}),
                encoding="utf-8",
            )
            workspace = root / "workspace"
            config = {"paths": {"blender": str(root / "blender.exe"), "workspace": str(workspace)}}
            completed = subprocess.CompletedProcess([], 0, stdout="mocked", stderr="")
            with patch.object(blender_job, "CFG", config), patch.object(
                blender_job.subprocess, "run", return_value=completed
            ) as mocked_run:
                with self.assertRaises(SystemExit) as result:
                    blender_job.run(job_path, approve_write=True)
            self.assertEqual(result.exception.code, 0)
            mocked_run.assert_called_once()
            generated_script = Path(mocked_run.call_args.args[0][-1]).read_text(encoding="utf-8")
            self.assertIn("save_as_mainfile", generated_script)


if __name__ == "__main__":
    unittest.main()
