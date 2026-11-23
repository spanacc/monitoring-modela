# Korak 3: Provere

## Šta smo napravili

Aplikacija sada prvi put zaista **pronalazi probleme**. Iz učitanih rezultata
(korak 2) pravi spisak nalaza: šta nije u redu, gde, od kada do kada i koliko
je ozbiljno.

```bash
python -m app.proveri data/simulirano/senzori.csv
```

Granice za alarme aplikacija računa sama, za svaki izvor posebno. Kako to
radi, objašnjeno je u `03b-kalibracija.md`.

## Provere

| Grupa | Provera | Šta otkriva | Treba stvarna vrednost | Ozbiljnost |
| --- | --- | --- | --- | --- |
| Dostupnost | `izostanak` | Rezultati ne stižu (i „tišina“ na kraju) | ne | kritično |
| | `duplikat` | Isti rezultat stigao više puta | ne | info |
| | `greska_modela` | Model javio grešku | ne | upozorenje |
| Kvalitet | `prazne_vrednosti` | Rezultat stigao bez vrednosti | ne | upozorenje |
| | `nemoguca_vrednost` | Vrednost naglo odskače od susednih | ne | upozorenje |
| Tačnost | `pristrasnost` | Model stalno greši u istom smeru | da | upozorenje |
| | `drift` | Model vremenom postaje lošiji ili se menja | **ne** (bolje sa njom) | upozorenje |
| | `promasen_skok` | Nagao, veliki promašaj | da | kritično |
| | `pad_tacnosti` | Drift za modele koji vraćaju kategorije | da | upozorenje |

## Kako koja provera radi, ukratko

- **Izostanak**: pauza između rezultata duža od granice naučene iz normalnog
  perioda. Proverava se i kraj: ako model „ućuti“, i to je izostanak.
- **Nemoguća vrednost**: vrednost se poredi sa svojim susedima (pola dana pre i
  posle). Ako odskoči više nego što je ikad odskakala u normalnom periodu (puta
  rezerva), nemoguća je. Pošto se poredi sa susedima, spora promena ili trajni
  pomak se ne prijavljuju ovde, nego kao drift.
- **Pristrasnost**: ako model greši nasumično, greške se poništavaju. Ako uvek
  predviđa više, ne poništavaju se. Pristrasnost je kad je **više od pola**
  greške uvek u istom smeru.
- **Drift**: podaci se dele na prozore od otprilike jednog dana. Za svaki prozor
  se računa tipična greška i poredi sa normalnim periodom. **Bez stvarnih
  vrednosti** umesto greške se prati prosečna vrednost koju model vraća. Tako
  aplikacija javlja promenu ponašanja i ako stvarne vrednosti nikad ne dobijemo.
- **Promašen skok**: kao nemoguća vrednost, ali za grešku: greška naglo odskoči
  od susednih grešaka.
- **Pad tačnosti**: stopa pogrešnih kategorija po prozoru poraste više nego što
  se ikad kolebala u normalnom periodu.

## Kako sprečavamo lažne uzbune

Lažna uzbuna je gora nego što izgleda: posle nekoliko lažnih, ljudi prestanu da
gledaju alarme. Zato:

1. **Jedan problem se prijavljuje samo jednom.** Rezultat sa greškom nije i
   „prazna vrednost“. Vrednost 9999 nije i „promašen skok“. Pristrasnost koja
   je tu od početka nije i „drift“.
2. **Uzastopni problemi se spajaju.** 6 praznih rezultata zaredom su jedan nalaz.
3. **Drift mora da traje.** Potrebna su bar 2 loša prozora zaredom.
4. **Medijana umesto proseka** gde god pojedinačna čudna vrednost ne sme da
   pomeri rezultat.

## Kako znamo da radi

`python -m simulator.ocena` pušta provere nad simuliranim podacima i poredi
nalaze sa spiskom problema koje je simulator namerno ubacio:

```
Pronađeno 10 od 10 ubačenih problema.
Lažnih uzbuna: 0
```

Testovi to proveravaju na 5 različitih skupova podataka. Pri razvoju je
provereno na 300 skupova (oko 3.000 izvora po 30 dana, odnosno oko 250
godina rada jednog izvora): svi ubačeni problemi su uvek pronađeni, a
pojavila se jedna lažna uzbuna za drift. Pravi podaci su „neuredniji“ od
simuliranih, pa će lažnih uzbuna tamo biti više. Koliko, videćemo u pilotu.

Bez stvarnih vrednosti ne mogu se otkriti pristrasnost, promašen skok i pad
tačnosti, jer za njih mora da se zna šta se stvarno desilo. Sve ostalo radi.

## Šta još ne radi

- **Vreme se ispisuje u UTC.** Lokalno vreme dolazi na dashboardu (korak 6).
- **Nema poređenja izvora međusobno** (npr. „M3 jedini odstupa od ostalih“).
  Može se dodati kasnije, ako se pokaže potrebnim.

## Pojmovi iz ovog koraka

- **Nalaz**: jedan pronađen problem.
- **Medijana**: srednja vrednost kad se sve poređa po veličini. Na nju ne utiču ekstremi.
- **Prozor**: grupa uzastopnih rezultata koja se posmatra zajedno (otprilike jedan dan).
- **Normalni period (osnova)**: početni deo podataka sa kojim se sve poredi.
- **Lažna uzbuna**: nalaz kad problema zapravo nema.

## Sledeći korak

Korak 3b: **samopodešavanje granica** (`03b-kalibracija.md`).
