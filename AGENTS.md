# AI Game Studio Agent Rules

GitHub Copilot is responsible for software engineering in this repository.

Allowed software work:
- Python
- PowerShell
- configuration schemas
- tests
- documentation
- adapters
- orchestrator refactoring

Do not assume access to local Ollama models, Blender execution, Unreal Engine execution, runtime state, or generated game assets.

ALIEN is responsible for Ollama inference, Blender execution, Unreal execution, GPU workloads, generated assets, and local integration evidence.

Never touch tasks/, results/, logs/, or state/.
Never force-push main.
Use pull requests for coding-agent changes.