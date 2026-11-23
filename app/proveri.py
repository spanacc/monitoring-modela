import argparse
from pathlib import Path

from app.citac import PODRAZUMEVANA_ZONA, ucitaj_csv
from app.prepoznavanje import Mapiranje
from app.provere import Podesavanja, proveri_sve
from app.provere.kalibracija import kalibrisi, opisi_granice
from app.provere.osnova import po_serijama

OZNAKE = {"info": "INFO", "upozorenje": "UPOZORENJE", "kriticno": "KRITIČNO"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Proverava rezultate modela iz CSV fajla.")
    parser.add_argument("putanja", type=Path)
    parser.add_argument("--model", help="naziv modela (podrazumevano: ime fajla)")
    parser.add_argument("--zona", default=PODRAZUMEVANA_ZONA)
    parser.add_argument("--mapiranje", type=Path, help="ručno podešeno mapiranje (JSON)")
    parser.add_argument("--rezerva", type=float, default=Podesavanja.rezerva,
                        help="osetljivost: veći broj = manje alarma")
    parser.add_argument("--granice", action="store_true",
                        help="ispiši granice koje je aplikacija naučila")
    parser.add_argument("--kolone", nargs="+", metavar="KOLONA",
                        help="široka tabela: svaka kolona je poseban izvor ('sve' = sve brojčane)")
    args = parser.parse_args()

    mapiranje = Mapiranje.ucitaj(args.mapiranje) if args.mapiranje else None
    try:
        ucitano = ucitaj_csv(args.putanja, args.model, mapiranje, args.zona, args.kolone)
    except ValueError as e:
        raise SystemExit(f"Greška: {e}")

    p = Podesavanja(rezerva=args.rezerva)

    print(f"Fajl: {args.putanja}")
    print(f"Učitano {len(ucitano.rezultati)} rezultata "
          f"({len(ucitano.greske)} neispravnih redova preskočeno).\n")

    if args.granice:
        print("Granice koje je aplikacija sama naučila:\n")
        for serija in po_serijama(ucitano.rezultati).values():
            g = kalibrisi(serija, p)
            print(f"  {serija[0].model} / {serija[0].izvor}")
            for red in opisi_granice(serija, g) if g else ["premalo podataka"]:
                print(f"    - {red}")
            print()

    nalazi = proveri_sve(ucitano.rezultati, p)
    if not nalazi:
        print("Nije pronađen nijedan problem.")
        return

    print(f"Pronađeno problema: {len(nalazi)}\n")
    for n in nalazi:
        print(f"[{OZNAKE[n.ozbiljnost.value]}] {n.tip} | {n.model} / {n.izvor}")
        print(f"    od {n.od:%d.%m.%Y %H:%M} do {n.do:%d.%m.%Y %H:%M} (UTC)")
        print(f"    {n.opis}\n")


if __name__ == "__main__":
    main()