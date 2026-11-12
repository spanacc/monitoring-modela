import argparse
import csv
import io
from dataclasses import dataclass
from datetime import tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.prepoznavanje import (
    Mapiranje,
    je_prazno,
    normalizuj,
    prepoznaj,
    procitaj_broj,
    procitaj_vreme,
)
from app.schema import Rezultat, Status

# Zona za vremena koja u fajlu nemaju zonu (npr. "10.11.2026 14:00").
PODRAZUMEVANA_ZONA = "Europe/Belgrade"

# Ako fajl nema kolonu sa izvorom, svi rezultati dobijaju ovaj izvor.
PODRAZUMEVANI_IZVOR = "glavni"

# Vrednosti kolone 'status' koje znače da je sve u redu. Sve ostalo je greška.
STATUSI_OK = {"ok", "success", "uspeh", "uspesno", "true", "done", "completed"}


@dataclass
class Ucitano:
    rezultati: list[Rezultat]
    greske: list[tuple[int, str]]  # (broj reda u fajlu, opis greške)
    mapiranje: Mapiranje


def procitaj_tekst(putanja: Path) -> str:
    """Excel na Windowsu često čuva u kodnoj strani 1250, ostali u UTF-8."""
    sirovo = putanja.read_bytes()
    try:
        # "-sig" uklanja nevidljivi znak koji Excel ume da doda na početak fajla.
        return sirovo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return sirovo.decode("cp1250")


def procitaj_csv(putanja: Path) -> tuple[list[str], list[dict]]:
    """Vraća nazive kolona i redove. Sam pogađa razdvajač (, ; tab |)."""
    tekst = procitaj_tekst(putanja)
    try:
        razdvajac = csv.Sniffer().sniff(tekst[:5000], delimiters=",;\t|").delimiter
    except csv.Error:
        razdvajac = ","
    citac = csv.DictReader(io.StringIO(tekst), delimiter=razdvajac)
    redovi = list(citac)
    return list(citac.fieldnames or []), redovi


def red_u_rezultat(red: dict, m: Mapiranje, model: str, zona: tzinfo) -> Rezultat:
    """Pretvara jedan red fajla u Rezultat. Baca ValueError ako red ne valja."""

    def uzmi(polje: str) -> str:
        kolona = m.polja.get(polje)
        tekst = red.get(kolona) if kolona else None
        return "" if je_prazno(tekst) else tekst.strip()

    vreme = procitaj_vreme(uzmi("vreme"), zona)
    if vreme is None:
        raise ValueError(f"neispravno vreme: '{uzmi('vreme')}'")

    podaci = {
        "vreme": vreme,
        "model": uzmi("model") or model,
        "izvor": uzmi("izvor") or PODRAZUMEVANI_IZVOR,
        "velicina": uzmi("velicina") or m.velicina,
    }

    for polje in ("vrednost", "stvarna_vrednost", "horizont_min"):
        tekst = uzmi(polje)
        if tekst:
            broj = procitaj_broj(tekst)
            if broj is None:
                raise ValueError(f"{polje} nije broj: '{tekst}'")
            podaci[polje] = int(broj) if polje == "horizont_min" else broj

    for polje in ("kategorija", "stvarna_kategorija", "jedinica", "poruka"):
        if uzmi(polje):
            podaci[polje] = uzmi(polje)

    status = uzmi("status")
    if status and normalizuj(status) not in STATUSI_OK:
        podaci["status"] = Status.GRESKA
        # Ako nema posebne poruke, sam tekst statusa je poruka (npr. "timeout").
        podaci.setdefault("poruka", status)

    return Rezultat(**podaci)


def ucitaj_csv(
    putanja: Path | str,
    model: str | None = None,
    mapiranje: Mapiranje | None = None,
    zona: str = PODRAZUMEVANA_ZONA,
) -> Ucitano:
    """
    Učitava ceo fajl.

    model:     naziv modela; ako se ne zada, uzima se ime fajla.
    mapiranje: ručno podešeno mapiranje; ako se ne zada, prepoznaje se samo.
    """
    putanja = Path(putanja)
    kolone, redovi = procitaj_csv(putanja)
    m = mapiranje or prepoznaj(kolone, redovi)

    if "vreme" not in m.polja:
        raise ValueError(
            "Nije pronađena kolona sa vremenom, a bez vremena praćenje nije "
            "moguće. Upišite je ručno u mapiranje (--mapiranje)."
        )
    if "vrednost" not in m.polja and "kategorija" not in m.polja:
        raise ValueError(
            "Nije pronađena kolona sa rezultatom modela (broj ili kategorija). "
            "Upišite je ručno u mapiranje (--mapiranje)."
        )

    tz = ZoneInfo(zona)
    model = model or putanja.stem
    rezultati: list[Rezultat] = []
    greske: list[tuple[int, str]] = []

    for broj_reda, red in enumerate(redovi, start=2):  # red 1 je zaglavlje
        try:
            rezultati.append(red_u_rezultat(red, m, model, tz))
        except ValueError as e:
            # Greške iz pydantic-a su dugačke; uzimamo samo prvu poruku.
            poruka = e.errors()[0]["msg"] if isinstance(e, ValidationError) else str(e)
            greske.append((broj_reda, poruka))

    return Ucitano(rezultati, greske, m)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Učitava rezultate modela iz CSV fajla i pokazuje šta je prepoznato."
    )
    parser.add_argument("putanja", type=Path, help="CSV fajl sa rezultatima")
    parser.add_argument("--model", help="naziv modela (podrazumevano: ime fajla)")
    parser.add_argument("--zona", default=PODRAZUMEVANA_ZONA,
                        help="vremenska zona za vremena koja je nemaju")
    parser.add_argument("--mapiranje", type=Path,
                        help="koristi ručno podešeno mapiranje iz JSON fajla")
    parser.add_argument("--sacuvaj-mapiranje", type=Path,
                        help="sačuvaj prepoznato mapiranje u JSON fajl")
    args = parser.parse_args()

    mapiranje = Mapiranje.ucitaj(args.mapiranje) if args.mapiranje else None
    try:
        ucitano = ucitaj_csv(args.putanja, args.model, mapiranje, args.zona)
    except ValueError as e:
        raise SystemExit(f"Greška: {e}")

    m = ucitano.mapiranje
    print(f"Fajl: {args.putanja}\n\nPrepoznate kolone:")
    for polje, kolona in m.polja.items():
        print(f"  {polje:20} <- {kolona:25} ({m.nacin.get(polje, 'ručno')})")
    print(f"\nNeprepoznate kolone: {', '.join(m.neprepoznate) or 'nema'}")
    print(f"\nUčitano: {len(ucitano.rezultati)} rezultata, {len(ucitano.greske)} grešaka")
    for broj_reda, poruka in ucitano.greske[:10]:
        print(f"  red {broj_reda}: {poruka}")
    if len(ucitano.greske) > 10:
        print(f"  ... i još {len(ucitano.greske) - 10}")

    if args.sacuvaj_mapiranje:
        m.sacuvaj(args.sacuvaj_mapiranje)
        print(f"\nMapiranje sačuvano u {args.sacuvaj_mapiranje}. "
              "Možete ga ispraviti i koristiti sa --mapiranje.")


if __name__ == "__main__":
    main()