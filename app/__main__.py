"""
Pokretanje cele aplikacije jednom komandom:

    python -m app

Pokrene nadzor (krug na svakih 60 s) i dashboard, pa otvori stranicu u
pregledaču. Podaci se dodaju na samoj stranici (dugme "Dodaj podatke"), a
podešavanja se sama čuvaju u data/podesavanja.json. Zaustavlja se sa Ctrl+C.

    python -m app --port 8080                 # ako je port 8000 zauzet
    python -m app --bez-pregledaca            # ne otvaraj pregledač sam (npr. na serveru)
    python -m app --konfiguracija moja.json   # ručno napisana podešavanja (koraci 4-6)
    python -m app --nadzor 300                # krug nadzora na 5 minuta

Stariji način (python -m app.nadzor, python -m app.dashboard) i dalje radi.
"""

import argparse
import threading
import webbrowser
from pathlib import Path

import uvicorn

from app.alarmi.konfiguracija import PODRAZUMEVANA_PUTANJA, ucitaj_konfiguraciju, ucitaj_ili_prazna
from app.dashboard.server import napravi_aplikaciju


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitoring modela: nadzor i dashboard u jednom.")
    parser.add_argument("--konfiguracija", type=Path, default=None,
                        help=f"podešavanja (podrazumevano {PODRAZUMEVANA_PUTANJA}, pravi se samo)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--nadzor", type=int, default=60, metavar="SEKUNDI",
                        help="krug nadzora na svakih toliko sekundi (0 = bez nadzora)")
    parser.add_argument("--bez-pregledaca", action="store_true", help="ne otvaraj pregledač sam")
    args = parser.parse_args()

    putanja = args.konfiguracija or PODRAZUMEVANA_PUTANJA
    try:
        k = ucitaj_konfiguraciju(putanja) if args.konfiguracija else ucitaj_ili_prazna(putanja)
    except ValueError as e:
        raise SystemExit(f"Greška u podešavanjima: {e}")

    app = napravi_aplikaciju(k, nadzor_sekundi=args.nadzor or None, putanja_podesavanja=putanja)
    adresa = f"http://127.0.0.1:{args.port}"
    print(f"Monitoring modela radi na {adresa}  (Ctrl+C za kraj)")
    if not k.izvori:
        print("Još nema podataka: dodajte ih na stranici dugmetom \"Dodaj podatke\".")
    if not args.bez_pregledaca:
        # Pregledač se otvara tek kad server krene (sekund kasnije).
        threading.Timer(1.0, lambda: webbrowser.open(adresa)).start()
    # Dashboard vidi samo ovaj računar (prijava i rad u mreži dolaze u koraku 8).
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
