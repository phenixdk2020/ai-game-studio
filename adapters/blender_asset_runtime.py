"""Executed only by Blender: --python this_file -- job.json."""
import json
import math
import sys
from pathlib import Path


def main(job):
    import bpy
    import bmesh
    from mathutils import Vector

    out = Path(job["output_dir"])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=job["input"])
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("Input contains no mesh")
    if any(obj.modifiers or obj.vertex_groups for obj in meshes):
        raise RuntimeError("Prop cleanup does not accept rigged or modified meshes")
    # Apply imported world transforms before removing empty hierarchy nodes.
    for obj in meshes:
        world = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = world
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH":
            bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = job["asset_name"]
    obj.rotation_euler.rotate_axis("X", math.radians(job["rotation_x_degrees"]))
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    bpy.context.view_layer.update()
    longest = max(obj.dimensions)
    if longest <= 0:
        raise RuntimeError("Mesh has zero dimensions")
    if job["target_size_m"] is not None:
        factor = job["target_size_m"] / longest
        obj.scale = (factor, factor, factor)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    low = Vector(tuple(min(v[i] for v in corners) for i in range(3)))
    high = Vector(tuple(max(v[i] for v in corners) for i in range(3)))
    pivot = (low + high) * 0.5
    if job["pivot"] == "bottom":
        pivot.z = low.z
    bpy.context.scene.cursor.location = pivot
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    obj.location = (0, 0, 0)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0
    bpy.context.view_layer.update()
    obj.data.calc_loop_triangles()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    non_manifold = sum(not edge.is_manifold for edge in bm.edges)
    bm.free()
    missing_textures = 0
    for material in obj.data.materials:
        if material and material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == "TEX_IMAGE" and (node.image is None or (
                    not node.image.packed_file and node.image.source == "FILE" and
                    not Path(bpy.path.abspath(node.image.filepath)).is_file()
                )):
                    missing_textures += 1
    metrics = {"mesh_count": 1, "vertices": len(obj.data.vertices),
               "triangles": len(obj.data.loop_triangles), "non_manifold_edges": non_manifold,
               "dimensions_m": list(obj.dimensions), "has_uv": bool(obj.data.uv_layers),
               "has_materials": bool(obj.data.materials) and all(obj.data.materials),
               "missing_textures": missing_textures, "blender_version": bpy.app.version_string}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    # Export only the asset, before cameras and lights are added.
    bpy.ops.export_scene.gltf(filepath=str(out / "asset-clean.glb"), export_format="GLB",
                              use_selection=True, export_animations=False)
    bpy.ops.export_scene.fbx(filepath=str(out / "asset.fbx"), use_selection=True,
                             object_types={"MESH"}, axis_forward="-Y", axis_up="Z",
                             apply_unit_scale=True, bake_anim=False, path_mode="COPY", embed_textures=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.world = scene.world or bpy.data.worlds.new("StudioWorld")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.2, 0.2, 0.2, 1)
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    center = sum(corners, Vector()) / 8
    radius = max((v - center).length for v in corners)
    bpy.ops.object.light_add(type="AREA", location=center + Vector((radius * 2, -radius * 2, radius * 3)))
    bpy.context.object.data.energy = 600
    bpy.context.object.data.shape = "DISK"
    bpy.context.object.data.size = radius * 4
    bpy.context.object.rotation_euler = (center - bpy.context.object.location).to_track_quat("-Z", "Y").to_euler()
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = radius * 2.5
    camera.data.clip_start = max(radius * 0.001, 0.00001)
    camera.data.clip_end = max(radius * 20, 100)
    scene.camera = camera
    for name, direction in (("front", (0, -1, 0)), ("side", (1, 0, 0)), ("perspective", (1, -1, 0.7))):
        camera.location = center + Vector(direction).normalized() * radius * 4
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(out / f"preview-{name}.png")
        bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "asset.blend"))
    print("AI_STUDIO_ASSET_OK")


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8-sig")))
