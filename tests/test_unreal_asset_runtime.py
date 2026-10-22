import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / "adapters" / "unreal_asset_runtime.py"
spec = importlib.util.spec_from_file_location("unreal_asset_runtime", RUNTIME)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class PropertyObject:
    def set_editor_property(self, name, value):
        setattr(self, name, value)

    def get_editor_property(self, name):
        return getattr(self, name)


class Mesh:
    def get_path_name(self):
        return "/Game/Test/SM_Sword.SM_Sword"


class UnrealRuntimeTests(unittest.TestCase):
    def fake_unreal(self, *, existing=False, meshes=True, save=True, outside=False):
        task = PropertyObject()
        task.get_objects = lambda: [Mesh()] if meshes else []
        task.imported_object_paths = ["/Game/Other/SM_Sword" if outside else "/Game/Test/SM_Sword"]
        options = PropertyObject()
        options.static_mesh_import_data = PropertyObject()
        saved = []
        library = SimpleNamespace(does_directory_exist=lambda path: existing,
            save_loaded_asset=lambda obj, **kwargs: saved.append(obj) or save,
            save_directory=lambda *a, **k: save)
        fake = SimpleNamespace(EditorAssetLibrary=library, AssetImportTask=lambda: task,
            FbxImportUI=lambda: options, FbxFactory=lambda: PropertyObject(),
            FBXImportType=SimpleNamespace(FBXIT_STATIC_MESH="STATIC"), StaticMesh=Mesh,
            AssetToolsHelpers=SimpleNamespace(get_asset_tools=lambda: SimpleNamespace(import_asset_tasks=lambda tasks: None)),
            SystemLibrary=SimpleNamespace(get_engine_version=lambda: "mock 5.7"))
        return fake, task, saved

    def invoke(self, fake, folder):
        job = {"destination": "/Game/Test", "asset_name": "SM_Sword", "input": "sword.fbx",
               "report": str(Path(folder) / "unreal.json")}
        with patch.dict(sys.modules, unreal=fake):
            runtime.main(job)
        return json.loads(Path(job["report"]).read_text())

    def test_static_mesh_import_and_save(self):
        fake, task, saved = self.fake_unreal()
        with TemporaryDirectory() as folder:
            report = self.invoke(fake, folder)
        self.assertEqual(report["status"], "imported")
        self.assertTrue(task.automated)
        self.assertFalse(task.replace_existing)
        self.assertFalse(task.options.import_as_skeletal)
        self.assertTrue(task.options.static_mesh_import_data.auto_generate_collision)
        self.assertTrue(saved)
        self.assertIn("screenshot", report["pending"])

    def test_existing_namespace_missing_mesh_failed_save_and_outside_paths(self):
        for kwargs in ({"existing": True}, {"meshes": False}, {"save": False}, {"outside": True}):
            fake, _, _ = self.fake_unreal(**kwargs)
            with self.subTest(kwargs=kwargs), TemporaryDirectory() as folder:
                with self.assertRaises(RuntimeError):
                    self.invoke(fake, folder)
                report = json.loads((Path(folder) / "unreal.json").read_text())
                self.assertEqual(report["status"], "failed")
                self.assertTrue(report["error"])


if __name__ == "__main__":
    unittest.main()
