import argparse
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config" / "studio.json").read_text(encoding="utf-8-sig"))

DEFAULT_BONES = ["root", "pelvis", "spine_01", "spine_02", "neck_01", "head"]
HUMANOID_BONES = (
    ("root", None, (0.0, 0.0, 0.0), (0.0, 0.0, 0.12)),
    ("pelvis", "root", (0.0, 0.0, 0.88), (0.0, 0.0, 1.08)),
    ("spine_01", "pelvis", (0.0, 0.0, 1.08), (0.0, 0.0, 1.34)),
    ("spine_02", "spine_01", (0.0, 0.0, 1.34), (0.0, 0.0, 1.58)),
    ("neck_01", "spine_02", (0.0, 0.0, 1.58), (0.0, 0.0, 1.76)),
    ("head", "neck_01", (0.0, 0.0, 1.76), (0.0, 0.0, 2.04)),
    ("clavicle_l", "spine_02", (0.02, 0.0, 1.53), (0.22, 0.0, 1.55)),
    ("upperarm_l", "clavicle_l", (0.22, 0.0, 1.55), (0.52, 0.0, 1.39)),
    ("lowerarm_l", "upperarm_l", (0.52, 0.0, 1.39), (0.78, 0.0, 1.27)),
    ("hand_l", "lowerarm_l", (0.78, 0.0, 1.27), (0.94, 0.0, 1.25)),
    ("clavicle_r", "spine_02", (-0.02, 0.0, 1.53), (-0.22, 0.0, 1.55)),
    ("upperarm_r", "clavicle_r", (-0.22, 0.0, 1.55), (-0.52, 0.0, 1.39)),
    ("lowerarm_r", "upperarm_r", (-0.52, 0.0, 1.39), (-0.78, 0.0, 1.27)),
    ("hand_r", "lowerarm_r", (-0.78, 0.0, 1.27), (-0.94, 0.0, 1.25)),
    ("thigh_l", "pelvis", (0.12, 0.0, 0.91), (0.14, 0.0, 0.49)),
    ("calf_l", "thigh_l", (0.14, 0.0, 0.49), (0.14, 0.0, 0.09)),
    ("foot_l", "calf_l", (0.14, 0.0, 0.09), (0.14, 0.22, 0.04)),
    ("thigh_r", "pelvis", (-0.12, 0.0, 0.91), (-0.14, 0.0, 0.49)),
    ("calf_r", "thigh_r", (-0.14, 0.0, 0.49), (-0.14, 0.0, 0.09)),
    ("foot_r", "calf_r", (-0.14, 0.0, 0.09), (-0.14, 0.22, 0.04)),
)
REQUIRED_HUMANOID_BONES = tuple(bone[0] for bone in HUMANOID_BONES)
ALLOWED_JOB_KEYS = {"type", "output_name", "write_asset", "bones"}
SUPPORTED_JOB_TYPES = {"skeleton_stub", "humanoid_rig_v1"}


def _validate_bones(bones):
    if (
        not isinstance(bones, list)
        or not bones
        or any(
            not isinstance(bone, str)
            or not bone.strip()
            or len(bone) > 63
            or any(ord(char) < 32 for char in bone)
            for bone in bones
        )
    ):
        raise ValueError("'bones' must be a non-empty list of valid names")
    if len(set(bones)) != len(bones):
        raise ValueError("'bones' must not contain duplicate names")
    return bones


def validate_job(job):
    if not isinstance(job, dict):
        raise ValueError("Blender job must be a JSON object")
    if set(job) - ALLOWED_JOB_KEYS:
        raise ValueError("Blender job contains unsupported fields")
    job_type = job.get("type")
    if not isinstance(job_type, str) or job_type not in SUPPORTED_JOB_TYPES:
        raise ValueError(
            "Unsupported Blender job type; expected 'skeleton_stub' or 'humanoid_rig_v1'"
        )
    if "write_asset" in job and not isinstance(job["write_asset"], bool):
        raise ValueError("'write_asset' must be a boolean")
    name = job.get("output_name", "job")
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
    ):
        raise ValueError("'output_name' must be a simple filename without path separators")
    if "bones" in job:
        bones = _validate_bones(job["bones"])
    elif job_type == "skeleton_stub":
        bones = DEFAULT_BONES
    else:
        bones = list(REQUIRED_HUMANOID_BONES)
    if job_type == "humanoid_rig_v1" and tuple(bones) != REQUIRED_HUMANOID_BONES:
        raise ValueError("'bones' for humanoid_rig_v1 must match its required humanoid rig")
    return {
        **job,
        "type": job_type,
        "output_name": name,
        "write_asset": job.get("write_asset", False),
        "bones": bones,
    }


def _python_string(value):
    return json.dumps(value, ensure_ascii=True)


def build_script(job, output_path):
    job = validate_job(job)
    code = (
        "import bpy\n"
        "print('AI_STUDIO_JOB_START')\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
    )
    if job["type"] == "skeleton_stub":
        bones = job["bones"]
        code += (
            "bpy.ops.object.armature_add(enter_editmode=True)\n"
            "obj=bpy.context.object\n"
            "obj.name='SK_1864_Human'\n"
            "arm=obj.data\n"
            f"first=arm.edit_bones[0];first.name={_python_string(bones[0])}\n"
            "prev=first\n"
        )
        for bone in bones[1:]:
            code += (
                f"b=arm.edit_bones.new({_python_string(bone)});"
                "b.head=prev.tail;"
                "b.tail=(prev.tail.x,prev.tail.y,prev.tail.z+0.1);"
                "b.parent=prev;prev=b\n"
            )
    else:
        code += (
            "bpy.ops.object.armature_add(enter_editmode=True)\n"
            "obj=bpy.context.object\n"
            "obj.name='SK_1864_Humanoid'\n"
            "arm=obj.data\n"
            "for existing in list(arm.edit_bones): arm.edit_bones.remove(existing)\n"
            "bones={}\n"
        )
        for name, parent, head, tail in HUMANOID_BONES:
            code += (
                f"bone=arm.edit_bones.new({_python_string(name)})\n"
                f"bone.head={head!r}\n"
                f"bone.tail={tail!r}\n"
                f"bones[{_python_string(name)}]=bone\n"
            )
            if parent is not None:
                code += f"bone.parent=bones[{_python_string(parent)}]\n"
    code += (
        "bpy.ops.object.mode_set(mode='OBJECT') "
        "if bpy.context.object and bpy.context.object.mode!='OBJECT' else None\n"
    )
    if job["write_asset"]:
        code += (
            "bpy.ops.wm.save_as_mainfile("
            f"filepath={_python_string(str(output_path))})\n"
        )
    code += "print('AI_STUDIO_JOB_OK')\n"
    return code


def _safe_output_path(workspace, output_name):
    workspace = workspace.resolve()
    if workspace == ROOT or ROOT in workspace.parents:
        raise ValueError("Blender workspace must be outside the repository")
    blender_workspace = (workspace / "blender").resolve()
    if blender_workspace.parent != workspace:
        raise ValueError("Blender workspace must remain inside the configured workspace")
    output_path = (blender_workspace / (output_name + ".blend")).resolve()
    if output_path.parent != blender_workspace:
        raise ValueError("Blender output path must remain inside the blender workspace")
    return blender_workspace, output_path


def run(job_path, approve_write=False, config=None, process_runner=None):
    job = validate_job(json.loads(Path(job_path).read_text(encoding="utf-8-sig")))
    if job["write_asset"] and approve_write is not True:
        raise SystemExit("Approval required: write_blender_asset")
    cfg = config or CFG
    workspace, output_path = _safe_output_path(
        Path(cfg["paths"]["workspace"]), job["output_name"]
    )
    script_path = workspace / "_job.py"
    evidence_path = workspace / (Path(job_path).stem + "-evidence.txt")
    workspace.mkdir(parents=True, exist_ok=True)
    script_path.write_text(build_script(job, output_path), encoding="utf-8")
    runner = process_runner or subprocess.run
    command = [
        str(Path(cfg["paths"]["blender"])),
        "--background",
        "--factory-startup",
        "--python",
        str(script_path),
    ]
    try:
        process = runner(command, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        evidence_path.write_text(
            f"Command: {command!r}\nTimed out after 300 seconds\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}\n",
            encoding="utf-8",
        )
        raise
    evidence_path.write_text(
        f"Command: {command!r}\nExit code: {process.returncode}\n"
        f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}\n",
        encoding="utf-8",
    )
    print(process.stdout)
    print("Evidence:", evidence_path)
    print("Output:", output_path if job["write_asset"] else "dry-run")
    raise SystemExit(process.returncode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job")
    parser.add_argument("--approve-write", action="store_true")
    arguments = parser.parse_args()
    run(arguments.job, arguments.approve_write)
