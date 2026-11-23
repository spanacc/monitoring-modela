# Monitoring modela

Aplikacija koja prati rezultate koje neki model vraća i upozorava kada nešto
nije u redu. Ne mora da zna ništa o samom modelu: gleda samo ono što model
vrati (takozvani *black-box* pristup).

## Šta aplikacija radi

1. **Prima rezultate** modela iz bilo kog izvora (fajl, baza, API).
2. **Prevodi ih** u jedan zajednički (univerzalni) format.
3. **Proverava ih**: da li stižu na vreme, da li ima praznih ili čudnih
   vrednosti, da li se ponašanje modela promenilo, koliko model greši.
4. **Javlja alarme** kad nešto nije u redu.
5. **Prikazuje sve na dashboardu** (stranica u pregledaču).

Aplikacija nikad ne šalje ništa nazad modelu i ništa ne menja. Samo čita.

## Kako se projekat pravi

Projekat se pravi deo po deo. Svaki deo ima svoje objašnjenje u folderu
`docs/koraci/`:

| Korak | Šta se pravi | Status |
| --- | --- | --- |
| 1 | Osnova projekta, univerzalni format rezultata, simulator izmišljenih modela | gotovo |
| 2 | Učitavanje rezultata i automatsko prepoznavanje kolona | gotovo |
| 3 | Provere: dostupnost, kvalitet podataka, promena ponašanja, tačnost | gotovo |
| 3b | Samopodešavanje granica (kalibracija) | gotovo |
| 4 | Alarmi | gotovo |
| 5 | Baza podataka | gotovo |
| 6 | Dashboard | gotovo |
| 6b | Test na pravim podacima (SKAB): široke tabele, merenja svake sekunde | gotovo |
| 7 | Jednostavna verzija: semafor, problemi običnim rečima, podaci se dodaju na stranici | gotovo |
| 8 | Bezbednost i postavljanje | sledeće |

## Struktura foldera

```
monitoring-modela/
├── app/                  # sama aplikacija
│   ├── __main__.py       # python -m app: sve u jednoj komandi
│   ├── schema.py         # univerzalni format jednog rezultata
│   ├── prepoznavanje.py  # pogađa koja kolona je šta
│   ├── citac.py          # učitava CSV fajl u univerzalni format
│   ├── proveri.py        # proverava fajl i ispisuje probleme
│   ├── dodavanje.py      # dodavanje podataka sa stranice: predlog kolona
│   ├── nadzor.py         # krug nadzora: učitaj, proveri, javi alarme
│   ├── baza.py           # baza podataka: rezultati i alarmi
│   ├── dashboard/        # stranica u pregledaču i njen server
│   │   ├── podaci.py         # iz baze priprema ono što ekran prikazuje
│   │   ├── server.py         # veb server (FastAPI) i zaštita
│   │   ├── __main__.py       # pokretanje: python -m app.dashboard
│   │   └── static/           # stranice, stil.css, pregled.js, podesavanja.js, alati.js
│   ├── provere/          # sve provere
│   │   ├── osnova.py         # nalaz, podešavanja, granice, pomoćne funkcije
│   │   ├── kalibracija.py    # sama računa granice za alarme
│   │   ├── dostupnost.py     # izostanak, duplikat, greška modela
│   │   ├── kvalitet.py       # prazne i nemoguće vrednosti
│   │   └── tacnost.py        # pristrasnost, drift, skok, pad tačnosti
│   └── alarmi/           # alarmi i obaveštenja
│       ├── evidencija.py     # jedan problem = jedan alarm
│       ├── kanali.py         # ekran, dnevnik, mejl, poruka
│       ├── konfiguracija.py  # podešavanja iz JSON fajla
│       └── __main__.py       # pregled, potvrda i rešavanje alarma
├── simulator/            # pravi izmišljene podatke za probu
│   ├── modeli.py         # tri izmišljena modela
│   ├── pokreni.py        # pokreće simulator i čuva CSV fajlove
│   └── ocena.py          # da li provere nalaze ubačene probleme
├── tests/                # automatske provere da kod radi
├── docs/koraci/          # objašnjenje svakog koraka
├── data/                 # podaci, baza i podešavanja sa stranice (ne idu na git)
├── konfiguracija.primer.json  # primer podešavanja nadzora
└── requirements.txt      # spisak biblioteka koje su potrebne
```

## Kako se pokreće

Potreban je Python 3.11 ili noviji.

```bash
# 1. Napraviti izolovano okruženje (da biblioteke ne smetaju ostatku računara)
python -m venv .venv

# 2. Uključiti ga
#    Linux / Mac:
source .venv/bin/activate
#    Windows:
.venv\Scripts\activate

# 3. Instalirati biblioteke
pip install -r requirements.txt

# 4. Pokrenuti aplikaciju
python -m app
```

Otvori se stranica u pregledaču. Zupčanik gore desno, pa **Dodaj podatke**: ubaci se CSV fajl
koji model pravi (ili putanja do foldera u kome ih ostavlja), aplikacija
pokaže šta je prepoznala, čovek potvrdi. Od tada radi sama: proverava na
svakih 60 s i prikazuje probleme običnim rečima. Detalji:
`docs/koraci/07-jednostavna-verzija.md`.

Za probu bez pravog modela, izmišljeni podaci:

```bash
python -m simulator.pokreni
```

U folderu `data/simulirano/` nastanu CSV fajlovi tri izmišljena modela,
koji se onda ubace kroz **Dodaj podatke**.

Automatske provere da kod radi:

```bash
pytest
```

Sve ispod je za one koji hoće da rade iz Terminala ili da podešavaju ručno.

## Učitavanje bilo kog CSV fajla

```bash
python -m app.citac data/simulirano/senzori.csv
```

Aplikacija sama prepozna koja kolona je vreme, koja izvor, a koja rezultat
modela, i pokaže šta je prepoznala. Ako je svaki senzor u svojoj koloni
("široka tabela"), svaka kolona može da bude poseban izvor:

```bash
python -m app.citac fajl.csv --kolone sve
```

Ako je aplikacija nešto pogrešno pogodila, mapiranje se sačuva, ispravi u
JSON fajlu i koristi dalje:

```bash
python -m app.citac fajl.csv --sacuvaj-mapiranje mapiranje.json
# ispraviti mapiranje.json u bilo kom editoru, pa:
python -m app.citac fajl.csv --mapiranje mapiranje.json
```

## Provera rezultata

```bash
python -m app.proveri data/simulirano/senzori.csv
```

Ispisuje pronađene probleme: izostanke, greške modela, prazne i nemoguće
vrednosti, duplikate, pristrasnost, drift, nagle promašaje i pad tačnosti.

Granice za alarme aplikacija računa sama, za svaki izvor posebno. Šta je
naučila, i kako se menja osetljivost:

```bash
python -m app.proveri data/simulirano/senzori.csv --granice
python -m app.proveri data/simulirano/senzori.csv --rezerva 3   # manje alarma
```

Da li provere nalaze sve probleme koje je simulator namerno ubacio:

```bash
python -m simulator.ocena
```

## Nadzor i alarmi

```bash
cp konfiguracija.primer.json konfiguracija.json   # prvi put
python -m app.nadzor --sada podaci                 # jedan krug (za simulirane podatke)
python -m app.nadzor --ponavljaj 60                # u pravom radu: krug na svakih 60 s
```

Isti problem se javlja samo jednom. Alarmi se pregledaju i potvrđuju ovako:

```bash
python -m app.alarmi                               # otvoreni alarmi
python -m app.alarmi potvrdi 3 --ko Veljko         # video sam, ne javljaj više
python -m app.alarmi resi 3                        # rešeno
```

Sva podešavanja (šta se prati, osetljivost, kuda se šalje) su u
`konfiguracija.json`. Lozinke se ne pišu u taj fajl, nego u promenljive
okruženja. Detalji: `docs/koraci/04-alarmi.md`.

Rezultati i alarmi se čuvaju u bazi (`data/monitoring.db`). U svakom krugu se
upisuju samo novi rezultati, a proverava se samo poslednjih 30 dana, pa nadzor
ostaje brz i posle godina rada. Detalji: `docs/koraci/05-baza.md`.

## Dashboard

```bash
python -m app.dashboard --sada podaci     # proba na simuliranim podacima
```

Zatim u pregledaču otvoriti http://127.0.0.1:8000. Na vrhu je stanje rečima,
ispod svaki izvor kao traka kroz vreme (sivo = u redu, boja = problem), a
desno alarmi sa dugmadima Potvrdi i Reši.

U pravom radu dashboard sam pokreće i nadzor, pa je dovoljan jedan program:

```bash
python -m app.dashboard --nadzor 60
```

Dashboard podrazumevano vidi samo ovaj računar (još nema prijavu korisnika;
dolazi u koraku 8). Detalji: `docs/koraci/06-dashboard.md`.

## Test na pravim podacima

Aplikacija je proverena na javnom skupu SKAB (pumpa sa 8 senzora, merenja
svake sekunde, 20 namernih zatvaranja ventila): sama je pronašla 19 od 20
zatvaranja, bez ikakvog znanja o pumpi. Kako se pokreće i šta tačno piše u
rezultatu: `docs/koraci/06b-pravi-podaci.md`. Probana je i na podacima o
iznajmljivanju bicikala (našla uragan Sendi) i na fajlu koji uopšte nisu
rezultati modela (odbila ga je): `docs/koraci/07-jednostavna-verzija.md`.
