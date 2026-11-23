# Korak 8: Obaveštenja mejlom

## Šta je napravljeno

Kad provera nađe problem, mejl stiže sam. Podešava se na stranici
**Podešavanja** (zupčanik), bez diranja fajlova:

| Šta | Kada |
| --- | --- |
| Mejl za nove probleme | Odmah, čim provera nađe nov problem (ili se problem pogorša). Svi novi problemi iz jedne provere idu u **jedan** mejl. Napomene (sitnice) se ne šalju. Isti problem se ne šalje ponovo. |
| Dnevni pregled | Jednom dnevno, u izabrano vreme (npr. 07:30): šta je otvoreno, šta je prošlo za 24 h, ili „Sve u redu“. |
| Probni mejl | Dugme na stranici: dnevni pregled odmah, da se vidi da slanje radi. |

Svi sa spiska primalaca dobijaju sve. Mejl ima boje i spisak problema kao
na stranici, i dugme „Otvori monitoring“ (ako je upisana adresa aplikacije).
Za stare programe za mejl, u istom mejlu je i obična tekstualna verzija.

## Kako se podešava (Gmail, za probu)

1. Na Google nalogu uključiti dvostepenu prijavu.
2. Na myaccount.google.com/apppasswords napraviti „lozinku za aplikaciju“
   (16 slova). Obična lozinka naloga ne radi, i to je dobro: ova lozinka
   može samo da šalje mejl i može se ugasiti u svakom trenutku.
3. U aplikaciji: Podešavanja → Obaveštenja mejlom → „Gmail“ (popuni server i
   port), upisati nalog, lozinku za aplikaciju i primaoce.
4. **Pošalji probni mejl.** Ako stigne, uključiti „Uključeno“.

Gmail je samo za probu: podaci firme ne bi trebalo da idu preko privatnog
naloga. Za pravi rad pitati IT za firmin nalog (ili „Microsoft 365 /
Outlook“, isto dugme za brzo popunjavanje).

## Bezbednost

| Pretnja | Zaštita |
| --- | --- |
| Lozinka procuri preko git-a, kopiranog fajla ili snimka ekrana | Lozinka nije u podešavanjima. Čuva se **šifrovana** u `data/tajne/mejl.tajna` (biblioteka `cryptography`, postupak Fernet), sa ključem u `data/tajne/kljuc`. Oba fajla čita samo korisnik koji pokreće aplikaciju (prava 600). `data/` ne ide na git. |
| Lozinka se vidi na stranici | Server je **nikad ne šalje nazad**, samo kaže „sačuvana“. Polje ostaje prazno; prazno pri čuvanju znači „ostavi staru“. Postoji „Zaboravi lozinku“. |
| Lozinka putuje nešifrovana do mejl servera | Veza je uvek šifrovana (port 465 ili STARTTLS). Ako server ne podržava šifrovanje, mejl se **ne šalje**. Sertifikat servera se proverava (nema razgovora sa lažnim serverom). |
| Lozinka u porukama o greškama | Greške su napisane za čoveka („server je odbio nalog ili lozinku“) i nikad ne sadrže lozinku. |
| Ime modela ubaci kod u mejl ili lažno zaglavlje („Bcc: svi“) | Tekst iz podataka se u HTML ubacuje očišćen (`html.escape`), a iz naslova se brišu novi redovi. |
| Neko koristi dugme kao „top za mejlove“ | Najviše jedan probni mejl na 10 s. Primalaca najviše 20. Adrese se proveravaju. |
| Druga stranica na internetu menja podešavanja | Kao i do sad: svaka izmena traži posebno zaglavlje (zaštita od CSRF), a dashboard vidi samo ovaj računar. |

Iskreno o granicama: šifrovanje štiti od slučajnog curenja. Ko ima potpun
pristup računaru ima i ključ. Na serveru je zato bolje ključ postaviti kao
promenljivu okruženja `MONITORING_KLJUC`, ili lozinku uopšte ne upisivati na
stranici nego kao `MONITORING_MEJL_LOZINKA` (ona ima prednost). Pravo
zaključavanje stranice (prijava) je korak 9.

## Šta je promenjeno u kodu

| Fajl | Šta |
| --- | --- |
| `app/tajne.py` (novo) | Šifrovano čuvanje lozinke. |
| `app/alarmi/mejl.py` (novo) | Izgled mejla (tekst + HTML), bezbedno slanje, dnevni pregled. |
| `app/alarmi/konfiguracija.py` | Podešavanja mejla sa stranice (`mejl` u `data/podesavanja.json`) sa proverom svakog polja. |
| `app/alarmi/kanali.py` | I stari mejl iz ručne konfiguracije sad šalje isto, bezbedno. |
| `app/nadzor.py` | Novi problemi idu i na mejl sa stranice. |
| `app/dashboard/server.py` | Adrese `/api/mejl` (lozinka se nikad ne vraća), probni mejl, dnevni pregled posle svake provere. |
| `podesavanja.html`, `podesavanja.js`, `stil.css` | Deo „Obaveštenja mejlom“ na stranici. |
| `tests/test_mejl.py` (novo) | 11 provera, sa lažnim mejl serverom (pravi se ne dira). |
| `requirements.txt` | Dodato `cryptography`. |

## Pojmovi

- **SMTP**: način na koji programi šalju mejl preko mejl servera.
- **STARTTLS / port 465**: šifrovanje veze sa mejl serverom.
- **Lozinka za aplikaciju**: posebna lozinka koju Google ili Microsoft daju
  za jedan program; ne otvara ceo nalog i može se ugasiti.

## Sledeći korak

Korak 9: prijava, uloge, HTTPS i postavljanje na server.
