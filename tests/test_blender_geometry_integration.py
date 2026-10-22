"""Opt-in real Blender regression; uses only a temporary synthetic scene."""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters"


@unittest.skipUnless(os.environ.get("AI_STUDIO_BLENDER_TEST_EXE"), "Set AI_STUDIO_BLENDER_TEST_EXE for real Blender regression")
class BlenderGeometryIntegration(unittest.TestCase):
    def test_gltf_seam_vertices_preserve_closed_mesh_uv_and_outward_normals(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "output"
            output.mkdir()
            job = {"input": str(root / "input.glb"), "output_dir": str(output), "asset_name": "SM_Regression",
                   "rotation_x_degrees": 0, "target_size_m": 1.0, "pivot": "bottom"}
            source = """
import bpy,json,sys
from pathlib import Path
from mathutils import Vector
sys.path.insert(0, ADAPTERS)
from blender_asset_runtime import main
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1)
obj=bpy.context.object
material=bpy.data.materials.new('RegressionMaterial');material.use_nodes=True
obj.data.materials.append(material)
bpy.ops.export_scene.gltf(filepath=JOB['input'],export_format='GLB',use_selection=True)
main(JOB)
metrics=json.loads((Path(JOB['output_dir'])/'metrics.json').read_text())
assert metrics['vertices'] == 8, metrics
assert metrics['welded_vertices'] == 16, metrics
assert metrics['non_manifold_edges'] == 0, metrics
assert metrics['triangles'] == 12 and metrics['has_uv'], metrics
mesh=bpy.data.objects[JOB['asset_name']].data
center=sum((vertex.co for vertex in mesh.vertices),Vector())/len(mesh.vertices)
assert all(face.normal.dot(face.center-center) > 0 for face in mesh.polygons), 'Inward normal after glTF cleanup'
print('SEAM_REGRESSION_PASSED')
""".replace("ADAPTERS", repr(str(ADAPTERS))).replace("JOB", repr(job))
            script = root / "regression.py"
            script.write_text(source, encoding="utf-8")
            result = subprocess.run([os.environ["AI_STUDIO_BLENDER_TEST_EXE"], "--background", "--factory-startup",
                                     "--python-exit-code", "1", "--python", str(script)],
                                    capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-6000:])
            self.assertIn("SEAM_REGRESSION_PASSED", result.stdout)
