# Flere spilprojekter: GitHub eller lokal mappe

Start `Start-AI-GAME-STUDIO.cmd` for Project Manager. Vaelg **Nyt projekt...**,
registrer et projekt og vaelg det under **Spilprojekt** for hver opgave.
Beskriv opgaven, klik **Lav plan**, start workeren og gennemgaa planen foer
**Godkend resultat / plan** opretter dens delopgaver.

## Projektets placering

- **GitHub:** registrer ejer/repository, basisgren og projektets testkommandoer.
  Repositoryet skal eksistere. Kodeagenten arbejder i et separat checkout,
  koerer eventuelt konfigurerede tests og afleverer en draft-PR. Der merges ikke automatisk;
  PR'en skal vaere gennemgaaet og merged foer opgaven kan godkendes som faerdig.
- **Lokal mappe:** vaelg en eksisterende mappe, som ogsaa gerne maa vaere tom.
  Den behoever hverken Git-repository, GitHub-remote eller GitHub-login. Studio
  kopierer kildefilerne til en separat arbejdskopi, bruger lokal Git til at
  registrere forskellene, koerer den installerede Copilot CLI og projektets
  eventuelt konfigurerede tests. Projektets oprindelige mappe aendres foerst ved din godkendelse.

Et lokalt projekts placering betyder ikke, at modeltjenesten er offline.
Copilot CLI bruger fortsat sin egen login-/modeltjeneste. Git er noedvendig
paa computeren til sammenligning af lokale kodeaendringer; Studio opretter
ikke `.git` i dit oprindelige spilprojekt.

Projektlisten ligger i `config/projects.json`. Den starter tom; Studio gaetter
ikke et repository. Projekter uden `kind` i en aeldre registrering behandles
som GitHub-projekter. Kode og planer uden projektvalg afvises. Eksisterende
opgaver flyttes ikke til et andet projekt, og Agent Control Center/SQLite er
fortsat et separat system.

## Lokalt kodearbejde og godkendelse

1. Arbejdskopien indeholder projektets kildefiler. Almindelige bygge-/enginecaches,
   Git-metadata, `.env`-filer og Studio-runtime-mapper udelades. Links/junctions
   i de inkluderede projektfiler afvises. Der kan derfor vaere projektspecifikke
   afhaengigheder, som skal installeres eller goeres tilgaengelige for kopien.
2. **Aabn resultat** viser `review.md` med aendrede filer, arbejdskopi, diff og
   testresultater. Gennemse `changes.patch` og selve koden.
3. **Godkend resultat / plan** er den udtrykkelige godkendelse af at overfoere
   lokale aendringer. Studio kontrollerer den validerede kodeversion,
   arbejdskopien og originalens filindhold. Ved konflikt overskrives originalen
   ikke; opret en ny opgave fra den opdaterede projektmappe.
4. Originale aendrede/slettede filer sikkerhedskopieres under opgavens
   `bridge/local-backup/original/` foer overfoersel. Ved almindelige skrivefejl
   rulles allerede anvendte filer tilbage. `application.json` dokumenterer
   status. Ved procesnedbrud eller samtidige eksterne redigeringer kan manuel
   gendannelse vaere noedvendig; et ufærdigt forloeb genanvendes ikke blindt.
5. En faerdig lokal opgave bliver foerst `Completed`, naar anvendelsen er
   verificeret. Efterfoelgende opgaver kan derefter kopiere den opdaterede mappe.

Godkend ikke, mens projektet aendres af en anden editor eller worker. Kun Studio
respekterer sin egen projektlaas; andre programmer kan fortsat redigere filer.
GitHub cloud-Copilot afvises for lokale mapper. Lokale planer bruger
`copilot-local` til kode, ogsaa hvis modellen eller global konfiguration foreslaar
cloud-backend. Ved genvalidering bruges den eksisterende arbejdskopi; der
startes ikke automatisk endnu en betalt Copilot-session.

## Testkommandoer

Testkommandoer er valgfrie ved registrering. Et tomt felt (eller `[]`) gemmes
som ingen konfigurerede automatiske tests. Projektet kan stadig planlaegges og
kodes, men rapport og godkendelsesspoergsmaal markerer tydeligt, at der kun er
koert Git/diff-kontrol. Spillets funktion er dermed ikke automatisk verificeret;
gennemgaa og afproev resultatet manuelt foer godkendelse.

Hvis projektet har tests, angives de som JSON-argumentlister. Brug tests og
buildkommandoer, der passer til spillets engine. Eksempel:

```json
[["python", "-m", "unittest", "discover", "-s", "tests"]]
```

Kodevalidering afviser aendringer af indsendte kildefiler under test. Byggevaerktoejer
skal derfor skrive genererede filer til ignorerede cache-/outputmapper.
De eksisterende kontroller for beskyttede runtime-mapper gaelder fortsat.

## CLI

```powershell
python tools/studio_projects.py add rumspil --name "Rumspil" --kind local --project-path "C:\Spil\Rumspil" --validation-json '[["python","-m","unittest","discover"]]'
python tools/studio_projects.py add strategi --name "Strategi" --kind github --repository "ejer/strategi" --validation-json '[["python","-m","unittest","discover"]]'
python tools/studio.py plan "Byg en lille spilbar prototype" --project-id rumspil
```

Projektvalg nedarves fra operatoren til planens delopgaver; modeltekst kan ikke
skifte det. Afhaengigheder mellem forskellige projekter frigives ikke. Skift af
projekt, repository, lokal kildeplacering, gren eller tests ugyldiggoer tidligere
kvitteringer. Opret en ny opgave efter saadanne skift.

Offline regressionstest bruger rigtig Git og lokale filer med simuleret Copilot.
Det afproever ikke en betalt modelsession eller en komplet spil-/Unreal-build.
