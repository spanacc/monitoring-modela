"""
Probni podaci "uživo": tri izmišljena modela koja rade od 1. novembra do sada
i nastavljaju da dopisuju rezultate dok aplikacija radi.

ZAŠTO
-----
Stari probni fajlovi su stali, pa aplikacija (tačno) javlja "Podaci ne
stižu". Za probu dashboarda i mejlova treba nešto što izgleda kao model
koji upravo radi.

KAKO SE KORISTI
---------------
    python -m app --demo          # aplikacija + probni podaci (preporučeno)
    python -m simulator.uzivo     # samo dopiši fajlove do sada, pa izađi

Fajlovi su u data/demo/. Svaki ima drugačije nazive kolona, kao što bi
bilo sa pravim modelima: aplikacija ih prepoznaje sama.

Rezultat za svako vreme se računa uvek isto (seme zavisi od vremena), pa
posle gašenja i ponovnog pokretanja fajl samo nastavi gde je stao.

UBAČENI PROBLEMI (vreme po Beogradu)
------------------------------------
    9.11. 10–16 h    temperatura_peci, Peć 2: podaci ne stižu 6 sati
    12.11. 14:20     temperatura_peci, Peć 1: nemoguća vrednost 9999
    15.11. 6–9 h     potrosnja_hale: model javlja grešku
    17.11. 18–21 h   potrosnja_hale: potrošnja skočila, model to nije video
    od 19.11.        temperatura_peci, Peć 3: model sve više greši (traje)
    od 20.11.        kontrola_kvaliteta, Linija 2: tačnost pala (traje)

Uz to, na stranici Podešavanja postoji dugme "Napravi problem sada": odmah
dopiše jedan loš rezultat, provera ga nađe i stiže mejl (vidi izazovi()).
"""

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("Europe/Belgrade")
POCETAK = datetime(2026, 11, 1, tzinfo=ZONA)
FOLDER = Path("data/demo")
FORMAT = "%Y-%m-%d %H:%M:%S"


def _t(dan: int, sat: int, minut: int = 0) -> datetime:
    return datetime(2026, 11, dan, sat, minut, tzinfo=ZONA)


def _rng(*delovi) -> random.Random:
    # Isto vreme i izvor uvek daju iste brojeve.
    return random.Random("|".join(str(d) for d in delovi))


def _dnevni(t: datetime) -> float:
    return math.sin(2 * math.pi * (t.hour + t.minute / 60 - 9) / 24)


# ---------------------------------------------------------------------------
# Model 1: temperatura u pećima (broj, na 10 minuta, 3 peći)
# ---------------------------------------------------------------------------

def redovi_temperature(t: datetime) -> list[dict]:
    redovi = []
    for i, pec in enumerate(["Peć 1", "Peć 2", "Peć 3"]):
        if pec == "Peć 2" and _t(9, 10) <= t < _t(9, 16):
            continue  # rezultati ne stižu
        r = _rng("temp", pec, t.strftime(FORMAT))
        izmereno = 820 + i * 15 + 12 * _dnevni(t) + r.gauss(0, 2)
        predvidjeno = izmereno + r.gauss(0, 2.5)
        if pec == "Peć 3" and t >= _t(19, 0):
            # Model polako počinje da greši: +4 °C dnevno, najviše +30 °C.
            predvidjeno += min(30.0, 4 * (t - _t(19, 0)) / timedelta(days=1))
        if pec == "Peć 1" and t == _t(12, 14, 20):
            predvidjeno = 9999
        redovi.append({"vreme": t.strftime(FORMAT), "masina": pec,
                       "predvidjena_temp": f"{predvidjeno:.1f}",
                       "izmerena_temp": f"{izmereno:.1f}"})
    return redovi


# ---------------------------------------------------------------------------
# Model 2: potrošnja struje (broj, na sat, jedan izvor, ponekad greška)
# ---------------------------------------------------------------------------

def redovi_potrosnje(t: datetime) -> list[dict]:
    r = _rng("struja", t.strftime(FORMAT))
    vikend = t.weekday() >= 5
    izmereno = (310 if vikend else 450) + 140 * _dnevni(t) + r.gauss(0, 12)
    if _t(17, 18) <= t < _t(17, 21):
        izmereno *= 1.6  # nešto se desilo u hali, model to nije predvideo
    prognoza = ((310 if vikend else 450) + 140 * _dnevni(t)) * (1 + r.gauss(0, 0.03))
    red = {"datum": t.strftime(FORMAT), "prognoza_kwh": f"{prognoza:.0f}",
           "izmereno_kwh": f"{izmereno:.0f}", "status": "ok", "poruka": ""}
    if _t(15, 6) <= t < _t(15, 9):
        red.update(prognoza_kwh="", status="greska", poruka="baza merenja nedostupna")
    return [red]


# ---------------------------------------------------------------------------
# Model 3: kontrola kvaliteta (kategorija, na 15 minuta, 2 linije)
# ---------------------------------------------------------------------------

def redovi_kvaliteta(t: datetime) -> list[dict]:
    redovi = []
    for linija in ["Linija 1", "Linija 2"]:
        r = _rng("kvalitet", linija, t.strftime(FORMAT))
        ispravno = r.random() > 0.08
        tacnost = 0.72 if linija == "Linija 2" and t >= _t(20, 0) else 0.96
        pogodio = r.random() < tacnost
        predikcija = ispravno if pogodio else not ispravno
        redovi.append({"vreme": t.strftime(FORMAT), "linija": linija,
                       "predikcija": "ispravno" if predikcija else "škart",
                       "stvarno": "ispravno" if ispravno else "škart"})
    return redovi


MODELI = {
    "temperatura_peci": (timedelta(minutes=10), redovi_temperature,
                         ["vreme", "masina", "predvidjena_temp", "izmerena_temp"]),
    "potrosnja_hale": (timedelta(hours=1), redovi_potrosnje,
                       ["datum", "prognoza_kwh", "izmereno_kwh", "status", "poruka"]),
    "kontrola_kvaliteta": (timedelta(minutes=15), redovi_kvaliteta,
                           ["vreme", "linija", "predikcija", "stvarno"]),
}


def poslednje_vreme(putanja: Path) -> datetime | None:
    """Vreme u poslednjem redu fajla (čita se samo kraj fajla)."""
    if not putanja.exists() or putanja.stat().st_size == 0:
        return None
    with putanja.open("rb") as f:
        f.seek(max(0, putanja.stat().st_size - 1000))
        poslednji = f.read().decode("utf-8", "replace").strip().splitlines()[-1]
    try:
        return datetime.strptime(poslednji.split(",")[0], FORMAT).replace(tzinfo=ZONA)
    except ValueError:
        return None


def _sledece(poslednje: datetime, korak: timedelta) -> datetime:
    """Sledeće "redovno" vreme posle poslednjeg (izazvani problem može biti između)."""
    return POCETAK + korak * (int((poslednje - POCETAK) / korak) + 1)


def dopuni(folder: Path = FOLDER, sada: datetime | None = None) -> int:
    """Dopiše sve modele do `sada`. Vraća broj novih redova."""
    folder.mkdir(parents=True, exist_ok=True)
    sada = (sada or datetime.now(ZONA)).astimezone(ZONA)
    novih = 0
    for ime, (korak, redovi, kolone) in MODELI.items():
        putanja = folder / f"{ime}.csv"
        poslednje = poslednje_vreme(putanja)
        t = _sledece(poslednje, korak) if poslednje else POCETAK
        if t > sada:
            continue
        nov_fajl = poslednje is None
        # Upis ide odjednom i na kraj fajla, da aplikacija nikad ne vidi pola reda.
        with putanja.open("w" if nov_fajl else "a", newline="", encoding="utf-8") as f:
            pisac = csv.DictWriter(f, fieldnames=kolone)
            if nov_fajl:
                pisac.writeheader()
            while t <= sada:
                for red in redovi(t):
                    pisac.writerow(red)
                    novih += 1
                t += korak
    return novih


# ---------------------------------------------------------------------------
# Problem na dugme: sve je bilo dobro, pa odjednom...
# ---------------------------------------------------------------------------

VRSTE_PROBLEMA = {
    "neobicna": "Peć 1 je upravo vratila nemoguću vrednost (9.999 °C).",
    "greska": "Model za potrošnju je upravo javio grešku umesto rezultata.",
}


def izazovi(vrsta: str, folder: Path = FOLDER, sada: datetime | None = None) -> str:
    """
    Odmah dopiše jedan loš rezultat, kao da je model upravo pogrešio.
    Sledeća provera ga nalazi, i ide mejl. Vraća opis za stranicu.
    """
    if vrsta not in VRSTE_PROBLEMA:
        raise ValueError(f"Nepoznata vrsta problema: {vrsta}")
    sada = (sada or datetime.now(ZONA)).astimezone(ZONA).replace(second=0, microsecond=0)
    dopuni(folder, sada)
    ime = "temperatura_peci" if vrsta == "neobicna" else "potrosnja_hale"
    putanja = folder / f"{ime}.csv"
    # Vreme posle poslednjeg reda (redovi moraju ići redom).
    t = max(sada, (poslednje_vreme(putanja) or sada) + timedelta(minutes=1))
    if vrsta == "neobicna":
        red = redovi_temperature(t)[0]
        red["predvidjena_temp"] = "9999.0"
    else:
        red = redovi_potrosnje(t)[0]
        red.update(prognoza_kwh="", status="greska", poruka="model se srušio (probni problem)")
    with putanja.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=MODELI[ime][2]).writerow(red)
    return VRSTE_PROBLEMA[vrsta]


# ---------------------------------------------------------------------------
# Uključivanje i isključivanje u aplikaciji (python -m app --demo / --bez-demoa)
# ---------------------------------------------------------------------------

def ukljuci(k, putanja_podesavanja: Path, folder: Path = FOLDER,
            sada: datetime | None = None) -> list[str]:
    """
    Dopiše fajlove do sada i doda modele koji još nisu praćeni, isto kao da
    ih je čovek dodao na stranici (kolone se prepoznaju same). Vraća nove.
    """
    from app.alarmi.konfiguracija import OsetljivostModela
    from app.dodavanje import dodaj_izvor, predlog

    dopuni(folder, sada)
    praceni = {i.model or i.putanja.stem for i in k.izvori}
    novi = []
    for ime in MODELI:
        if ime in praceni:
            continue
        putanja = folder / f"{ime}.csv"
        p = predlog(putanja, k.zona, ime)
        dodaj_izvor(k, putanja, ime, p["polja"], None, False, p["redosled_datuma"],
                    putanja_podesavanja)
        # Normalni period: prva nedelja novembra (ne pomera se kako podaci rastu).
        k.modeli[ime] = OsetljivostModela(dana_osnove=7)
        novi.append(ime)
    k.demo = True
    k.sacuvaj(putanja_podesavanja)
    return novi


def iskljuci(k, putanja_podesavanja: Path, baza) -> list[str]:
    """Skloni probne modele iz podešavanja i iz baze (fajlovi u data/demo ostaju)."""
    from app.dodavanje import ukloni_izvor

    sklonjeni = []
    for ime in MODELI:
        try:
            ukloni_izvor(k, ime, putanja_podesavanja)
        except KeyError:
            pass
        k.modeli.pop(ime, None)
        baza.obrisi_model(ime)
        sklonjeni.append(ime)
    k.demo = False
    k.sacuvaj(putanja_podesavanja)
    return sklonjeni


def main() -> None:
    novih = dopuni()
    print(f"Dopisano {novih} redova u {FOLDER.resolve()}")


if __name__ == "__main__":
    main()
