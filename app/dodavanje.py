"""
Dodavanje podataka sa dashboarda (korak 7).

ŠTA JE OVO
----------
Umesto da čovek piše konfiguraciju u JSON fajlu, na stranici ubaci CSV fajl
(ili upiše folder u kome model ostavlja fajlove). Aplikacija:

    1. predlog()     pročita fajl, prepozna kolone i vrati predlog: šta je
                     vreme, šta je rezultat modela, na šta treba paziti
    2. čovek pogleda predlog i, ako treba, ispravi
    3. dodaj_izvor() upiše izvor u podešavanja (data/podesavanja.json) i
                     proveri da fajl zaista može da se učita

Aplikacija i ovde samo ČITA podatke modela. Fajl ubačen sa stranice se
kopira u data/ulaz/, a fajlovi na zadatoj putanji se ne diraju.

ZAŠTO PREDLOG, A NE AUTOMATIKA DO KRAJA
----------------------------------------
Neke stvari se iz samog fajla ne mogu znati (da li je 11/10 novembar ili
oktobar, koja od pet brojčanih kolona je odgovor modela). Zato aplikacija
pogodi, pokaže šta je pogodila i čovek jednom potvrdi. Posle toga radi sama.
"""

import glob
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.alarmi.konfiguracija import Izvor, Konfiguracija
from app.citac import brojcane_kolone, procitaj_csv, ucitaj_csv
from app.prepoznavanje import je_prazno, napravi_profil, prepoznaj, procitaj_vreme

FOLDER_ULAZA = Path("data/ulaz")  # ovde se kopiraju fajlovi ubačeni sa stranice
NAJVECI_FAJL = 200 * 1024 * 1024  # 200 MB
STARO_POSLE = timedelta(days=7)  # poslednji rezultat stariji od ovoga = stari podaci

# Polja koja čovek bira na stranici, sa objašnjenjem.
POLJA_ZA_IZBOR = [
    ("vreme", "Vreme", "Kada je rezultat nastao. Obavezno."),
    ("doba_dana", "Sat (ako je u posebnoj koloni)", "Npr. kolona 'hr' uz kolonu sa datumom."),
    ("vrednost", "Rezultat modela (broj)", "Broj koji model vraća."),
    ("kategorija", "Rezultat modela (kategorija)", "Reč koju model vraća, npr. 'ispravno'."),
    ("stvarna_vrednost", "Stvarna vrednost", "Šta se zaista desilo, ako se zna. Služi za tačnost."),
    ("stvarna_kategorija", "Stvarna kategorija", "Isto, za kategorije."),
    ("izvor", "Izvor", "Na šta se rezultat odnosi: mašina, lokacija..."),
    ("status", "Status", "Da li je model uspeo (ok) ili javio grešku."),
]


def bezbedno_ime(ime: str) -> str:
    """Ime fajla bez putanje i čudnih znakova: 'moj fajl.csv' -> 'moj_fajl.csv'."""
    ime = Path(ime).name
    ime = re.sub(r"[^A-Za-z0-9._-]+", "_", ime).strip("._") or "podaci.csv"
    return ime if ime.lower().endswith((".csv", ".txt")) else ime + ".csv"


def sacuvaj_ubaceni_fajl(model: str, ime: str, sadrzaj: bytes) -> Path:
    """Kopira fajl ubačen sa stranice u data/ulaz/<model>/<ime>."""
    if len(sadrzaj) > NAJVECI_FAJL:
        raise ValueError(f"Fajl je veći od {NAJVECI_FAJL // 1024 // 1024} MB.")
    folder = FOLDER_ULAZA / bezbedno_ime(model).removesuffix(".csv")
    folder.mkdir(parents=True, exist_ok=True)
    putanja = folder / bezbedno_ime(ime)
    putanja.write_bytes(sadrzaj)
    return putanja


def razresi_putanju(tekst: str) -> Path:
    """
    Šta je čovek upisao: fajl, folder (-> svi CSV fajlovi u njemu) ili
    putanja sa zvezdicom. Vraća putanju za podešavanja.
    """
    p = Path(tekst.strip()).expanduser()
    if any(z in str(p) for z in "*?["):
        return p
    if p.is_dir():
        return p / "*.csv"
    return p


def prvi_fajl(putanja: Path) -> Path:
    """Prvi fajl na putanji (za predlog je dovoljan jedan)."""
    if any(z in str(putanja) for z in "*?["):
        lista = sorted(glob.glob(str(putanja)))
        if not lista:
            raise ValueError(f"Na putanji {putanja} nema nijednog fajla.")
        return Path(lista[0])
    if not putanja.is_file():
        raise ValueError(f"Nema fajla {putanja}.")
    return putanja


def vrsta_kolone(p) -> str:
    if p.popunjenih == 0:
        return "prazno"
    if p.udeo_vremena >= 0.8:
        return "vreme"
    if p.redni:
        return "redni broj"
    if p.udeo_brojeva >= 0.9:
        return "broj"
    return "tekst"


def predlog(putanja: Path, zona: str, model: str | None = None,
            sada: datetime | None = None) -> dict:
    """
    Pročita fajl i vrati sve što stranici treba da čovek potvrdi: kolone sa
    primerima, prepoznata polja, brojčane kolone (za široku tabelu),
    vremenski opseg i upozorenja.
    """
    fajl = prvi_fajl(putanja)
    kolone, redovi = procitaj_csv(fajl)
    if not kolone or not redovi:
        raise ValueError(f"Fajl {fajl.name} je prazan ili nema zaglavlje sa nazivima kolona.")
    m = prepoznaj(kolone, redovi)
    uzorak = redovi[:500]
    profili = {k: napravi_profil([r.get(k) or "" for r in uzorak], m.redosled_datuma) for k in kolone}
    upozorenja = list(m.napomene)

    opis_kolona = []
    for k in kolone:
        p = profili[k]
        primeri = []
        for r in uzorak:
            v = r.get(k) or ""
            if not je_prazno(v) and v not in primeri:
                primeri.append(v)
            if len(primeri) == 3:
                break
        opis_kolona.append({"naziv": k, "vrsta": vrsta_kolone(p), "razlicitih": p.razlicitih,
                            "primeri": primeri})

    # Vremenski opseg iz cele kolone sa vremenom (ako je prepoznata).
    od = do = None
    vreme_k = m.polja.get("vreme")
    if vreme_k:
        tz = ZoneInfo(zona)
        vremena = [procitaj_vreme(r.get(vreme_k) or "", tz, m.redosled_datuma) for r in redovi]
        vremena = [t for t in vremena if t is not None]
        if vremena:
            od, do = min(vremena), max(vremena)
            if len(set(vremena)) < 3:
                upozorenja.append(f"U koloni '{vreme_k}' su samo {len(set(vremena))} različita "
                                  "vremena. Praćenje kroz vreme neće imati smisla.")
    else:
        upozorenja.append("Nije prepoznata kolona sa vremenom. Bez nje praćenje nije moguće: "
                          "izaberite je ručno.")
    if "vrednost" not in m.polja and "kategorija" not in m.polja:
        upozorenja.append("Nije prepoznata kolona sa rezultatom modela. Izaberite je ručno.")
    for polje, nacin in m.nacin.items():
        if "proveriti" in nacin:
            upozorenja.append(f"Kolona '{m.polja[polje]}' je uzeta kao '{polje}' po sadržaju, "
                              "ne po nazivu: proverite.")

    sada = sada or datetime.now(timezone.utc)
    istorijski = bool(do) and do < sada - STARO_POSLE
    brojcane = brojcane_kolone(kolone, redovi, m) if vreme_k else []
    # Široka tabela se predlaže kad ima više brojčanih kolona, a nijedna se
    # po nazivu ne izdvaja kao rezultat modela (npr. 8 senzora u 8 kolona).
    predlozi_siroku = len(brojcane) >= 3 and m.nacin.get("vrednost", "") != "naziv kolone"

    return {
        "fajl": str(fajl),
        "putanja": str(putanja),
        "model": model or re.sub(r"[^\w-]+", "_", putanja.stem if "*" not in putanja.stem else putanja.parent.name),
        "redova": len(redovi),
        "kolone": opis_kolona,
        "polja": m.polja,
        "nacin": m.nacin,
        "redosled_datuma": m.redosled_datuma,
        "brojcane": brojcane,
        "siroka": predlozi_siroku,
        "od": od.isoformat() if od else None,
        "do": do.isoformat() if do else None,
        "istorijski": istorijski,
        "upozorenja": upozorenja,
        "polja_za_izbor": [{"polje": p, "naziv": n, "opis": o} for p, n, o in POLJA_ZA_IZBOR],
    }


def dodaj_izvor(k: Konfiguracija, putanja: Path, model: str, polja: dict[str, str],
                kolone: list[str] | None, istorijski: bool, redosled_datuma: str,
                putanja_podesavanja: Path) -> Izvor:
    """
    Upisuje nov izvor u podešavanja. Pre toga proba da učita fajl sa tim
    mapiranjem: ako ne može, javlja grešku i ništa ne upisuje.
    """
    model = model.strip()
    if not model:
        raise ValueError("Naziv modela ne sme da bude prazan.")
    if any((i.model or i.putanja.stem) == model for i in k.izvori):
        raise ValueError(f"Model '{model}' već postoji. Izaberite drugi naziv ili prvo uklonite stari.")
    polja = {p: kol for p, kol in polja.items() if kol}
    if "vreme" not in polja:
        raise ValueError("Mora da se izabere kolona sa vremenom.")
    if not kolone and "vrednost" not in polja and "kategorija" not in polja:
        raise ValueError("Mora da se izabere kolona sa rezultatom modela, ili više kolona kao izvori.")

    izvor = Izvor(putanja=putanja, model=model, polja=polja, kolone=kolone or None,
                  istorijski=istorijski, redosled_datuma=redosled_datuma)
    ucitano = ucitaj_csv(prvi_fajl(putanja), model, izvor.napravi_mapiranje(), k.zona, izvor.kolone)
    if not ucitano.rezultati:
        prva = ucitano.greske[0][1] if ucitano.greske else "fajl je prazan"
        raise ValueError(f"Sa ovim izborom kolona nijedan red ne može da se učita ({prva}).")
    if len(ucitano.greske) > len(ucitano.rezultati):
        raise ValueError(f"Većina redova ne može da se učita (npr. red {ucitano.greske[0][0]}: "
                         f"{ucitano.greske[0][1]}). Proverite izbor kolona.")

    k.izvori.append(izvor)
    k.sacuvaj(putanja_podesavanja)
    return izvor


def ukloni_izvor(k: Konfiguracija, model: str, putanja_podesavanja: Path) -> Izvor:
    for i, izvor in enumerate(k.izvori):
        if (izvor.model or izvor.putanja.stem) == model:
            k.izvori.pop(i)
            k.sacuvaj(putanja_podesavanja)
            return izvor
    raise KeyError(f"Nema izvora za model '{model}'.")


def opis_izvora(izvor: Izvor) -> dict:
    return {
        "model": izvor.model or izvor.putanja.stem,
        "putanja": str(izvor.putanja),
        "kolone": izvor.kolone,
        "polja": izvor.polja,
        "istorijski": izvor.istorijski,
        "ubacen": str(izvor.putanja).startswith(str(FOLDER_ULAZA)),
    }
