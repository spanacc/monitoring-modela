import json
import math
import re
import unicodedata
from dataclasses import asdict,dataclass,field
from datetime import datetime,timezone,tzinfo
from pathlib import Path

from app.schema import Rezultat

POLJA = list (Rezultat.model_fields.keys())

PRAZNO = {"","nan","null","none","n/a","-"}

RECI = {
    "vreme": {"vreme", "vrijeme", "time", "timestamp", "datetime", "date",
              "datum", "ts", "at"},
    "prognoza_jako": {"predicted", "prediction", "pred", "forecast", "prognoza",
                      "predvidjeno", "output", "yhat", "score"},
    "stvarno": {"stvarno", "stvarna", "stvarni", "izmereno", "izmerena", "actual",
                "observed", "measured", "true", "truth", "target", "label"},
    "prognoza_slabo": {"value", "vrednost", "result", "rezultat"},
    "izvor": {"izvor", "source", "masina", "machine", "device", "uredjaj",
              "sensor", "senzor", "stanica", "station", "lokacija", "location",
              "site", "linija", "line", "asset", "node"},
    "status": {"status", "state"},
    "poruka": {"poruka", "message", "msg", "error", "greska", "err"},
    "jedinica": {"jedinica", "unit", "units", "uom"},
    "horizont_min": {"horizont", "horizon", "lead"},
    # Redni brojevi redova ne nose nikakvu informaciju, pa ih preskačemo.
    # Da ih ne preskočimo, "id" bi lako bio pogrešno uzet kao vrednost.
    "preskoci": {"id", "index", "idx", "row", "rb", "redni", "unnamed"},
}

FORMATI_VREMENA = [
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
    "%d.%m.%Y. %H:%M:%S", "%d.%m.%Y. %H:%M", "%d.%m.%Y.",
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
]

def normalizuj(tekst: str) -> str:
    """'Mašina ID' -> 'masina_id'. Uklanja kvačice, velika slova i razmake."""
    tekst = tekst.strip().lower().replace("đ", "dj")
    tekst = unicodedata.normalize("NFKD", tekst)
    tekst = "".join(z for z in tekst if not unicodedata.combining(z))
    return re.sub(r"[^a-z0-9]+", "_", tekst).strip("_")


def je_prazno(tekst: str | None) -> bool:
    return tekst is None or tekst.strip().lower() in PRAZNO


def procitaj_broj(tekst: str) -> float | None:
    """'12,5' -> 12.5 i '1.234,5' -> 1234.5. Vraća None ako nije broj."""
    t = tekst.strip().replace(" ", "")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):  # evropski zapis: 1.234,5
            t = t.replace(".", "").replace(",", ".")
        else:  # američki zapis: 1,234.5
            t = t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        broj = float(t)
    except ValueError:
        return None
    return broj if math.isfinite(broj) else None


def procitaj_vreme(tekst: str, zona: tzinfo) -> datetime | None:
    """
    Pretvara tekst u vreme. Vraća None ako tekst nije vreme.

    Ako vreme nema zonu (npr. '10.11.2026 14:00'), dodeljuje mu se `zona`,
    jer pretpostavljamo da je zapisano po lokalnom vremenu.
    """
    t = tekst.strip()
    vreme = None

    # ISO zapis tražimo samo ako ima crticu, inače bi broj 20261110 bio
    # pogrešno pročitan kao datum.
    if "-" in t:
        try:
            vreme = datetime.fromisoformat(t)
        except ValueError:
            pass

    if vreme is None:
        for format_ in FORMATI_VREMENA:
            try:
                vreme = datetime.strptime(t, format_)
                break
            except ValueError:
                pass

    if vreme is None:
        # Mašine često pišu vreme kao broj sekundi (ili milisekundi)
        # od 1.1.1970. To vreme je uvek u UTC.
        broj = procitaj_broj(t)
        if broj is not None and 1e9 <= broj < 1e10:
            return datetime.fromtimestamp(broj, timezone.utc)
        if broj is not None and 1e12 <= broj < 1e13:
            return datetime.fromtimestamp(broj / 1000, timezone.utc)
        return None

    if vreme.tzinfo is None:
        vreme = vreme.replace(tzinfo=zona)
    return vreme


# ---------------------------------------------------------------------------
# Profil kolone: šta se nalazi u njoj
# ---------------------------------------------------------------------------


@dataclass
class Profil:
    udeo_vremena: float  # koliki deo popunjenih vrednosti su vremena (0 do 1)
    udeo_brojeva: float  # koliki deo su brojevi
    razlicitih: int  # koliko različitih vrednosti ima
    popunjenih: int  # koliko vrednosti nije prazno


def napravi_profil(vrednosti: list[str]) -> Profil:
    popunjene = [v for v in vrednosti if not je_prazno(v)]
    if not popunjene:
        return Profil(0, 0, 0, 0)
    n = len(popunjene)
    return Profil(
        udeo_vremena=sum(procitaj_vreme(v, timezone.utc) is not None for v in popunjene) / n,
        udeo_brojeva=sum(procitaj_broj(v) is not None for v in popunjene) / n,
        razlicitih=len(set(popunjene)),
        popunjenih=n,
    )


def je_tekst(p: Profil) -> bool:
    return p.popunjenih > 0 and p.udeo_brojeva < 0.9 and p.udeo_vremena < 0.8


# ---------------------------------------------------------------------------
# Mapiranje: rezultat prepoznavanja
# ---------------------------------------------------------------------------


@dataclass
class Mapiranje:
    """Koja kolona iz fajla odgovara kom polju univerzalnog formata."""

    polja: dict[str, str] = field(default_factory=dict)  # polje -> kolona
    nacin: dict[str, str] = field(default_factory=dict)  # polje -> kako je nađeno
    neprepoznate: list[str] = field(default_factory=list)
    velicina: str = "vrednost"  # koristi se ako fajl nema kolonu 'velicina'

    def sacuvaj(self, putanja: Path) -> None:
        """Čuva mapiranje u JSON, da bi čovek mogao da ga pregleda i ispravi."""
        tekst = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        Path(putanja).write_text(tekst, encoding="utf-8")

    @classmethod
    def ucitaj(cls, putanja: Path) -> "Mapiranje":
        return cls(**json.loads(Path(putanja).read_text(encoding="utf-8")))


def uloga_po_nazivu(naziv: str) -> str | None:
    """Vraća ulogu kolone na osnovu reči u njenom nazivu, ili None ako ne zna."""
    reci = set(normalizuj(naziv).split("_"))
    for uloga, poznate in RECI.items():
        if reci & poznate:
            return uloga
    return None


def prepoznaj(kolone: list[str], redovi: list[dict]) -> Mapiranje:
    """Pogađa koja kolona je koje polje. Gleda samo prvih 500 redova."""
    uzorak = redovi[:500]
    profili = {k: napravi_profil([r.get(k) or "" for r in uzorak]) for k in kolone}
    m = Mapiranje()
    slobodne = list(kolone)

    def dodeli(polje: str, kolona: str, nacin: str) -> None:
        # Svako polje dobija samo jednu kolonu, i svaka kolona ide samo jednom polju.
        if polje not in m.polja and kolona in slobodne:
            m.polja[polje] = kolona
            m.nacin[polje] = nacin
            slobodne.remove(kolona)

    # --- 1. prolaz: po nazivu, uz proveru sadržaja ---
    for kolona in kolone:
        # Kolona koja se zove baš kao polje (npr. fajlovi iz simulatora)
        # uzima se bez daljeg pogađanja.
        if normalizuj(kolona) in POLJA:
            dodeli(normalizuj(kolona), kolona, "tačan naziv")
            continue

        uloga = uloga_po_nazivu(kolona)
        p = profili[kolona]
        # Naziv već kaže da je kolona prognoza ili stvarna vrednost; sadržaj
        # samo odlučuje da li je broj ili kategorija. Dovoljno je da je više
        # od pola vrednosti brojeva, da jedna pokvarena vrednost ne bi
        # pretvorila celu kolonu u kategoriju.
        broj_ili_prazno = p.popunjenih == 0 or p.udeo_brojeva >= 0.5

        if uloga == "vreme" and p.udeo_vremena >= 0.5:
            dodeli("vreme", kolona, "naziv kolone")
        elif uloga in ("prognoza_jako", "prognoza_slabo"):
            # Isti naziv ("prediction") može da nosi broj ili kategoriju.
            # Sadržaj odlučuje koje je od ta dva.
            polje = "vrednost" if broj_ili_prazno else "kategorija"
            dodeli(polje, kolona, "naziv kolone")
        elif uloga == "stvarno":
            polje = "stvarna_vrednost" if broj_ili_prazno else "stvarna_kategorija"
            dodeli(polje, kolona, "naziv kolone")
        elif uloga in ("izvor", "status", "poruka", "jedinica", "horizont_min"):
            dodeli(uloga, kolona, "naziv kolone")
        elif uloga == "preskoci":
            slobodne.remove(kolona)

    # --- 2. prolaz: po sadržaju, za ono što nije nađeno po nazivu ---
    def prva(uslov) -> str | None:
        return next((k for k in slobodne if uslov(profili[k])), None)

    nesigurno = "sadržaj (proveriti)"

    if "vreme" not in m.polja:
        k = prva(lambda p: p.popunjenih > 0 and p.udeo_vremena >= 0.8)
        if k:
            dodeli("vreme", k, nesigurno)

    if "vrednost" not in m.polja and "kategorija" not in m.polja:
        k = prva(lambda p: p.popunjenih > 0 and p.udeo_brojeva >= 0.9)
        if k:
            dodeli("vrednost", k, nesigurno)

    if "izvor" not in m.polja:
        k = prva(lambda p: je_tekst(p) and p.razlicitih <= 200)
        if k:
            dodeli("izvor", k, nesigurno)

    if "vrednost" not in m.polja and "kategorija" not in m.polja:
        k = prva(lambda p: je_tekst(p) and p.razlicitih <= 200)
        if k:
            dodeli("kategorija", k, nesigurno)

    # Šta model predviđa: naziv kolone sa rezultatom, npr. "predicted_temp".
    glavna = m.polja.get("vrednost") or m.polja.get("kategorija")
    if glavna:
        m.velicina = normalizuj(glavna)

    m.neprepoznate = [k for k in kolone if k not in m.polja.values()]
    return m

