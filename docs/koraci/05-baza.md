# Korak 5: Baza podataka

## Šta smo napravili

Rezultati i alarmi se sada čuvaju u **bazi podataka**. Krug nadzora izgleda ovako:

```
fajlovi modela -> upiši NOVE redove u bazu -> iz baze pročitaj šta treba -> proveri -> alarmi
```

## Zašto baza

1. **Istorija ostaje.** Ako model svaki dan prepiše svoj fajl, ili ga obriše,
   rezultati su i dalje u bazi. Bez toga bi nestao i normalni period, pa
   aplikacija ne bi imala sa čim da poredi.
2. **Brzina i posle godina rada.** Iz baze se čita samo normalni period (za
   učenje granica) i poslednjih 30 dana (za proveru). Ono između ne treba, pa
   se ni ne čita. Krug zato traje isto i kad se skupe godine podataka.
3. **Alarmi na jednom mestu.** Odatle će ih čitati i dashboard (korak 6).

## Koja baza

| | Za probu | Za pravi rad |
| --- | --- | --- |
| Baza | SQLite | PostgreSQL, ili šta IT odredi |
| Šta treba instalirati | ništa, to je jedna datoteka | server baze (radi IT) |
| Adresa u konfiguraciji | `sqlite:///data/monitoring.db` | `postgresql+psycopg://korisnik@server/monitoring` |

Kod je pisan preko biblioteke **SQLAlchemy**, koja ume da radi sa većinom baza.
Prelazak na drugu bazu je promena adrese u `konfiguracija.json` (i instalacija
odgovarajućeg „drajvera“, npr. `psycopg` za PostgreSQL). Sa PostgreSQL-om ovo
još nije isprobano. Proverićemo kad IT obezbedi server.

## Tabele

| Tabela | Šta je u njoj |
| --- | --- |
| `rezultati` | svaki rezultat modela (polja iz koraka 1) + iz kog fajla je i koji je po redu |
| `alarmi` | svi alarmi sa statusima (polja iz koraka 4) |

## Uvoz samo novih redova

Svaki rezultat pamti iz kog fajla je došao i koji je po redu u njemu. Kad se
fajl ponovo pročita, u bazu se upisuju samo redovi posle poslednjeg već
upisanog:

```
prvi krug:   9442 novih rezultata
drugi krug:     0 novih rezultata   (fajlovi se nisu menjali)
```

**Pretpostavka:** model fajl samo **dopisuje** (nove redove na kraj). Ako ga
prepisuje od početka sa drugim sadržajem, ovo treba prilagoditi. Kad saznamo
kako pravi model izbacuje rezultate, uvoz se prilagođava tome.

Duplikati iz fajla se namerno čuvaju kao dva rezultata, da bi ih provera
duplikata iz koraka 3 i dalje videla.

## Zamka sa vremenom

SQLite tiho **odbacuje vremensku zonu**. Bez zaštite, 14:00 po beogradskom
vremenu bilo bi upisano kao 14:00 bez zone, a to je pogrešan trenutak (pravi
je 13:00 UTC). Zato baza **svako vreme pre upisa pretvara u UTC**, a pri čitanju
mu vraća zonu UTC. Test `test_vreme_sa_zonom_ostaje_tacno` to proverava.

## Fiksan normalni period

Do sada je normalni period bio prva četvrtina **svih** podataka. U stalnom radu
to bi se pomeralo kako podaci rastu (posle godinu dana, „normalni period“ bi
bio prva tri meseca), pa bi se i granice menjale same od sebe.

Sada može da se zada **broj dana**:

```json
"provere": {"rezerva": 2.0, "dana_osnove": 7}
```

Normalni period je onda prvih 7 dana i nikad se ne pomera.

**Koliko dana?** Što duže, to bolje, jer se granice uče iz više podataka. Na
simuliranim podacima (300 skupova): sa 25% podataka (oko 7,5 dana) pojavila
se 1 lažna uzbuna, a sa 7 dana 3. Svi problemi su pronađeni u oba slučaja. U
primeru je 7 dana jer simulirani podaci traju samo 30. **Za pravi rad
preporuka je bar 14 dana**, i to perioda za koji se zna da je bio miran.

## Provera samo poslednjih N dana

```json
"dana_provere": 30
```

Prijavljuju se samo problemi iz poslednjih 30 dana. Stariji su već prijavljeni
ranije i čuvaju se u bazi kao alarmi. Dva izuzetka su namerna:

- **Pristrasnost** se računa od početka podataka, pa se zadržava čim traje i u
  poslednjih 30 dana.
- **Izostanak koji počinje pre perioda provere** se odbacuje, jer se deo između
  normalnog perioda i poslednjih 30 dana ne čita iz baze, pa bi izgledao kao da
  rezultati nisu stizali.

Provereno na simulaciji od 90 dana: sa celom istorijom je pronađeno svih 10
problema, a sa poslednjih 30 dana tačno oni iz tog perioda, bez ijedne lažne
uzbune.

## Šta se promenilo u podešavanjima

U `konfiguracija.json`:

| Bilo | Sada |
| --- | --- |
| `"evidencija": "data/alarmi.json"` | `"baza": "sqlite:///data/monitoring.db"` |
| | `"dana_provere": 30` (novo) |
| `"provere": {"rezerva": 2.0}` | `"provere": {"rezerva": 2.0, "dana_osnove": 7}` |

Najlakše je ponovo kopirati primer: `cp konfiguracija.primer.json konfiguracija.json`.
Stari alarmi iz `data/alarmi.json` se ne prenose. Za simulirane podatke to nije
važno, a prvi krug ih ponovo napravi u bazi.

## Kako proveriti

```bash
pip install -r requirements.txt     # nova biblioteka: sqlalchemy
pytest                              # 93 provere
cp konfiguracija.primer.json konfiguracija.json
python -m app.nadzor --sada podaci  # prvi put: 9442 novih rezultata
python -m app.nadzor --sada podaci  # drugi put: 0 novih rezultata, 0 novih alarma
```

## Šta još ne radi

- Svaki krug i dalje pročita **ceo CSV fajl**, a u bazu upiše samo nove redove.
  Za ogromne fajlove i to može biti sporo. Kad saznamo kako model isporučuje
  rezultate, čitanje se prilagođava.
- Ako model ćuti duže od `dana_provere` dana, „tišina“ se više ne prijavljuje
  kao nova. Alarm je ipak napravljen čim je tišina počela, i ostaje otvoren u bazi.

## Pojmovi

- **Baza podataka**: program za uredno čuvanje i brzo pretraživanje podataka.
- **Tabela**: deo baze, kao jedan list u Excelu: kolone su polja, a redovi zapisi.
- **SQLite / PostgreSQL**: dve vrste baza. SQLite je datoteka, a PostgreSQL server.
- **SQLAlchemy**: biblioteka preko koje Python radi sa bazama, bez obzira na vrstu.
- **Indeks**: kao sadržaj knjige. Baza brzo nađe rezultate jednog modela u nekom
  vremenskom periodu, bez pregledanja cele tabele.
- **Transakcija**: grupa izmena koja se izvrši cela ili nikako. Ako nešto pukne
  na pola, u bazi ne ostane polovičan upis.

## Sledeći korak

Korak 6: **dashboard**.
