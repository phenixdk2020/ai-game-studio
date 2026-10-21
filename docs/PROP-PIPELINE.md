# Prop pipeline implementation and local validation

Status: software implementation with isolated automated tests. No actual Hunyuan,
Blender or Unreal execution has been performed by this coding agent. M1 is pending.

## Implemented backlog slices

| Backlog | Implementation | Remaining evidence/work |
| --- | --- | --- |
| P0-001 | Worker reads legacy arrays, single tasks and value/Count wrappers; removes null entries; adds schemaVersion/defaults; atomically writes UTF-8 arrays | GUI uses its existing writer; cross-process GUI edit conflicts remain |
| P0-002 | Exclusive OS-held worker lock with PID/version; process death releases handle | GUI version indicator; existing older workers do not honor this lock |
| P0-004 | Task-local immutable attempt directories, checksums, metadata and manifests | Retention/cleanup policy |
| P0-010 | Raw Base64, content type and GLB validation, rejected response preservation | Real API compatibility and Blender readability |
| P0-020/021/022 | GLB import, preserve transforms, join prop meshes, remove loose vertices, recalculate normals, optional size/orientation, center/bottom pivot | Actual Blender run and visual inspection |
| P0-026 | Three orthographic CPU-rendered PNG previews | Visual inspection on a real mesh |
| P0-030/031 | QA JSON/Markdown with thresholds and an import gate | Artistic/visual quality, normal direction, scale against references |
| P0-040/041 | Allowed project roots, unambiguous .uproject, explicit plugins, automated FBX StaticMesh import, dependency save, fresh namespace | Actual Unreal 5.7 integration run |
| P0-042 | Requests automatic collision and imports materials/textures | Collision/LOD verification, Nanite policy, texture fidelity |
| P0-044 | Worker returns status, resultPath, qaStatus and manifest path to queue | Dedicated GUI preview/output controls |

Automatic remediation, async Hunyuan, multiview, texture generation, character work,
full state machine, dependency graph, test levels and screenshots are not implemented.

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
```

Use the worker bridge after stopping older workers; it cannot lock out old versions:

```powershell
powershell -NoProfile -File tools/project-manager-worker.ps1 -Once -ProcessAssets -ApproveBlenderWrite

# Both external asset write stages approved for this invocation.
powershell -NoProfile -File tools/project-manager-worker.ps1 -Once -ProcessAssets -ApproveBlenderWrite -ApproveUnrealWrite
```

`-Python` chooses the Python executable; `-AssetConfig` selects the pipeline config.
`-ProcessAssets` is opt-in. Without `-ApproveBlenderWrite`, the bridge records
`WaitingForApproval` and launches no asset tool. The operator then restores
`QueuedForBlender` and restarts with the approval flag. The flags express the existing
asset-write policy; they are not a GUI approval workflow.

The worker processes `QueuedForBlender` and, with Unreal approval, `ReadyForUnreal`.
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
A failed Unreal stage can reuse the validated Blender result.

QA failure blocks Unreal import. Non-manifold geometry and a soft triangle budget
violation are warnings; missing UV/materials/textures and hard triangle budget
violations fail by default. Policy is configurable. Normals are recalculated but
their direction is not independently verified by QA.

Successful Blender processing returns `ReadyForUnreal`. Successful import returns
`ReadyForUnrealQA`, never `Completed`. Test-level, screenshot, collision/LOD checks
and GUI preview acceptance are still required for M1. Preview PNG signature and GLB
structure checks are not a substitute for visual inspection or opening assets.

Unreal imports get a fresh namespace under `/Game/AIStudio/<task>/<Import_uuid>`.
No re-import/overwrite is attempted. Failed imports can leave partial assets there;
their namespace remains recorded for operator review. This trades a stable namespace
across retries for preservation of existing assets; controlled re-import is pending.

Both subprocesses have timeouts, per-attempt stdout/stderr and checked exit codes.
Blender uses `--python-exit-code 1`, so a Python exception cannot appear successful.
Unreal requires a success report with a StaticMesh in the assigned namespace.

The task `.asset-pipeline.lock` prevents two asset runs for one task. If an operator
terminates Python forcibly, verify Blender/Unreal are stopped before removing that
task lock. The persistent queue `.worker.lock` uses an OS-held handle and can be
reacquired after a crash without deleting the file. The queue lock protects this
worker version only, not GUI writers or older versions. Do not edit the queue from
the GUI during a long worker operation until shared queue coordination is added.

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
