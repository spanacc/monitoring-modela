from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from statistics import median

from app.schema import Rezultat

Tacke = list[tuple[datetime, float]]  # (vreme, broj), poređano po vremenu


class Ozbiljnost(str, Enum):
    """Nivoi iz plana: informacija, upozorenje, kritično."""

    INFO = "info"
    UPOZORENJE = "upozorenje"
    KRITICNO = "kriticno"


@dataclass
class Nalaz:
    """Jedan pronađen problem."""

    tip: str  # npr. "izostanak", "drift"
    model: str
    izvor: str
    od: datetime
    do: datetime
    ozbiljnost: Ozbiljnost
    opis: str  # objašnjenje za čoveka


@dataclass
class Podesavanja:
    """
    Jedino što podešava čovek. Sve granice za alarme aplikacija izračuna
    sama, za svaki izvor posebno (vidi kalibracija.py).
    """

    # Osetljivost: alarm se diže tek kad je nešto `rezerva` puta gore od
    # najgoreg što se desilo u normalnom periodu. Veće = manje alarma.
    rezerva: float = 2.0
    # Koji deo podataka sa početka se smatra normalnim periodom.
    udeo_osnove: float = 0.25
    # Definicija pristrasnosti: više od ovog dela greške je stalno u istom
    # smeru ("većina greške u istom smeru"). Ovo je definicija, a ne
    # procena: pristrasnost postoji od samog početka, pa nema normalnog
    # perioda sa kojim bi se poredila.
    prag_pristrasnosti: float = 0.5


@dataclass
class Granice:
    """
    Granice za jednu seriju, koje aplikacija sama izračuna iz normalnog
    perioda. None znači: premalo podataka da bi se granica naučila, pa se
    ta provera za ovu seriju preskače.
    """

    korak: timedelta  # koliko obično prođe između dva rezultata
    kraj_osnove: datetime  # do kada traje normalni period
    prozor: int  # koliko rezultata ide u jedan prozor (otprilike jedan dan)
    max_pauza: timedelta  # duža pauza od ove = izostanak
    max_odskok_vrednosti: float | None = None  # veći odskok = nemoguća vrednost
    max_odskok_greske: float | None = None  # veći odskok greške = promašen skok
    drift_po_greski: bool = True  # drift prati grešku (True) ili samo vrednosti
    drift_sredina: float | None = None  # tipičan broj po prozoru u normalnom periodu
    drift_dozvoljeno: float | None = None  # koliko sme da se pomeri od toga
    stopa_gresaka: float | None = None  # za kategorije: normalna stopa grešaka
    dozvoljen_rast_stope: float | None = None  # koliko sme da poraste


# ---------------------------------------------------------------------------
# Pomoćne funkcije
# ---------------------------------------------------------------------------


def po_serijama(rezultati: list[Rezultat]) -> dict[tuple, list[Rezultat]]:
    """
    Deli rezultate na serije: jedan model, jedan izvor, jedna veličina,
    jedan horizont. Svaka serija se proverava posebno i ima svoje granice,
    jer npr. prognoza za 1 sat i za 24 sata unapred normalno različito greše.
    """
    serije = defaultdict(list)
    for r in rezultati:
        serije[(r.model, r.izvor, r.velicina, r.horizont_min)].append(r)
    for serija in serije.values():
        serija.sort(key=lambda r: r.vreme)
    return dict(serije)


def ocekivani_korak(serija: list[Rezultat]) -> timedelta | None:
    """Koliko obično prođe između dva rezultata. Uči se iz samih podataka."""
    vremena = sorted({r.vreme for r in serija})
    razmaci = [b - a for a, b in zip(vremena, vremena[1:])]
    return median(razmaci) if razmaci else None


def odskoci_od_suseda(tacke: Tacke, prozor: int) -> list[float]:
    """
    Za svaku tačku: koliko odskače od medijane svojih suseda
    (pola prozora pre nje i pola posle).

    Poređenje sa susedima, a ne sa celim periodom, znači:
    - jedna luda vrednost (npr. 9999) jako odskače i biva pronađena,
    - spora promena ili trajni pomak NE odskače, jer se i susedi pomeraju
      zajedno sa njom. Takve promene prijavljuje provera drifta.
    """
    pola = prozor // 2
    x = [v for _, v in tacke]
    return [x[i] - median(x[max(0, i - pola): i + pola + 1]) for i in range(len(x))]


def prozori(tacke: Tacke, velicina: int) -> list[Tacke]:
    """Deli tačke na uzastopne grupe od po `velicina` tačaka, bez preklapanja."""
    return [tacke[i:i + velicina] for i in range(0, len(tacke) - velicina + 1, velicina)]


def klizni_prozori(tacke: Tacke, velicina: int) -> list[Tacke]:
    """
    Kao `prozori`, ali svaki sledeći počinje samo jednu tačku kasnije.
    Koristi se u normalnom periodu: tako se vidi svaki mogući prozor, pa
    je "najgore što se desilo" pouzdanije nego da gledamo samo nekoliko.
    """
    return [tacke[i:i + velicina] for i in range(len(tacke) - velicina + 1)]


def u_intervale(vremena: list[datetime], korak: timedelta) -> list[tuple[datetime, datetime]]:
    """
    Spaja vremena koja idu jedno za drugim u intervale.
    [14h, 15h, 16h, 20h] sa korakom 1h -> [(14h, 17h), (20h, 21h)]
    Tako 6 praznih rezultata zaredom postaje jedan nalaz, a ne šest.
    """
    intervali: list[tuple[datetime, datetime]] = []
    for t in sorted(set(vremena)):
        if intervali and t <= intervali[-1][1] + korak / 2:
            intervali[-1] = (intervali[-1][0], t + korak)
        else:
            intervali.append((t, t + korak))
    return intervali


def trajanje(td: timedelta) -> str:
    """timedelta(hours=6) -> '6 h'. Za poruke koje čita čovek."""
    minuta = round(td.total_seconds() / 60)
    if minuta < 60:
        return f"{minuta} min"
    if minuta < 48 * 60:
        return f"{minuta / 60:g} h"
    return f"{minuta / 1440:g} dana"


def napravi(tip: str, serija: list[Rezultat], od: datetime, do: datetime,
            ozbiljnost: Ozbiljnost, opis: str) -> Nalaz:
    """Pravi nalaz za datu seriju (model i izvor se uzimaju iz serije)."""
    prvi = serija[0]
    return Nalaz(tip, prvi.model, prvi.izvor, od, do, ozbiljnost, opis)