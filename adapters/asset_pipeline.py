"""Approved, isolated prop processing; never reads or writes the studio queue."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid

from asset_qa import evaluate, markdown, validate_profile

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def contained(path, root):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(Path(root).resolve()):
        raise ValueError(f"Path outside allowed root: {path}")
    return resolved


def validate_glb(path, minimum=20):
    """Validate chunk structure without loading the binary mesh into memory."""
    path = Path(path)
    size = path.stat().st_size
    if size < max(20, minimum):
        raise ValueError("GLB is too small")
    with path.open("rb") as stream:
        magic, version, length = struct.unpack("<4sII", stream.read(12))
        if magic != b"glTF" or version != 2 or length != size:
            raise ValueError("Invalid GLB header")
        first = True
        while stream.tell() < size:
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError("Truncated GLB chunk")
            length, kind = struct.unpack("<II", header)
            if length % 4 or stream.tell() + length > size:
                raise ValueError("Invalid GLB chunk length")
            if first:
                if kind != 0x4E4F534A or length > 64 * 1024 * 1024:
                    raise ValueError("Invalid or oversized GLB JSON chunk")
                data = json.loads(stream.read(length).decode("utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("asset"), dict) or data["asset"].get("version") != "2.0":
                    raise ValueError("Invalid glTF asset version")
                # External resources cannot escape the job sandbox through Blender's importer.
                for key in ("buffers", "images"):
                    resources = data.get(key, [])
                    if not isinstance(resources, list) or any(not isinstance(item, dict) for item in resources):
                        raise ValueError(f"Invalid glTF {key}")
                    for resource in resources:
                        uri = resource.get("uri", "")
                        if not isinstance(uri, str) or (uri and not uri.startswith("data:")):
                            raise ValueError("GLB must embed all resources")
                first = False
            else:
                stream.seek(length, 1)
        if first:
            raise ValueError("Missing GLB JSON chunk")


def validate_job(job, config):
    if not isinstance(config, dict) or not isinstance(config.get("jobs_root"), str) or not config["jobs_root"]:
        raise ValueError("Configure jobs_root")
    for key, default in (("minimum_glb_bytes", 1024), ("blender_timeout", 1800), ("unreal_timeout", 1800)):
        if type(config.get(key, default)) is not int or config.get(key, default) < 1:
            raise ValueError(f"Invalid configuration: {key}")
    validate_profile(config.get("qa"))
    if "schemaVersion" in config and (type(config["schemaVersion"]) is not int or config["schemaVersion"] != 1):
        raise ValueError("Unsupported pipeline configuration schemaVersion")
    if not isinstance(job, dict) or type(job.get("schemaVersion")) is not int or job["schemaVersion"] != 1:
        raise ValueError("Asset job requires schemaVersion 1")
    if set(job) - {"schemaVersion", "taskId", "asset_name", "input", "target_size_m", "rotation_x_degrees", "pivot", "project"}:
        raise ValueError("Unknown asset job options")
    task_id = job.get("taskId", "")
    name = job.get("asset_name", "")
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", task_id):
        raise ValueError("Invalid taskId")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
        raise ValueError("Invalid asset_name")
    if task_id.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ValueError("Reserved taskId")
    if job.get("project") is not None and not isinstance(job["project"], str):
        raise ValueError("project must be a path string")
    jobs_root = Path(config["jobs_root"])
    if not jobs_root.is_absolute():
        jobs_root = ROOT / jobs_root
    task_root = contained(jobs_root / task_id, jobs_root)
    if not isinstance(job.get("input"), str) or not job["input"]:
        raise ValueError("input must be a path string")
    source = Path(job["input"])
    if not source.is_absolute():
        source = task_root / source
    source = contained(source, task_root)
    if not source.is_file() or source.suffix.lower() != ".glb":
        raise ValueError("Input must be an existing task-local GLB")
    validate_glb(source, config.get("minimum_glb_bytes", 1024))
    size = job.get("target_size_m")
    if size is not None and (type(size) not in (int, float) or not math.isfinite(size) or not 0.001 <= size <= 1000):
        raise ValueError("target_size_m must be between 0.001 and 1000")
    rotation = job.get("rotation_x_degrees", 0)
    if type(rotation) not in (int, float) or not math.isfinite(rotation) or abs(rotation) > 360:
        raise ValueError("Invalid rotation_x_degrees")
    pivot = job.get("pivot", "bottom")
    if pivot not in ("bottom", "center"):
        raise ValueError("Invalid pivot")
    return {"schemaVersion": 1, "taskId": task_id, "asset_name": name,
            "input": str(source), "task_root": str(task_root), "target_size_m": size,
            "rotation_x_degrees": rotation, "pivot": pivot,
            "project": job.get("project")}


def find_project(path, allowed_roots):
    candidate = Path(path).resolve()
    if not any(candidate.is_relative_to(Path(root).resolve()) for root in allowed_roots):
        raise ValueError("Unreal project is outside allowed_project_roots")
    if candidate.is_dir():
        matches = list(candidate.glob("*.uproject"))
        if len(matches) != 1:
            raise ValueError("Select one unambiguous .uproject")
        candidate = matches[0].resolve()
    if not candidate.is_file() or candidate.suffix.lower() != ".uproject":
        raise ValueError("Missing .uproject")
    if not any(candidate.is_relative_to(Path(root).resolve()) for root in allowed_roots):
        raise ValueError("Resolved Unreal project is outside allowed roots")
    project = read_json(candidate)
    plugins = {p["Name"]: p.get("Enabled") for p in project.get("Plugins", [])}
    if plugins.get("PythonScriptPlugin") is not True or plugins.get("EditorScriptingUtilities") is not True:
        raise ValueError("Enable PythonScriptPlugin and EditorScriptingUtilities explicitly in the Unreal project")
    return candidate


@contextmanager
def task_lock(root):
    path = Path(root) / ".asset-pipeline.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("Task is locked; verify no process is running before recovering its lock") from None
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(json.dumps({"pid": os.getpid(), "createdAt": now()}))
        yield
    finally:
        path.unlink()


def now():
    return datetime.now(timezone.utc).isoformat()


def run_tool(arguments, directory, label, timeout, runner, env=None):
    with (directory / f"{label}.stdout.txt").open("w", encoding="utf-8") as stdout, \
         (directory / f"{label}.stderr.txt").open("w", encoding="utf-8") as stderr:
        result = runner(arguments, stdout=stdout, stderr=stderr, text=True,
                        timeout=timeout, check=False, env=env)
    if result.returncode:
        raise RuntimeError(f"{label} exited with code {result.returncode}; see per-attempt logs")


def tool_path(config, name):
    executable = Path(config.get(name, ""))
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError(f"Configure an existing absolute {name} path")
    return str(executable.resolve())


def artifacts(directory, names):
    output = []
    for name in names:
        path = contained(directory / name, directory)
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError(f"Missing output: {name}")
        if name.endswith(".png"):
            with path.open("rb") as stream:
                if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                    raise RuntimeError(f"Invalid preview: {name}")
        if name.endswith(".glb"):
            validate_glb(path)
        output.append({"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size})
    return output


def fingerprint(job, config):
    payload = {"job": job, "config": config, "inputSha256": sha256(job["input"]),
               "code": {name: sha256(HERE / name) for name in (
                   "asset_pipeline.py", "asset_qa.py", "blender_asset_runtime.py", "unreal_asset_runtime.py")}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def run(job, config, *, approve_blender=False, approve_unreal=False, target="blender", resume=False,
        runner=subprocess.run):
    if target not in ("blender", "unreal"):
        raise ValueError("Invalid target")
    normalized = validate_job(job, config)
    if not approve_blender:
        raise PermissionError("Approval required: write_blender_asset (--approve-blender)")
    if target == "unreal" and not approve_unreal:
        raise PermissionError("Approval required: write_unreal_asset (--approve-unreal)")
    blender = tool_path(config, "blender_executable")
    project = None
    if target == "unreal":
        project = find_project(normalized.get("project") or "", config.get("allowed_project_roots", []))
        unreal_editor = tool_path(config, "unreal_executable")
    root = Path(normalized["task_root"])
    signature = fingerprint(normalized, config)
    manifest_path = root / "asset-manifest.json"
    with task_lock(root):
        previous = read_json(manifest_path) if resume and manifest_path.exists() else None
        if previous and previous.get("fingerprint") == signature and previous.get("blenderComplete"):
            output = contained(previous["outputDirectory"], root)
            if any(sha256(contained(item["path"], output)) != item["sha256"] for item in previous["artifacts"]):
                raise RuntimeError("Cannot resume: artifact checksum changed")
            report = evaluate(read_json(output / "metrics.json"), config.get("qa"))
            if report["status"] == "fail":
                raise RuntimeError("Cannot resume failed QA")
            if previous.get("status") == "ReadyForUnrealQA":
                return previous
            manifest = previous
            manifest.pop("error", None)
            manifest.update(status="ReadyForUnreal", stage="unreal-import")
        else:
            output = contained(root / "outputs" / ("attempt-" + uuid.uuid4().hex), root)
            output.mkdir(parents=True, exist_ok=False)
            manifest = {"schemaVersion": 1, "taskId": normalized["taskId"], "fingerprint": signature,
                        "status": "Running", "stage": "blender-cleanup", "startedAt": now(),
                        "inputPath": normalized["input"], "inputSha256": sha256(normalized["input"]),
                        "outputDirectory": str(output), "artifacts": [], "blenderComplete": False}
        def save():
            manifest["updatedAt"] = now()
            write_json(manifest_path, manifest)
            write_json(output / "manifest.json", manifest)
        try:
            save()
            if not manifest["blenderComplete"]:
                runtime_job = {**normalized, "output_dir": str(output)}
                write_json(output / "blender-job.json", runtime_job)
                run_tool([blender, "--background", "--factory-startup", "--python-exit-code", "1",
                          "--python", str(HERE / "blender_asset_runtime.py"), "--", str(output / "blender-job.json")],
                         output, "blender", config.get("blender_timeout", 1800), runner)
                manifest["stage"] = "asset-qa"
                manifest["artifacts"] = artifacts(output, ["asset.blend", "asset-clean.glb", "asset.fbx",
                    "metrics.json", "preview-front.png", "preview-side.png", "preview-perspective.png"])
                report = evaluate(read_json(output / "metrics.json"), config.get("qa"))
                write_json(output / "qa.json", report)
                (output / "qa.md").write_text(markdown(report), encoding="utf-8")
                manifest["qaStatus"] = report["status"]
                manifest["artifacts"] += artifacts(output, ["qa.json", "qa.md"])
                if report["status"] == "fail":
                    raise RuntimeError("Asset QA failed; Unreal import blocked")
                manifest["blenderComplete"] = True
                manifest["status"] = "ReadyForUnreal"
                manifest["stage"] = "unreal-import"
                save()
            if target == "unreal":
                # A fresh namespace prevents importers from replacing prior assets on retry.
                import_id = "Import_" + uuid.uuid4().hex
                destination = f"/Game/AIStudio/{normalized['taskId'].replace('-', '_')}/{import_id}"
                unreal_job = {"input": str(output / "asset.fbx"), "asset_name": normalized["asset_name"],
                              "destination": destination, "report": str(output / (import_id + ".json"))}
                unreal_job_path = output / (import_id + "-job.json")
                write_json(unreal_job_path, unreal_job)
                env = {**os.environ, "AI_STUDIO_UNREAL_JOB": str(unreal_job_path)}
                manifest.update(status="Running", stage="unreal-import", unrealDestination=destination)
                save()
                run_tool([unreal_editor, str(project), "-unattended", "-nop4", "-nosplash", "-nullrhi",
                          "-run=pythonscript", "-script=" + str(HERE / "unreal_asset_runtime.py")],
                         output, import_id, config.get("unreal_timeout", 1800), runner, env)
                imported = read_json(unreal_job["report"])
                if imported.get("status") != "imported" or not imported.get("staticMeshPaths") or any(
                    not isinstance(path, str) or not path.startswith(destination + "/")
                    for path in imported["staticMeshPaths"]
                ):
                    raise RuntimeError("Unreal import report did not confirm a StaticMesh")
                manifest["artifacts"] += artifacts(output, [Path(unreal_job["report"]).name])
                manifest.update(status="ReadyForUnrealQA", stage="unreal-qa", unreal=imported)
            save()
            return manifest
        except Exception as error:
            manifest.update(status="Failed", error=str(error))
            save()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "asset-pipeline.json")
    parser.add_argument("--target", choices=("blender", "unreal"), default="blender")
    parser.add_argument("--approve-blender", action="store_true")
    parser.add_argument("--approve-unreal", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--plan", action="store_true", help="Validate and print job without writing or launching tools")
    args = parser.parse_args()
    try:
        job, config = read_json(args.job), read_json(args.config)
        result = validate_job(job, config) if args.plan else run(job, config, target=args.target,
            approve_blender=args.approve_blender, approve_unreal=args.approve_unreal, resume=args.resume)
        # ASCII JSON survives Windows PowerShell 5 pipe encodings; the JSON parser restores Unicode.
        print(json.dumps(result))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
