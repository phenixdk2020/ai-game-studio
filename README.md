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

Run the standard-library unit tests from the repository root with Python 3.12:

```powershell
python -m unittest discover -s tests -v
```

The suite does not require Ollama, Blender, or Unreal Engine. Blender adapter tests use temporary directories and a mocked process runner; repository runtime folders (`tasks/`, `results/`, `logs/`, and `state/`) remain ignored and are not used by the tests.
