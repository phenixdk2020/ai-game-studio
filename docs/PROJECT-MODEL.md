# Project manager, agents and execution backends

This describes the code/configuration observed on 2026-10-22, not a claim that every
configured role or model is running.

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

## Current implementation: three partially overlapping tracks

| Track | Entry points | Queue/backend | What it actually does |
| --- | --- | --- | --- |
| Prop GUI/worker | tools/project-manager-gui.ps1 and project-manager-worker.ps1 | tasks/queue.gui.json | Fixed Hunyuan → Blender → QA → Unreal path; asset stages are opt-in with write approvals |
| Python planner | core/studio.py and core/runtime.py | tasks/queue.json and Ollama-compatible API | Creates a predefined task dependency plan, loads role prompts, routes local models and runs ready tasks |
| Earlier project manager | gui/project-manager.ps1 and AIStudio.Queue.psm1 | data/queue.json and local Copilot command | Keyword-based role selection, local CLI invocation and review/retry status |

The prop GUI and its worker now share the transaction/revision/merge implementation
in adapters/Studio.Queue.psm1. That does not unify the other two queues.

## Local model configuration

config/studio.json points to http://127.0.0.1:11434/v1 and names two profiles:

- light: qwen3.5-9b-gpu:latest
- heavy: qwen3.6:35b-a3b-coding

Historical research, character 3D, rigging, animation, QA and environment roles are
configured as light; technical research, gameplay, Unreal and integration are heavy.
Configured names do not verify model availability or hardware placement.

config/agents.json separately defines seven role records: research, Blender, rigging,
animation, Unreal, QA and project manager. Other lists include additional role IDs.
Those naming differences and routing contracts remain to be reconciled.

The current project-manager prompt asks its specialist to record evidence and
describe child tasks when another specialty is needed. It does not implement a full
autonomous planner/dispatcher by itself. The prop worker's routing is ordinary code,
not an LLM autonomously controlling all listed agents.

## Copilot/GitHub bridge status

A local copilot.exe executable and gh agent-task command were found on this machine.
No Copilot task was started as part of this inspection. Existing code contains both
a local Copilot invocation and a tools/start-github-copilot-task.ps1 dispatch helper.
config/project-manager.json also contains a Copilot enabled=false flag; these older
paths are not one consolidated, uniformly configured backend.

A complete bridge still needs one authoritative task contract, dispatch/session/PR
IDs, remote progress collection, controlled checkout of returned code, local tests,
tool validation and result reconciliation. The bridge should exchange code and job
manifests through Git/PRs. The local runner executes machine-specific Blender/Unreal
jobs and returns evidence; a GitHub task is not treated as proof of local GPU/engine
execution. This bridge was not implemented or exercised in the prop smoke test.
