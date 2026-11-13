import argparse
from pathlib import Path
from zoneinfo import ZoneInfo

from app.alarmi.evidencija import Evidencija, StatusAlarma
from app.alarmi.kanali import OZNAKE

ZONA = ZoneInfo("Europe/Belgrade")


def ispisi(evidencija: Evidencija, svi: bool) -> None:
    alarmi = evidencija.alarmi if svi else evidencija.otvoreni()
    if not alarmi:
        print("Nema otvorenih alarma." if not svi else "Nema alarma.")
        return
    for a in alarmi:
        status = a.status.value + (f" ({a.potvrdio})" if a.potvrdio else "")
        print(f"#{a.id:<4} [{OZNAKE[a.ozbiljnost]}] {a.tip} | {a.model} / {a.izvor} | {status}")
        print(f"      od {a.od.astimezone(ZONA):%d.%m.%Y %H:%M} "
              f"do {a.do.astimezone(ZONA):%d.%m.%Y %H:%M}")
        print(f"      {a.opis}")
        if a.napomena:
            print(f"      napomena: {a.napomena}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pregled, potvrda i rešavanje alarma.")
    parser.add_argument("--evidencija", type=Path, default=Path("data/alarmi.json"))
    komande = parser.add_subparsers(dest="komanda")

    lista = komande.add_parser("lista", help="prikaži alarme")
    lista.add_argument("--svi", action="store_true", help="prikaži i rešene")

    potvrdi = komande.add_parser("potvrdi", help="video sam alarm, više ga ne javljaj dok traje")
    potvrdi.add_argument("id", type=int)
    potvrdi.add_argument("--ko", required=True)
    potvrdi.add_argument("--napomena")

    resi = komande.add_parser("resi", help="problem je otklonjen")
    resi.add_argument("id", type=int)
    resi.add_argument("--napomena")

    args = parser.parse_args()
    evidencija = Evidencija(args.evidencija)

    try:
        if args.komanda == "potvrdi":
            a = evidencija.potvrdi(args.id, args.ko, args.napomena)
            print(f"Alarm #{a.id} je potvrđen.")
        elif args.komanda == "resi":
            a = evidencija.resi(args.id, args.napomena)
            print(f"Alarm #{a.id} je označen kao rešen.")
        else:
            ispisi(evidencija, getattr(args, "svi", False))
            return
    except KeyError as e:
        raise SystemExit(e.args[0])
    evidencija.sacuvaj()


if __name__ == "__main__":
    main()