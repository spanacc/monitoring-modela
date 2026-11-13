# Monitoring modela

Aplikacija koja prati rezultate koje neki model vraća i upozorava kada nešto
nije u redu. Ne mora da zna ništa o samom modelu: gleda samo ono što model
vrati (takozvani *black-box* pristup).

## Šta aplikacija radi (kad bude gotova)

1. **Prima rezultate** modela iz bilo kog izvora (fajl, baza, API).
2. **Prevodi ih** u jedan zajednički (univerzalni) format.
3. **Proverava ih**: da li stižu na vreme, da li ima praznih ili čudnih
   vrednosti, da li se ponašanje modela promenilo, koliko model greši.
4. **Javlja alarme** kad nešto nije u redu.
5. **Prikazuje sve na dashboardu.**

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
| 4 | Alarmi | sledeće |
| 5 | Baza podataka | |
| 6 | Dashboard | |
| 7 | Bezbednost i postavljanje | |

## Struktura foldera

```
monitoring-modela/
├── app/                  # sama aplikacija
│   ├── schema.py         # univerzalni format jednog rezultata
│   ├── prepoznavanje.py  # pogađa koja kolona je šta
│   ├── citac.py          # učitava CSV fajl u univerzalni format
│   ├── proveri.py        # proverava fajl i ispisuje probleme
│   └── provere/          # sve provere
│       ├── osnova.py     #   nalaz, podešavanja, granice, pomoćne funkcije
│       ├── kalibracija.py #  sama računa granice za alarme
│       ├── dostupnost.py #   izostanak, duplikat, greška modela
│       ├── kvalitet.py   #   prazne i nemoguće vrednosti
│       └── tacnost.py    #   pristrasnost, drift, skok, pad tačnosti
├── simulator/            # pravi izmišljene podatke za probu
│   ├── modeli.py         # tri izmišljena modela
│   ├── pokreni.py        # pokreće simulator i čuva CSV fajlove
│   └── ocena.py          # da li provere nalaze ubačene probleme
├── tests/                # automatske provere da kod radi
├── docs/koraci/          # objašnjenje svakog koraka
├── data/                 # podaci (ne idu na git)
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

# 4. Napraviti izmišljene podatke
python -m simulator.pokreni

# 5. Pokrenuti automatske provere
pytest
```

Posle koraka 4, u folderu `data/simulirano/` nalaze se CSV fajlovi sa
izmišljenim rezultatima tri modela, koji se mogu otvoriti i u Excelu.

## Učitavanje bilo kog CSV fajla

```bash
python -m app.citac data/simulirano/senzori.csv
```

Aplikacija sama prepozna koja kolona je vreme, koja izvor, a koja rezultat
modela, i pokaže šta je prepoznala. Ako je nešto pogrešno pogodila,
mapiranje se sačuva, ispravi u JSON fajlu i koristi dalje:

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