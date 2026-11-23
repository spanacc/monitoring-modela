"""
Učitavanje rezultata modela iz CSV fajla.

ŠTA JE OVO
----------
Čita CSV fajl bilo kakvog oblika, prepoznaje kolone (modul prepoznavanje)
i svaki red pretvara u `Rezultat` iz univerzalnog formata.

ZAŠTO OVAKO
-----------
- Neispravan red NE ruši učitavanje. Zapisuje se na spisak grešaka sa brojem
  reda, a ostali redovi se učitaju. Monitoring mora da radi i kad su podaci
  delimično pokvareni, jer upravo tada je najpotrebniji.
- Prazna vrednost NIJE greška. Takav rezultat se učita kao prazan, a provere
  u koraku 3 će ga prijaviti.
- Fajl može biti iz Excela (tačka-zarez, decimalni zarez, kodna strana 1250)
  ili iz nekog programa (zarez, decimalna tačka, UTF-8). Prepoznajemo oba.

ŠIROKA TABELA
-------------
Često je svaki senzor u svojoj koloni: vreme;Pritisak;Protok;Temperatura.
Tada se navedu kolone (`kolone`), pa svaka postaje poseban izvor, kao da je
fajl zapisan red po red: vreme, izvor, vrednost. Reč "sve" znači: sve
kolone u kojima su brojevi (osim vremena).

KAKO SE KORISTI
---------------
    python -m app.citac data/simulirano/senzori.csv
    python -m app.citac neki_fajl.csv --sacuvaj-mapiranje mapiranje.json
    python -m app.citac neki_fajl.csv --mapiranje mapiranje.json
    python -m app.citac siroka_tabela.csv --kolone Pritisak Protok
    python -m app.citac siroka_tabela.csv --kolone sve
"""

import argparse
import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.prepoznavanje import (
    Mapiranje,
    je_prazno,
    napravi_profil,
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


def dodaj_doba_dana(vreme: datetime, tekst: str) -> datetime:
    """Datumu iz jedne kolone dodaje sat iz druge: '14:30' ili ceo broj sati (0-23)."""
    if ":" in tekst:
        delovi = tekst.split(":")
        try:
            sati, minuti = int(delovi[0]), int(delovi[1])
            sekunde = int(delovi[2]) if len(delovi) > 2 else 0
        except ValueError:
            raise ValueError(f"neispravno doba dana: '{tekst}'")
    else:
        broj = procitaj_broj(tekst)
        if broj is None or not 0 <= broj < 24:
            raise ValueError(f"neispravno doba dana: '{tekst}'")
        sati, minuti, sekunde = int(broj), round((broj - int(broj)) * 60), 0
    if not (0 <= sati < 24 and 0 <= minuti < 60 and 0 <= sekunde < 60):
        raise ValueError(f"neispravno doba dana: '{tekst}'")
    return vreme.replace(hour=sati, minute=minuti, second=sekunde)


def red_u_rezultat(red: dict, m: Mapiranje, model: str, zona: tzinfo) -> Rezultat:
    """Pretvara jedan red fajla u Rezultat. Baca ValueError ako red ne valja."""

    def uzmi(polje: str) -> str:
        kolona = m.polja.get(polje)
        tekst = red.get(kolona) if kolona else None
        return "" if je_prazno(tekst) else tekst.strip()

    vreme = procitaj_vreme(uzmi("vreme"), zona, m.redosled_datuma)
    if vreme is None and re.fullmatch(r"(19|20)\d\d", uzmi("vreme")):
        # Samo godina (npr. 2007): kolona je izričito označena kao vreme,
        # pa je uzimamo kao 1. januar te godine.
        vreme = datetime(int(uzmi("vreme")), 1, 1, tzinfo=zona)
    if vreme is None:
        raise ValueError(f"neispravno vreme: '{uzmi('vreme')}'")
    if uzmi("doba_dana"):
        vreme = dodaj_doba_dana(vreme, uzmi("doba_dana"))

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


def red_u_rezultate(red: dict, m: Mapiranje, model: str, zona: tzinfo,
                    kolone: list[str] | None = None) -> list[Rezultat]:
    """
    Jedan red fajla u rezultate. Obično je to jedan rezultat, a kod široke
    tabele po jedan za svaku navedenu kolonu: izvor je naziv kolone.
    """
    if not kolone:
        return [red_u_rezultat(red, m, model, zona)]
    zajednicka = {"vreme", "doba_dana", "model", "horizont_min", "status", "poruka", "jedinica"}
    rezultati = []
    for kolona in kolone:
        polja = {p: k for p, k in m.polja.items() if p in zajednicka}
        polja["vrednost"] = kolona
        siroko = Mapiranje(polja=polja, velicina=normalizuj(kolona), redosled_datuma=m.redosled_datuma)
        r = red_u_rezultat(red, siroko, model, zona)
        rezultati.append(r.model_copy(update={"izvor": kolona}))
    return rezultati


def brojcane_kolone(kolone: list[str], redovi: list[dict], m: Mapiranje) -> list[str]:
    """Kolone u kojima su (skoro) sve vrednosti brojevi, osim vremena i rednog broja."""
    uzorak = redovi[:500]
    lista = []
    for k in kolone:
        if k in (m.polja.get("vreme"), m.polja.get("doba_dana")):
            continue
        p = napravi_profil([r.get(k) or "" for r in uzorak])
        if p.udeo_brojeva >= 0.9 and not p.redni:  # redni broj reda nije merenje
            lista.append(k)
    return lista


def ucitaj_csv(
    putanja: Path | str,
    model: str | None = None,
    mapiranje: Mapiranje | None = None,
    zona: str = PODRAZUMEVANA_ZONA,
    kolone: list[str] | None = None,
) -> Ucitano:
    """
    Učitava ceo fajl.

    model:     naziv modela; ako se ne zada, uzima se ime fajla.
    mapiranje: ručno podešeno mapiranje; ako se ne zada, prepoznaje se samo.
    kolone:    široka tabela: svaka od ovih kolona je poseban izvor
               (["sve"] = sve brojčane kolone).
    """
    putanja = Path(putanja)
    kolone_fajla, redovi = procitaj_csv(putanja)
    m = mapiranje or prepoznaj(kolone_fajla, redovi)

    if "vreme" not in m.polja:
        raise ValueError(
            "Nije pronađena kolona sa vremenom, a bez vremena praćenje nije "
            "moguće. Upišite je ručno u mapiranje (--mapiranje)."
        )
    if kolone == ["sve"]:
        kolone = brojcane_kolone(kolone_fajla, redovi, m)
    if kolone:
        nema = [k for k in kolone if k not in kolone_fajla]
        if nema:
            raise ValueError(f"U fajlu nema kolona: {', '.join(nema)}. "
                             f"Postoje: {', '.join(kolone_fajla)}.")
    elif "vrednost" not in m.polja and "kategorija" not in m.polja:
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
            rezultati += red_u_rezultate(red, m, model, tz, kolone)
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
    parser.add_argument("--kolone", nargs="+", metavar="KOLONA",
                        help="široka tabela: svaka kolona je poseban izvor ('sve' = sve brojčane)")
    args = parser.parse_args()

    mapiranje = Mapiranje.ucitaj(args.mapiranje) if args.mapiranje else None
    try:
        ucitano = ucitaj_csv(args.putanja, args.model, mapiranje, args.zona, args.kolone)
    except ValueError as e:
        raise SystemExit(f"Greška: {e}")

    m = ucitano.mapiranje
    print(f"Fajl: {args.putanja}\n\nPrepoznate kolone:")
    for polje, kolona in m.polja.items():
        if args.kolone and polje not in ("vreme", "doba_dana", "status", "poruka", "jedinica"):
            continue  # kod široke tabele vrednosti i izvori dolaze iz navedenih kolona
        print(f"  {polje:20} <- {kolona:25} ({m.nacin.get(polje, 'ručno')})")
    for napomena in m.napomene:
        print(f"  PAŽNJA: {napomena}")
    if args.kolone:
        izvori = sorted({r.izvor for r in ucitano.rezultati})
        print(f"\nŠiroka tabela, kolone kao izvori: {', '.join(izvori)}")
    else:
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
