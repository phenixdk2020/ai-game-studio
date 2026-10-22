# AI Game Studio 1864 v11.0

## Unified project manager v18

Project planning, specialist roles, Ollama, local Copilot, GitHub Copilot and the
Blender/Unreal asset pipeline now share one queue and result contract.
Automatic coding tasks and newly generated plans use local Copilot by default.
Start `tools/start-project-manager.ps1` or use `python tools/studio.py`.
See [the integrated workflow and setup](docs/ORCHESTRATOR.md).
Agents can also use [Pinokio app tools](docs/PINOKIO-TOOLS.md), including a live-tested
Hunyuan image-to-GLB operation with upload, result download and artifact hashes.
ComfyUI image tasks use a registered text-to-image workflow with installed-model
selection, persistent prompt IDs, PNG validation and explicit result resumption.

## Prop pipeline development

The opt-in worker asset pipeline adds Blender prop cleanup/export, three previews,
structured QA, and Unreal StaticMesh import, saved-mesh QA, isolated test-map and
optional offscreen screenshot adapters. See
[setup, approvals, local validation and remaining M1 work](docs/PROP-PIPELINE.md).
A real synthetic-prop smoke test has exercised Blender and Unreal; see
[local integration evidence](docs/INTEGRATION-2026-10-22.md). Asset-specific M1 evidence is still required. The existing v11
skeleton job workflow below remains available.

Real V11 adds the first controlled Blender execution adapter.

- Existing `tasks/`, `results/`, `logs/`, `state/` remain local and are not part of this update payload.
- Blender jobs run headless and produce evidence logs in `C:\ai-game-studio-workspace\blender`.
- Asset writes are denied by default. `--approve-write` / `-ApproveWrite` is required for a job declaring `write_asset=true`.
- `make-skeleton-job.ps1` creates a starter humanoid skeleton job specification; `blender-job.ps1` executes it only with explicit write approval.
- Git update/release scripts handle Git stderr without treating normal push/pull progress as a PowerShell failure.

Example:

```powershell
C:\ai-game-studio\tools\make-skeleton-job.ps1
C:\ai-game-studio\tools\blender-job.ps1 -Job C:\ai-game-studio-workspace\jobs\skeleton_stub.json -ApproveWrite
```

## Automated tests

Run the standard-library unit tests from the repository root with Python 3.12:

```powershell
python -m unittest discover -s tests -v
```

The suite does not require Ollama, Blender, or Unreal Engine. Blender adapter tests use temporary directories and a mocked process runner; repository runtime folders (`tasks/`, `results/`, `logs/`, and `state/`) remain ignored and are not used by the tests.
