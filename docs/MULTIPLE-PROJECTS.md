# Flere spilprojekter

Start `Start-AI-GAME-STUDIO.cmd` for Project Manager. Feltet **Spilprojekt**
vælger projekt for den enkelte opgave. **Nyt projekt...** registrerer et nyt
projekt med navn, stabilt ID, GitHub-repository, basisgren, valgfrie lokale
projektstier og projektets testkommandoer. Repositoryet skal eksistere først;
registrering opretter ikke et GitHub-repository eller et Unreal-projekt.

Projektlisten gemmes i `config/projects.json`. Listen starter tom, så Studio
ikke gætter et repository. Eksisterende opgaver flyttes ikke til et projekt.
Kodeopgaver og planer uden et registreret projekt bliver afvist. Research
uden projekt kan stadig køres gennem CLI. Gamle konfigurationer uden
`require_project` beholder deres udtrykkelige legacy-adfærd.

Hvert projekt har egne testkommandoer. De skal passe til projektets engine
og buildsystem; Studioets Python-tests bruges ikke automatisk til spillet.
Kommandoerne er argumentlister, ikke shelltekst. Eksempel for et Python-spil:

```json
[["python", "-m", "unittest", "discover", "-s", "tests"]]
```

Kodeagenten kloner det valgte projekts repository til et isoleret checkout,
opretter en opgavegren og afleverer en draft-PR i samme repository. Den
ændrer ikke automatisk den lokale spilmappe eller merger kode. Projektets
egen `AGENTS.md` gælder i checkoutet. Eksisterende Studio-kontroller for
beskyttede mapper gælder fortsat også i spilprojekter.

CLI-eksempel (tilpas repository, gren og tests):

```powershell
python tools/studio_projects.py add rumspil --name "Rumspil" --repository "ejer/rumspil" --validation-json '[["python","-m","unittest","discover"]]'
python tools/studio.py plan "Byg en lille spilbar prototype" --project-id rumspil
```

Planers delopgaver arver operatørens projektvalg; en models forslag kan ikke
skifte repository. Afhængigheder mellem forskellige projekter frigives ikke.
Ændres projekt, repository, gren eller testkommandoer efter afsendelse,
kan en gammel kvittering ikke genbruges. Opgaver uden projekt skal vælges
og tilknyttes det rigtige projekt før ny afsendelse; allerede afsendte opgaver
skal afsluttes i deres oprindelige konfiguration eller erstattes med nye.

Agent Control Center (SQLite) er fortsat et separat system. Dette projektvalg
gælder Project Manager/JSON-køens kode- og planforløb. Registrering og offline
tests beviser ikke, at et helt spil kan bygges automatisk; første reelle opgave
skal verificere det valgte projekts værktøjer og tests.
