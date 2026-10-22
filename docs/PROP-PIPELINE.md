# Prop pipeline implementation and local validation

Status: software implementation with isolated automated tests. No actual Hunyuan,
Blender or Unreal execution has been performed by this coding agent. M1 is pending.

## Implemented backlog slices

| Backlog | Implementation | Remaining evidence/work |
| --- | --- | --- |
| P0-001 | Worker reads legacy arrays, single tasks and value/Count wrappers; removes null entries; adds schemaVersion/defaults; atomically writes UTF-8 arrays; worker rejects stale queue revisions | GUI uses its existing writer; a fully shared transactional writer remains pending |
| P0-002 | Exclusive OS-held worker lock with PID/version; process death releases handle | GUI version indicator; existing older workers do not honor this lock |
| P0-004 | Task-local immutable attempt directories, checksums, metadata and manifests | Retention/cleanup policy |
| P0-010 | Raw Base64, content type and GLB validation, rejected response preservation | Real API compatibility and Blender readability |
| P0-020/021/022 | GLB import, preserve transforms, join prop meshes, remove loose vertices, recalculate normals, optional size/orientation, center/bottom pivot | Actual Blender run and visual inspection |
| P0-026 | Three orthographic CPU-rendered PNG previews | Visual inspection on a real mesh |
| P0-030/031 | QA JSON/Markdown with thresholds and an import gate | Artistic/visual quality, normal direction, scale against references |
| P0-040/041 | Allowed project roots, unambiguous .uproject, explicit plugins, automated FBX StaticMesh import, dependency save, fresh namespace | Actual Unreal 5.7 integration run |
| P0-042 | Requests automatic collision; Unreal QA checks saved collision, LOD count, UV, materials and triangle budget | Actual collision behavior, additional LOD generation, Nanite policy and texture fidelity |
| P0-043 | Optional separate QA commandlet creates/saves isolated test map, spawns imported mesh, and exports offscreen PNG with a nonuniform-pixel check | Real Unreal run and operator visual review |
| P0-044 | Worker returns status, resultPath, qaStatus and manifest path to queue | Dedicated GUI preview/output controls |

Automatic remediation, async Hunyuan, multiview, texture generation, character work,
full state machine and dependency graph are not implemented. Unreal test-map and
screenshot adapters are implemented but have not been run against the real engine.

## Configuration

`config/asset-pipeline.json` is the trusted local allowlist/configuration. Verify its
Blender and Unreal executable paths and allowed Unreal project roots before running.
Use `--config path/to/machine.local.json` for local overrides (a complete config).
The supplied executable paths come from the existing studio configuration; their
existence/version has not been assumed or verified. Python requires 3.12.

Input must be a GLB contained within `jobs_root/<taskId>`. Relative input paths are
resolved against that task directory. Traversal and symlink escape are rejected.
External GLB image/buffer URIs are rejected; resources must be embedded.
Asset name and task ID are constrained. Task-provided executable paths are ignored.

Unreal projects must explicitly enable `PythonScriptPlugin` and
`EditorScriptingUtilities`. The adapter does not edit project/plugin settings.

## Job example

Save a job outside protected runtime folders, or let the worker create its job file:

```json
{
  "schemaVersion": 1,
  "taskId": "TASK-EXAMPLE",
  "asset_name": "SM_Sword",
  "input": "hunyuan-output/hunyuan-model.glb",
  "target_size_m": 1.0,
  "rotation_x_degrees": 0,
  "pivot": "bottom",
  "project": "R:\\Onedrive\\Unreal\\NinjaFrog"
}
```

`target_size_m` sets the longest bounding-box dimension in meters. Omit it to retain
the imported scale. A value of 1.0 above is illustrative, not a historical measurement.
Rotation is an explicit X-axis adjustment; cleanup does not infer sword orientation.
The job schema is `config/asset-job.schema.json`; runtime validation uses the Python
standard library and adds filesystem/GLB checks.

## Local ALIEN validation sequence

Run from the repository root. These are instructions for the local operator; they
have not been executed against the real tool installations.

```powershell
# Validation only: no writes or external process launches.
python adapters/asset_pipeline.py asset-job.json --plan

# Blender output writes explicitly approved; stop after QA.
python adapters/asset_pipeline.py asset-job.json --approve-blender

# Reuse verified Blender outputs, then import to the configured Unreal project.
python adapters/asset_pipeline.py asset-job.json --approve-blender --approve-unreal --target unreal --resume

# Reload saved assets, run Unreal QA, and create/save a fresh test map.
python adapters/asset_pipeline.py asset-job.json --approve-blender --approve-unreal --target unreal-qa --resume

# Also render an Unreal scene preview. Requires a functioning graphics renderer.
python adapters/asset_pipeline.py asset-job.json --approve-blender --approve-unreal --target unreal-qa --capture --resume
```

Use the worker bridge after stopping older workers; it cannot lock out old versions:

```powershell
powershell -NoProfile -File tools/project-manager-worker.ps1 -Once -ProcessAssets -ApproveBlenderWrite

# Both external asset write stages approved for this invocation.
powershell -NoProfile -File tools/project-manager-worker.ps1 -Once -ProcessAssets -ApproveBlenderWrite -ApproveUnrealWrite

# Include Unreal QA, isolated test map, and offscreen preview.
powershell -NoProfile -File tools/project-manager-worker.ps1 -Once -ProcessAssets -ApproveBlenderWrite -ApproveUnrealWrite -ValidateUnreal -CaptureUnrealPreview
```

`-ValidateUnreal` enables Unreal QA and test-map creation; `-CaptureUnrealPreview`
also requests offscreen rendering. Both require `-ProcessAssets` and
`-ApproveUnrealWrite`. `-Python` chooses the Python executable; `-AssetConfig` selects the pipeline config.
`-ProcessAssets` is opt-in. Without `-ApproveBlenderWrite`, the bridge records
`WaitingForApproval` and launches no asset tool. The operator then restores
`QueuedForBlender` and restarts with the approval flag. The flags express the existing
asset-write policy; they are not a GUI approval workflow.

The worker processes `QueuedForBlender` and, with Unreal approval, `ReadyForUnreal`.
With Unreal validation enabled it also processes `ReadyForUnrealQA`; with capture
enabled it processes `AwaitingScreenshot`.
A task retried as `Queued` with an existing `hunyuanOutput` resumes asset processing
when `-ProcessAssets` is active. To regenerate changed references, use a new task ID;
the old output is protected. Optional task properties `asset_name`, `target_size_m`,
`rotation_x_degrees` and `pivot` are forwarded by the bridge.

## Outputs, retries and truthful status

Each fresh Blender attempt uses `outputs/attempt-<uuid>/` containing:

- `asset.blend`, `asset-clean.glb`, `asset.fbx`
- `preview-front.png`, `preview-side.png`, `preview-perspective.png`
- `metrics.json`, `qa.json`, `qa.md`
- `blender-job.json`, `blender.stdout.txt`, `blender.stderr.txt`
- `manifest.json`, and per-import Unreal job/report/log files when applicable

`asset-manifest.json` in the task directory points to the latest attempt. Manifests
are written atomically and include the source checksum, output checksums and status.
`--resume` reuses a completed Blender stage only when job, input, configuration,
adapter source fingerprint and all recorded artifact checksums match. Corrupted
artifacts block reuse. A failed Blender/QA attempt creates a fresh directory on retry.
A failed Unreal stage can reuse the validated Blender result. A failed Unreal
validation stage can also reuse the successful import instead of creating another
asset import. QA retries get a fresh map/report/image ID. Resume verifies recorded
evidence files; it does not detect external edits to Unreal .uasset packages.

QA failure blocks Unreal import. Non-manifold geometry and a soft triangle budget
violation are warnings; missing UV/materials/textures and hard triangle budget
violations fail by default. Policy is configurable. Normals are recalculated but
their direction is not independently verified by QA.

Successful Blender processing returns `ReadyForUnreal`. Successful import returns
`ReadyForUnrealQA`. With `--target unreal-qa`, saved StaticMeshes are reloaded in a
separate commandlet; geometry, UV, material slots, simple/convex collision and LOD
count are checked against `unreal_qa` configuration. Negative API results fail.
Default minimum LOD count is 1 (LOD0); this does not imply generated distance LODs.
After QA, a fresh map is saved under the assigned import namespace with spawned
mesh actors and dynamic lighting. An existing test map is never overwritten.

Without rendering, status is `AwaitingScreenshot`. With `--capture`, the validation
commandlet uses `-AllowCommandletRendering -RenderOffscreen` instead of `-nullrhi`.
A SceneCapture2D exports a 640x640 PNG. Empty/uniform pixel data, missing files and
non-PNG output fail the stage; render targets and transient capture actors are
released even on failure. The actor remains in the saved test map, but the capture
actor is transient and is not saved. Shader/render startup problems may require a
local retry; offscreen engine compatibility is not yet established.

Successful capture returns `AwaitingVisualReview`, never `Completed`. A pipeline
preview proves that rendering returned nonuniform data, not that the asset looks
correct. Local integration evidence and operator visual acceptance remain required
for M1. Preview PNG signature and GLB
structure checks are not a substitute for visual inspection or opening assets.

Unreal imports get a fresh namespace under `/Game/AIStudio/<task>/<Import_uuid>`.
No re-import/overwrite is attempted. Failed imports can leave partial assets there;
their namespace remains recorded for operator review. This trades a stable namespace
across retries for preservation of existing assets; controlled re-import is pending.

Both subprocesses have timeouts, per-attempt stdout/stderr and checked exit codes.
Blender uses `--python-exit-code 1`, so a Python exception cannot appear successful.
Unreal requires a success report with a StaticMesh in the assigned namespace.

The task `.asset-pipeline.lock` uses an OS-held byte/file lock. The lock file is
persistent and must not be deleted during normal operation: ownership is released
when Python exits, including forced termination. Legacy lock files from the older
exclusive-create implementation are rejected without alteration; stop older
pipelines/tool processes before an operator removes that legacy file once.
A crashed Python process can leave Blender/Unreal subprocesses alive. Automatic
release of the Python lock does not prove those tool processes have stopped; inspect
them before resuming after a forced termination. Fresh attempts/import namespaces
preserve earlier outputs.

The persistent queue `.worker.lock` also uses an OS-held handle and can be reacquired
after a crash without deleting the file. That queue lock protects this worker
version only, not GUI writers or older versions. Queue reads capture a SHA256 revision
of exactly the bytes parsed. Before publishing a new queue, the worker compares the
current file revision with its last read/write revision. If the GUI changed or deleted
the queue in the meantime, the worker stops with a revision-conflict error, preserves
the GUI data and removes its temporary write file. Reload/restart after reviewing the
conflict; do not bypass it by overwriting the queue.

Revision checking detects edits already present at the pre-write check. It is not a
fully transactional cross-process compare-and-swap: an uncoordinated GUI writer can
still race in the final check/replace window. Shared GUI/worker queue transactions
remain pending. Avoid simultaneous queue edits during worker processing.

CLI failures return a structured JSON error on stdout and readable text on stderr,
including errors before a new manifest can be written. The worker copies the current
process error into the task failure and records the manifest link before execution.
It does not substitute an older failure manifest for the current error.

## Tests and API references

```powershell
python -m unittest discover -s tests -v
```

PowerShell contract tests require `pwsh`; tests use temporary directories and mocks.
They never launch a live worker or access repository tasks/results/logs/state.
The symlink-escape case runs where the OS allows creating symlinks.

Implementation references:

- [Blender GLB import](https://docs.blender.org/api/main/bpy.ops.import_scene.html)
- [Blender export operators](https://docs.blender.org/api/5.0/bpy.ops.export_scene.html)
- [Unreal 5.7 AssetImportTask](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/AssetImportTask?application_version=5.7)
- [Unreal 5.7 FbxImportUI](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/FbxImportUI?application_version=5.7)

Additional Unreal QA API references:

- [StaticMeshEditorSubsystem](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/StaticMeshEditorSubsystem?application_version=5.7)
- [LevelEditorSubsystem](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/LevelEditorSubsystem?application_version=5.7)
- [RenderingLibrary](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/RenderingLibrary?application_version=5.7)
- [SceneCaptureComponent2D](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/SceneCaptureComponent2D?application_version=5.7)
