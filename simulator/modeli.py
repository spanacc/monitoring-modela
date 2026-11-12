"""
Tri izmišljena modela sa namerno ubačenim problemima.

ŠTA JE OVO
----------
Pravimo rezultate tri potpuno različita izmišljena modela:

1. "senzori"  - predviđa temperaturu na 5 mašina, svakog sata, sat unapred.
2. "potrosnja" - predviđa dnevnu potrošnju energije na 3 lokacije, dan unapred.
3. "kvalitet" - za svaki proizvod na 2 linije kaže "ispravno" ili "neispravno".

Za svaki rezultat pravimo i "stvarnu" vrednost, ono što se zaista desilo,
da bi kasnije moglo da se meri koliko model greši.

ZAŠTO TRI RAZLIČITA MODELA
--------------------------
Da bismo dokazali da je aplikacija univerzalna. Ako ista aplikacija, bez
ikakvih izmena, ispravno prati i brojeve na sat, i brojeve na dan, i
kategorije, onda će raditi i sa pravim modelom o kome ništa ne znamo.

ZAŠTO NAMERNO UBACUJEMO PROBLEME
--------------------------------
Da bismo kasnije proverili da li ih aplikacija pronalazi. Svaki ubačeni
problem se zapisuje na spisak (`Problem`). Kad napravimo provere (korak 3),
uporedićemo šta su one našle sa ovim spiskom. Ako neki problem nisu našle,
znamo da provera ne radi dobro.

KAKO
----
Koristimo generator slučajnih brojeva sa fiksnim "semenom" (seed). To znači
da se svaki put dobijaju potpuno isti podaci, pa testovi uvek daju isti
rezultat. Ako se promeni seme, dobijaju se drugi, ali isto tako realni podaci.
"""

import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from app.schema import Rezultat, Status

# Sva vremena su u UTC. Tako nema zabune oko letnjeg i zimskog vremena.
# Prikaz u lokalnom vremenu dolazi tek na dashboardu.
POCETAK = datetime(2026, 10, 1, tzinfo=timezone.utc)


@dataclass
class Problem:
    """Opis jednog namerno ubačenog problema."""

    tip: str
    model: str
    izvor: str
    od: str
    do: str
    opis: str


@dataclass
class Simulacija:
    """Ono što simulator vrati za jedan model: rezultate i spisak problema."""

    rezultati: list[Rezultat]
    problemi: list[Problem]

    def problemi_kao_recnik(self) -> list[dict]:
        return [asdict(p) for p in self.problemi]


def _u_intervalu(t: datetime, od: datetime, do: datetime) -> bool:
    return od <= t < do


# ---------------------------------------------------------------------------
# Model 1: senzori (brojevi, svakog sata, sat unapred)
# ---------------------------------------------------------------------------


def simuliraj_senzore(dani: int = 30, seed: int = 1) -> Simulacija:
    rng = random.Random(seed)
    model = "senzori"
    izvori = ["M1", "M2", "M3", "M4", "M5"]
    kraj = POCETAK + timedelta(days=dani)

    # Vremena problema se računaju kao deo ukupnog perioda, da bi simulator
    # radio i kad se promeni broj dana.
    def dan(udeo: float, sat: int = 0) -> datetime:
        return POCETAK + timedelta(days=int(dani * udeo), hours=sat)

    greska_od = dan(0.17, 3)
    izostanak = (dan(0.33, 8), dan(0.33, 14))
    nemoguca = dan(0.40, 10)
    prazne = (dan(0.67, 0), dan(0.67, 6))
    drift_od = dan(0.73)
    skok = (dan(0.83, 12), dan(0.83, 15))
    pristrasnost = 5.0

    problemi = [
        Problem("greska_modela", model, "M1", greska_od.isoformat(),
                (greska_od + timedelta(hours=1)).isoformat(),
                "Model je javio grešku umesto rezultata."),
        Problem("izostanak", model, "M2", izostanak[0].isoformat(),
                izostanak[1].isoformat(),
                "Rezultati nisu stizali 6 sati."),
        Problem("pristrasnost", model, "M3", POCETAK.isoformat(), kraj.isoformat(),
                f"Model za M3 stalno predviđa oko {pristrasnost} °C više nego što jeste."),
        Problem("nemoguca_vrednost", model, "M4", nemoguca.isoformat(),
                (nemoguca + timedelta(hours=1)).isoformat(),
                "Jedan rezultat ima nemoguću vrednost 9999."),
        Problem("prazne_vrednosti", model, "M4", prazne[0].isoformat(),
                prazne[1].isoformat(),
                "Rezultati su stizali, ali bez vrednosti."),
        Problem("drift", model, "M5", drift_od.isoformat(), kraj.isoformat(),
                "Greška modela polako raste do oko +8 °C na kraju perioda."),
        Problem("promasen_skok", model, "M1", skok[0].isoformat(), skok[1].isoformat(),
                "Temperatura je naglo skočila za 15 °C, a model to nije predvideo."),
    ]

    rezultati: list[Rezultat] = []
    t = POCETAK
    while t < kraj:
        for i, izvor in enumerate(izvori):
            # "Prava" temperatura: osnova + dnevni ciklus + mali šum.
            sat_u_danu = t.hour + t.minute / 60
            stvarno = 60 + i * 3 + 10 * math.sin(2 * math.pi * sat_u_danu / 24)
            stvarno += rng.gauss(0, 1)

            # Model predviđa sa malom greškom.
            predvidjeno = stvarno + rng.gauss(0, 1.5)

            # --- ubacivanje problema ---
            if izvor == "M2" and _u_intervalu(t, *izostanak):
                continue  # rezultat uopšte ne stiže

            if izvor == "M1" and _u_intervalu(t, *skok):
                stvarno += 15  # desio se skok, model ga nije video

            if izvor == "M3":
                predvidjeno += pristrasnost

            if izvor == "M5" and t >= drift_od:
                udeo = (t - drift_od) / (kraj - drift_od)
                predvidjeno += 8 * udeo

            status, poruka = Status.OK, None
            vrednost: float | None = round(predvidjeno, 2)

            if izvor == "M1" and _u_intervalu(t, greska_od, greska_od + timedelta(hours=1)):
                status, poruka, vrednost = Status.GRESKA, "timeout: nema odgovora", None

            if izvor == "M4" and _u_intervalu(t, nemoguca, nemoguca + timedelta(hours=1)):
                vrednost = 9999.0

            if izvor == "M4" and _u_intervalu(t, *prazne):
                vrednost = None

            # Stvarna vrednost se saznaje tek posle nekog vremena,
            # pa za poslednja 2 sata još ne postoji.
            stvarna = round(stvarno, 2) if t < kraj - timedelta(hours=2) else None

            rezultati.append(Rezultat(
                vreme=t, model=model, izvor=izvor, velicina="temperatura",
                jedinica="°C", horizont_min=60, vrednost=vrednost,
                stvarna_vrednost=stvarna, status=status, poruka=poruka,
            ))
        t += timedelta(hours=1)

    return Simulacija(rezultati, problemi)


# ---------------------------------------------------------------------------
# Model 2: potrosnja (brojevi, jednom dnevno, dan unapred)
# ---------------------------------------------------------------------------


def simuliraj_potrosnju(dani: int = 30, seed: int = 2) -> Simulacija:
    rng = random.Random(seed)
    model = "potrosnja"
    osnova = {"L1": 1200.0, "L2": 800.0, "L3": 2000.0}
    kraj = POCETAK + timedelta(days=dani)

    pauza = (POCETAK + timedelta(days=int(dani * 0.57)),
             POCETAK + timedelta(days=int(dani * 0.57) + 3))
    duplikat_dan = POCETAK + timedelta(days=int(dani * 0.27))

    problemi = [
        Problem("izostanak", model, "L2", pauza[0].isoformat(), pauza[1].isoformat(),
                "Model 3 dana nije dao prognozu za L2."),
        Problem("duplikat", model, "L3", duplikat_dan.isoformat(),
                (duplikat_dan + timedelta(days=1)).isoformat(),
                "Isti rezultat je stigao dva puta."),
    ]

    rezultati: list[Rezultat] = []
    for d in range(dani):
        t = POCETAK + timedelta(days=d, hours=6)  # model se pokreće u 6 ujutru
        vikend = t.weekday() >= 5
        for izvor, baza in osnova.items():
            stvarno = baza * (0.7 if vikend else 1.0) * rng.gauss(1, 0.05)
            predvidjeno = stvarno * rng.gauss(1, 0.04)

            if izvor == "L2" and _u_intervalu(t, *pauza):
                continue

            stvarna = round(stvarno, 1) if d < dani - 1 else None
            r = Rezultat(
                vreme=t, model=model, izvor=izvor, velicina="potrosnja",
                jedinica="kWh", horizont_min=24 * 60, vrednost=round(predvidjeno, 1),
                stvarna_vrednost=stvarna,
            )
            rezultati.append(r)

            if izvor == "L3" and _u_intervalu(t, duplikat_dan, duplikat_dan + timedelta(days=1)):
                rezultati.append(r.model_copy())

    return Simulacija(rezultati, problemi)


# ---------------------------------------------------------------------------
# Model 3: kvalitet (kategorije, svakih 15 minuta)
# ---------------------------------------------------------------------------


def simuliraj_kvalitet(dani: int = 30, seed: int = 3) -> Simulacija:
    rng = random.Random(seed)
    model = "kvalitet"
    linije = ["Linija-1", "Linija-2"]
    kraj = POCETAK + timedelta(days=dani)
    pad_od = POCETAK + timedelta(days=int(dani * 0.6))

    problemi = [
        Problem("pad_tacnosti", model, "Linija-2", pad_od.isoformat(), kraj.isoformat(),
                "Tačnost modela za Liniju-2 pada sa oko 95% na oko 75%."),
    ]

    rezultati: list[Rezultat] = []
    t = POCETAK
    while t < kraj:
        for linija in linije:
            stvarno_ispravno = rng.random() > 0.05  # 5% proizvoda je neispravno

            tacnost = 0.95
            if linija == "Linija-2" and t >= pad_od:
                tacnost = 0.75
            pogodio = rng.random() < tacnost
            predvidjeno_ispravno = stvarno_ispravno if pogodio else not stvarno_ispravno

            # Ne proverava se svaki proizvod ručno, pa stvarnu kategoriju
            # znamo samo za oko 80% njih.
            stvarna = None
            if rng.random() < 0.8:
                stvarna = "ispravno" if stvarno_ispravno else "neispravno"

            rezultati.append(Rezultat(
                vreme=t, model=model, izvor=linija, velicina="stanje_proizvoda",
                kategorija="ispravno" if predvidjeno_ispravno else "neispravno",
                stvarna_kategorija=stvarna,
            ))
        t += timedelta(minutes=15)

    return Simulacija(rezultati, problemi)


SVI_MODELI = {
    "senzori": simuliraj_senzore,
    "potrosnja": simuliraj_potrosnju,
    "kvalitet": simuliraj_kvalitet,
}