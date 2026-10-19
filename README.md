# AI Game Studio 1864 v9

V9 is a STATE-SAFE UPGRADE package. It intentionally contains NO `tasks` directory and NO `results` directory. Therefore simply extracting the archive cannot overwrite `tasks\queue.json` or existing agent results.

Recommended upgrade:
1. Extract V9 to a temporary folder.
2. Run `tools\install-v9.ps1` from the extracted V9 folder.
3. The installer copies program/config files to `C:\ai-game-studio`, explicitly excludes `tasks` and `results`, and also backs up existing state first.

After upgrade:
`python .\core\studio.py setup`
`python .\core\studio.py status`

Do NOT run `plan` for the existing Dansk infanterist workflow, because the existing queue already contains that work.
