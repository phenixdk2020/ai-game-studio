# AI Game Studio 1864 v11.0

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

Run the unit suite with Python 3.12 or newer from the repository root:

```powershell
python -m unittest discover -s tests -v
```

The tests cover studio configuration and model routing, task dependency readiness,
UTF-8 queue loading (with and without a BOM), runtime-state isolation, and Blender
job validation and write-approval enforcement. They do not require Blender,
Unreal Engine, or an Ollama server; external execution is not performed by the
unit suite. GitHub Actions runs the same suite on pushes and pull requests.
