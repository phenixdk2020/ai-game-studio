"""Unreal commandlet entry point; imports only into a fresh task namespace."""
import json
import os
from pathlib import Path


def main(job):
    import unreal

    report_path = Path(job["report"])
    report = {"schemaVersion": 1, "status": "failed", "assetPaths": []}
    try:
        destination = job["destination"]
        if unreal.EditorAssetLibrary.does_directory_exist(destination):
            raise RuntimeError("Destination already exists; explicit re-import is not implemented")
        task = unreal.AssetImportTask()
        for key, value in {"filename": job["input"], "destination_path": destination,
                           "destination_name": job["asset_name"], "automated": True,
                           "replace_existing": False, "save": False, "async_": False}.items():
            task.set_editor_property(key, value)
        options = unreal.FbxImportUI()
        options.set_editor_property("import_mesh", True)
        options.set_editor_property("import_as_skeletal", False)
        options.set_editor_property("import_animations", False)
        options.set_editor_property("automated_import_should_detect_type", False)
        options.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
        options.set_editor_property("import_materials", True)
        options.set_editor_property("import_textures", True)
        options.static_mesh_import_data.set_editor_property("combine_meshes", True)
        options.static_mesh_import_data.set_editor_property("auto_generate_collision", True)
        task.set_editor_property("options", options)
        task.set_editor_property("factory", unreal.FbxFactory())
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        objects = list(task.get_objects())
        meshes = [obj for obj in objects if isinstance(obj, unreal.StaticMesh)]
        if not meshes:
            raise RuntimeError("Unreal did not return a StaticMesh")
        paths = list(task.get_editor_property("imported_object_paths"))
        if not paths or any(not path.startswith(destination + "/") for path in paths):
            raise RuntimeError("Importer returned assets outside the assigned namespace")
        for obj in objects:
            if not unreal.EditorAssetLibrary.save_loaded_asset(obj, only_if_is_dirty=False):
                raise RuntimeError(f"Failed to save {obj.get_path_name()}")
        if not unreal.EditorAssetLibrary.save_directory(destination, only_if_is_dirty=False, recursive=True):
            raise RuntimeError("Could not save imported asset dependencies")
        report.update(status="imported", assetPaths=paths,
                      staticMeshPaths=[obj.get_path_name() for obj in meshes],
                      engineVersion=unreal.SystemLibrary.get_engine_version(),
                      pending=["Unreal mesh QA", "test level", "screenshot", "LOD validation"])
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(json.loads(Path(os.environ["AI_STUDIO_UNREAL_JOB"]).read_text(encoding="utf-8-sig")))
