# Korak 6: Dashboard

## Šta smo napravili

**Dashboard**: stranicu u pregledaču (Chrome, Safari...) koja na jednom ekranu
pokazuje stanje svih modela, i odakle se alarmi potvrđuju i rešavaju.

```
pregledač (stranica)  <-- pita -->  mali veb server (FastAPI)  <-- čita -->  baza (korak 5)
```

Stranica ne čita bazu sama. Pita server, a server čita bazu i vraća tačno ono
što stranica prikazuje.

## Kako se pokreće

```bash
pip install -r requirements.txt                 # nove biblioteke: fastapi, uvicorn, httpx
python -m app.dashboard --sada podaci           # proba na simuliranim podacima
```

Zatim u pregledaču otvoriti **http://127.0.0.1:8000**. Zaustavlja se sa Ctrl+C.

U pravom radu dashboard sam pokreće i nadzor (korak 5), pa je dovoljan jedan
program:

```bash
python -m app.dashboard --nadzor 60             # krug nadzora na svakih 60 s
```

## Šta se vidi na ekranu

| Deo | Šta pokazuje |
| --- | --- |
| **Rečenica na vrhu** | stanje rečima: „3 kritična problema i 6 upozorenja traže pažnju“, i šta je najhitnije. Odgovor pre ijednog grafikona. |
| **Stanje izvora** | svaki izvor je jedna traka kroz vreme. Siva ćelija: sve u redu. Obojena: u tom periodu je bio alarm. Desno: poslednja vrednost i koliko je stara. |
| **Izabrani izvor** | brojevi ukratko, grafikon vrednosti (model i stvarno), grafikon onoga što prati provera drifta, i šta je aplikacija naučila o tom izvoru. |
| **Alarmi** | nerešeni alarmi, najvažniji prvi. Dugmad **Potvrdi** i **Reši**. |

Klik na izvor ili na alarm prikazuje taj izvor. Preko grafikona se prelazi
mišem (ili strelicama sa tastature, kad je grafikon izabran tasterom Tab), a
oblačić pokazuje tačne brojeve. Dugme **Prikaži tabelu** pokazuje iste
podatke kao brojeve.

## Zašto je sve sivo

Princip iz kontrolnih sala elektrana (standard ISA-101): **sve što je u redu je
sivo, a boja se troši samo na probleme**. Kad je ekran šaren, oko prestane da
primećuje ono što je važno. Ovde, čim nešto ima boju, nešto nije u redu.

Ozbiljnost se uvek pokazuje i **oblikom** i **rečju**, nikad samo bojom, da bi je
video i neko ko ne razlikuje boje:

| Oblik | Značenje |
| --- | --- |
| romb | kritično |
| trougao | upozorenje |
| krug | info |
| samo obris oblika | potvrđeno, neko već radi na tome |
| bleda ćelija | problem je bio, ali je rešen |

Boje su proverene alatom za kontrast i za ljude koji ne razlikuju boje, a ne
„od oka“. Postoje svetla i tamna tema (dugme **Tema**), a podrazumevana prati
podešavanje računara.

## Ništa izmišljeno

Dashboard ne računa svoje granice. Naučene granice i nemoguće vrednosti
računaju se **istim funkcijama kao u nadzoru** (`kalibrisi`, `nemoguce_tacke`),
nad istim normalnim periodom. Tako:

- linija „granica“ na dnevnom grafikonu je baš ona preko koje nadzor diže alarm
  (test `test_dnevni_grafikon_ima_iste_granice_kao_nadzor` to proverava),
- spisak „Šta je aplikacija naučila“ je isti kao `python -m app.proveri --granice`.

Dnevni grafikon pokazuje ono što prati provera drifta:

| Model vraća | Dnevni grafikon |
| --- | --- |
| brojeve, a stvarne vrednosti su poznate | tipična greška po danu |
| brojeve, bez stvarnih vrednosti | prosečna vrednost po danu |
| kategorije | tačnost po danu |

Dan sa mnogo manje rezultata nego obično (npr. današnji, koji je tek počeo)
crta se kao **prazan krug** i ne spaja se linijom, jer je njegov broj nepouzdan.

Za modele koji vraćaju kategorije, glavni grafikon pokazuje **koliko puta je
model vratio koju kategoriju**. Ako se taj odnos promeni, vidi se i kad stvarne
kategorije nikad ne stignu.

## Kako je brzo

1. **Stranica pita samo za „verziju“.** Na svakih 15 sekundi stranica pita server
   jedno kratko pitanje: da li se nešto promenilo? Odgovor je nekoliko bajtova.
   Sve ostalo traži tek kad se verzija promeni (stigao nov rezultat ili se
   promenio alarm). Kad kartica pregledača nije vidljiva, ne pita ništa.
2. **Keš.** Server pamti već izračunate odgovore dok se verzija ne promeni. Deset
   otvorenih dashboarda ne opterećuju bazu deset puta više.
3. **Proređivanje.** Grafikon nikad ne dobije više od 1500 tačaka. Ako ih ima
   više, iz svake grupe susednih tačaka zadržava se najmanja i najveća, pa se
   skokovi i rupe i dalje vide. Ekran ionako nema više piksela od toga.
4. **Sažimanje (gzip).** Odgovori putuju sažeti, oko 4 puta manji.
5. **Bez biblioteka.** Stranica ne koristi nijednu spoljnu biblioteku. Grafikoni
   se crtaju ručno, kao SVG. Ništa se ne preuzima sa interneta, pa radi i u
   mreži bez interneta.

Izmereno na simulaciji od 90 dana: pregled svih izvora 37 ms prvi put, 7 ms iz
keša; grafikon jednog izvora 65 ms, a iz keša 9 ms.

## Bezbednost (osnovna)

Potpuna bezbednost, sa prijavom korisnika i HTTPS-om, dolazi u koraku 7. Do tada:

| Zaštita | Od čega štiti |
| --- | --- |
| Server sluša samo na `127.0.0.1` | dashboard može da otvori samo ovaj računar, ne i drugi u mreži |
| Provera imena servera (TrustedHost) | napad „DNS rebinding“: tuđa stranica se predstavlja kao naš server |
| Svaka izmena traži zaglavlje `X-Dashboard` | napad „CSRF“: tuđa stranica otvorena u istom pregledaču pokušava da reši alarm u vaše ime |
| Zaglavlje Content-Security-Policy | stranica sme da učita i pokrene samo svoje fajlove |
| Tekst iz podataka se ubacuje kao tekst, nikad kao HTML | čudno ime izvora ne može da „izvrši“ kod u pregledaču |
| Ime i napomena imaju najveću dužinu | slanje ogromnih podataka |

Aplikacija i dalje samo **čita** rezultate modela. Menja samo svoje alarme.

Ako dashboard treba da vide i drugi računari: `--adresa 0.0.0.0`. Aplikacija
tada ispiše upozorenje, jer još nema prijavu. To raditi samo u zaštićenoj
mreži, i tek posle razgovora sa IT-jem.

## Jedan program za sve upise

Alarme menjaju i nadzor (novi alarmi) i ljudi (potvrda, rešavanje). Kad bi to
radila dva programa u isto vreme, jedan bi mogao da pregazi izmenu drugog: npr.
nadzor pročita alarme, vi potvrdite alarm, a nadzor zatim upiše svoju staru
kopiju i vaša potvrda nestane.

Zato je preporuka: **pokretati samo dashboard, sa `--nadzor 60`**. Tada isti
program radi oboje, a **brava** (lock) pazi da se dva upisa nikad ne dese u
isto vreme. Dugme **Proveri sada** pokreće jedan krug nadzora odmah.

## Fajlovi

| Fajl | Šta radi |
| --- | --- |
| `app/dashboard/podaci.py` | iz baze priprema ono što ekran prikazuje |
| `app/dashboard/server.py` | veb server: adrese `/api/...`, zaštita, keš, nadzor u pozadini |
| `app/dashboard/__main__.py` | pokretanje iz Terminala |
| `app/dashboard/static/index.html` | kostur stranice |
| `app/dashboard/static/stil.css` | izgled: boje, slova, raspored |
| `app/dashboard/static/app.js` | sve što se dešava u pregledaču: grafikoni, alarmi, osvežavanje |
| `tests/test_dashboard.py` | 18 provera |

Adrese koje server nudi (API):

```
GET  /api/stanje                     verzija podataka
GET  /api/pregled?dana=30            stanje svih izvora
GET  /api/serija?model=..&izvor=..   sve za jedan izvor
GET  /api/alarmi?svi=false           spisak alarma
POST /api/alarmi/{broj}/potvrdi      {"ko": "Veljko", "napomena": "..."}
POST /api/alarmi/{broj}/resi         {"napomena": "..."}
POST /api/nadzor                     jedan krug nadzora, odmah
```

## Kako proveriti

```bash
pip install -r requirements.txt
pytest                                   # 111 provera
python -m app.nadzor --sada podaci       # ako baza još ne postoji
python -m app.dashboard --sada podaci    # pa otvoriti http://127.0.0.1:8000
```

Na ekranu treba da piše „3 kritična problema i 6 upozorenja traže pažnju“, a u
stanju izvora da se vide svi ubačeni problemi iz simulatora: M1 (greška modela
i promašen skok), M2 (izostanak), M3 (pristrasnost, cela traka), M4 (nemoguća
vrednost i prazne vrednosti), M5 (drift), L2 (izostanak), L3 (duplikat) i
Linija-2 (pad tačnosti).

## Šta još ne radi

- Nema prijave korisnika: svako ko može da otvori stranicu može i da potvrdi
  alarm. Zato server podrazumevano sluša samo na ovom računaru. Dolazi u koraku 7.
- Ime onoga ko potvrđuje alarm se upisuje rukom (pregledač ga zapamti). Kad
  bude prijave, ime će se uzimati iz nje.
- Ako se `python -m app.nadzor` pokrene **pored** dashboarda (dva programa
  odjednom), retko može da se izgubi potvrda alarma. Zato koristiti `--nadzor`.
- Provere su pisane jednostavno, za čitljivost. Za model koji šalje rezultat
  svakog minuta (desetine hiljada tačaka mesečno), računanje odskoka od suseda
  je sporo i treba ga ubrzati. Kad saznamo koliko rezultata pravi model šalje.

## Pojmovi

- **Veb server**: program koji čeka pitanja pregledača i odgovara na njih.
- **API**: spisak adresa na kojima server odgovara podacima, a ne stranicom.
- **FastAPI**: biblioteka za pravljenje veb servera u Python-u.
- **uvicorn**: program koji pokreće FastAPI server.
- **SVG**: slika opisana linijama i oblicima. Pregledač je sam iscrta, oštra je
  u svakoj veličini.
- **Keš**: zapamćen odgovor, da se isti posao ne radi ponovo.
- **gzip**: sažimanje podataka pre slanja, kao zip.
- **CSRF, DNS rebinding**: vrste napada u kojima tuđa veb stranica pokušava da
  iskoristi vaš pregledač da bi nešto uradila na serveru u vaše ime.
- **Brava (lock)**: obezbeđuje da samo jedan deo programa u isto vreme menja
  podatke.

## Sledeći korak

Korak 7: **bezbednost i postavljanje**: prijava korisnika, uloge (ko sme samo da
gleda, a ko i da rešava alarme), HTTPS i uputstvo za postavljanje na server firme.
