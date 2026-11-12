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
| 2 | Učitavanje rezultata i automatsko prepoznavanje kolona | sledeće |
| 3 | Provere: dostupnost, kvalitet podataka, promena ponašanja, tačnost | |
| 4 | Alarmi | |
| 5 | Baza podataka | |
| 6 | Dashboard | |
| 7 | Bezbednost i postavljanje | |

## Struktura foldera

```
monitoring-modela/
├── app/                  # sama aplikacija
│   └── schema.py         # univerzalni format jednog rezultata
├── simulator/            # pravi izmišljene podatke za probu
│   ├── modeli.py         # tri izmišljena modela
│   └── pokreni.py        # pokreće simulator i čuva CSV fajlove
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