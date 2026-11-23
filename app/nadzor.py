"""
Nadzor: srce aplikacije. Jedan "krug" nadzora je:

    1. upiši nove rezultate iz svih izvora u bazu      (koraci 2 i 5)
    2. iz baze pročitaj ono što treba i proveri         (koraci 3 i 5)
    3. uskladi nalaze sa evidencijom alarma             (korak 4)
    4. pošalji obaveštenja za nove alarme               (korak 4)

KAKO SE KORISTI
---------------
    python -m app.nadzor                              # jedan krug
    python -m app.nadzor --ponavljaj 60               # krug na svakih 60 sekundi
    python -m app.nadzor --sada podaci                # za simulirane (stare) podatke
    python -m app.nadzor --konfiguracija moja.json

ŠTA ZNAČI --sada podaci
-----------------------
Da bi primetila "tišinu" (model prestao da šalje), aplikacija poredi
poslednji rezultat sa trenutnim vremenom. Simulirani podaci su iz prošlosti,
pa bi za njih odmah javila da je svaki model "ućutao". Sa `--sada podaci`
se kao "sada" uzima vreme poslednjeg rezultata, pa tišina ne smeta probi.
U pravom radu ova opcija se NE koristi.

BRZINA
------
Iz baze se čita samo normalni period (za učenje granica) i poslednjih
`dana_provere` dana (za proveru). Zato krug traje isto i posle godina rada,
bez obzira na to koliko se istorije skupilo.
"""

import argparse
import glob
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.alarmi.evidencija import Alarm, Evidencija
from app.alarmi.konfiguracija import Konfiguracija, ucitaj_konfiguraciju
from app.baza import Baza
from app.citac import ucitaj_csv
from app.provere import Nalaz, proveri_sve


@dataclass
class Izvestaj:
    """Šta se desilo u jednom krugu."""

    novih_rezultata: int = 0  # upisano u bazu u ovom krugu
    provereno: int = 0  # pročitano iz baze i provereno
    nalaza: int = 0
    novih_alarma: int = 0
    otvorenih_alarma: int = 0
    poslato: dict[str, int] = field(default_factory=dict)  # kanal -> broj alarma
    greske: list[str] = field(default_factory=list)


def jedan_krug(k: Konfiguracija, sada: datetime | None = None) -> Izvestaj:
    """
    sada: trenutno vreme za proveru tišine. None = vreme poslednjeg
          rezultata (za simulirane podatke).
    """
    izvestaj = Izvestaj()
    baza = Baza(k.baza)

    # 1. Uvoz u bazu. Ako jedan fajl ne valja, ostali se i dalje uvoze.
    for izvor in k.izvori:
        putanje = fajlovi(izvor.putanja)
        if not putanje:
            izvestaj.greske.append(f"Izvor {izvor.putanja}: nijedan fajl ne odgovara ovoj putanji.")
        for putanja in putanje:
            try:
                mapiranje = izvor.napravi_mapiranje()
                ucitano = ucitaj_csv(putanja, izvor.model, mapiranje, k.zona, izvor.kolone)
                izvestaj.novih_rezultata += baza.upisi_rezultate(str(putanja), ucitano.rezultati)
            except (OSError, ValueError) as e:
                izvestaj.greske.append(f"Izvor {putanja}: {e}")

    # 2. Provere iz baze, svaki model sa svojom osetljivošću.
    nalazi: list[Nalaz] = []
    istorijski = k.istorijski_modeli()
    for model in baza.modeli():
        p = k.podesavanja_za(model)
        prvo, poslednje = baza.prvo_i_poslednje(model)
        # Za stare podatke (proba, arhiva) "sada" je poslednji rezultat.
        sada_modela = None if model in istorijski else sada
        kraj = sada_modela or poslednje

        # Čita se samo normalni period i poslednjih `dana_provere` dana. Stari
        # podaci (proba, arhiva) se proveravaju celi: tu se gleda istorija.
        pocetak = (kraj - timedelta(days=k.dana_provere)
                   if k.dana_provere and model not in istorijski else None)
        kraj_osnove = prvo + timedelta(days=p.dana_osnove) if p.dana_osnove else None
        rezultati = baza.citaj_rezultate(model, kraj_osnove, pocetak)
        izvestaj.provereno += len(rezultati)

        njegovi = proveri_sve(rezultati, p, sada_modela)
        if pocetak:
            njegovi = [n for n in njegovi if u_periodu_provere(n, pocetak)]
        nalazi += njegovi
    izvestaj.nalaza = len(nalazi)

    # 3. Usklađivanje sa evidencijom.
    evidencija = Evidencija(baza=baza)
    # Problemi koje provere više ne nalaze sami se zatvaraju, ali samo kad je
    # krug prošao bez greške (inače bi nedostupan fajl "rešio" sve alarme).
    izvestaj.novih_alarma = len(evidencija.uskladi(nalazi, datetime.now(timezone.utc),
                                                   zatvori_nestale=not izvestaj.greske))

    # 4. Slanje. Uspešno poslati alarmi više ne čekaju.
    posalji_obavestenja(evidencija, k, izvestaj)

    evidencija.sacuvaj()
    izvestaj.otvorenih_alarma = len(evidencija.otvoreni())
    return izvestaj


def fajlovi(putanja: Path) -> list[Path]:
    """
    Fajlovi jednog izvora. Putanja sa zvezdicom (npr. data/*.csv) znači sve
    takve fajlove: korisno kad model svaki dan (ili svaki eksperiment) piše
    nov fajl. Svaki fajl se u bazu uvozi zasebno, samo njegovi novi redovi.
    """
    if any(znak in str(putanja) for znak in "*?["):
        return [Path(p) for p in sorted(glob.glob(str(putanja)))]
    return [Path(putanja)]


def u_periodu_provere(n: Nalaz, pocetak: datetime) -> bool:
    """
    Da li nalaz pripada periodu provere (poslednjih `dana_provere` dana).

    - Problem koji se završio pre početka perioda je star. Već je prijavljen
      ranije i čuva se u evidenciji alarma.
    - Problem koji traje u period provere se zadržava, npr. pristrasnost,
      koja se računa od samog početka podataka.
    - Izuzetak je izostanak koji počinje pre perioda provere: deo između
      normalnog perioda i perioda provere se namerno ne čita iz baze, pa bi
      izgledao kao da rezultati nisu stizali, a to nije istina.
    """
    if n.do <= pocetak:
        return False
    return not (n.tip == "izostanak" and n.od < pocetak)


def posalji_obavestenja(evidencija: Evidencija, k: Konfiguracija, izvestaj: Izvestaj) -> None:
    """
    Svaki kanal dobija JEDNU poruku sa svim svojim alarmima.

    Ako kanal ne uspe (npr. mejl server ne radi), alarm ostaje "za slanje"
    i pokušava se ponovo u sledećem krugu. Bolje je da poruka stigne dvaput
    nego nijednom.
    """
    cekaju = [a for a in evidencija.alarmi if a.za_slanje]
    po_kanalu: dict[str, list[Alarm]] = defaultdict(list)
    for a in cekaju:
        for ime in k.kanali_za(a.ozbiljnost):
            po_kanalu[ime].append(a)

    neuspeli: set[str] = set()
    for ime, alarmi in po_kanalu.items():
        try:
            k.napravi_kanal(ime).posalji(alarmi)
            izvestaj.poslato[ime] = len(alarmi)
        except Exception as e:  # bilo koja greška kanala ne sme da zaustavi nadzor
            neuspeli.add(ime)
            izvestaj.greske.append(f"Kanal '{ime}' nije uspeo: {e}")

    for a in cekaju:
        if not neuspeli & set(k.kanali_za(a.ozbiljnost)):
            a.za_slanje = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Nadzor modela: proveri i javi alarme.")
    parser.add_argument("--konfiguracija", type=Path, default=Path("konfiguracija.json"))
    parser.add_argument("--sada", choices=["trenutno", "podaci"], default="trenutno",
                        help="'podaci' samo za probu na simuliranim (starim) podacima")
    parser.add_argument("--ponavljaj", type=int, metavar="SEKUNDI",
                        help="ponavljaj krug na svakih toliko sekundi (Ctrl+C za kraj)")
    args = parser.parse_args()

    try:
        k = ucitaj_konfiguraciju(args.konfiguracija)
    except ValueError as e:
        raise SystemExit(f"Greška u podešavanjima: {e}")

    while True:
        pocetak = time.monotonic()
        sada = datetime.now(timezone.utc) if args.sada == "trenutno" else None
        iz = jedan_krug(k, sada)

        print(f"[{datetime.now():%H:%M:%S}] {iz.novih_rezultata} novih rezultata, "
              f"{iz.provereno} provereno, {iz.nalaza} nalaza, {iz.novih_alarma} novih alarma, "
              f"{iz.otvorenih_alarma} otvorenih ({time.monotonic() - pocetak:.1f} s)")
        for ime, broj in iz.poslato.items():
            print(f"    poslato na '{ime}': {broj}")
        for greska in iz.greske:
            print(f"    GREŠKA: {greska}")

        if not args.ponavljaj:
            break
        time.sleep(args.ponavljaj)


if __name__ == "__main__":
    main()
