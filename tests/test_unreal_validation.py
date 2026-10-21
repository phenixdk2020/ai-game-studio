from dataclasses import dataclass
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "adapters"))
import unreal_validation_runtime as runtime


def metrics(**updates):
    return {"lods": 1, "vertices": 8, "triangles": 12, "uv_channels": 1,
            "material_slots": 1, "missing_materials": 0, "simple_collisions": 1,
            "convex_collisions": 0, "dimensions_cm": [100.0, 10.0, 20.0], **updates}


@dataclass
class Vector:
    x: float = 0
    y: float = 0
    z: float = 0

    def __add__(self, other):
        return Vector(self.x + other.x, self.y + other.y, self.z + other.z)


class Mesh:
    def get_bounds(self):
        return SimpleNamespace(box_extent=Vector(50, 5, 10))

    def get_editor_property(self, name):
        return [SimpleNamespace(get_editor_property=lambda key: object())]

    def get_num_vertices(self, index):
        return 8

    def get_num_triangles(self, index):
        return 12


class Actor:
    def set_actor_label(self, label):
        self.label = label

    def get_component_by_class(self, kind):
        return SimpleNamespace(set_mobility=lambda *a: None,
                               set_editor_property=lambda *a: None, capture_scene=lambda: None)

    def get_actor_bounds(self, only_colliding):
        return Vector(), Vector(50, 5, 10)


class UnrealValidationTests(unittest.TestCase):
    def fake(self, *, collision=1, lods=1, uniform=False, save=True, spawn=True, exported=True):
        calls = []
        mesh = Mesh()
        static = SimpleNamespace(get_lod_count=lambda m: lods,
            get_num_uv_channels=lambda *a: 1, get_simple_collision_count=lambda m: collision,
            get_convex_collision_count=lambda m: 0)
        def new_level(path):
            calls.append("new_level")
            return True
        levels = SimpleNamespace(new_level=new_level, save_current_level=lambda: save)
        def actor(*args):
            calls.append("spawn")
            return Actor() if spawn else None
        actors = SimpleNamespace(spawn_actor_from_object=actor, spawn_actor_from_class=actor,
                                 destroy_actor=lambda obj: calls.append("destroy_capture"))
        world = SimpleNamespace(get_editor_world=lambda: object())
        components = {"static": static, "levels": levels, "actors": actors, "world": world}
        def export(world, target, folder, name):
            if exported:
                (Path(folder) / name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"mock image data" * 3)
        pixel = lambda n: SimpleNamespace(r=n, g=n, b=n)
        fake = SimpleNamespace(StaticMesh=Mesh, StaticMeshEditorSubsystem="static",
            LevelEditorSubsystem="levels", EditorActorSubsystem="actors", UnrealEditorSubsystem="world",
            get_editor_subsystem=lambda kind: components[kind], Vector=Vector, Rotator=lambda *a: object(),
            DirectionalLight=object(), DirectionalLightComponent=object(), SceneCapture2D=object(),
            SceneCaptureComponent2D=object(), ComponentMobility=SimpleNamespace(MOVABLE="movable"),
            TextureRenderTargetFormat=SimpleNamespace(RTF_RGBA8="rgba8"),
            SceneCaptureSource=SimpleNamespace(SCS_FINAL_COLOR_LDR="ldr"),
            MathLibrary=SimpleNamespace(find_look_at_rotation=lambda *a: object()),
            EditorAssetLibrary=SimpleNamespace(load_asset=lambda path: mesh, does_asset_exist=lambda path: False),
            RenderingLibrary=SimpleNamespace(create_render_target2d=lambda *a, **k: object(),
                read_render_target=lambda *a: [pixel(0), pixel(0 if uniform else 255)],
                export_render_target=export, release_render_target2d=lambda *a: calls.append("release_target")))
        return fake, calls

    def job(self, folder, capture=False):
        destination = "/Game/AIStudio/TASK_1/Import_abc"
        return {"destination": destination, "level_path": destination + "/QA_123",
                "mesh_paths": [destination + "/SM_Sword.SM_Sword"], "capture": capture,
                "screenshot": str(Path(folder) / "preview.png"), "report": str(Path(folder) / "qa.json")}

    def test_qa_and_saved_scene(self):
        fake, calls = self.fake()
        with TemporaryDirectory() as folder, patch.dict(sys.modules, unreal=fake):
            job = self.job(folder)
            runtime.main(job)
            report = json.loads(Path(job["report"]).read_text())
        self.assertEqual(report["status"], "validated")
        self.assertEqual(report["spawnedActors"], 1)
        self.assertEqual(report["meshes"][0]["status"], "pass")
        self.assertIn("new_level", calls)
        self.assertIn("Unreal screenshot", report["pending"])

    def test_screenshot_and_resource_cleanup(self):
        fake, calls = self.fake()
        with TemporaryDirectory() as folder, patch.dict(sys.modules, unreal=fake):
            job = self.job(folder, capture=True)
            runtime.main(job)
            report = json.loads(Path(job["report"]).read_text())
            self.assertTrue(Path(report["screenshot"]).is_file())
        self.assertIn("release_target", calls)
        self.assertIn("destroy_capture", calls)
        self.assertNotIn("Unreal screenshot", report["pending"])

    def test_collision_failure_blocks_scene(self):
        fake, calls = self.fake(collision=0)
        with TemporaryDirectory() as folder, patch.dict(sys.modules, unreal=fake):
            job = self.job(folder)
            with self.assertRaisesRegex(RuntimeError, "QA failed"):
                runtime.main(job)
            report = json.loads(Path(job["report"]).read_text())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["meshes"][0]["checks"]["collision"])
        self.assertNotIn("new_level", calls)

    def test_invalid_api_metrics_fail_closed(self):
        fake, calls = self.fake(lods=-1)
        with TemporaryDirectory() as folder, patch.dict(sys.modules, unreal=fake):
            with self.assertRaisesRegex(ValueError, "lods"):
                runtime.main(self.job(folder))
        self.assertFalse(calls)

    def test_scene_and_capture_failures_record_report(self):
        for options in ({"save": False}, {"spawn": False}, {"uniform": True}, {"exported": False}):
            fake, calls = self.fake(**options)
            with self.subTest(options=options), TemporaryDirectory() as folder, patch.dict(sys.modules, unreal=fake):
                job = self.job(folder, capture=True)
                with self.assertRaises(RuntimeError):
                    runtime.main(job)
                self.assertEqual(json.loads(Path(job["report"]).read_text())["status"], "failed")
                if options.get("uniform") or options.get("exported") is False:
                    self.assertIn("destroy_capture", calls)
                    self.assertIn("release_target", calls)

    def test_screenshot_overwrite_and_escape_blocked_before_scene_creation(self):
        fake, calls = self.fake()
        with TemporaryDirectory() as folder, patch.dict(sys.modules, unreal=fake):
            job = self.job(folder, capture=True)
            Path(job["screenshot"]).write_bytes(b"existing")
            with self.assertRaisesRegex(ValueError, "fresh"):
                runtime.main(job)
            self.assertEqual(Path(job["screenshot"]).read_bytes(), b"existing")
        self.assertFalse(calls)

    def test_namespace_checks(self):
        for change in ({"destination": "/Game/Existing"}, {"mesh_paths": ["/Game/Other/Asset"]},
                       {"level_path": "/Game/AIStudio/TASK_1/Import_abc/../Other"}):
            fake, calls = self.fake()
            with self.subTest(change=change), TemporaryDirectory() as folder, patch.dict(sys.modules, unreal=fake):
                with self.assertRaises(ValueError):
                    runtime.main({**self.job(folder), **change})
            self.assertFalse(calls)


class UnrealQAPolicyTests(unittest.TestCase):
    def test_default_and_threshold_policy(self):
        self.assertEqual(runtime.evaluate(metrics())["status"], "pass")
        for changes in ({"triangles": 150001}, {"vertices": 0}, {"lods": 0}, {"uv_channels": 0},
                        {"material_slots": 0}, {"missing_materials": 1}, {"simple_collisions": 0}):
            with self.subTest(changes=changes):
                self.assertEqual(runtime.evaluate(metrics(**changes))["status"], "fail")
        self.assertEqual(runtime.evaluate(metrics(), {"minimum_lods": 2})["status"], "fail")
        self.assertEqual(runtime.evaluate(metrics(simple_collisions=0), {"require_collision": False})["status"], "pass")

    def test_bad_metrics_and_policies(self):
        for changes in ({"lods": -1}, {"vertices": True}, {"dimensions_cm": [float("nan"), 1, 1]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                runtime.evaluate(metrics(**changes))
        for policy in ({"minimum_lods": 0}, {"require_collision": "yes"}, {"unknown": 1}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                runtime.validate_policy(policy)


if __name__ == "__main__":
    unittest.main()
