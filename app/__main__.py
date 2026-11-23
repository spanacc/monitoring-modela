import argparse
import threading
import webbrowser
from pathlib import Path

import uvicorn

from app.alarmi.konfiguracija import PODRAZUMEVANA_PUTANJA, ucitaj_konfiguraciju, ucitaj_ili_prazna
from app.baza import Baza
from app.dashboard.server import napravi_aplikaciju
from app.dodavanje import napusteni_modeli
from simulator import uzivo


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitoring modela: nadzor i dashboard u jednom.")
    parser.add_argument("--konfiguracija", type=Path, default=None,
                        help=f"podešavanja (podrazumevano {PODRAZUMEVANA_PUTANJA}, pravi se samo)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--nadzor", type=int, default=60, metavar="SEKUNDI",
                        help="krug nadzora na svakih toliko sekundi (0 = bez nadzora)")
    parser.add_argument("--bez-pregledaca", action="store_true", help="ne otvaraj pregledač sam")
    parser.add_argument("--demo", action="store_true",
                        help="probni podaci uživo (data/demo): tri izmišljena modela od 1. novembra")
    parser.add_argument("--bez-demoa", action="store_true", help="skloni probne podatke")
    args = parser.parse_args()

    putanja = args.konfiguracija or PODRAZUMEVANA_PUTANJA
    try:
        k = ucitaj_konfiguraciju(putanja) if args.konfiguracija else ucitaj_ili_prazna(putanja)
    except ValueError as e:
        raise SystemExit(f"Greška u podešavanjima: {e}")

    baza = Baza(k.baza)
    if args.bez_demoa:
        uzivo.iskljuci(k, putanja, baza)
        print("Probni podaci su sklonjeni.")
    elif args.demo or k.demo:
        try:
            novi = uzivo.ukljuci(k, putanja)
        except (ValueError, OSError) as e:
            raise SystemExit(f"Probni podaci nisu mogli da se dodaju: {e}")
        if novi:
            print(f"Dodati probni modeli: {', '.join(novi)} (gase se sa --bez-demoa).")
    if not args.konfiguracija:
        # Ostaci starih proba: modeli u bazi čije fajlove više niko ne prati.
        # Inače bi zauvek javljali "Podaci ne stižu". Originalni fajlovi se ne diraju.
        for model in napusteni_modeli(k, baza):
            baza.obrisi_model(model)
            print(f"Sklonjen stari model iz baze (više se ne prati): {model}")

    app = napravi_aplikaciju(k, nadzor_sekundi=args.nadzor or None, putanja_podesavanja=putanja,
                             pre_kruga=uzivo.dopuni if k.demo else None,
                             izazovi_problem=uzivo.izazovi if k.demo else None)
    adresa = f"http://127.0.0.1:{args.port}"
    print(f"Monitoring modela radi na {adresa}  (Ctrl+C za kraj)")
    if not k.izvori:
        print("Još nema podataka: dodajte ih na stranici dugmetom \"Dodaj podatke\".")
    if not args.bez_pregledaca:
        # Pregledač se otvara tek kad server krene (sekund kasnije).
        threading.Timer(1.0, lambda: webbrowser.open(adresa)).start()
    # Dashboard vidi samo ovaj računar (prijava i rad u mreži dolaze u koraku 9).
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
