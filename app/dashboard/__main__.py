"""
Pokretanje dashboarda iz Terminala.

    python -m app.dashboard --sada podaci        # proba na simuliranim podacima
    python -m app.dashboard --nadzor 60          # pravi rad: i krug nadzora na 60 s
    python -m app.dashboard --port 8080          # ako je port 8000 zauzet

Zatim u pregledaču otvoriti adresu koju ispiše (http://127.0.0.1:8000).
Zaustavlja se sa Ctrl+C.
"""

import argparse
from pathlib import Path

import uvicorn

from app.alarmi.konfiguracija import ucitaj_konfiguraciju
from app.dashboard.server import napravi_aplikaciju

SAMO_OVAJ_RACUNAR = {"127.0.0.1", "localhost", "::1"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Dashboard monitoringa modela.")
    parser.add_argument("--konfiguracija", type=Path, default=Path("konfiguracija.json"))
    parser.add_argument("--adresa", default="127.0.0.1",
                        help="127.0.0.1 = dashboard vidi samo ovaj računar (preporučeno)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--nadzor", type=int, metavar="SEKUNDI",
                        help="pokreći i krug nadzora na svakih toliko sekundi")
    parser.add_argument("--sada", choices=["trenutno", "podaci"], default="trenutno",
                        help="'podaci' samo za probu na simuliranim (starim) podacima")
    args = parser.parse_args()

    try:
        k = ucitaj_konfiguraciju(args.konfiguracija)
    except ValueError as e:
        raise SystemExit(f"Greška u podešavanjima: {e}")

    hostovi = ["127.0.0.1", "localhost"]
    if args.adresa not in SAMO_OVAJ_RACUNAR:
        print("PAŽNJA: dashboard je dostupan i drugim računarima u mreži, a još nema "
              "prijavu (dolazi u koraku 9). Koristite ovo samo u zaštićenoj mreži.")
        hostovi = ["*"] if args.adresa in ("0.0.0.0", "::") else hostovi + [args.adresa]

    app = napravi_aplikaciju(k, sada_po_podacima=args.sada == "podaci",
                             nadzor_sekundi=args.nadzor, hostovi=hostovi)
    prikaz = "127.0.0.1" if args.adresa in ("0.0.0.0", "::") else args.adresa
    print(f"Dashboard radi na http://{prikaz}:{args.port}  (Ctrl+C za kraj)")
    # access_log=False: bez reda u Terminalu za svako osvežavanje stranice.
    uvicorn.run(app, host=args.adresa, port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
