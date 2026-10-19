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
            {"type": []},
            {"type": "skeleton_stub", "unexpected": "value"},
            {"type": "skeleton_stub", "output_name": "..\\outside"},
            {"type": "skeleton_stub", "output_name": "C:\\outside"},
            {"type": "skeleton_stub", "write_asset": "yes"},
            {"type": "skeleton_stub", "bones": ["root", "root"]},
            {"type": "skeleton_stub", "bones": ["root\nprint('injected')"]},
            {"type": "skeleton_stub", "bones": [None]},
        ]

        for job in invalid_jobs:
            with self.subTest(job=job), self.assertRaises(ValueError):
                blender_job.validate_job(job)

    def test_script_quotes_bone_names_as_python_literals(self):
        job = blender_job.validate_job({"type": "skeleton_stub", "bones": ["root", "it's safe"]})

        script = blender_job.build_script(job, Path("output.blend"))

        self.assertIn(json.dumps("it's safe"), script)
        self.assertIn("AI_STUDIO_JOB_OK", script)
        compile(script, "<generated-blender-job>", "exec")

    def test_humanoid_job_has_required_bones_and_branched_hierarchy(self):
        job = blender_job.validate_job({"type": "humanoid_rig_v1"})
        names = {name for name, _, _, _ in blender_job.HUMANOID_BONES}
        parents = {name: parent for name, parent, _, _ in blender_job.HUMANOID_BONES}

        self.assertTrue(set(blender_job.REQUIRED_HUMANOID_BONES).issubset(names))
        self.assertEqual(tuple(job["bones"]), blender_job.REQUIRED_HUMANOID_BONES)
        self.assertEqual(parents["pelvis"], "root")
        self.assertEqual(parents["spine_01"], "pelvis")
        self.assertEqual(parents["spine_02"], "spine_01")
        self.assertEqual(parents["neck_01"], "spine_02")
        self.assertEqual(parents["head"], "neck_01")
        for side in ("l", "r"):
            self.assertEqual(parents[f"clavicle_{side}"], "spine_02")
            self.assertEqual(parents[f"upperarm_{side}"], f"clavicle_{side}")
            self.assertEqual(parents[f"lowerarm_{side}"], f"upperarm_{side}")
            self.assertEqual(parents[f"hand_{side}"], f"lowerarm_{side}")
            self.assertEqual(parents[f"thigh_{side}"], "pelvis")
            self.assertEqual(parents[f"calf_{side}"], f"thigh_{side}")
            self.assertEqual(parents[f"foot_{side}"], f"calf_{side}")

    def test_humanoid_bones_have_distinct_three_dimensional_positions(self):
        centers = []
        for _, _, head, tail in blender_job.HUMANOID_BONES:
            self.assertNotEqual(head, tail)
            centers.append(tuple((start + end) / 2 for start, end in zip(head, tail)))

        self.assertEqual(len(set(centers)), len(centers))
        self.assertEqual(
            {axis for point in centers for axis, value in enumerate(point) if value != 0},
            {0, 1, 2},
        )

    def test_humanoid_script_builds_parented_armature_without_user_code(self):
        job = blender_job.validate_job({"type": "humanoid_rig_v1"})

        script = blender_job.build_script(job, Path("humanoid.blend"))

        self.assertIn("bone.parent=bones[\"spine_02\"]", script)
        self.assertIn("bone.parent=bones[\"pelvis\"]", script)
        self.assertNotIn("save_as_mainfile", script)
        compile(script, "<generated-humanoid-job>", "exec")

    def test_humanoid_rejects_modified_or_duplicate_bone_names(self):
        with self.assertRaisesRegex(ValueError, "must not contain duplicate"):
            blender_job.validate_job(
                {"type": "humanoid_rig_v1", "bones": ["root", "root"]}
            )
        with self.assertRaisesRegex(ValueError, "must match"):
            blender_job.validate_job(
                {"type": "humanoid_rig_v1", "bones": ["root", "custom"]}
            )

    def test_output_path_cannot_escape_blender_workspace(self):
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            with self.assertRaisesRegex(ValueError, "inside the blender workspace"):
                blender_job._safe_output_path(workspace, "..\\outside")
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            blender_job._safe_output_path(ROOT, "inside-repo")

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

    def test_approved_humanoid_job_requests_blend_write_and_records_evidence(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_path = root / "humanoid.json"
            job_path.write_text(
                json.dumps(
                    {
                        "type": "humanoid_rig_v1",
                        "output_name": "SK_1864_Humanoid",
                        "write_asset": True,
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "paths": {
                    "blender": "blender.exe",
                    "workspace": str(root / "workspace"),
                }
            }
            calls = []

            def fake_runner(args, **kwargs):
                calls.append((args, kwargs))
                return SimpleNamespace(stdout="mocked", stderr="", returncode=0)

            with self.assertRaises(SystemExit) as result:
                blender_job.run(
                    job_path,
                    approve_write=True,
                    config=config,
                    process_runner=fake_runner,
                )

            blender_workspace = root / "workspace" / "blender"
            generated_script = (blender_workspace / "_job.py").read_text(encoding="utf-8")
            evidence = (blender_workspace / "humanoid-evidence.txt").read_text(
                encoding="utf-8"
            )
            self.assertEqual(result.exception.code, 0)
            self.assertIn("save_as_mainfile", generated_script)
            self.assertIn("SK_1864_Humanoid.blend", generated_script)
            self.assertIn("Exit code: 0", evidence)
            self.assertIn("AI_STUDIO_JOB_OK", generated_script)
            self.assertEqual(len(calls), 1)

    @staticmethod
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Blender must not run when asset-write approval is missing")


if __name__ == "__main__":
    unittest.main()
