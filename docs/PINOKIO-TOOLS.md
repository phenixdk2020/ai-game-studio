# Pinokio-værktøjer for agentrollerne

Pinokio er nu en udførelsesbackend ved siden af Ollama og Copilot. Rollen vælger
en værktøjskapabilitet og en registreret handling. Den fælles adapter finder appen
med `pterm search`, læser status, starter den gennem `pterm run`, venter på readiness
og foretager en probe før API-kald. Den starter ikke appens interne Python direkte.

Konfigurationen er `config/pinokio-tools.json`; adapteren er
`adapters/pinokio_tools.py`. Backendens opgaver får kvitteringer og review-status
gennem `adapters/project_bridge.py` og den fælles worker. Også det eksisterende
`asset3d`-forløbs Hunyuan-trin bruger nu den fælles Pinokio-adapter.

## Hvad er tilsluttet?

| Kapabilitet | Roller | Udførelse |
|---|---|---|
| `image_to_3d` | Projektleder, character3d, environment, art_world, integration, QA | Hunyuan `generate_shape` er forbundet og afprøvet med en rigtig GLB |
| `image_generation` | Projektleder, character3d, environment, art_world, integration, QA | ComfyUI `generate_image`: fast tekst-til-billede-workflow, PNG og jobkvittering |
| `animation` | Projektleder, rigging, animation, integration, QA | Mesh2Motion-kandidater kan findes; rigging/animation er endnu ikke tilsluttet som udførelse |

Søgeresultater er kandidater, ikke bevis for at en app kan udføre en bestemt
handling. En model kan ikke opfinde et endpoint: kun handlinger i den lokale
konfiguration kan kaldes. `inspect` læser en apps dokumenterede Gradio- eller
ComfyUI-API. Hver protokol har sin egen klient. Konfigurationens `supported_apps`
afgrænser de apps, som en registreret handling kan bruge; en kørende 3D-app bliver
derfor ikke valgt som billedgenerator alene på grund af et bredt søgematch.
En manglende/ændret API-kontrakt giver en fejl frem for en intern CLI-fallback.

## Brug i projektlederen

Vælg backend `pinokio` og eksempelvis rollen `character3d`. Angiv:

- Værktøj: `image_to_3d`.
- Handling: `generate_shape`.
- Vedhæft en reference som første fil. Adapteren overfører den automatisk til appen.
- Parametre: `{}` bruger standarderne; eksempelvis `{"steps":5,"octree_resolution":128}` kan overstyre dem.
- App-ID kan angives for at vælge en bestemt installeret kandidat.

Aktivér **Agenter / Pinokio / Copilot** og start workeren. **Vis Pinokio-værktøjer**
viser roller, handlinger og appsøgninger i feedbackfeltet. Værktøjsresultatet får
`AwaitingVisualReview`, før det kan godkendes. Inputændringer efter udførelse
kræver en ny opgave. Planlæggeren får de tilladte værktøjer i sine instruktioner
og kan foreslå Pinokio-delopgaver med samme felter.

## CLI

Kør fra repositoryet:

```powershell
python tools/pinokio.py catalog
python tools/pinokio.py discover image_to_3d
python tools/pinokio.py inspect image_to_3d --approve-launch
python tools/studio.py add "Lav en prop fra referencen" --backend pinokio --role character3d --tool image_to_3d --operation generate_shape --attachment C:\references\prop.png
python tools/studio.py run --specialists
```

## Billedgenerering med ComfyUI

Vælg rollen `art_world` eller en anden tilladt billedrolle, backend `pinokio`,
værktøjet `image_generation` og handlingen `generate_image`. Parametre kan være:

```json
{"prompt":"A blue wooden crate, isolated on a neutral background","checkpoint":"an-installed-model.safetensors","width":512,"height":512,"steps":20,"seed":1234}
```

Checkpoint-navnet skal findes i appens `/object_info/CheckpointLoaderSimple`.
`inspect`-opgaven viser de installerede muligheder. Ved mere end én model kræves
et eksplicit valg. Klienten downloader ingen model og accepterer ikke vilkårlige
workflows fra modellen. Det faste workflow understøtter almindelige Stable
Diffusion/SDXL-checkpoints; Flux- og videomodeller kræver særskilte workflows.

ComfyUI-jobbet gemmes med prompt-ID og workflow, hvorefter `/history/<ID>` følges
og resultatet hentes fra `/view`. PNG-struktur og chunk-checksummer kontrolleres.
En timeout starter ikke en ny generering. Brug **Hent værktøjsresultat igen** eller:

```powershell
python tools/studio.py resume-tool TASK-ID
python tools/studio.py run --specialists
```

Genoptagelse kræver en kvittering for et faktisk indsendt job. En tvetydig dispatch
skal afklares i appen først. Ændrede input kræver en ny opgave. Hunyuan og ComfyUI
bruger samme review-kontrakt, selv om deres API-protokoller er forskellige.
Under ventetiden skriver klienten `tool-progress.json` med job-ID og forløbet tid.
GUI'ens feedbackfelt læser denne status for en kørende opgave; der vises ingen
opdigtet procent for indlæsning eller generering.

Pinokios kontrolplan skal være tilgængeligt. `pterm` findes fra Pinokios
konfigurerede home eller PATH; Windows-scriptet kaldes gennem PowerShell, så
argumenterne ikke sammensættes til en batch-kommando. En utilgængelig kontrolplan
rapporteres særskilt fra et manglende `pterm`. Adapteren installerer/opdaterer
ingen apps og stopper ikke den kørende app. Kold Hunyuan-opstart tog mere end tre
minutter i testen; værktøjet har derfor en særskilt opstartsgrænse på 900 sekunder.

## Resultater og genoptagelse

Gradio-filer uploades gennem appens upload-API. Kaldets event-ID gemmes før
resultatstrømmen følges. Et tvetydigt eller afbrudt kald genafsendes ikke automatisk.
Filer hentes fra appens egen origin, og GLB-strukturen valideres før publicering.
Resultatfiler registreres med størrelse og SHA-256. Ændrede inputfiler eller
manglende/ændrede gemte resultater giver fejl frem for en ny skjult generering.

Kvitteringerne ligger i opgavens isolerede mappe som `tool-call.json`,
`tool-result.json`, `artifact-*.glb` og eventuelt `tool-error.json` med Pinokio-log.
En API-fejl med null fejldetaljer er derfor ikke tilstrækkelig til at erklære
genereringen gennemført.

## Virkelig validering 2026-10-22

Pinokios kontrolplan blev startet, hvorefter Hunyuan blev fundet og startet med
launcherens `start.js?profile=4`. Den annoncerede Gradio-API blev læst fra den
kørende app, og en billig indstillingsoperation blev udført gennem HTTP/SSE.

En syntetisk blå prop-reference blev derefter sendt gennem en rigtig
`character3d`-opgave med backend `pinokio`:

- Opgave `PINOKIO-LIVE-SHAPE-2`, Gradio-event `117ac163f3104cdb95ec103b6623ea81`.
- 5 samplingtrin, resolution 128, seed 1234, ingen teksturgenerering.
- 17.854 vertices og 35.704 flader ifølge appens mesh-statistik.
- Hentet GLB: 643.928 bytes.
- SHA-256: `28f8cc200a8c331fac9f626a41c0f415b46b65769b8024e8cbdfda6e8284beee`.
- Resultat: `AwaitingVisualReview`; en gyldig fil er ikke det samme som godkendt assetkvalitet.

Et tidligere forsøg med ét samplingtrin/resolution 64 gav ingen udtrækkelig
overflade. Fejlen blev bevaret som en separat opgave. Det er ikke automatisk
genkørsel eller en vellykket kvalitetsprøve.

Den rigtige worker og CLI blev desuden kørt mod en isoleret testkø med den
kørende app. `decode_settings` gik gennem `Queued` → `AwaitingVisualReview` →
`Completed` efter eksplicit testgodkendelse. Produktionskøer blev ikke læst eller
ændret. Andre apps blev søgt frem, men ikke startet eller erklæret fungerende.
