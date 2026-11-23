# Korak 3b: Samopodešavanje granica (kalibracija)

## Problem

U prvoj verziji provera granice za alarme bile su brojevi upisani u kod:
„izostanak je pauza 2,5 puta duža od uobičajene“, „nemoguća vrednost je 10
puta dalje od sredine“ i slično. Ti brojevi su bili procena, a o modelu ne
znamo ništa, pa ne znamo ni da li su dobri.

## Rešenje: aplikacija sama računa granice

Za svaki izvor posebno aplikacija:

1. uzme **normalni period**: prvu četvrtinu podataka, kad je model radio kako treba,
2. pogleda **najgore što se tada desilo**,
3. postavi granicu za alarm na **dvostruko gore od toga** (to je `rezerva`).

| Provera | Šta se meri u normalnom periodu | Alarm kad je |
| --- | --- | --- |
| izostanak | najduža pauza između rezultata | pauza duža od 2 x te |
| nemoguća vrednost | najveći odskok vrednosti od susednih | odskok veći od 2 x tog |
| promašen skok | najveći odskok greške od susednih | odskok veći od 2 x tog |
| drift | koliko se tipična greška menjala iz dana u dan | promena veća od 2 x te |
| pad tačnosti | koliko se stopa grešaka kolebala iz dana u dan | rast veći od 2 x tog |

Primer: ako je u normalnom periodu najduža pauza bila 1 sat, izostanak je
pauza duža od 2 sata. Za model kome su pauze normalno do 5 sati, granica
je 10 sati. **Isti kod, različite granice, a nijedna nije izmišljena.**

## Šta je aplikacija naučila

```bash
python -m app.proveri data/simulirano/senzori.csv --granice
```

Primer ispisa:

```
  senzori / M1
    - normalni period: do 08.10.2026 11:00 (UTC)
    - rezultati obično stižu na svakih 1 h
    - izostanak: pauza duža od 2 h
    - nemoguća vrednost: odskok od susednih veći od 29.1 °C
    - promašen skok: greška odskoči od susednih više od 8.44 °C
    - drift: tipična greška se pomeri za više od 1.34 °C (normalno je oko 1.08 °C)
```

## Šta ostaje čoveku

Samo tri stvari, i nijedna nije znanje o modelu:

| Podešavanje | Podrazumevano | Šta znači |
| --- | --- | --- |
| `rezerva` | 2 | **Osetljivost.** Koliko puta gore od najgoreg normalnog mora da bude za alarm. Veće = manje alarma. |
| `udeo_osnove` | 0,25 | Koji deo podataka sa početka je normalni period. |
| `prag_pristrasnosti` | 0,5 | Definicija pristrasnosti: više od pola greške uvek u istom smeru. |

Rezerva je **poslovna odluka**: koliko alarma ljudi žele da dobijaju. Nju
nijedan sistem ne može da zna unapred. Određuje se u pilotu. Može da se
proba i bez menjanja koda:

```bash
python -m app.proveri fajl.csv --rezerva 3
```

Pristrasnost je izuzetak od pravila „uči iz normalnog perioda“: ona postoji
od samog početka, pa nema normalnog perioda sa kojim bi se poredila. Zato je
za nju ostala definicija.

## Dokaz da granice nisu fiksne

Test `test_isti_nalazi_bez_obzira_na_jedinice` uzme simulirane podatke, pa
iste te podatke pomnožene sa 1.000 (kao da su u drugim jedinicama), i
zahteva da nalazi budu potpuno isti. Sa granicama upisanim u kod to ne bi
moglo da prođe.

## Pretpostavke i ograničenja

- **Normalni period mora biti normalan.** Ako je model već tada imao problem,
  aplikacija će ga naučiti kao normalno stanje.
- **Treba dovoljno podataka.** Granica se uči tek kad u normalnom periodu ima
  bar 10 rezultata (za drift bar 2 dana rezultata). Do tada se ta provera
  preskače. Za model koji šalje jedan rezultat dnevno to znači oko 40 dana.
- **Važnost u praksi se ne zna.** Ako greška poraste sa 0,1 na 0,3, to je za
  aplikaciju veliki skok, a možda nikome ne smeta. To se rešava kad saznamo
  kakav je model.
- **Statistika nije savršena.** Na 300 simuliranih skupova (oko 250 godina
  rada jednog izvora) pojavila se jedna lažna uzbuna. Pravi podaci su
  „neuredniji“, pa će ih tamo biti više. Koliko, videćemo u pilotu.

## Pojmovi

- **Kalibracija**: podešavanje granica na osnovu stvarnog ponašanja.
- **Rezerva**: koliko puta gore od najgoreg normalnog mora da bude za alarm.
- **Odskok od susednih**: koliko se vrednost razlikuje od medijane vrednosti oko nje.

## Sledeći korak

Korak 4: **alarmi**. Nalazi treba da stignu do ljudi: na ekran, mejlom ili
porukom, po ozbiljnosti, bez ponavljanja istog alarma sto puta.
