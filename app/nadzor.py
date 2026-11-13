import argparse
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.alarmi.evidencija import Alarm, Evidencija
from app.alarmi.konfiguracija import Konfiguracija, ucitaj_konfiguraciju
from app.citac import ucitaj_csv
from app.prepoznavanje import Mapiranje
from app.provere import Nalaz, proveri_sve


@dataclass
class Izvestaj:
    """Šta se desilo u jednom krugu."""

    rezultata: int = 0
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

    # 1. Učitavanje. Ako jedan izvor ne valja, ostali se i dalje proveravaju.
    rezultati = []
    for izvor in k.izvori:
        try:
            mapiranje = Mapiranje.ucitaj(izvor.mapiranje) if izvor.mapiranje else None
            rezultati += ucitaj_csv(izvor.putanja, izvor.model, mapiranje, k.zona).rezultati
        except (OSError, ValueError) as e:
            izvestaj.greske.append(f"Izvor {izvor.putanja}: {e}")
    izvestaj.rezultata = len(rezultati)

    # 2. Provere, svaki model sa svojom osetljivošću.
    po_modelu = defaultdict(list)
    for r in rezultati:
        po_modelu[r.model].append(r)
    nalazi: list[Nalaz] = []
    for model, njegovi in po_modelu.items():
        nalazi += proveri_sve(njegovi, k.podesavanja_za(model), sada)
    izvestaj.nalaza = len(nalazi)

    # 3. Usklađivanje sa evidencijom.
    evidencija = Evidencija(k.evidencija)
    izvestaj.novih_alarma = len(evidencija.uskladi(nalazi, datetime.now(timezone.utc)))

    # 4. Slanje. Uspešno poslati alarmi više ne čekaju.
    posalji_obavestenja(evidencija, k, izvestaj)

    evidencija.sacuvaj()
    izvestaj.otvorenih_alarma = len(evidencija.otvoreni())
    return izvestaj


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
        for ime in k.slanje.get(a.ozbiljnost, []):
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
        if not neuspeli & set(k.slanje.get(a.ozbiljnost, [])):
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

        print(f"[{datetime.now():%H:%M:%S}] {iz.rezultata} rezultata, {iz.nalaza} nalaza, "
              f"{iz.novih_alarma} novih alarma, {iz.otvorenih_alarma} otvorenih "
              f"({time.monotonic() - pocetak:.1f} s)")
        for ime, broj in iz.poslato.items():
            print(f"    poslato na '{ime}': {broj}")
        for greska in iz.greske:
            print(f"    GREŠKA: {greska}")

        if not args.ponavljaj:
            break
        time.sleep(args.ponavljaj)


if __name__ == "__main__":
    main()