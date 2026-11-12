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

Claude får Read/Edit/Write/Glob/Grep i den isolerede projektkopi. CLI-sessionen
bruger en separat konfigurationsmappe, loopback-API, ingen bruger-/projektindstillinger,
ingen MCP-servere og ingen shellværktøjer. Studios eksisterende runner kører
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

`tools/install-claude-ollama.py --root <installation> --model <lokal-model>`
installerer adapteren med backup og bevarer den nyere GUI/worker samt projektregister.

Dokumentation: https://docs.ollama.com/integrations/claude-code og
https://code.claude.com/docs/en/cli-reference.
