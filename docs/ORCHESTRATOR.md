# Samlet projektleder og agenter – v18

Alle offentlige startpunkter bruger nu `tasks/queue.gui.json` gennem samme
transaktionsmodul. `core/studio.py`, den tidligere GUI i `gui/` og
`AIStudio.Queue.psm1` sender videre til den fælles styring. Ingen eksisterende
kø bliver automatisk importeret. Der er én worker pr. kø, og afhængigheder
frigives først, når deres forældre står som `Completed`.

## Roller og udførelse

Projektlederen bruger rollen `project_manager` til at foreslå 1–12 konkrete
delopgaver med roller, backends og afhængigheder. Planen får status
`AwaitingPlanReview`; knappen **Godkend resultat / plan** tilføjer delopgaverne
atomisk. Modellen kan foreslå arbejde, men dens tekst tæller ikke som udført kode
eller valideret spilindhold.

| Backend | Udførelse | Resultat |
|---|---|---|
| `ollama` | Lokale modeller og rolleprompts fra `agents/` | Tekst eller plan til gennemgang |
| `copilot-local` | Installeret Copilot CLI i separat Git-checkout | Testet kode og draft-PR |
| `copilot-github` | `gh agent-task create`, efterfølgende session-polling | PR hentet til separat checkout og testet lokalt |
| `asset3d` | Eksisterende Hunyuan → Blender → QA → Unreal | Model, previews, QA og importbeviser |

Modeller og rollefordeling læses fra `config/studio.json`. Repository, basegren,
CLI-programmer, timeout, polling og testkommandoer læses fra
`config/orchestrator.json`. Testkommandoer er faste argv-lister fra denne lokale
konfiguration. Godkendte afhængigheders resultater og PR-links sendes med til
efterfølgende specialister. Lokale referencestier kan ikke læses af cloud-agenten;
læg nødvendige cloud-referencer i repositoryet.

## Start fra Windows

```powershell
& C:\ai-game-studio\tools\start-project-manager.ps1
```

Vælg backend og agentrolle, skriv opgaven og gem. Brug **Lav plan** til at lade
projektlederen opdele en større opgave. Opgave-ID'er i feltet afhængigheder
adskilles med komma. Afkryds **Copilot / lokale modeller**, før workeren skal
kalde disse tjenester. Blender- og Unreal-trin har deres egne afkrydsninger.
Unreal QA/preview kræver både behandling af 3D og tilladelse til Unreal-skrivning.
Start workeren igen efter ændring af afkrydsningerne.

**Åbn PR** viser kode til gennemgang. Merge PR'en manuelt efter gennemgang,
og godkend derefter opgaven. Godkendelsen kontrollerer, at den testede SHA
stadig er PR'ens head, og at PR'en er merged. Det sikrer, at næste kodeopgave kan
hente forældrenes ændringer fra basegrenen. **Validér PR igen** tester en opdateret
PR uden at oprette en ny Copilot-session. Den lokale hovedinstallation opdateres
fortsat med det eksisterende update-flow; test-checkouts erstatter den ikke.

## CLI

```powershell
python tools/studio.py plan "Lav spillets hovedmenu"
python tools/studio.py add "Undersøg uniformer" --backend ollama --role historical_research
python tools/studio.py add "Implementér menu" --backend copilot-github --role gameplay
python tools/studio.py add "Ret lokal kode" --backend copilot-local --role integration
python tools/studio.py run --specialists
python tools/studio.py run-all --specialists
python tools/studio.py status
python tools/studio.py approve TASK-ID
```

`run` behandler én klar opgave. `run-all` fortsætter med at vente/polle indtil
processen stoppes. Ollama-serveren skal være startet med modellerne fra
`config/studio.json`. Copilot kræver installeret/login-klar `copilot`; GitHub
kræver `gh`, login, rettigheder og adgang til coding agent. Git og identitet til
commits skal være konfigureret. Eventuelle tjenesteomkostninger følger kontoen.

## Afbrudte sessioner og gamle køer

Kvitteringer, session-ID, PR-link, checkout og testresultater ligger i
`data/pipeline-jobs/<ID>/bridge/`. En tvetydig dispatch eller afbrudt lokal session
giver `NeedsInput` og bliver ikke sendt igen automatisk. `recover` flytter kun
`Running` til `NeedsInput`; det stopper ikke eventuelle eksterne processer.

Hvis en GitHub-dispatch blev gennemført uden et læsbart svar, kan dens eksisterende
session/PR forbindes eksplicit efter kontrol i GitHub:

```powershell
python adapters/project_bridge.py data/pipeline-jobs/TASK-ID/bridge-task.json --approve-dispatch --bind-pr https://github.com/OWNER/REPO/pull/123 --bind-session SESSION-ID
python adapters/project_bridge.py data/pipeline-jobs/TASK-ID/bridge-task.json --approve-dispatch --revalidate
```

Brug den konfigurerede repositoryadresse. Ændrede opgaveinput efter dispatch
kræver en ny opgave, så den gamle kvittering bevares.

Gamle køer kan først forhåndsvises og derefter importeres bevidst. Identiske ID'er
springes over; gamle statusnavne, referencer og afhængigheder normaliseres.

```powershell
python tools/studio.py import-legacy data/queue.json
python tools/studio.py import-legacy data/queue.json --apply
python tools/studio.py import-legacy tasks/queue.json --apply
```

Legacy-API'en afviser direkte færdigmelding og gammel global pause; brug
resultatgodkendelse samt GUI'ens opgavepause og worker-stop.

## Kontrol

Testene dækker dispatch, session-polling, genoptagelse uden dobbeltafsendelse,
PR-SHA, beskyttede runtime-stier, testfejl, lokal Copilot-kommando, planer,
afhængigheder, migration, CLI og WPF-kontroller. En isoleret integrationstest
kører den rigtige worker, køtransaktioner og adapter mod en lokal HTTP-testserver
og godkender resultatet. Copilot-udbyderne simuleres; testen starter ingen betalte
Copilot-opgaver. Den tidligere virkelige Blender/Unreal-validering er beskrevet i
[integrationsrapporten](INTEGRATION-2026-10-22.md).
