# Korak 2: Učitavanje rezultata i automatsko prepoznavanje kolona

## Šta smo napravili

1. **Prepoznavanje kolona** (`app/prepoznavanje.py`): gleda nazive i sadržaj
   kolona i pogađa koja kolona je vreme, koja izvor, koja rezultat modela...
2. **Čitač** (`app/citac.py`): čita CSV fajl, koristi prepoznavanje i svaki red
   pretvara u `Rezultat` iz koraka 1.
3. **Komandu** `python -m app.citac fajl.csv` koja pokazuje šta je prepoznato.
4. **Testove** za oba dela (sada ih ima ukupno 34).

## Zašto je ovo potrebno

O modelu ne znamo ništa, pa ne znamo ni kako će izgledati njegovi fajlovi.
Kolone se mogu zvati `Timestamp`, `vreme_merenja` ili samo `a`. Razdvajač može
biti zarez ili tačka-zarez, decimale mogu biti sa tačkom ili zarezom, vreme sa
zonom ili bez nje. Čitač sve to prepoznaje sam.

## Kako radi prepoznavanje

U dva prolaza:

| Prolaz | Šta gleda | Primer | Sigurnost |
| --- | --- | --- | --- |
| 0 | Kolona se zove tačno kao polje | `vreme`, `izvor` | potpuna |
| 1 | Poznate reči u nazivu, potvrđene sadržajem | `Machine ID` → izvor | visoka |
| 2 | Samo sadržaj kolone | kolona puna datuma → vreme | proveriti |

Dva pravila vredi zapamtiti:

- **Naziv kaže ulogu, sadržaj kaže vrstu.** Kolona `prediction` je rezultat
  modela, ali tek sadržaj odlučuje da li je to broj ili kategorija.
- **Redosled reči je bitan.** `actual_value` sadrži i „actual“ i „value“. Pošto se
  „actual“ proverava pre „value“, kolona postaje stvarna vrednost, što je tačno.

Kolone kao `id` ili `index` (redni brojevi) se namerno preskaču, jer bi inače
lako bile pogrešno uzete kao rezultat modela.

## Šta čitač prepoznaje

| Šta | Primeri |
| --- | --- |
| Razdvajač | `,` `;` tab `\|` |
| Kodiranje | UTF-8, UTF-8 iz Excela, Windows-1250 (č, ć, š, ž, đ) |
| Brojevi | `12.5`, `12,5`, `1.234,5`, `1,234.5` |
| Vreme | `2026-11-10T14:00:00Z`, `2026-11-10 14:00`, `10.11.2026 14:00`, `10.11.2026. 14:00`, sekunde ili milisekunde od 1970. |
| Prazno | prazna ćelija, `nan`, `null`, `none`, `n/a`, `-` |

Vreme bez zone se tumači kao beogradsko vreme. Može se promeniti opcijom `--zona`.

## Važne odluke

- **Neispravan red ne ruši učitavanje.** Zapisuje se na spisak grešaka sa brojem
  reda u fajlu, a ostali redovi se učitaju. Monitoring mora da radi i kad su
  podaci delimično pokvareni, jer je tada najpotrebniji.
- **Prazna vrednost nije greška.** Učita se kao prazan rezultat, a provere iz
  koraka 3 će ga prijaviti.
- **Ako nema kolone sa izvorom**, svi rezultati dobijaju izvor `glavni`. Mnogi
  modeli prave samo jednu prognozu, pa izvor i nije potreban.
- **Bez vremena ili bez rezultata modela učitavanje staje** sa jasnom porukom,
  jer tada praćenje nema smisla.

## Kad prepoznavanje pogreši

Primer: fajl ima kolone `t`, `kol1`, `kol2`, obe sa brojevima. Aplikacija ne
može da zna koja je prognoza, a koja stvarna vrednost, pa uzme prvu. Tada:

```bash
python -m app.citac fajl.csv --sacuvaj-mapiranje mapiranje.json
```

U `mapiranje.json` se ispravi koja kolona je koje polje:

```json
{
  "polja": {
    "vreme": "t",
    "vrednost": "kol2",
    "stvarna_vrednost": "kol1"
  }
}
```

i od tada se koristi:

```bash
python -m app.citac fajl.csv --mapiranje mapiranje.json
```

Ovo je princip iz plana: **podešava se, ne programira**.

## Kako proveriti da radi

```bash
pip install -r requirements.txt               # zbog nove biblioteke tzdata
pytest                                        # 34 provere, sve treba da prođu
python -m simulator.pokreni
python -m app.citac data/simulirano/senzori.csv
```

Poslednja komanda treba da pokaže sva polja prepoznata kao „tačan naziv“ i
`Učitano: 3594 rezultata, 0 grešaka`.

## Pojmovi iz ovog koraka

- **Mapiranje**: spisak koja kolona iz fajla odgovara kom polju.
- **Normalizacija naziva**: `Mašina ID` → `masina_id`, da bi se nazivi lakše poredili.
- **Razdvajač (delimiter)**: znak koji razdvaja kolone u CSV fajlu.
- **Kodiranje (encoding)**: način na koji su slova zapisana u fajlu.
- **Epoch vreme**: vreme zapisano kao broj sekundi od 1. 1. 1970.

## Sledeći korak

Korak 3: **provere**. Aplikacija će iz učitanih rezultata otkrivati izostanke,
prazne i nemoguće vrednosti, duplikate, promenu ponašanja (drift) i pad tačnosti,
i proveriti da li pronalazi svih 10 problema koje je simulator namerno ubacio.
