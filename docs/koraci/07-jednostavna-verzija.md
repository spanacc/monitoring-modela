# Korak 7: Jednostavna verzija

## Zašto

Posle testova na pravim fajlovima (korak 6b) ispostavilo se da aplikacija
radi, ali da je komplikovana za korišćenje: pokretanje iz Terminala sa
opcijama, podešavanja u JSON fajlu, kolone koje treba ručno navesti, ekran
sa dva grafikona i stručnim rečima, alarmi sa nivoima i formama za potvrdu.

Cilj ovog koraka: **jedna komanda, pa sve ostalo mišem**, i ekran koji
razume neko ko ne zna šta je „drift“.

## Šta se promenilo

### 1. Pokretanje: jedna komanda

```bash
python -m app
```

Pokrene proveru (na svakih 60 s) i stranicu, i sam otvori pregledač. Sve
stare komande (`python -m app.nadzor`, `python -m app.dashboard`) i dalje
rade, za one koji hoće da podešavaju ručno.

### 2. Podaci se dodaju na stranici

Zupčanik gore desno, pa dugme **Dodaj podatke**. Ubaci se CSV fajl (ili prevuče), ili se
upiše putanja do fajla ili foldera na računaru. Folder znači: svi CSV fajlovi
u njemu, i oni koji se tek pojave; to je za pravi rad, kad model sam ostavlja
fajlove.

Aplikacija pročita fajl i pokaže šta je prepoznala: koja kolona je vreme,
koja rezultat modela, koliko redova ima i od kad do kad. Čovek pogleda,
ispravi ako treba, i klikne **Dodaj i proveri**. Ako nešto ne može da zna
sama (npr. da li je `11/10` novembar ili oktobar), kaže to u žutom okviru.

Podešavanja se sama čuvaju u `data/podesavanja.json`. Fajlovi ubačeni sa
stranice se kopiraju u `data/ulaz/`; fajlovi na zadatoj putanji se ne diraju.
Aplikacija i dalje samo čita podatke modela.

### 3. Stari podaci (proba, arhiva)

Ako je poslednji rezultat stariji od nedelju dana, aplikacija predloži
„Ovo su stari podaci“. Tada se vreme računa od poslednjeg rezultata (inače
bi pisalo da model ćuti od 2012.), a proverava se cela istorija, ne samo
poslednjih 30 dana. Svaki model ima svoju vremensku osu, pa podaci iz 2012.
i iz 2020. mogu da stoje jedan ispod drugog.

### 4. Ekran: dashboard na jednoj strani

Izgled je dogovoren u dva kruga pitanja i skica, pre pisanja koda: svetao i
čist, plava boja aplikacije, a zelena, žuta i crvena samo za stanje.

1. **Tri pločice gore:**
   - *Stanje* (semafor): „Sve u redu“, „2 problema“ ili „Hitno: 3“, i koji
     model je u pitanju.
   - *Odstupanje od normalnog*: koliko se izabrani model udaljio od onoga
     što je naučeno kao normalno. 0% je isto kao u normalnom periodu, 100% je
     granica posle koje se javlja problem. Mali grafikon pokazuje kako se to
     menjalo.
   - *Otvoreni problemi*: koliko ih ima i koliko ih još niko nije video.
2. **Veliki grafikon**: rezultati modela kroz vreme. Zeleni pojas je ono što
   je normalno, obojene trake su vreme problema, a najvažniji problem ima
   oblačić („11.10. · 6,4, obično između 36 i 64“). Iznad su dugmad sa
   imenima modela (tačka u boji stanja) i period (24 h do „sve“).
   Grafikon sam izabere model koji ima problem; može se kliknuti i drugi.
3. **Problemi desno**, kao kartice. Otvoreni imaju **Video sam** (prvi put
   pita za ime) i **Prikaži na grafikonu**. Ispod su napomene (sitnice) i
   ono što je prošlo u poslednjih 7 dana.
4. **Zupčanik** gore desno: stranica sa podešavanjima (šta se prati,
   dodavanje i uklanjanje fajlova, „Proveri sada“).

Nazivi modela i izvora nisu upisani u aplikaciju: dolaze iz fajlova koji se
dodaju (ime fajla, kolona sa nazivom modela ili nazivi kolona).

Radi i na telefonu (sve jedno ispod drugog). Tema (svetla, tamna) prati računar.

Kod stranice je podeljen na tri fajla u `app/dashboard/static/`:
`pregled.js` (glavna strana), `podesavanja.js` (podešavanja) i `alati.js`
(ono što obe koriste: vreme, brojevi, razgovor sa serverom).

### 5. Problemi se sami gase

Kad problem prođe (npr. podaci opet stižu), aplikacija ga sama zatvori i u
„prošlim“ piše „Prošlo.“ Niko ne mora ništa da „rešava“. To se radi samo
kad je provera prošla bez greške, da nedostupan fajl ne bi „rešio“ sve.

Nazivi problema su obične reči:

| Ranije (u bazi i dalje tako) | Sada na ekranu |
| --- | --- |
| izostanak | Podaci ne stižu |
| duplikat | Isti podaci stigli više puta |
| greska_modela | Model javlja grešku |
| prazne_vrednosti | Rezultati bez vrednosti |
| nemoguca_vrednost | Neobična vrednost |
| pristrasnost | Model stalno greši u istom smeru |
| drift | Ponašanje se promenilo |
| promasen_skok | Veliki promašaj |
| pad_tacnosti | Tačnost je opala |
| promena_kategorija (novo) | Odgovori su se promenili |

Nivoi su „hitno“, „problem“ i „napomena“. Ako se problem vrati posle
zatvaranja, otvara se ponovo.

### 6. Sedam rupa iz testova sa pingvinima i biciklima

| Rupa | Popravka |
| --- | --- |
| Redni broj reda (`rowid`, `instant`) uzet kao rezultat modela | Prepoznaje se po sadržaju (1, 2, 3, 4…), ma kako se zvao |
| Reči „predviđena“, „predikcija“ nisu bile poznate | Dodati sinonimi za predviđeno i stvarno |
| Model vraća kategoriju, a stvarni odgovor se ne zna: ništa se nije pratilo | Nova provera **promena odgovora**: prati koliki deo odgovora je koja kategorija. U simulatoru sad nalazi i pad tačnosti bez stvarnih vrednosti |
| Datum u jednoj koloni, sat u drugoj (`dteday` + `hr`): sva 24 sata u istom trenutku | Prepoznaje se kolona sa satom (po nazivu ili sadržaju 0–23) i spaja sa datumom |
| Samo godina ili samo mesec kao vreme | Mesec radi sam (`2026-11`, `11.2026`); godina kad se kolona ručno izabere |
| Prikaz najviše 90 dana | Dodato „godinu dana“ i „sve“; osa za duge periode piše mesece |
| Brojevi kao `4,94e+03`; pad nacrtan na vrhu grafikona kao skok | Svi brojevi u srpskom zapisu (`4.940`); neobična vrednost se crta gore, dole ili na svom mestu, gde joj je mesto |

Uz to: datumi sa kosim crtama (`11/10/2026`) se čitaju, a redosled dana i
meseca se pogađa iz cele kolone; kad ne može, čovek bira na stranici.

## Šta je ostalo isto

Provere, kalibracija, baza, alarmi u bazi, kanali, konfiguracija iz fajla:
sve iz koraka 1–6 radi kao i pre. Dodato je, ništa nije izbačeno.

## Rezultat na pravim fajlovima, bez ijednog podešavanja

Sva tri fajla iz testova ubačena su kroz stranicu, samo sa potvrdom predloga:

- **day.csv (bicikli po danu):** uragan Sendi (29.10.2012.), kišna nedelja
  (22.4.2012.) i promena ponašanja u septembru 2012. Isto kao ranije, ali
  bez pisanja konfiguracije.
- **hour.csv (bicikli po satu):** sad se čita tačno (17.379 sati umesto 731
  dana). Nalazi dve napomene: isti sat zapisan dvaput, u noći kad se sat
  vraća sa letnjeg na zimsko vreme. To je istina o fajlu.
- **SKAB (pumpa):** folder sa 16 fajlova, 6 senzora kao izvori. Sa
  podrazumevanim podešavanjima nalazi zagrevanje termopara. Za 19 od 20
  zatvaranja ventila (korak 6b) i dalje treba podesiti normalni period i
  rezervu, u `data/podesavanja.json` (`"provere": {"rezerva": 4,
  "dana_osnove": 0.00625}`). To još nije na stranici.
- **penguins.csv:** aplikacija kaže da nema kolone sa vremenom i ne dozvoli
  dodavanje. Tačno: to nisu rezultati modela kroz vreme.

## Šta još ne radi

- Normalni period i osetljivost se ne podešavaju na stranici, samo u
  `data/podesavanja.json`.
- Excel fajl (.xlsx) direktno; prvo se sačuva kao CSV.
- Čitanje iz baze ili preko API-ja; za sad samo fajlovi.
- Prijava korisnika i rad u mreži: korak 8. Dok toga nema, dashboard vidi
  samo ovaj računar, jer sa stranice može da se zada putanja do bilo kog
  CSV fajla na njemu.

## Pojmovi

- **Predlog**: šta je aplikacija pogodila o fajlu, pre nego što čovek potvrdi.
- **Stari podaci**: fajl koji se više ne dopunjava (proba, arhiva). Vreme se
  računa od poslednjeg rezultata.
- **Promena odgovora**: kod modela koji vraćaju kategorije, odnos kategorija
  se pomerio više nego ikad u normalnom periodu.

## Sledeći korak

Korak 8: prijava, uloge, HTTPS i postavljanje na server.
