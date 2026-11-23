# Korak 1: Osnova projekta, univerzalni format i simulator

## Šta smo napravili

1. **Osnovu projekta**: strukturu foldera, spisak biblioteka, pravila šta ne ide na git.
2. **Univerzalni format rezultata** (`app/schema.py`): jedan oblik u koji se prevodi
   svaki rezultat, ma od kog modela stigao.
3. **Simulator** (`simulator/`): pravi izmišljene rezultate tri različita modela,
   sa namerno ubačenim problemima.
4. **Testove** (`tests/`): automatske provere da sve ovo radi.

## Zašto ovim redom

Pre nego što aplikacija bilo šta prati, mora da se zna **kako izgleda jedan
rezultat**. To je temelj na kome stoji sve ostalo. Zato je format prvi.

Odmah posle formata pravimo **simulator**, jer nemamo prave podatke, a bez
podataka ne možemo ništa da probamo. Kad jednog dana stignu pravi podaci,
simulator i dalje ostaje koristan za testove.

## Univerzalni format

Svaki rezultat ima ova polja:

| Polje | Obavezno | Šta znači |
| --- | --- | --- |
| `vreme` | da | Kada je rezultat nastao, uvek sa vremenskom zonom |
| `model` | da | Koji model ga je dao (jedna aplikacija može da prati više modela) |
| `izvor` | da | Na šta se odnosi: mašina, lokacija, linija... |
| `velicina` | da | Šta je predviđeno: temperatura, potrošnja, stanje... |
| `vrednost` | ne | Broj koji je model vratio |
| `kategorija` | ne | Ili kategorija, ako model ne vraća brojeve |
| `jedinica` | ne | °C, kWh... |
| `horizont_min` | ne | Koliko minuta unapred model predviđa |
| `stvarna_vrednost` | ne | Šta se stvarno desilo, za merenje tačnosti |
| `stvarna_kategorija` | ne | Isto, za kategorije |
| `status` | ne | `ok` ili `greska` |
| `poruka` | ne | Poruka o grešci |

Dve važne odluke:

- **Prazan rezultat se ne odbacuje.** Kad bismo ga odbacili, ne bismo ni znali da
  postoji. A prazni rezultati su upravo jedan od problema koje treba prijaviti.
- **Vreme mora imati vremensku zonu.** Inače se lako pomešaju letnje i zimsko
  vreme, ili vreme servera i vreme mašine, pa svi grafikoni budu pomereni za sat.

## Simulator

Pravi tri modela koji namerno nemaju ništa zajedničko:

| Model | Šta vraća | Koliko često | Izvori |
| --- | --- | --- | --- |
| `senzori` | broj (temperatura, °C) | svakog sata | 5 mašina |
| `potrosnja` | broj (kWh) | jednom dnevno | 3 lokacije |
| `kvalitet` | kategorija (ispravno / neispravno) | na 15 minuta | 2 linije |

Ako ista aplikacija ispravno prati sva tri bez ikakvih izmena, radiće i sa pravim
modelom o kome ništa ne znamo.

### Ubačeni problemi

| Model | Izvor | Problem | Šta aplikacija treba da otkrije |
| --- | --- | --- | --- |
| senzori | M1 | Model javio grešku | greška modela |
| senzori | M2 | 6 sati bez rezultata | izostanak |
| senzori | M3 | Stalno predviđa 5 °C više | pristrasnost |
| senzori | M4 | Vrednost 9999 | nemoguća vrednost |
| senzori | M4 | 6 sati praznih rezultata | prazne vrednosti |
| senzori | M5 | Greška polako raste | drift |
| senzori | M1 | Nagli skok koji model nije video | promašen skok |
| potrosnja | L2 | 3 dana bez prognoze | izostanak |
| potrosnja | L3 | Isti rezultat stigao dvaput | duplikat |
| kvalitet | Linija-2 | Tačnost pada sa 95% na 75% | pad tačnosti |

Spisak se čuva u `data/simulirano/ubaceni_problemi.json`. U koraku 3 ćemo
proveriti da li aplikacija pronalazi svaki od njih.

Pored namernih problema, simulator pravi i stvari koje **nisu** problemi, a mogle
bi da zbune lošu proveru: vikendom je potrošnja manja, temperatura ima dnevni
ciklus, a stvarne vrednosti za poslednja dva sata još ne postoje. Dobra provera
ne sme na to da se uzbuni.

## Kako proveriti da radi

```bash
python -m simulator.pokreni   # pravi CSV fajlove u data/simulirano/
pytest                        # pokreće 15 provera, sve treba da prođu
```

Fajlovi iz `data/simulirano/` mogu da se otvore u Excelu.

## Pojmovi iz ovog koraka

- **Schema (šema)**: opis kako podaci moraju da izgledaju.
- **pydantic**: biblioteka koja automatski proverava da li podaci odgovaraju šemi.
- **Seed (seme)**: početni broj za generator slučajnih brojeva. Isto seme uvek daje
  iste "slučajne" podatke, pa testovi uvek daju isti rezultat.
- **Test**: mali program koji proverava da li kod radi kako treba.
- **venv**: izolovano Python okruženje samo za ovaj projekat.

## Sledeći korak

Korak 2: učitavanje rezultata iz CSV fajla (kasnije i iz baze ili API-ja) i
**automatsko prepoznavanje kolona**, tako da aplikacija sama shvati šta je vreme,
šta izvor, a šta vrednost, i kad pravi podaci imaju potpuno drugačije nazive kolona.
