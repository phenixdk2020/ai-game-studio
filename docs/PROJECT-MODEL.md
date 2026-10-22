# Project manager, agents and execution backends

Updated for the unified v18 orchestrator on 2026-10-22. See
[setup and operation](ORCHESTRATOR.md). Configured roles/models are not a claim
that every provider is currently running.

## Intended model

The operator supplies a goal and references. A project manager decomposes the goal
into tasks, assigns specialist roles, tracks dependencies/approvals and chooses an
execution backend. Specialist results pass through QA before returning to the
operator. A specialist role is an instruction set and capability contract, not
necessarily a separate process or a separately trained model.

Possible execution backends have different responsibilities:

- Local language models: specification, research synthesis, planning and code/text reasoning.
- Hunyuan: mesh generation from references.
- Blender: geometry processing, rigging/animation operations, export and previews.
- Unreal: import, engine-side QA and test scenes.
- Local Copilot CLI: local repository software work, when explicitly dispatched.
- GitHub agent tasks: repository software work through GitHub and pull requests.

## Current implementation: one queue and dispatcher

| Component | Entry points | Queue/backend | What it actually does |
| --- | --- | --- | --- |
| GUI/worker | tools/project-manager-gui.ps1 and project-manager-worker.ps1 | tasks/queue.gui.json | Routes roles/backends, dependencies, plan approval and existing asset stages |
| CLI | tools/studio.py and compatibility core/studio.py | Same canonical queue | Adds tasks/plans, runs worker, approves results and explicitly imports old queues |
| Earlier entry points | gui/project-manager.ps1 and AIStudio.Queue.psm1 | Same canonical queue | Compatibility facade; no second queue writer |
| Provider adapter | adapters/project_bridge.py | Per-task receipts | Ollama, local Copilot, GitHub task dispatch/polling and isolated PR validation |
| Pinokio tools | adapters/pinokio_tools.py | pterm and registered app APIs | Discover/launch apps, transfer inputs and return verified artifacts to role tasks |

The [Pinokio tool integration](PINOKIO-TOOLS.md) now includes live-tested Hunyuan
shape generation and a real worker/queue round trip. Image and animation app
candidates can be discovered; their generation operations still need app-specific
API registration and validation.

The GUI, worker and CLI share adapters/Studio.Queue.psm1 and
adapters/Studio.Orchestrator.psm1. Historical queues are imported only on an explicit
operator command; source runtime state is not automatically migrated.

## Local model configuration

config/studio.json points to http://127.0.0.1:11434/v1 and names two profiles:

- light: qwen3.5-9b-gpu:latest
- heavy: qwen3.6:35b-a3b-coding

Historical research, character 3D, rigging, animation, QA and environment roles are
configured as light; technical research, gameplay, Unreal and integration are heavy.
Configured names do not verify model availability or hardware placement.

config/orchestrator.json defines the supported canonical roles. Common older role
IDs are normalized by the bridge; canonical instruction files are in agents/.
Older config/agents.json and config/project-manager.json are not authoritative.

The project manager proposes a bounded JSON dependency plan. Applying that plan
requires operator review. Deterministic code validates the graph and schedules ready
tasks; the LLM does not directly execute arbitrary commands or mark jobs complete.

## Copilot/GitHub bridge status

A local copilot.exe executable and gh agent-task command were found on this machine.
The subsequent [live test](COPILOT-LIVE-2026-10-22.md) verified local Copilot through
local tests and draft PR creation; cloud-agent dispatch was refused with 403 and
remains unverified end to end. Both Copilot providers use the same task/result contract. Direct standalone
dispatch helpers remain manual tools outside the authoritative queue.

Receipts record dispatch/session/PR IDs, progress, isolated checkout, exact validated
head and test evidence. Interrupted/ambiguous dispatches do not automatically start a
second session. Code approval checks the current PR head and requires manual merge
before dependencies are released. Revalidation does not dispatch another agent.
The local runner executes Blender/Unreal jobs; remote code results do not establish
local GPU/engine execution. Provider behavior is covered with fake CLIs, real local
Git/tests, and an isolated worker/HTTP integration test. Real Blender/Unreal evidence
comes from the separate synthetic-prop smoke test.
