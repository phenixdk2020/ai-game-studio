import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "adapters"))
import asset_pipeline as pipeline
import asset_qa


def glb(extra=None):
    body = json.dumps({"asset": {"version": "2.0"}, **(extra or {})}).encode()
    body += b" " * (-len(body) % 4)
    return struct.pack("<4sIIII", b"glTF", 2, 20 + len(body), len(body), 0x4E4F534A) + body


def metrics(**updates):
    return {"mesh_count": 1, "vertices": 8, "triangles": 12,
            "non_manifold_edges": 0, "dimensions_m": [1.0, 0.1, 0.2],
            "has_uv": True, "has_materials": True, "missing_textures": 0, **updates}


class AssetPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task_root = self.root / "TASK-1"
        self.task_root.mkdir()
        self.source = self.task_root / "input.glb"
        self.source.write_bytes(glb())
        self.exe = self.root / "tool with spaces.exe"
        self.exe.write_bytes(b"fake executable")
        self.config = {"jobs_root": str(self.root), "minimum_glb_bytes": 20,
                       "blender_executable": str(self.exe), "unreal_executable": str(self.exe),
                       "allowed_project_roots": [str(self.root / "project")]}
        self.job = {"schemaVersion": 1, "taskId": "TASK-1", "asset_name": "SM_Sword", "input": "input.glb"}
        self.calls = []

    def fake_blender(self, args, **kwargs):
        self.calls.append((args, kwargs))
        job = pipeline.read_json(args[-1])
        out = Path(job["output_dir"])
        for name in ("asset.blend", "asset.fbx"):
            (out / name).write_bytes(b"mock artifact")
        (out / "asset-clean.glb").write_bytes(glb())
        for name in ("front", "side", "perspective"):
            (out / f"preview-{name}.png").write_bytes(b"\x89PNG\r\n\x1a\nmock")
        pipeline.write_json(out / "metrics.json", metrics())
        return SimpleNamespace(returncode=0)

    def run_blender(self, **kwargs):
        return pipeline.run(self.job, self.config, approve_blender=True, runner=self.fake_blender, **kwargs)

    def project(self):
        directory = self.root / "project"
        directory.mkdir(exist_ok=True)
        path = directory / "Test.uproject"
        pipeline.write_json(path, {"Plugins": [{"Name": name, "Enabled": True}
                             for name in ("PythonScriptPlugin", "EditorScriptingUtilities")]})
        self.job["project"] = str(path)
        return path

    def test_approval_before_output_or_execution(self):
        with self.assertRaises(PermissionError):
            pipeline.run(self.job, self.config, runner=lambda *a, **k: self.fail("must not launch"))
        self.assertEqual(list(self.task_root.iterdir()), [self.source])

    def test_unreal_has_separate_approval(self):
        with self.assertRaisesRegex(PermissionError, "write_unreal_asset"):
            pipeline.run(self.job, self.config, approve_blender=True, target="unreal")
        self.assertFalse((self.task_root / "outputs").exists())

    def test_success_manifest_and_resume(self):
        first = self.run_blender()
        self.assertEqual(first["status"], "ReadyForUnreal")
        self.assertEqual(first["qaStatus"], "pass")
        self.assertEqual(len(first["artifacts"]), 9)
        self.assertEqual(self.calls[0][0][0], str(self.exe.resolve()))
        self.assertIn("--python-exit-code", self.calls[0][0])
        self.assertNotIn("shell", self.calls[0][1])
        again = self.run_blender(resume=True)
        self.assertEqual(first["outputDirectory"], again["outputDirectory"])
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.task_root / ".asset-pipeline.lock").exists())

    def test_retry_does_not_overwrite_previous_output(self):
        first = self.run_blender()
        again = self.run_blender()
        self.assertNotEqual(first["outputDirectory"], again["outputDirectory"])
        self.assertTrue((Path(first["outputDirectory"]) / "asset.blend").is_file())

    def test_changed_input_invalidates_resume(self):
        first = self.run_blender()
        self.source.write_bytes(glb({"extras": {"new": True}}))
        second = self.run_blender(resume=True)
        self.assertNotEqual(first["outputDirectory"], second["outputDirectory"])

    def test_changed_artifact_blocks_resume(self):
        result = self.run_blender()
        (Path(result["outputDirectory"]) / "asset.fbx").write_bytes(b"tampered")
        with self.assertRaisesRegex(RuntimeError, "checksum"):
            self.run_blender(resume=True)
        self.assertEqual(len(self.calls), 1)

    def test_concurrent_task_is_rejected(self):
        with pipeline.task_lock(self.task_root):
            with self.assertRaisesRegex(RuntimeError, "locked"):
                self.run_blender()
        self.assertFalse(self.calls)

    def test_subprocess_failure_is_recorded(self):
        def failed(*args, **kwargs):
            return SimpleNamespace(returncode=7)
        with self.assertRaisesRegex(RuntimeError, "code 7"):
            pipeline.run(self.job, self.config, approve_blender=True, runner=failed)
        manifest = pipeline.read_json(self.task_root / "asset-manifest.json")
        self.assertEqual(manifest["status"], "Failed")
        self.assertIn("code 7", manifest["error"])
        self.assertFalse(manifest["blenderComplete"])

    def test_timeout_is_recorded_and_lock_released(self):
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 1)
        with self.assertRaises(subprocess.TimeoutExpired):
            pipeline.run(self.job, self.config, approve_blender=True, runner=timeout)
        self.assertEqual(pipeline.read_json(self.task_root / "asset-manifest.json")["status"], "Failed")
        self.assertFalse((self.task_root / ".asset-pipeline.lock").exists())

    def test_success_exit_without_outputs_is_failure(self):
        with self.assertRaisesRegex(RuntimeError, "Missing output"):
            pipeline.run(self.job, self.config, approve_blender=True,
                         runner=lambda *a, **k: SimpleNamespace(returncode=0))

    def test_qa_failure_blocks_import(self):
        self.project()
        def bad_mesh(args, **kwargs):
            result = self.fake_blender(args, **kwargs)
            out = Path(pipeline.read_json(args[-1])["output_dir"])
            pipeline.write_json(out / "metrics.json", metrics(has_uv=False))
            return result
        with self.assertRaisesRegex(RuntimeError, "QA failed"):
            pipeline.run(self.job, self.config, approve_blender=True, approve_unreal=True,
                         target="unreal", runner=bad_mesh)
        self.assertEqual(len(self.calls), 1)
        manifest = pipeline.read_json(self.task_root / "asset-manifest.json")
        self.assertEqual(manifest["qaStatus"], "fail")
        self.assertTrue((Path(manifest["outputDirectory"]) / "qa.md").is_file())

    def test_unreal_resume_import_and_status(self):
        self.project()
        self.run_blender()
        def fake_unreal(args, **kwargs):
            self.calls.append((args, kwargs))
            job = pipeline.read_json(kwargs["env"]["AI_STUDIO_UNREAL_JOB"])
            pipeline.write_json(job["report"], {"status": "imported", "staticMeshPaths": [job["destination"] + "/SM_Sword"]})
            return SimpleNamespace(returncode=0)
        result = pipeline.run(self.job, self.config, approve_blender=True, approve_unreal=True,
                              target="unreal", resume=True, runner=fake_unreal)
        self.assertEqual(result["status"], "ReadyForUnrealQA")
        self.assertNotEqual(result["status"], "Completed")
        self.assertEqual(len(self.calls), 2)
        self.assertIn("-run=pythonscript", self.calls[-1][0])
        pipeline.run(self.job, self.config, approve_blender=True, approve_unreal=True,
                     target="unreal", resume=True, runner=lambda *a, **k: self.fail("completed stages rerun"))

    def test_paths_and_bad_options(self):
        cases = [{"taskId": "../escape"}, {"asset_name": "bad/name"}, {"input": "../outside.glb"},
                 {"pivot": "unknown"}, {"target_size_m": float("nan")}, {"target_size_m": True},
                 {"rotation_x_degrees": float("inf")}, {"schemaVersion": 2}, {"schemaVersion": True},
                 {"input": 42}, {"project": []}, {"executable": "unexpected.exe"}, {"taskId": "CON"}]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValueError):
                pipeline.validate_job({**self.job, **change}, self.config)

    def test_invalid_configuration_rejected_before_execution(self):
        for change in ({"qa": {"require_uv": "yes"}}, {"blender_timeout": -1}, {"jobs_root": ""},
                       {"minimum_glb_bytes": True}, {"schemaVersion": 99}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                pipeline.run(self.job, {**self.config, **change}, approve_blender=True,
                             runner=lambda *a, **k: self.fail("Invalid config launched a tool"))

    def test_symlink_escape(self):
        outside = self.root / "outside.glb"
        outside.write_bytes(glb())
        link = self.task_root / "linked.glb"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "outside"):
            pipeline.validate_job({**self.job, "input": str(link)}, self.config)

    def test_external_glb_resources_rejected(self):
        for uri in ("../../secret.png", "file:///secret.bin", "https://example.org/image.png"):
            self.source.write_bytes(glb({"images": [{"uri": uri}]}))
            with self.subTest(uri=uri), self.assertRaisesRegex(ValueError, "embed"):
                pipeline.validate_glb(self.source)

    def test_project_discovery_and_plugins(self):
        project = self.project()
        self.assertEqual(pipeline.find_project(project.parent, self.config["allowed_project_roots"]), project)
        pipeline.write_json(project.parent / "Other.uproject", {})
        with self.assertRaisesRegex(ValueError, "unambiguous"):
            pipeline.find_project(project.parent, self.config["allowed_project_roots"])
        with self.assertRaisesRegex(ValueError, "outside"):
            pipeline.find_project(project, [])
        pipeline.write_json(project, {})
        with self.assertRaisesRegex(ValueError, "PythonScriptPlugin"):
            pipeline.find_project(project, self.config["allowed_project_roots"])

    def test_plan_has_no_writes(self):
        job_path, config_path = self.root / "job.json", self.root / "config.json"
        pipeline.write_json(job_path, self.job)
        pipeline.write_json(config_path, self.config)
        result = subprocess.run([sys.executable, str(ROOT / "adapters" / "asset_pipeline.py"),
                                 str(job_path), "--config", str(config_path), "--plan"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["taskId"], "TASK-1")
        self.assertEqual(list(self.task_root.iterdir()), [self.source])


class QATests(unittest.TestCase):
    def test_status_and_threshold_boundaries(self):
        self.assertEqual(asset_qa.evaluate(metrics())["status"], "pass")
        self.assertEqual(asset_qa.evaluate(metrics(triangles=60000))["status"], "pass")
        self.assertEqual(asset_qa.evaluate(metrics(triangles=60001))["status"], "warning")
        self.assertEqual(asset_qa.evaluate(metrics(triangles=150001))["status"], "fail")
        self.assertEqual(asset_qa.evaluate(metrics(non_manifold_edges=1))["status"], "warning")

    def test_hard_failures(self):
        for updates in ({"mesh_count": 0}, {"triangles": 0}, {"has_uv": False},
                        {"has_materials": False}, {"missing_textures": 1}, {"dimensions_m": [0, 0, 0]}):
            with self.subTest(updates=updates):
                self.assertEqual(asset_qa.evaluate(metrics(**updates))["status"], "fail")

    def test_invalid_metrics_and_profile(self):
        for updates in ({"triangles": -1}, {"vertices": True}, {"has_uv": "yes"},
                        {"dimensions_m": [float("nan"), 1, 1]}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                asset_qa.evaluate(metrics(**updates))
        with self.assertRaises(ValueError):
            asset_qa.evaluate(metrics(), {"triangle_limit": 1})


if __name__ == "__main__":
    unittest.main()
