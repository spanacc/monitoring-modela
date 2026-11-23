# Korak 6b: Test na pravim podacima (SKAB)

## Šta je SKAB

Javni skup podataka sa pravog uređaja (Skoltech Anomaly Benchmark): pumpa za
vodu sa 8 senzora koji mere **svake sekunde** (vibracije, struja, pritisak,
temperatura, napon, protok). U svakom eksperimentu od 20 minuta neko namerno
zatvori ventil. Za svaku sekundu piše da li je tada bila anomalija, pa može
tačno da se proveri koliko aplikacija pogađa.

Aplikacija o pumpi ne zna ništa. Za nju su to samo brojevi u CSV fajlovima,
isto kao rezultati modela o kome ne znamo ništa.

## Šta je test otkrio i šta je popravljeno

| Problem | Popravka |
| --- | --- |
| Svaki senzor je u svojoj koloni („široka tabela“), a aplikacija je gledala samo prvu kolonu | `kolone` u konfiguraciji (ili `--kolone` u Terminalu): svaka kolona postaje poseban izvor. `"sve"` = sve kolone sa brojevima |
| Svaki eksperiment je poseban fajl | Putanja sa zvezdicom: `"../SKAB/data/valve1/*.csv"` prati sve takve fajlove |
| Prozor od „jednog dana“ je kod merenja svake sekunde 86.400 merenja: duži od samih podataka, pa drift nije mogao da radi, a sve je bilo vrlo sporo | Kad je normalni period kraći od dva takva prozora, prozor je 1/50 normalnog perioda. Za podatke na sat, dan ili 15 minuta ništa se ne menja |
| Dashboard prikazuje najmanje 7 dana, pa bi 7 sati bilo tanka crta | Prikaz počinje od prvog rezultata (zumira se na podatke), osa piše sate i minute, ćelije mogu biti i po 5 minuta, a „dnevni“ grafikon ide po prozorima |
| Trajanja kraća od minuta pisala su se kao „0 min“ | Sada sekunde: „1 s“, „53 s“ |
| Kad svih 8 senzora zaćuti isti minut, to je bilo 8 kritičnih alarma | Isti problem u isto vreme na više izvora jednog modela broji se i prikazuje kao jedan, sa spiskom izvora |

## Rezultat

Podešeno je samo dvoje: normalni period su prvih 9 minuta (pre prvog
zatvaranja ventila) i rezerva je 4. Ništa drugo.

| | |
| --- | --- |
| Zatvaranja ventila (označena u SKAB-u) | 20 |
| Pronađeno samo preko protoka (drift) | **15 od 20** |
| Za vreme zatvaranja javljen bar neki alarm | **19 od 20** |
| Pravi nestanci podataka u snimku (svih 8 senzora, oko 1 minut) | 4, svi pronađeni |
| Lažne kratke uzbune | 3 |
| Vreme provere 180.000 merenja | oko 16 s |

Dve stvari treba znati da bi se rezultat pravilno pročitao:

- **Temperatura i termopar** imaju dugačak drift skoro sve vreme. Pumpa se
  tokom 5 sati zagrevala, a normalni period je samo 9 minuta, pa aplikacija
  tačno javlja da se ponašanje promenilo. To nije kvar. U pravom radu
  normalni period treba da obuhvati i uobičajeno zagrevanje.
- Aplikacija nije znala unapred da je protok najvažniji senzor. Pratila je
  svih osam, i protok se sam izdvojio.

## Kako se pokreće

SKAB treba da bude na Desktopu, pored projekta (`Desktop/SKAB/data`).
Aplikacija ga samo čita i ništa u njemu ne menja.

```bash
python -m app.nadzor --sada podaci --konfiguracija data/proba/skab.json
python -m app.dashboard --sada podaci --konfiguracija data/proba/skab.json
```

Prvi krug traje oko 15 sekundi. U pregledaču: klikni red **Volume Flow
RateRMS**. Svako udubljenje na grafikonu je jedno zatvaranje ventila, a žuta
traka je alarm koji je aplikacija sama postavila.

Podešavanja su u `data/proba/skab.json` (folder `data/` ne ide na git):

| Polje | Značenje |
| --- | --- |
| `"putanja": "../SKAB/data/valve1/*.csv"` | svi fajlovi iz foldera valve1 |
| `"model": "ventil_1"` | svi ti fajlovi su jedan model |
| `"kolone": [...]` | 8 senzora, svaki je poseban izvor |
| `"dana_osnove": 0.00625` | normalni period: 0,00625 dana = 9 minuta |
| `"rezerva": 4` | manje osetljivo nego podrazumevano (2), jer je normalni period kratak |
| `"dana_provere": null` | proveravaju se svi podaci, ne samo poslednjih 30 dana |

## Pouke za pravi model

1. **Normalni period mora da bude zaista normalan i dovoljno dug** da obuhvati
   uobičajene promene (zagrevanje, smene, dan i noć). Što je kraći, to
   rezerva mora biti veća.
2. **Ne zna se unapred koja vrednost je važna**, pa se prati sve što model vrati.
3. **Pravi podaci imaju rupe.** Aplikacija ih nalazi i javlja, i to je
   korisno samo po sebi.

## Šta još ne radi

- Grupišu se samo potpuno isti problemi (isto vreme, ista vrsta). Povezani
  problemi na više senzora (npr. protok i temperatura u istom zatvaranju
  ventila) i dalje su posebni alarmi.
- Za mesece merenja svake sekunde provere bi bile spore (pisane su
  jednostavno, za čitljivost). To se ubrzava kad saznamo koliko podataka pravi
  model šalje.
- Normalni period se zadaje u danima (`0.00625` za 9 minuta), što je nezgodno
  za kratke podatke.

## Pojmovi

- **Široka tabela**: svaki senzor (ili veličina) je posebna kolona. Suprotno
  je „dugačka“: jedan red je vreme, izvor i vrednost.
- **Prozor**: grupa uzastopnih rezultata koja se posmatra zajedno (npr. njihov
  prosek). Drift poredi prozore sa normalnim periodom.
- **Benchmark**: javni skup podataka sa poznatim tačnim odgovorima, na kome se
  proverava koliko neki metod valja.

## Sledeći korak

Korak 7: bezbednost i postavljanje.
