# Korak 8b: Probni podaci uživo i „Rešio sam“

## Zašto

Stari probni fajlovi su stali u oktobru, pa je aplikacija (tačno) javljala
„Podaci ne stižu“ za sve. Za probu dashboarda i mejlova treba nešto što
izgleda kao model koji upravo radi. Uz to, problem je mogao samo da se
označi kao „viđen“; zatvarao se tek sam, kad prođe.

## Probni podaci uživo

```bash
python -m app --demo
```

Tri izmišljena modela, sa različitim nazivima kolona (aplikacija ih
prepoznaje sama, kao da ih je čovek dodao na stranici):

| Model | Šta vraća | Koliko često |
| --- | --- | --- |
| `temperatura_peci` | broj (°C), 3 peći, uz izmerenu vrednost | na 10 min |
| `potrosnja_hale` | broj (kWh), uz izmerenu vrednost i status | na sat |
| `kontrola_kvaliteta` | kategorija („ispravno“ / „škart“), 2 linije | na 15 min |

Podaci počinju 1. novembra. Pre svake provere (na svakih 60 s) dopisuju se
novi redovi do tog trenutka. Posle gašenja i ponovnog pokretanja fajl samo
nastavi gde je stao. Normalni period je prva nedelja novembra.

Ubačeni problemi (vreme po Beogradu):

| Kada | Gde | Šta |
| --- | --- | --- |
| 9.11. 10–16 h | temperatura_peci, Peć 2 | Podaci ne stižu |
| 12.11. 14:20 | temperatura_peci, Peć 1 | Neobična vrednost (9999) |
| 15.11. 6–9 h | potrosnja_hale | Model javlja grešku |
| 17.11. 18–21 h | potrosnja_hale | Veliki promašaj |
| od 19.11., traje | temperatura_peci, Peć 3 | Ponašanje se promenilo |
| od 20.11., traje | kontrola_kvaliteta, Linija 2 | Tačnost je opala |

Aplikacija nalazi svih šest. Fajlovi su u `data/demo/`, podešavanje se pamti
(`"demo": true`), pa sledeći put je dovoljno `python -m app`. Gašenje:

```bash
python -m app --bez-demoa
```

Aplikacija i dalje samo čita podatke modela: `data/demo/` piše „lažni
model“ iz `simulator/uzivo.py`, ne provere.

## Problem na dugme (proba mejla)

Na stranici **Podešavanja**, samo dok su probni podaci uključeni, postoji
deo **Probni problem**. Izabere se šta će model „odjednom“ uraditi:

- Peć 1 vrati nemoguću vrednost (9.999 °C), ili
- model za potrošnju javi grešku umesto rezultata,

i klikne **Napravi problem sada**. Loš rezultat se odmah dopiše u fajl,
provera krene odmah (ne čeka se minut), nađe nov problem i, ako su
obaveštenja mejlom uključena, pošalje mejl. Ispod dugmeta piše šta se
desilo: koliko novih problema i da li je mejl otišao (ili zašto nije).

Isti problem u roku od 10 minuta se računa kao nastavak prethodnog, pa
drugi mejl ne ide. Za drugi mejl odmah: izabrati drugu vrstu problema.

## Stari modeli iz baze

Pri pokretanju `python -m app` modeli koji su u bazi, a čiji fajl više ne
prati nijedan izvor (ostaci starih proba), sklanjaju se iz baze. Inače bi
zauvek javljali „Podaci ne stižu“. Originalni fajlovi se ne diraju.

## „Rešio sam“

Na svakoj kartici problema, pored „Video sam“, sad je i **Rešio sam**.
Otvori mali prozor: ime (pita se samo prvi put) i, ako hoćeš, šta je
urađeno. Problem prelazi u „Prošlo u poslednjih 7 dana“ sa tekstom „Rešio
Veljko, 23.11. 13:03: ponovo pokrenut prenos podataka.“

Ako problem i dalje traje (npr. model i dalje greši), sledeća provera ga
ponovo otvara i šalje mejl. To piše i u prozoru, da ne bude iznenađenje.

## „Sve u redu“ i spisak modela

Ekran samo sa problemima ima manu: prazan ekran može da znači „sve je
dobro“ ili „monitoring je stao“. Zato desna kolona sad uvek pokazuje i
dokaz da sve radi:

- Kad nema problema: **Sve u redu**, „Bez problema 5 dana. Provereno
  upravo.“ (od kraja poslednjeg pravog problema; napomene se ne računaju).
- Ispod toga **svi modeli**, po jedan red: tačka u boji stanja, ime, „u
  redu“ / „problem“ / „hitno“ (i „neko je video“), i kad je stigao
  poslednji rezultat. Klik na red prikaže model na grafikonu.
- Kad ima problema, problemi su prvi, a spisak modela je ispod njih.

Zelena je namerno mala: normalno stanje treba da bude tiho, a problem
upadljiv.

## Šta je promenjeno u kodu

| Fajl | Šta |
| --- | --- |
| `simulator/uzivo.py` (novo) | Tri modela uživo, ubačeni problemi, uključivanje i gašenje. |
| `app/__main__.py` | `--demo`, `--bez-demoa`, sklanjanje starih modela iz baze. |
| `app/dashboard/server.py` | Dopisivanje probnih podataka pre kruga (pod istom bravom: provera nikad ne čita pola reda). „Rešio sam“ prima i ime. Adresa `/api/demo/problem` (postoji samo uz `--demo`, traži zaglavlje protiv CSRF). |
| `app/alarmi/evidencija.py` | Pamti ko je rešio i kada. |
| `app/alarmi/konfiguracija.py` | Polje `demo`. |
| `app/baza.py`, `app/dodavanje.py` | Koji model je stigao iz kog fajla; prepoznavanje napuštenih modela. |
| `index.html`, `pregled.js`, `stil.css` | Dugme i prozor „Rešio sam“; „Sve u redu“ i spisak modela desno. |
| `app/dashboard/podaci.py` | `mirno_od`: od kad nema problema. |
| `podesavanja.html`, `podesavanja.js` | Deo „Probni problem“ (vidi se samo uz `--demo`). |
| `tests/test_demo.py` (novo) | 7 provera. |
