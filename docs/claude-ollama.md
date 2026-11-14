# Claude Code gennem lokal Ollama

Vælg et registreret projekt og backend `claude-ollama` i Project Manager.
Genåbn Project Manager efter installation for at indlæse den nye valgmulighed.
Copilot forbliver standard; automatisk kodevalg med `prefer-ollama` eller
`offline-only` kan vælge Claude, når CLI og den konfigurerede model findes.
`ollama` alene er fortsat tekst-/planagenten.

Konfigurer i `config/orchestrator.json`:

```json
{
  "claude_executable": "claude",
  "claude_ollama": {
    "base_url": "http://127.0.0.1:11434",
    "model": "qwen3.6:35b-a3b-coding"
  }
}
```

Modellen skal allerede være installeret lokalt og understøtte tool calling.
Brug mindst 64k kontekst til Claude Code. Adapteren ændrer ikke Ollamas globale
opsætning og downloader ikke modeller. Claude Code skal understøtte `--restricted`.
`context_tokens` er som standard 65536 og `max_output_tokens` 8192. De overføres
til Claudes lokale kontekst-/svargrænser, så en ukendt Ollama-model ikke behandles
som en model med 200k kontekst. Indstil værdierne efter Ollamas faktiske kontekst.
Strukturerede CLI-fejl vises nu med deres egentlige årsag i opgaven.

Claude får Read/Edit/Write/Glob/Grep i den isolerede projektkopi. CLI-sessionen
bruger en separat konfigurationsmappe, loopback-API, ingen bruger-/projektindstillinger,
kun Studios opgavespecifikke MCP-server og ingen shellværktøjer. Studios eksisterende runner kører
projektets konfigurerede testkommandoer bagefter. Testkommandoer er kodekørsel
og følger projektets sædvanlige tillidsmodel.

Lokale projekter afleverer diff, testresultat og review til manuel godkendelse;
originalmappen ændres først ved godkendelse. GitHub-projekter bruger en separat
checkout og afleverer draft-PR gennem Studio. Modellen publicerer ikke selv.

Vedhæftede Markdown-/tekstfiler kopieres ind i arbejdskopien som designreferencer
(højst 5 MB samlet). De oprindelige referencefiler ændres ikke. Kopierne udelukkes
fra Git-diff og overførsel til spilprojektet; originalsti og SHA256 gemmes som evidens.
Manglende vedhæftede tekstfiler blokerer udførsel, indtil de er rettet.

Session-ID, model og endpoint gemmes i receipt før udførsel. Ved timeout eller
uklart svar bliver opgaven `NeedsInput`; den sendes ikke automatisk igen.
Efter manuel kontrol kan eksisterende ændringer genvalideres. Ændret model,
endpoint eller opgave kræver en ny opgaveversion.

## Bestilling af Pinokio-arbejde

`claude_ollama.tool_capabilities` aktiverer et udsnit af det registrerede katalog.
Installationsprogrammet aktiverer `image_generation`, `image_to_3d` og `animation`.
Uregistrerede operationer afvises; apps installeres ikke automatisk.

Claude får værktøjerne `studio_list_tools`, `studio_submit_tool`,
`studio_tool_status`, `studio_wait_tool` og `studio_copy_artifact`.
Bestillinger får et stabilt request-ID, samme projekt som kodeopgaven og en separat
Pinokio-opgave i køen. Gentagelse af samme bestilling sender ikke jobbet igen.
Studios eksisterende PowerShell-køskriver håndterer alle køændringer.

En særskilt executor starter Studios normale Pinokio-adapter, så den synkrone
kode-worker ikke blokerer værktøjsarbejdet. Højst 12 bestillinger pr. kodeopgave.
GPU-bestillinger udføres én ad gangen i denne executor. Under generering venter
Claude, og dens Ollama-model frigives; efter ComfyUI-generering frigives vores
jobs cachede ComfyUI-modeller. Andre workers/apps bruger fortsat deres egen
ressourcestyring, så dette er ikke en global GPU-scheduler.

Artefakter kan først kopieres efter afsluttet værktøjsudførsel og kun med korrekt
SHA256 og registreret filtype, til en ny fil i den isolerede projektkopi.
Resultatet er foreløbigt indtil brugerens review. Studio kræver godkendelse af
de importerede værktøjsresultater, før kodeændringerne kan godkendes og anvendes.

`tools/install-claude-ollama.py --root <installation> --model <lokal-model>`
installerer adapteren med backup og bevarer den nyere GUI/worker samt projektregister.

Dokumentation: https://docs.ollama.com/integrations/claude-code og
https://code.claude.com/docs/en/cli-reference.
