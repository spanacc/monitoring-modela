# Korak 4: Alarmi

## Šta smo napravili

Nalazi iz provera sada stižu do ljudi. Aplikacija ima svoje „srce“: **krug
nadzora**, koji se može ponavljati na svakih nekoliko sekundi ili minuta.

```
učitaj rezultate -> nauči granice i proveri -> uskladi sa alarmima -> pošalji obaveštenja
     (korak 2)            (korak 3)                 (korak 4)              (korak 4)
```

```bash
cp konfiguracija.primer.json konfiguracija.json
python -m app.nadzor --sada podaci
```

## Najvažnije: isti problem se ne javlja sto puta

Provere svaki put ponovo pregledaju sve podatke i ponovo nađu iste probleme.
Zato postoji **evidencija alarma** (`data/alarmi.json`):

- **Jedan problem je jedan alarm.** Nalaz koji odgovara postojećem alarmu
  (isti tip, model i izvor, i vremena se dodiruju) samo produži taj alarm.
- **Obaveštenje se šalje samo kad ima nešto novo:**
    * nov problem,
    * problem se pogoršao (upozorenje je postalo kritično),
    * problem je bio rešen, a ponovo se javlja.
- **Svi novi alarmi idu u jednoj poruci.** Ako odjednom bude 20 problema,
  stiže jedna poruka sa spiskom, a ne 20 poruka.

Primer na simuliranim podacima:

```
prvi krug:  10 nalaza, 10 novih alarma  -> poslata obaveštenja
drugi krug: 10 nalaza,  0 novih alarma  -> ništa se ne šalje
```

## Statusi alarma

| Status | Značenje | Šta se dešava ako problem traje |
| --- | --- | --- |
| `otvoren` | Nov, niko ga još nije pogledao | ne javlja se ponovo, osim ako se pogorša |
| `potvrdjen` | Neko ga je video („radim na tome“) | ne javlja se ponovo |
| `resen` | Problem je otklonjen | **ponovo se otvara i javlja** |

```bash
python -m app.alarmi                                  # otvoreni alarmi
python -m app.alarmi lista --svi                      # i rešeni
python -m app.alarmi potvrdi 3 --ko Veljko --napomena "proveravam server"
python -m app.alarmi resi 3 --napomena "restartovan"
```

Razlika između potvrde i rešavanja je bitna. **Potvrda** znači „znamo za ovo,
ne javljaj više“, npr. kad je model namerno ugašen zbog održavanja. **Rešavanje**
znači „popravljeno je“, pa ako se problem nastavi, to je nov razlog za uzbunu.

## Kanali i nivoi ozbiljnosti

| Kanal | Šta radi | Treba mu |
| --- | --- | --- |
| `ekran` | ispis u Terminalu | ništa |
| `dnevnik` | upis u tekstualni fajl | putanja |
| `mejl` | e-pošta | SMTP server firme, adrese, lozinka |
| `poruka` | Slack, Microsoft Teams, Mattermost... („webhook“) | adresa koju da IT |

Koji nivo ide na koje kanale, piše u podešavanjima. Po planu bi bilo ovako:

| Nivo | Kanali |
| --- | --- |
| info | dnevnik (kasnije i dashboard) |
| upozorenje | dnevnik + mejl |
| kritično | dnevnik + mejl + poruka |

U `konfiguracija.primer.json` mejl i poruka su opisani, ali se još ne koriste
(nemamo pravi server). Kad IT da podatke, samo se dodaju u `slanje`.

## Podešavanja u fajlu, ne u kodu

Sve je u `konfiguracija.json`: koji fajlovi se prate, osetljivost (ukupno i po
modelu), kanali, šta ide kuda. Primer je u `konfiguracija.primer.json`.

```json
"provere": {"rezerva": 2.0},
"modeli": {
  "potrosnja": {"rezerva": 3.0}
}
```

Ovo znači: svi modeli imaju rezervu 2, a potrošnja 3 (manje alarma).

**Greške u fajlu se javljaju odmah i jasno**, npr:

```
konfiguracija.json ne valja:
  kanali.ekran.boja: nepoznato polje (proverite da li je dobro napisano)
  fajl: U 'slanje' za 'kriticno' piše kanal 'telefon', a on nije definisan u 'kanali'
```

## Bezbednost: tajne nisu u fajlu

Lozinka za mejl i adresa za poruke **ne pišu se** u `konfiguracija.json`. U fajlu
stoji samo **ime promenljive okruženja** u kojoj se tajna nalazi:

```json
"lozinka_iz": "MONITORING_MEJL_LOZINKA"
```

a na serveru se tajna postavi ovako:

```bash
export MONITORING_MEJL_LOZINKA='...'
```

Tako tajne nikad ne završe na git-u. Pored toga, `konfiguracija.json` je u
`.gitignore`, jer sadrži adrese servera i ljudi. Na git ide samo primer.

## Kad nešto ne radi

- **Kanal ne radi** (npr. mejl server je pao): greška se ispiše, ostali kanali
  rade normalno, a alarm ostaje „za slanje“ i pokušava se ponovo u sledećem
  krugu. Bolje je da poruka stigne dvaput nego nijednom.
- **Izvor ne postoji ili je pokvaren**: greška se ispiše, a ostali izvori se
  proveravaju normalno.

## Šta znači `--sada podaci`

Da bi primetila „tišinu“ (model prestao da šalje), aplikacija poredi poslednji
rezultat sa trenutnim vremenom. Simulirani podaci su iz prošlosti, pa bi bez ove
opcije odmah javila da je svaki model ućutao. **U pravom radu se ne koristi.**

## Brzina

Ceo krug za simulirane podatke (oko 9.500 rezultata) traje manje od sekunde.

```bash
python -m app.nadzor --ponavljaj 60     # krug na svakih 60 sekundi
```

## Šta još ne radi

- Alarmi se čuvaju u JSON fajlu, a **baza dolazi u koraku 5**. Ostatak aplikacije
  se tada neće menjati, jer sve ide preko klase `Evidencija`.
- Krug svaki put čita ceo fajl iznova. Za mnogo veće količine podataka to će
  biti sporo, pa i to rešava baza u koraku 5.
- Normalni period je prva četvrtina **svih** podataka, pa se u dugom radu
  pomera kako podaci rastu. U koraku 5 normalni period postaje fiksan.

## Pojmovi

- **Krug nadzora**: jedno izvršavanje celog posla (učitaj, proveri, javi).
- **Evidencija**: spisak svih alarma i njihovih statusa.
- **Kanal**: način slanja obaveštenja.
- **SMTP**: način na koji programi šalju mejl.
- **Webhook**: adresa na koju program pošalje poruku, a ona se pojavi u Slack-u, Teams-u i sl.
- **Promenljiva okruženja**: podešavanje koje se čuva van programa, na računaru
  na kome program radi. Koristi se za tajne.

## Sledeći korak

Korak 5: **baza podataka**. Rezultati i alarmi prelaze u bazu, pa aplikacija
ostaje brza i sa godinama istorije, a normalni period postaje fiksan.
