"""Unreal asset QA, isolated test map and optional offscreen scene capture.

Runs in a fresh full-editor process, never inside the operator's open editor.
"""
import json
import math
import os
import re
from pathlib import Path


DEFAULT_POLICY = {"minimum_lods": 1, "triangle_limit": 150000,
                  "require_collision": True, "require_uv": True, "require_materials": True}


def validate_policy(policy=None):
    if policy is not None and (not isinstance(policy, dict) or set(policy) - set(DEFAULT_POLICY)):
        raise ValueError("Unknown Unreal QA options")
    result = {**DEFAULT_POLICY, **(policy or {})}
    for key in ("minimum_lods", "triangle_limit"):
        if type(result[key]) is not int or result[key] < 1:
            raise ValueError(f"Invalid Unreal QA threshold: {key}")
    for key in ("require_collision", "require_uv", "require_materials"):
        if type(result[key]) is not bool:
            raise ValueError(f"Invalid Unreal QA flag: {key}")
    return result


def evaluate(metrics, policy=None):
    policy = validate_policy(policy)
    for key in ("lods", "vertices", "triangles", "uv_channels", "material_slots", "missing_materials", "simple_collisions", "convex_collisions"):
        if type(metrics.get(key)) is not int or metrics[key] < 0:
            raise ValueError(f"Unreal QA metric unavailable: {key}")
    dims = metrics.get("dimensions_cm")
    if not isinstance(dims, list) or len(dims) != 3 or any(
        type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in dims
    ):
        raise ValueError("Invalid Unreal dimensions")
    checks = {
        "geometry": metrics["vertices"] > 0 and 0 < metrics["triangles"] <= policy["triangle_limit"],
        "lods": metrics["lods"] >= policy["minimum_lods"],
        "bounds": max(dims) > 0,
        "uv": not policy["require_uv"] or metrics["uv_channels"] > 0,
        "materials": not policy["require_materials"] or (metrics["material_slots"] > 0 and metrics["missing_materials"] == 0),
        "collision": not policy["require_collision"] or metrics["simple_collisions"] + metrics["convex_collisions"] > 0,
    }
    return {"status": "pass" if all(checks.values()) else "fail", "checks": checks,
            "metrics": metrics, "policy": policy}


def inspect_mesh(mesh, unreal, policy):
    subsystem = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    if subsystem is None:
        raise RuntimeError("StaticMeshEditorSubsystem unavailable; launch QA with -ExecutePythonScript, not -run=pythonscript")
    bounds = mesh.get_bounds()
    materials = list(mesh.get_editor_property("static_materials"))
    lods = subsystem.get_lod_count(mesh)
    # Negative subsystem return values signal an API error; never convert them into success.
    metrics = {"lods": lods, "vertices": mesh.get_num_vertices(0) if lods > 0 else 0,
               "triangles": mesh.get_num_triangles(0) if lods > 0 else 0,
               "uv_channels": subsystem.get_num_uv_channels(mesh, 0) if lods > 0 else 0,
               "simple_collisions": subsystem.get_simple_collision_count(mesh),
               "convex_collisions": subsystem.get_convex_collision_count(mesh),
               "material_slots": len(materials),
               "missing_materials": sum(slot.get_editor_property("material_interface") is None for slot in materials),
               "dimensions_cm": [2 * bounds.box_extent.x, 2 * bounds.box_extent.y, 2 * bounds.box_extent.z]}
    return evaluate(metrics, policy)


def test_scene(meshes, level_path, unreal):
    if unreal.EditorAssetLibrary.does_asset_exist(level_path):
        raise RuntimeError("Test map already exists; refusing overwrite")
    levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if not levels.new_level(level_path):
        raise RuntimeError("Could not create isolated test map")
    placed = []
    for index, mesh in enumerate(meshes):
        actor = actors.spawn_actor_from_object(mesh, unreal.Vector(index * 300, 0, 0), unreal.Rotator())
        if actor is None:
            raise RuntimeError("Could not spawn imported mesh")
        actor.set_actor_label(f"QA_Prop_{index + 1}")
        placed.append(actor)
    # Dynamic lighting supports the isolated preview without baking or changing project settings.
    for yaw, intensity in ((45, 5.0), (135, 1.25)):
        light = actors.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 300),
                                              unreal.Rotator(roll=0.0, pitch=-45.0, yaw=yaw))
        if light is None:
            raise RuntimeError("Could not create test lighting")
        component = light.get_component_by_class(unreal.DirectionalLightComponent)
        component.set_mobility(unreal.ComponentMobility.MOVABLE)
        component.set_editor_property("intensity", intensity)
    if not levels.save_current_level():
        raise RuntimeError("Could not save test map")
    return placed


def screenshot(placed, path, unreal):
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if world is None:
        raise RuntimeError("Editor world unavailable for scene capture")
    boxes = [actor.get_actor_bounds(False) for actor in placed]
    low = [min(getattr(origin, axis) - getattr(extent, axis) for origin, extent in boxes) for axis in ("x", "y", "z")]
    high = [max(getattr(origin, axis) + getattr(extent, axis) for origin, extent in boxes) for axis in ("x", "y", "z")]
    center = unreal.Vector(*[(a + b) / 2 for a, b in zip(low, high)])
    radius = max(math.sqrt(sum((b - a) ** 2 for a, b in zip(low, high))) / 2, 1.0)
    location = center + unreal.Vector(-radius * 2, -radius * 2, radius)
    rotation = unreal.MathLibrary.find_look_at_rotation(location, center)
    capture_actor = actors.spawn_actor_from_class(unreal.SceneCapture2D, location, rotation)
    if capture_actor is None:
        raise RuntimeError("Could not create scene capture")
    target = None
    try:
        capture = capture_actor.get_component_by_class(unreal.SceneCaptureComponent2D)
        target = unreal.RenderingLibrary.create_render_target2d(world, width=640, height=640,
                        format=unreal.TextureRenderTargetFormat.RTF_RGBA8)
        if target is None:
            raise RuntimeError("Could not allocate render target")
        capture.set_editor_property("texture_target", target)
        capture.set_editor_property("capture_every_frame", False)
        capture.set_editor_property("capture_on_movement", False)
        capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        capture.set_editor_property("fov_angle", 50.0)
        # A one-shot capture has no eye-adaptation history. Fix exposure explicitly
        # rather than inheriting the project's startup camera/exposure state.
        settings = unreal.PostProcessSettings()
        settings.set_editor_property("override_auto_exposure_method", True)
        settings.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
        settings.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
        settings.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
        settings.set_editor_property("override_auto_exposure_bias", True)
        settings.set_editor_property("auto_exposure_bias", 0.0)
        settings.set_editor_property("override_bloom_intensity", True)
        settings.set_editor_property("bloom_intensity", 0.0)
        capture.set_editor_property("post_process_settings", settings)
        capture.set_editor_property("post_process_blend_weight", 1.0)
        # Verified in UE 5.7's AsyncCompilationHelpers/AssetCompilingManager sources.
        # Finish pending material/mesh work so the capture does not use fallback shaders.
        unreal.SystemLibrary.execute_console_command(world, "Editor.AsyncAssetCompilationFinishAll")
        capture.capture_scene()
        pixels = unreal.RenderingLibrary.read_render_target(world, target)
        if not pixels or max(max(getattr(pixel, channel) for pixel in pixels) - min(
            getattr(pixel, channel) for pixel in pixels
        ) for channel in ("r", "g", "b")) < 8:
            raise RuntimeError("Scene capture is empty or uniform; wait for shader/render readiness before retrying")
        unreal.RenderingLibrary.export_render_target(world, target, str(path.parent), path.name)
        if not path.is_file() or path.stat().st_size < 24:
            raise RuntimeError("Unreal did not export a screenshot")
        with path.open("rb") as stream:
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                raise RuntimeError("Unreal screenshot is not PNG")
    finally:
        actors.destroy_actor(capture_actor)
        if target is not None:
            unreal.RenderingLibrary.release_render_target2d(target)


def main(job):
    import unreal

    report_path = Path(job["report"])
    report = {"schemaVersion": 1, "status": "failed", "meshes": []}
    try:
        policy = validate_policy(job.get("policy"))
        destination = job["destination"]
        level_path = job["level_path"]
        if (not re.fullmatch(r"/Game/AIStudio/[A-Za-z0-9_]+/Import_[A-Za-z0-9_]+", destination)
                or not re.fullmatch(re.escape(destination) + r"/[A-Za-z0-9_]+", level_path)):
            raise ValueError("Test map must be contained in the task import namespace")
        paths = job["mesh_paths"]
        if not isinstance(paths, list) or not paths or any(not isinstance(path, str) or not re.fullmatch(
            re.escape(destination) + r"/[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*(?:\.[A-Za-z0-9_]+)?", path
        ) for path in paths):
            raise ValueError("Mesh paths must be contained in the task import namespace")
        if job.get("capture"):
            image = Path(job["screenshot"])
            if image.resolve().parent != report_path.resolve().parent or image.exists():
                raise ValueError("Screenshot must be a fresh file beside the QA report")
        meshes = []
        for path in paths:
            mesh = unreal.EditorAssetLibrary.load_asset(path)
            if not isinstance(mesh, unreal.StaticMesh):
                raise RuntimeError(f"Saved StaticMesh could not be reloaded: {path}")
            result = inspect_mesh(mesh, unreal, policy)
            report["meshes"].append({"path": path, **result})
            meshes.append(mesh)
        if any(result["status"] != "pass" for result in report["meshes"]):
            raise RuntimeError("Unreal asset QA failed; test map and preview blocked")
        placed = test_scene(meshes, level_path, unreal)
        report.update(levelPath=level_path, spawnedActors=len(placed), status="validated")
        if job.get("capture"):
            screenshot(placed, image, unreal)
            report["screenshot"] = str(image)
        report["pending"] = ["operator visual review", "real pipeline integration evidence"]
        if not job.get("capture"):
            report["pending"].append("Unreal screenshot")
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main(json.loads(Path(os.environ["AI_STUDIO_UNREAL_VALIDATION_JOB"]).read_text(encoding="utf-8-sig")))
