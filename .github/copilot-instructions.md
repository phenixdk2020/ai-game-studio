# AI Game Studio 1864 - GitHub Copilot Instructions

## Purpose
AI Game Studio is a local multi-agent development and production orchestrator for an Unreal Engine game set in 1864.

## Local production machine
ALIEN runs Windows, Python, Git, Ollama, Blender 5.2, Unreal Engine 5.7, Visual Studio C++, and FFmpeg.
Do not assume the GitHub cloud environment can access ALIEN or its local applications/assets.

## Architecture
Roles: Project Manager, Historical Research, Technical Research, Gameplay Developer, Character 3D, Rigging, Animation, Art/World, Unreal Integration, QA, Integration, Environment.

## Source controlled
agents/, adapters/, config/, core/, tools/, tests/, .github/, AGENTS.md, README.md

## Local runtime state - NEVER modify, add, delete, commit, or relocate
- tasks/
- results/
- logs/
- state/

## Generated assets
Generated production assets belong under C:\ai-game-studio-workspace, not inside this repository.

## Blender and Unreal
Never claim Blender or Unreal execution succeeded unless actual execution evidence is available.
Production asset writes require explicit approval.

## Git
Never force-push. Coding agents must work on feature branches and deliver pull requests rather than changing main directly.

## Quality
For each change: explain implementation, add/update appropriate tests, run available repository tests, report exactly which tests ran, and never invent execution evidence.